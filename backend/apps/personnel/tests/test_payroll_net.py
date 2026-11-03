"""Brütten nete ön bordro (3. adım; docs/DECISIONS.md "Personel bordrosu", "3. adım kararları"):
kümülatif zincir ve devir, ek ödeme ve kesintiler, nakit yemek istisnası, yeni uyarılar, bordro
listesi PDF'i, Excel sayfaları, API ve yetki.

Örnek kişi: 50.000 TL brüt, Eylül sonu kümülatif GV matrahı 382.500 ve 9 ay asgari ücret istisnası
(252.679,50). Ekim: GV 10.250,00 − 5.615,10 = 4.634,90, net 37.736,30; Kasım (Ekim'in 42.500
matrahıyla kümülatif 425.000): GV 11.475,00 − 5.615,10 = 5.859,90, net 36.511,30."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from openpyxl import load_workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import exports, pdf, selectors, services
from apps.personnel.api.serializers import PayrollMonthSerializer
from apps.personnel.models import (
    AttendanceStatus,
    Employee,
    ExternalPayrollFigure,
    PayrollItem,
    PayrollItemCategory,
    PayrollOpeningBalance,
)
from apps.personnel.tests.factories import employee, parameter_set

pytestmark = pytest.mark.django_db
D = Decimal
C = PayrollItemCategory
S = AttendanceStatus
BASE = "/api/v1/personnel"
OTHER_ROLES = ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]
VALID_TC = "10000000146"


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


def _wage(actor: User, person: Employee, amount: str = "50000", since: date = date(2020, 1, 1)):
    return services.add_wage(
        actor, {"employee": person, "gross_monthly": D(amount), "valid_from": since}
    )


def _row(year: int, month: int, person: Employee) -> selectors.PayrollRow:
    payroll = selectors.payroll_month(year, month)
    return next(row for row in payroll.rows if row.employee.pk == person.pk)


def _code(call: Callable[[], Any]) -> str:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value.code


def _opening(
    actor: User,
    person: Employee,
    *,
    month: int = 10,
    tax_base: str = "382500",
    months: int = 9,
    **extra: Any,
) -> PayrollOpeningBalance:
    return services.set_opening_balance(
        actor, person, 2026, month, tax_base=D(tax_base), exemption_months=months, **extra
    )


def _item(
    actor: User,
    person: Employee,
    category: str,
    amount: str,
    *,
    year: int = 2026,
    month: int = 10,
    description: str = "",
) -> PayrollItem:
    return services.add_payroll_item(
        actor,
        {
            "employee": person,
            "year": year,
            "month": month,
            "category": category,
            "description": description,
            "amount": D(amount),
        },
    )


def _next_month() -> tuple[int, int]:
    today = timezone.localdate()
    ahead = today.replace(day=1) + timedelta(days=32)
    return ahead.year, ahead.month


# --- zincir ve devir ---------------------------------------------------------------------------


def test_start_month_and_chain_start() -> None:
    assert selectors.PAYROLL_START == (2026, 10)
    assert not selectors.net_available(2026, 9) and selectors.net_available(2026, 10)
    assert (selectors.chain_start(2025), selectors.chain_start(2026)) == (None, 10)
    assert selectors.chain_start(2027) == 1


def test_october_needs_the_september_opening(manager: User) -> None:
    """Ekim 2026 ilk ERP ayı: önceden çalışan kişinin Eylül sonu devri beklenir; girilmeden gelir
    vergisi kümülatifsiz (düşük) hesaplanır."""
    person = employee(manager, employee_no="S-1")
    _wage(manager, person)
    row = _row(2026, 10, person)
    assert row.warnings == (selectors.OPENING_MISSING,)
    assert (row.entry_month, row.opening_needed, row.suggestion_months) == (10, True, 9)
    assert row.suggestion_base == D("252679.50")  # 9 × 28.075,50
    assert (row.line.income_tax, row.line.net_pay) == (D("2163.67"), D("40207.53"))
    opening = _opening(manager, person)
    assert (opening.exemption_months, opening.exemption_base) == (9, D("252679.50"))
    row = _row(2026, 10, person)
    assert row.warnings == () and row.opening == opening and not row.opening_needed
    line = row.line
    assert (line.cumulative_tax_base_before, line.exemption_base_before) == (
        D("382500.00"),
        D("252679.50"),
    )
    assert (line.income_tax_computed, line.income_tax_exemption, line.income_tax) == (
        D("10250.00"),
        D("5615.10"),
        D("4634.90"),
    )
    assert line.net_pay == D("37736.30")
    assert [(link.month, link.source) for link in row.carry_months] == [(10, "opening")]


def test_november_continues_the_chain(manager: User) -> None:
    person = employee(manager)
    _wage(manager, person)
    _opening(manager, person)
    row = _row(2026, 11, person)
    assert row.warnings == () and row.entry_month == 10
    assert row.line.cumulative_tax_base_before == D("425000.00")
    assert row.line.exemption_base_before == D("280755.00")
    assert (row.line.income_tax, row.line.net_pay) == (D("5859.90"), D("36511.30"))
    assert [(link.month, link.source, link.tax_base) for link in row.carry_months] == [
        (10, "opening", D("382500.00")),
        (10, "erp", D("42500.00")),
    ]


def test_hired_after_start_and_new_year_need_no_opening(manager: User) -> None:
    newcomer = employee(manager, full_name="Ali Can", hire_date=date(2026, 10, 5))
    _wage(manager, newcomer, since=date(2026, 10, 5))
    row = _row(2026, 10, newcomer)
    assert row.warnings == () and (row.opening_needed, row.suggestion_months) == (False, 0)
    veteran = employee(manager, full_name="Ece Ak", hire_date=date(2024, 1, 1))
    _wage(manager, veteran)
    january = _row(2027, 1, veteran)
    assert selectors.OPENING_MISSING not in january.warnings
    assert january.line.cumulative_tax_base_before == D(0) and january.entry_month == 1


def test_external_month_breaks_the_chain(manager: User) -> None:
    """Ekim'de bordrosu mali müşavirdeydi (rakamı girildi), Kasım'da ERP'ye geçti: Ekim mali
    müşavirde kalır, Kasım giriş ayıdır ve devir ister (onay gerekmez)."""
    person = employee(manager, payroll_external=True)
    _wage(manager, person)
    services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("50000"), employer_cost=D("59375")
    )
    services.update_employee(manager, person, {"payroll_external": False})
    october = _row(2026, 10, person)
    assert october.external and october.figure is not None
    row = _row(2026, 11, person)
    assert row.warnings == (selectors.OPENING_MISSING,) and row.entry_month == 11
    assert [link.source for link in row.carry_months] == ["external"]
    assert row.suggestion_months == 10
    _opening(manager, person, month=11, tax_base="425000", months=10)
    row = _row(2026, 11, person)
    assert row.warnings == ()
    assert row.line.cumulative_tax_base_before == D("425000.00")
    assert row.line.exemption_base_before == D("280755.00")


def test_reanchoring_needs_confirmation(manager: User) -> None:
    """Her ay devir girilebilir (mali müşavirle eşitleme); ERP'de hesaplanmış aydan sonra girilen
    devir o ayların yerine geçtiği için onay ister."""
    person = employee(manager)
    _wage(manager, person)
    _opening(manager, person)
    assert (
        _code(lambda: _opening(manager, person, month=11, tax_base="430000", months=10))
        == "opening_overrides_chain"
    )
    opening = _opening(
        manager, person, month=11, tax_base="430000", months=10, confirm_override=True
    )
    row = _row(2026, 11, person)
    assert row.opening == opening and row.line.cumulative_tax_base_before == D("430000.00")
    # Satır kişinin bu yılki bütün devirlerini taşır (devir penceresi Ekim devrini de görsün).
    assert [item.month for item in row.openings] == [10, 11]
    assert [link.source for link in row.carry_months] == ["opening"]


def test_opening_rules(manager: User) -> None:
    person = employee(manager)
    _wage(manager, person)
    assert _code(lambda: _opening(manager, person, month=9)) == "before_start"
    assert (
        _code(
            lambda: services.set_opening_balance(
                manager, person, 2027, 1, tax_base=D(0), exemption_months=0
            )
        )
        == "opening_not_needed"
    )
    assert _code(lambda: _opening(manager, person, months=10)) == "invalid_exemption_months"
    assert _code(lambda: _opening(manager, person, tax_base="-1")) == "invalid_tax_base"
    newcomer = employee(manager, full_name="Ali Can", hire_date=date(2026, 10, 5))
    assert _code(lambda: _opening(manager, newcomer, months=0)) == "opening_not_needed"
    march = employee(manager, full_name="Ece Ak", hire_date=date(2026, 3, 16))
    assert _code(lambda: _opening(manager, march, months=8)) == "invalid_exemption_months"
    assert _opening(manager, march, months=7).exemption_base == D("196528.50")  # Mart–Eylül
    external = employee(manager, full_name="Can Kaya", payroll_external=True)
    assert _code(lambda: _opening(manager, external)) == "not_computed"
    gone = employee(manager, full_name="Deniz Su", hire_date=date(2024, 1, 1))
    services.terminate_employee(manager, gone, date(2026, 9, 30))
    assert _code(lambda: _opening(manager, gone)) == "not_employed"
    first = _opening(manager, person)
    again = _opening(manager, person, tax_base="390000")
    assert again.pk == first.pk and again.tax_base == D("390000.00")
    assert PayrollOpeningBalance.objects.filter(is_active=True).count() == 2


def test_opening_exemption_base_uses_each_months_parameters(manager: User) -> None:
    """Asgari ücret Temmuz'dan 36.000 (istisna matrahı 30.600): Mart–Haziran 4 × 28.075,50 ve
    Temmuz–Eylül 3 × 30.600 toplanır (tek ayın parametresiyle 214.200 olurdu)."""
    parameter_set(manager, valid_from=date(2026, 7, 1), minimum_wage=D("36000.00"))
    march = employee(manager, full_name="Ece Ak", hire_date=date(2026, 3, 16))
    _wage(manager, march)
    assert _opening(manager, march, months=7).exemption_base == D("204102.00")


def test_changed_parameters_mark_the_opening_stale(manager: User) -> None:
    """Devirden sonra kapsadığı ayların parametreleri değişirse zincir eksik sayılır; devir
    yeniden kaydedilince istisna matrahı yenilenir ve uyarı kalkar."""
    person = employee(manager)
    _wage(manager, person)
    _opening(manager, person)
    assert _row(2026, 10, person).warnings == ()
    parameter_set(manager, valid_from=date(2026, 7, 1), minimum_wage=D("36000.00"))
    row = _row(2026, 10, person)
    assert selectors.CARRY_INCOMPLETE in row.warnings
    assert row.carry_months[0].flags == (selectors.OPENING_STALE,)
    refreshed = _opening(manager, person)
    assert refreshed.exemption_base == D("260253.00")  # 6 × 28.075,50 + 3 × 30.600
    assert _row(2026, 10, person).warnings == ()


def test_fallback_parameters_mark_the_chain_incomplete(manager: User) -> None:
    """2027 parametreleri kayıtlı değil ve yasal değerleri yok: zincir ayları tahmindir."""
    person = employee(manager, hire_date=date(2024, 1, 1))
    _wage(manager, person)
    february = _row(2027, 2, person)
    assert selectors.CARRY_INCOMPLETE in february.warnings
    assert [link.flags for link in february.carry_months] == [(selectors.FALLBACK_PARAMETERS,)]


def test_future_month_opening_is_refused(manager: User) -> None:
    person = employee(manager)
    _wage(manager, person)
    year = timezone.localdate().year + 1  # gelecek yılın Mart'ı (Ocak'ta devir zaten girilmez)
    assert (
        _code(
            lambda: services.set_opening_balance(
                manager, person, year, 3, tax_base=D("1"), exemption_months=1
            )
        )
        == "future_month"
    )


def test_removed_opening_restores_the_warning(manager: User) -> None:
    person = employee(manager)
    _wage(manager, person)
    opening = _opening(manager, person)
    assert (
        _code(lambda: services.remove_opening_balance(manager, opening, " ")) == "reason_required"
    )
    removed = services.remove_opening_balance(manager, opening, "Yanlış kişi")
    assert not removed.is_active and removed.removal_reason == "Yanlış kişi"
    assert _row(2026, 10, person).warnings == (selectors.OPENING_MISSING,)
    assert (
        _code(lambda: services.remove_opening_balance(manager, opening, "Yine"))
        == "already_removed"
    )
    assert _opening(manager, person).pk != opening.pk  # yeniden girilebilir
    notes = list(selectors.employee_history(person).values_list("note", flat=True))
    assert "Devir kaldırıldı: Ekim 2026. Neden: Yanlış kişi" in notes
    assert any(note.startswith("Devir girildi: Ekim 2026 · kümülatif GV matrahı") for note in notes)


def test_opening_batch_is_all_or_nothing(manager: User) -> None:
    first = employee(manager, employee_no="S-1")
    second = employee(manager, employee_no="S-2", full_name="Can Kaya")
    rows = [
        {"employee": first, "tax_base": D("382500"), "exemption_months": 9},
        {"employee": second, "tax_base": D("1"), "exemption_months": 11},
    ]
    with pytest.raises(services.PayrollBatchError) as exc:
        services.set_opening_balances(manager, 2026, 10, rows)
    assert [(row["index"], row["employee"], row["code"]) for row in exc.value.errors] == [
        (1, second.pk, "invalid_exemption_months")
    ]
    assert not PayrollOpeningBalance.objects.exists()
    rows[1]["exemption_months"] = 9
    assert len(services.set_opening_balances(manager, 2026, 10, rows)) == 2


# --- ek ödeme ve kesintiler --------------------------------------------------------------------


def test_items_enter_gross_and_payable(manager: User) -> None:
    person = employee(manager)
    _wage(manager, person)
    _opening(manager, person)
    _item(manager, person, C.PREMIUM, "5000")
    _item(manager, person, C.ADVANCE, "1000")
    row = _row(2026, 10, person)
    line = row.line
    assert (line.gross_total, line.extras_total, line.income_tax, line.net_pay) == (
        D("55000.00"),
        D("5000.00"),
        D("5782.40"),
        D("40800.85"),
    )
    assert (line.deductions_total, line.payable, line.employer_cost) == (
        D("1000.00"),
        D("39800.85"),
        D("65312.50"),
    )
    assert [item.category for item in row.items] == [C.ADVANCE, C.PREMIUM]
    assert [extra.kind for extra in line.extras] == [C.PREMIUM]


def test_item_rules(manager: User) -> None:
    person = employee(manager)
    _wage(manager, person)
    year, month = _next_month()
    assert _code(lambda: _item(manager, person, C.PREMIUM, "1", month=9)) == "before_start"
    assert (
        _code(lambda: _item(manager, person, C.PREMIUM, "1", year=year, month=month))
        == "future_month"
    )
    assert _code(lambda: _item(manager, person, "XYZ", "1")) == "invalid_category"
    assert _code(lambda: _item(manager, person, C.OTHER_EXTRA, "1")) == "description_required"
    assert _code(lambda: _item(manager, person, C.PREMIUM, "0")) == "invalid_amount"
    later = employee(manager, full_name="Ali Can", hire_date=date(2026, 11, 1))
    assert _code(lambda: _item(manager, later, C.PREMIUM, "1")) == "not_employed"
    external = employee(manager, full_name="Can Kaya", payroll_external=True)
    assert _code(lambda: _item(manager, external, C.PREMIUM, "1")) == "not_computed"
    item = _item(manager, person, C.PREMIUM, "5000")
    item = services.update_payroll_item(manager, item, {"amount": D("6000"), "category": C.BONUS})
    assert (item.amount, item.category, item.kind) == (D("6000"), C.BONUS, "EXTRA")
    assert (
        _code(lambda: services.update_payroll_item(manager, item, {"category": C.ADVANCE}))
        == "invalid_category"
    )
    change = AuditLog.objects.filter(
        action=AuditLog.Action.UPDATE, content_type__model="payrollitem", object_id=item.pk
    ).first()
    assert change is not None and {"amount", "category"} <= set(change.changes)
    assert _code(lambda: services.remove_payroll_item(manager, item, "")) == "reason_required"
    services.remove_payroll_item(manager, item, "Yanlış ay")
    assert _row(2026, 10, person).items == ()
    assert (
        _code(lambda: services.update_payroll_item(manager, item, {"amount": D("1")}))
        == "item_removed"
    )
    assert _code(lambda: services.remove_payroll_item(manager, item, "Yine")) == "already_removed"


def test_item_batch_is_all_or_nothing(manager: User) -> None:
    first = employee(manager, employee_no="S-1")
    second = employee(manager, employee_no="S-2", full_name="Can Kaya", payroll_external=True)
    rows = [
        {"employee": first, "category": C.MEAL, "description": "", "amount": D("3000")},
        {"employee": second, "category": C.MEAL, "description": "", "amount": D("3000")},
    ]
    with pytest.raises(services.PayrollBatchError) as exc:
        services.add_payroll_items(manager, 2026, 10, rows)
    assert [row["code"] for row in exc.value.errors] == ["not_computed"]
    assert not PayrollItem.objects.exists()
    saved = services.add_payroll_items(manager, 2026, 10, rows[:1])
    assert [item.amount for item in saved] == [D("3000")]


def test_card_history_hides_item_descriptions(manager: User) -> None:
    person = employee(manager)
    item = _item(manager, person, C.GARNISHMENT, "2000", description="2026/1234 E.")
    notes = list(selectors.employee_history(person).values_list("note", flat=True))
    assert "Kesinti eklendi: Ekim 2026 · İcra / nafaka 2.000,00 TL" in notes
    assert not any("2026/1234" in note for note in notes)
    assert str(item) == f"İcra / nafaka {person.pk} 10.2026"


def test_unchanged_saves_write_no_card_note(manager: User) -> None:
    """Değişmeyen devir ya da kalem yeniden kaydedilince kartın geçmişine boş "düzeltildi" notu
    düşmez."""
    person = employee(manager)
    _wage(manager, person)
    opening = _opening(manager, person)
    item = _item(manager, person, C.PREMIUM, "5000")
    before = selectors.employee_history(person).count()
    assert _opening(manager, person).pk == opening.pk
    services.update_payroll_item(manager, item, {"amount": D("5000.00"), "description": ""})
    assert selectors.employee_history(person).count() == before
    services.update_payroll_item(manager, item, {"amount": D("5500")})
    notes = list(selectors.employee_history(person).values_list("note", flat=True))
    assert "Ek ödeme düzeltildi: Ekim 2026 · Prim 5.500,00 TL" in notes


def test_cash_meal_exemption_from_parameters(manager: User) -> None:
    """Ekim 2026: 27 fiilen çalışılan gün (4 pazar hafta tatili) × 158 = 4.266 TL SGK istisnası."""
    parameter_set(manager, meal_exemption_daily=D("158.00"))
    person = employee(manager)
    _wage(manager, person, "33030")
    _item(manager, person, C.MEAL, "5000")
    line = _row(2026, 10, person).line
    assert (line.worked_days, line.meal_exemption) == (27, D("4266.00"))
    assert line.sgk_gross == line.gross_total - D("4266.00") == D("33764.00")


# --- uyarılar ve tutarlılık ---------------------------------------------------------------------


def test_new_warnings(manager: User) -> None:
    owing = employee(manager, employee_no="S-1")
    _wage(manager, owing)
    _opening(manager, owing)
    _item(manager, owing, C.ADVANCE, "40000")
    row = _row(2026, 10, owing)
    assert row.warnings == (selectors.NEGATIVE_PAYABLE,) and row.line.payable == D("-2263.70")
    high = employee(manager, employee_no="S-2", full_name="Can Kaya")
    _wage(manager, high, "300000")
    _opening(manager, high, tax_base="2500000")
    _item(manager, high, C.BONUS, "10000")
    assert _row(2026, 10, high).warnings == (selectors.CEILING_WITH_BONUS,)
    late = employee(manager, employee_no="S-3", full_name="Ece Ak")
    _wage(manager, late, since=date(2026, 10, 15))  # Ekim'in ilk günleri ücretsiz
    _opening(manager, late)
    november = _row(2026, 11, late)
    assert november.warnings == (selectors.CARRY_INCOMPLETE,)
    assert november.carry_months[-1].flags == (selectors.MISSING_WAGE,)


def test_payroll_records_follow_employment(manager: User) -> None:
    person = employee(manager, hire_date=date(2024, 1, 1))
    _wage(manager, person)
    _item(manager, person, C.PREMIUM, "1000", month=11)
    assert (
        _code(lambda: services.terminate_employee(manager, person, date(2026, 10, 31)))
        == "payroll_items_after_exit"
    )
    _item(manager, person, C.PREMIUM, "1000")
    with pytest.raises(BusinessRuleError) as exc:
        services.update_employee(manager, person, {"hire_date": date(2026, 11, 1)})
    assert exc.value.code == "payroll_items_before_hire"
    assert "gerekçeyle kaldırın" in exc.value.message and "taşı" not in exc.value.message


def test_openings_follow_employment(manager: User) -> None:
    """Devir ayında ya da sonra işe giriş ve devir ayından önce ayrılış reddedilir (devir, devir
    ayından önce işte olmayı gerektirir)."""
    hired = employee(manager, hire_date=date(2024, 1, 1))
    _wage(manager, hired)
    _opening(manager, hired)  # Ekim devri
    assert (
        _code(lambda: services.update_employee(manager, hired, {"hire_date": date(2026, 10, 1)}))
        == "payroll_items_before_hire"
    )
    leaver = employee(manager, full_name="Ece Ak", hire_date=date(2024, 1, 1))
    _wage(manager, leaver)
    _opening(manager, leaver)
    later = _opening(manager, leaver, month=11, tax_base="425000", months=10, confirm_override=True)
    assert (
        _code(lambda: services.terminate_employee(manager, leaver, date(2026, 10, 31)))
        == "payroll_items_after_exit"
    )
    services.remove_opening_balance(manager, later, "Yanlış ay")
    services.terminate_employee(manager, leaver, date(2026, 10, 31))


def test_hire_date_cannot_leave_opening_months_too_many(manager: User) -> None:
    """İşe giriş ileri alınınca devrin istisna ay sayısı yeni tarihe göre fazla kalamaz
    (asgari ücret istisnası fazla hesaplanırdı); devir düzeltilince değişiklik kabul edilir."""
    for hire in (date(2024, 1, 1), None):
        person = employee(manager, full_name=f"Ali {hire}", hire_date=hire)
        _wage(manager, person)
        _opening(manager, person)  # Ekim devri, 9 ay
        with pytest.raises(BusinessRuleError) as exc:
            services.update_employee(manager, person, {"hire_date": date(2026, 6, 15)})
        assert exc.value.code == "opening_months_exceed_hire"
        _opening(manager, person, months=4)  # Haziran–Eylül
        services.update_employee(manager, person, {"hire_date": date(2026, 6, 15)})
        line = _row(2026, 10, person).line
        assert line.exemption_base_before == D("112302.00")  # 4 × 28.075,50
        assert line.income_tax_exemption == D("4211.33")


def test_update_employee_locks_the_card_before_checking_records(manager: User) -> None:
    """Kilit sırası: önce kart, sonra bordro kayıtları (aynı anda girilen kalem denetimi
    atlatamaz)."""
    person = employee(manager, hire_date=date(2024, 1, 1))
    with CaptureQueriesContext(connection) as queries:
        services.update_employee(manager, person, {"hire_date": date(2024, 2, 1)})
    statements = [query["sql"] for query in queries.captured_queries]
    lock = next(
        index
        for index, sql in enumerate(statements)
        if '"personnel_employee"' in sql and "FOR UPDATE" in sql
    )
    first_record = next(index for index, sql in enumerate(statements) if "personnel_payroll" in sql)
    assert lock < first_record


def test_orphan_items_are_listed(manager: User) -> None:
    gone = employee(manager, hire_date=date(2024, 1, 1))
    services.terminate_employee(manager, gone, date(2026, 9, 30))
    PayrollItem.objects.create(
        employee=gone,
        year=2026,
        month=10,
        kind="EXTRA",
        category=C.PREMIUM,
        amount=D("100"),
        created_by=manager,
        updated_by=manager,
    )
    month = selectors.payroll_month(2026, 10)
    assert [item.employee_id for item in month.orphan_items] == [gone.pk]


def test_net_month_queries_do_not_grow_with_people(manager: User) -> None:
    def add(index: int) -> None:
        person = employee(manager, employee_no=f"S-{index}", full_name=f"Kişi {index}")
        _wage(manager, person)
        _opening(manager, person)
        _item(manager, person, C.PREMIUM, "1000")

    def count() -> int:
        with CaptureQueriesContext(connection) as queries:
            assert PayrollMonthSerializer(selectors.payroll_month(2026, 11)).data
        return len(queries)

    add(1)
    add(2)
    two = count()
    for index in range(3, 6):
        add(index)
    assert count() == two


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_only_management_writes_net_payroll(
    make_user: Callable[..., User], manager: User, role: str
) -> None:
    person = employee(manager)
    opening = _opening(manager, person)
    item = _item(manager, person, C.PREMIUM, "1")
    flagged = employee(manager, full_name="Can Kaya", payroll_external=True)
    figure = services.set_external_payroll(
        manager, flagged, 2026, 10, gross_total=D("1"), employer_cost=D("2")
    )
    other = make_user(role)
    calls = [
        lambda: services.remove_external_payroll(other, figure, "X"),
        lambda: services.set_opening_balance(
            other, person, 2026, 10, tax_base=D(1), exemption_months=1
        ),
        lambda: services.set_opening_balances(other, 2026, 10, []),
        lambda: services.remove_opening_balance(other, opening, "X"),
        lambda: services.add_payroll_item(other, {"employee": person}),
        lambda: services.add_payroll_items(other, 2026, 10, []),
        lambda: services.update_payroll_item(other, item, {"amount": D(2)}),
        lambda: services.remove_payroll_item(other, item, "X"),
    ]
    for call in calls:
        with pytest.raises(PermissionDenied):
            call()


# --- çıktılar ----------------------------------------------------------------------------------


def _net_month(manager: User) -> tuple[Employee, Employee]:
    person = employee(manager, employee_no="S-1", national_id=VALID_TC)
    _wage(manager, person)
    _opening(manager, person)
    _item(manager, person, C.PREMIUM, "5000")
    _item(manager, person, C.GARNISHMENT, "1000", description="dosya 2026/1")
    external = employee(manager, employee_no="S-2", full_name="Can Kaya", payroll_external=True)
    services.set_external_payroll(
        manager, external, 2026, 10, gross_total=D("40000"), employer_cost=D("48000")
    )
    return person, external


def test_register_rows_and_pdf(manager: User) -> None:
    _net_month(manager)
    month = selectors.payroll_month(2026, 10)
    lines = pdf.register_rows(month)
    assert [kind for kind, _ in lines] == ["row", "total"]
    cells = lines[0][1]
    assert cells[0] == "Ayşe Demir\nS-1 · Dolum\nTC *******0146"
    assert cells[2] == "Normal 50.000,00\nEk ödeme 5.000,00"
    assert cells[3] == "55.000,00"
    assert cells[7] == "11.397,50\n−5.615,10\n5.782,40"  # hesaplanan / istisna / kesilen
    assert cells[10] == "İcra / nafaka 1.000,00"  # açıklama yazılmaz
    assert cells[11] == "39.800,85\n65.312,50"  # ödenecek / işverene maliyet
    assert lines[-1][1][11] == "39.800,85\n65.312,50"
    assert pdf.external_rows(month) == [["Can Kaya\nS-2 · Dolum", "40.000,00", "48.000,00", ""]]
    # Tablo A4 yatay sayfanın çerçevesine sığar (10 mm kenar boşluğu, 6 pt çerçeve iç boşluğu).
    frame = landscape(A4)[0] - 20 * mm - 12
    assert sum(pdf.REGISTER_WIDTHS) * mm <= frame
    assert len(pdf.REGISTER_WIDTHS) == len(pdf.REGISTER_HEADER)
    employee_side = dict(pdf.summary_rows(month)[0][1])
    assert employee_side["Kişi (ERP / mali müşavirde)"] == "1 / 1"
    assert employee_side["Kesilen gelir vergisi"] == "5.782,40"
    content = pdf.register_pdf(month)
    assert content.startswith(b"%PDF")
    assert content.count(b"/Type /Page") - content.count(b"/Type /Pages") == 2  # liste + icmal


def test_payroll_excel_in_net_month(manager: User) -> None:
    person, _ = _net_month(manager)
    services.set_attendance_day(manager, person, date(2026, 10, 5), status=S.SICK_LEAVE)
    services.set_attendance_day(manager, person, date(2026, 10, 6), status=S.SICK_LEAVE)
    services.set_attendance_day(manager, person, date(2026, 10, 12), status=S.UNPAID_LEAVE)
    workbook = load_workbook(BytesIO(exports.payroll_xlsx(selectors.payroll_month(2026, 10))))
    assert workbook.sheetnames == [
        "Bordro",
        "İşveren maliyeti",
        "Karşılaştırma",
        "Eksik gün",
        "Parametreler",
    ]
    rows = list(workbook["Bordro"].iter_rows(values_only=True))
    columns = exports.payroll_columns()
    header = rows.index(tuple(columns))
    data = dict(zip(columns, rows[header + 1], strict=True))
    assert data["TC kimlik no (maskeli)"] == "*******0146"
    assert D(str(data["Prim (TL)"])) == D("5000") and D(str(data["İcra / nafaka (TL)"])) == D(
        "1000"
    )
    assert data["Devir ayı"] == "Ekim 2026" and D(str(data["Devir GV matrahı (TL)"])) == D("382500")
    assert rows[header + 2][1] == "Genel toplam"
    compare = list(workbook["Karşılaştırma"].iter_rows(values_only=True))
    first = next(row for row in compare if row and row[0] == "S-1")
    assert str(first[4]).startswith("=IF(")
    missing = list(workbook["Eksik gün"].iter_rows(values_only=True))
    found = next(row for row in missing if row and row[0] == "S-1")
    assert (found[7], found[8], found[10], found[11]) == (2, 1, 3, "12")
    assert "İstirahat (rapor): 05–06.10" in found[13] and "Diğer ücretsiz izin: 12.10" in found[13]


# --- API ---------------------------------------------------------------------------------------


def test_net_payroll_month_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person, _ = _net_month(manager)
    body = client.get(f"{BASE}/payroll/2026/10/").json()
    assert (body["net"], body["net_available"], body["start"]) == (True, True, "2026-10")
    row = next(item for item in body["rows"] if item["employee"]["id"] == person.pk)
    assert row["line"]["income_tax"] == "5782.40" and row["line"]["payable"] == "39800.85"
    assert [item["category"] for item in row["items"]] == ["GARNISHMENT", "PREMIUM"]
    assert row["items"][0]["created_by_name"] and row["opening"]["tax_base"] == "382500.00"
    assert row["entry_month"] == 10 and row["opening_needed"] is False
    assert row["carry_months"] == [
        {
            "month": 10,
            "kind": "opening",
            "tax_base": "382500.00",
            "exemption_base": "252679.50",
            "flags": [],
        }
    ]
    assert body["totals"]["computed_gross_total"] == "55000.00"
    assert body["totals"]["gross_total"] == "95000.00"


def test_item_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager)
    created = client.post(
        f"{BASE}/payroll/items/",
        {"employee": person.pk, "year": 2026, "month": 10, "category": "PREMIUM", "amount": "500"},
        format="json",
    )
    assert created.status_code == 201 and created.json()["category_label"] == "Prim"
    item_id = created.json()["id"]
    assert client.get(f"{BASE}/payroll/items/").json()["code"] == "filter_required"
    listed = client.get(f"{BASE}/payroll/items/", {"year": 2026, "month": 10}).json()
    assert [item["id"] for item in listed["results"]] == [item_id]
    patched = client.patch(f"{BASE}/payroll/items/{item_id}/", {"amount": "750"}, format="json")
    assert patched.status_code == 200 and patched.json()["amount"] == "750.00"
    wrong = client.patch(f"{BASE}/payroll/items/{item_id}/", {"month": 11}, format="json")
    assert wrong.status_code == 400 and wrong.json()["code"] == "field_not_editable"
    batch = client.post(
        f"{BASE}/payroll/items/batch/",
        {
            "year": 2026,
            "month": 10,
            "items": [
                {"employee": person.pk, "category": "MEAL", "amount": "3000"},
                {"employee": person.pk, "category": "OTHER_DEDUCTION", "amount": "10"},
            ],
        },
        format="json",
    )
    assert batch.status_code == 400 and batch.json()["code"] == "batch_rejected"
    assert [row["code"] for row in batch.json()["rows"]] == ["description_required"]
    removed = client.post(
        f"{BASE}/payroll/items/{item_id}/remove/", {"reason": "Yanlış"}, format="json"
    )
    assert removed.status_code == 200 and removed.json()["is_active"] is False
    removed_list = client.get(
        f"{BASE}/payroll/items/", {"employee": str(person.pk), "is_active": "false"}
    )
    assert removed_list.json()["count"] == 1
    assert client.delete(f"{BASE}/payroll/items/{item_id}/").status_code == 405


def test_opening_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager)
    saved = client.post(
        f"{BASE}/payroll/openings/",
        {
            "employee": person.pk,
            "year": 2026,
            "month": 10,
            "tax_base": "382500",
            "exemption_months": 9,
        },
        format="json",
    )
    assert saved.status_code == 200 and saved.json()["exemption_base"] == "252679.50"
    batch = client.post(
        f"{BASE}/payroll/openings/batch/",
        {
            "year": 2026,
            "month": 11,
            "rows": [{"employee": person.pk, "tax_base": "425000", "exemption_months": 10}],
        },
        format="json",
    )
    assert batch.status_code == 400
    assert [row["code"] for row in batch.json()["rows"]] == ["opening_overrides_chain"]
    removed = client.post(
        f"{BASE}/payroll/openings/{saved.json()['id']}/remove/", {"reason": "Yanlış"}, format="json"
    )
    assert removed.status_code == 200 and removed.json()["is_active"] is False


def test_register_pdf_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    _net_month(manager)
    early = client.get(f"{BASE}/payroll/2026/9/register.pdf")
    assert early.status_code == 400 and early.json()["code"] == "before_start"
    response = client.get(f"{BASE}/payroll/2026/10/register.pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert response["Content-Disposition"] == 'inline; filename="bordro-listesi-2026-10.pdf"'
    assert response["Cache-Control"] == "no-store"
    assert AuditLog.objects.filter(
        note="Bordro çıktısı açıldı: Bordro listesi (PDF) · Ekim 2026"
    ).exists()


def test_external_figure_removal(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager, payroll_external=True)
    figure = services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("1"), employer_cost=D("2")
    )
    response = client.post(
        f"{BASE}/payroll/external/{figure.pk}/remove/", {"reason": "Yanlış ay"}, format="json"
    )
    assert response.status_code == 200
    assert not ExternalPayrollFigure.objects.get(pk=figure.pk).is_active
    assert _row(2026, 10, person).warnings == (selectors.EXTERNAL_MISSING,)
    again = services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("3"), employer_cost=D("4")
    )
    assert again.pk != figure.pk  # kaldırılanın yerine yenisi açılır


def test_external_figure_rules(manager: User) -> None:
    person = employee(manager, payroll_external=True)
    figure = services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("50000"), employer_cost=D("59375")
    )
    services.update_employee(manager, person, {"payroll_external": False})
    fixed = services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("51000"), employer_cost=D("60000")
    )
    assert fixed.pk == figure.pk and fixed.gross_total == D("51000")  # işaret kalksa da düzeltilir
    assert (
        _code(
            lambda: services.set_external_payroll(
                manager, person, 2026, 11, gross_total=D("1"), employer_cost=D("2")
            )
        )
        == "not_external"
    )
    assert _code(lambda: services.remove_external_payroll(manager, figure, " ")) == (
        "reason_required"
    )
    services.remove_external_payroll(manager, figure, "Yanlış ay")
    assert _code(lambda: services.remove_external_payroll(manager, figure, "Yine")) == (
        "already_removed"
    )


def test_external_figure_refused_while_the_month_has_items(manager: User) -> None:
    """Rakam girilen ay mali müşavirde sayılır: o aya ERP'de girilmiş kalem hesaptan sessizce
    düşmesin diye önce kalem kaldırılır. Kartı sonradan işaretlenen kişinin kalemi bordro listesinde
    mali müşavir bloğunun notunda (açıklamasız) yazılır."""
    person = employee(manager, employee_no="S-1")
    _wage(manager, person)
    item = _item(manager, person, C.ADVANCE, "1000", description="Ekim avansı")
    services.update_employee(manager, person, {"payroll_external": True})
    with pytest.raises(BusinessRuleError) as exc:
        services.set_external_payroll(
            manager, person, 2026, 10, gross_total=D("50000"), employer_cost=D("59375")
        )
    assert exc.value.code == "payroll_items_external"
    assert "Ekim 2026 Avans 1.000,00 TL" in exc.value.message
    month = selectors.payroll_month(2026, 10)
    assert pdf.external_rows(month)[0][3] == (
        "rakam girilmedi\nERP'de girilen kalemler hesaplanmadı: Avans 1.000,00"
    )
    services.remove_payroll_item(manager, item, "Mali müşavire bildirildi")
    services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("50000"), employer_cost=D("59375")
    )


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_reach_net_payroll(
    client_for: Callable[..., APIClient], manager: User, role: str
) -> None:
    person = employee(manager)
    item = _item(manager, person, C.PREMIUM, "1")
    opening = _opening(manager, person)
    client = client_for(role)
    responses = [
        client.patch(f"{BASE}/payroll/items/{item.pk}/", {"amount": "2"}, format="json"),
        client.post(f"{BASE}/payroll/items/{item.pk}/remove/", {"reason": "X"}, format="json"),
        client.post(
            f"{BASE}/payroll/openings/{opening.pk}/remove/", {"reason": "X"}, format="json"
        ),
        client.get(f"{BASE}/payroll/items/", {"year": 2026, "month": 10}),
        client.post(f"{BASE}/payroll/items/", {}, format="json"),
        client.post(f"{BASE}/payroll/items/batch/", {}, format="json"),
        client.get(f"{BASE}/payroll/openings/"),
        client.post(f"{BASE}/payroll/openings/", {}, format="json"),
        client.post(f"{BASE}/payroll/openings/batch/", {}, format="json"),
        client.get(f"{BASE}/payroll/2026/10/register.pdf"),
        client.post(f"{BASE}/payroll/external/1/remove/", {}, format="json"),
    ]
    assert [response.status_code for response in responses] == [403] * len(responses)
    assert person.pk  # kart yalnızca yetkili tarafından açıldı
