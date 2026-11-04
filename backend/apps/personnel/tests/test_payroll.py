"""Ön bordro (docs/DECISIONS.md "Personel bordrosu"): bordro parametreleri, ayın hesabı
(puantaj ve ücretlerden), yarım gün tatil çalışması, bordrosu mali müşavirde olan kişi, işveren
maliyeti PDF'i ve Excel'i, erişim izi ve yetki."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from openpyxl import load_workbook
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus.tables import Table
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import exports, pdf, selectors, services
from apps.personnel.api.serializers import PayrollMonthSerializer
from apps.personnel.models import (
    AttendanceEntry,
    AttendanceStatus,
    Employee,
    ExternalPayrollFigure,
    PayrollParameterSet,
)
from apps.personnel.tests.factories import employee, parameter_set, parameter_values

pytestmark = pytest.mark.django_db
D = Decimal
S = AttendanceStatus
BASE = "/api/v1/personnel"
OTHER_ROLES = ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


def _wage(actor: User, person: Employee, amount: str, valid_from: date = date(2020, 1, 1)) -> None:
    services.add_wage(
        actor, {"employee": person, "gross_monthly": D(amount), "valid_from": valid_from}
    )


def _code(call: Callable[[], Any]) -> str:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value.code


def _row(year: int, month: int, person: Employee) -> selectors.PayrollRow:
    payroll = selectors.payroll_month(year, month)
    return next(row for row in payroll.rows if row.employee.pk == person.pk)


def _half_flag_shown(person: Employee, day: date) -> bool:
    """Yarım gün tatil işareti tabloda, puantaj Excel'inde ve bordroda birlikte görünür ya da
    birlikte görünmez; görünüp görünmediğini döndürür."""
    grid = selectors.attendance_grid(day.year, day.month)
    row = next(row for row in grid.rows if row.employee.pk == person.pk)
    cell = next(cell for cell in row.cells if cell.date == day)
    sheet = _sheet(load_workbook(BytesIO(exports.attendance_xlsx(grid))), "Puantaj")
    header = list(sheet[1])
    code = sheet[2][header.index(f"{day.day} Ça")]
    paid = _row(day.year, day.month, person).line.holiday_pay
    shown = cell.holiday_half_worked
    assert code == (exports.HALF_HOLIDAY_CODE if shown else "Ç")
    assert paid == (D("550.50") if shown else D("0.00"))
    return shown


# --- parametreler ----------------------------------------------------------------------------


def test_parameter_set_rules(manager: User) -> None:
    created = parameter_set(manager, valid_from=date(2026, 1, 15), note="  Mali   müşavirle ")
    # Geçerlilik ayın ilk gününe çekilir; metin boşlukları temizlenir; denetim kaydı yazılır.
    assert created.valid_from == date(2026, 1, 1) and created.note == "Mali müşavirle"
    assert created.created_by == manager
    assert AuditLog.objects.filter(
        content_type__model="payrollparameterset",
        object_id=created.pk,
        action=AuditLog.Action.CREATE,
    ).exists()

    def create(**values: Any) -> Callable[[], Any]:
        values.setdefault("valid_from", date(2026, 7, 1))
        return lambda: services.create_parameter_set(manager, parameter_values(**values))

    assert _code(lambda: parameter_set(manager)) == "duplicate_parameters"
    assert _code(create(minimum_wage=None)) == "parameters_incomplete"
    assert _code(create(minimum_wage=D(0))) == "invalid_minimum_wage"
    assert _code(create(ceiling_multiplier=D("0.5"))) == "invalid_ceiling"
    assert _code(create(employee_sgk_rate=D("100.01"))) == "invalid_rate"
    assert _code(create(incentive_points=D(22))) == "invalid_incentive"
    assert _code(create(stamp_tax_per_mille=D(-1))) == "invalid_stamp_tax"
    assert _code(create(meal_exemption_daily=D(-1))) == "invalid_meal_exemption"
    assert _code(create(meal_exemption_daily=D("100000001"))) == "invalid_meal_exemption"
    assert _code(create(tax_bracket_2=D("150000"))) == "invalid_brackets"
    assert _code(create(valid_from=date(1999, 1, 1))) == "invalid_valid_from"
    with pytest.raises(ValueError):
        services.create_parameter_set(manager, {**parameter_values(), "extra": 1})

    updated = services.update_parameter_set(manager, created, {"incentive_points": D(2)})
    assert updated.incentive_points == D(2)
    change = AuditLog.objects.filter(
        content_type__model="payrollparameterset",
        object_id=created.pk,
        action=AuditLog.Action.UPDATE,
    ).latest("id")
    assert change.changes["incentive_points"] == ["5.00", "2.00"]
    july = parameter_set(manager, valid_from=date(2026, 7, 1))
    to_january = {"valid_from": date(2026, 1, 1)}
    assert (
        _code(lambda: services.update_parameter_set(manager, july, to_january))
        == "duplicate_parameters"
    )
    assert _code(lambda: services.remove_parameter_set(manager, july, " ")) == "reason_required"
    removed = services.remove_parameter_set(manager, july, "Yanlış açıldı")
    assert not removed.is_active
    assert _code(lambda: services.remove_parameter_set(manager, removed, "X")) == "already_removed"
    assert (
        _code(lambda: services.update_parameter_set(manager, removed, {"incentive_points": D(0)}))
        == "parameters_removed"
    )
    # Kaldırılan ayın yerine yeniden set açılabilir.
    assert parameter_set(manager, valid_from=date(2026, 7, 1)).is_active


def test_concurrent_duplicate_parameter_set_is_a_business_error(
    manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def clash(*args: Any, **kwargs: Any) -> Any:
        raise IntegrityError("personnel_payroll_parameters_date_uniq")

    monkeypatch.setattr(services, "save_with_audit", clash)
    assert _code(lambda: parameter_set(manager)) == "duplicate_parameters"


def test_parameters_follow_the_year_and_valid_from(manager: User) -> None:
    """Kayıtlı set yoksa yılın yasal değerleri; yasal değeri bilinmeyen yılda en yakın yılın
    değerleri (tahmin). Set yalnızca kendi yılında, geçerli olduğu aydan itibaren uygulanır."""
    settings = selectors.payroll_parameters(2026, 10)
    assert (settings.source, settings.year, settings.record) == ("legal_default", 2026, None)
    fallback = selectors.payroll_parameters(2031, 1)
    assert (fallback.source, fallback.year) == ("fallback", 2026)
    january = parameter_set(manager, incentive_points=D(2))
    july = parameter_set(manager, valid_from=date(2026, 7, 1), minimum_wage=D("35000"))
    assert selectors.payroll_parameters(2026, 6).record == january
    assert selectors.payroll_parameters(2026, 7).record == july
    assert selectors.payroll_parameters(2026, 12).params.minimum_wage == D("35000")
    # 2026 seti 2027'ye uygulanmaz.
    assert selectors.payroll_parameters(2027, 1).source == "fallback"
    # Ocak seti yokken Haziran yasal değerlerle (Temmuz seti geriye uygulanmaz).
    services.remove_parameter_set(manager, january, "Deneme")
    assert selectors.payroll_parameters(2026, 6).source == "legal_default"


# --- ayın hesabı -----------------------------------------------------------------------------


def test_payroll_month_from_attendance_and_wages(manager: User) -> None:
    """Ekim 2026: 28 Ekim yarım gün tatil (öğleden sonra çalışıldı), 29 Ekim resmi tatil (4 saat
    çalışıldı). 45.000 TL: tatil ilavesi 1.500 (bir gün) + 750 (yarım gün); SGK matrahı 47.250."""
    services.add_fixed_holidays(manager, 2026)
    person = employee(manager, employee_no="S-1", hire_date=date(2024, 1, 1))
    _wage(manager, person, "45000")
    services.set_attendance_day(
        manager, person, date(2026, 10, 28), status=S.WORKED, holiday_half_worked=True
    )
    services.set_attendance_day(
        manager, person, date(2026, 10, 29), status=S.PUBLIC_HOLIDAY, overtime_hours=D(4)
    )
    row = _row(2026, 10, person)
    line = row.line
    # Ekim 2026 brütten nete bordronun ilk ayı: 2024'ten beri çalışan kişinin Eylül devri beklenir.
    assert not row.external and row.warnings == (selectors.OPENING_MISSING,)
    assert (row.entry_month, row.opening_needed, row.suggestion_months) == (10, True, 9)
    assert (line.holiday_days, line.holiday_half_days, line.holiday_pay) == (1, 1, D("2250.00"))
    assert (line.gross_total, line.sgk_base, line.sgk_days) == (D("47250.00"), D("47250.00"), 30)
    # 47.250 × %18,75 = 8.859,375 → kalem kalem: 10.276,88 − 2.362,50 + 945,00.
    assert line.employer_cost == D("56109.38")
    month = selectors.payroll_month(2026, 10)
    assert (month.gross_total, month.employer_cost) == (D("47250.00"), D("56109.38"))
    assert month.total("holiday_pay") == D("2250.00")


def test_half_holiday_flag_counts_only_on_half_day_holidays(manager: User) -> None:
    """İşaret yalnızca takvimde yarım gün tatil olan güne girilir; tatil sonradan kaldırılırsa
    hesapta sayılmaz."""
    services.add_fixed_holidays(manager, 2026)
    person = employee(manager)
    _wage(manager, person, "33030")
    day = date(2026, 10, 28)
    assert (
        _code(
            lambda: services.set_attendance_day(
                manager, person, date(2026, 10, 27), status=S.WORKED, holiday_half_worked=True
            )
        )
        == "not_half_holiday"
    )
    assert (
        _code(
            lambda: services.set_attendance_day(
                manager, person, day, status=S.ANNUAL_LEAVE, holiday_half_worked=True
            )
        )
        == "half_holiday_not_worked"
    )
    entry = services.set_attendance_day(
        manager, person, day, status=S.WORKED, holiday_half_worked=True
    )
    assert entry.holiday_half_worked
    grid = selectors.attendance_grid(2026, 10)
    cell = next(cell for cell in grid.rows[0].cells if cell.date == day)
    assert cell.holiday_half_worked
    assert _row(2026, 10, person).line.holiday_pay == D("550.50")
    # Aralık girişi çalışılmayan duruma geçen günün işaretini sıfırlar; çalışılan kalır.
    services.set_attendance_range(manager, start=day, end=day, status=S.WORKED, employee=person)
    assert AttendanceEntry.objects.get(employee=person, date=day).holiday_half_worked
    services.set_attendance_range(manager, start=day, end=day, status=S.SICK_LEAVE, employee=person)
    assert not AttendanceEntry.objects.get(employee=person, date=day).holiday_half_worked
    services.set_attendance_day(manager, person, day, status=S.WORKED, holiday_half_worked=True)
    holiday = selectors.holidays_between(day, day)[day]
    # Tatil tam güne çevrilir ya da kaldırılırsa saklı işaret durur ama tabloda, Excel'de ve
    # bordroda sayılmaz; yarım gün tatil geri gelince yeniden sayılır.
    assert _half_flag_shown(person, day)
    services.update_holiday(manager, holiday, {"half_day": False})
    assert not _half_flag_shown(person, day)
    services.update_holiday(manager, holiday, {"half_day": True})
    assert _half_flag_shown(person, day)
    services.remove_holiday(manager, holiday)
    assert not _half_flag_shown(person, day)
    assert AttendanceEntry.objects.get(employee=person, date=day).holiday_half_worked


def test_half_holiday_flag_cannot_be_set_ahead(manager: User) -> None:
    today = timezone.localdate()
    ahead = today + timedelta(days=3)
    services.add_holiday(manager, {"date": ahead, "name": "Arife", "half_day": True})
    person = employee(manager)
    assert (
        _code(
            lambda: services.set_attendance_day(
                manager, person, ahead, status=S.WORKED, holiday_half_worked=True
            )
        )
        == "future_day"
    )


def test_payroll_warnings(manager: User) -> None:
    """Uyarılar: ücret eksik, asgari ücretin altında aylık ücret (ay içinde giriş, çıkış ve zamda
    da), ay içinde çıkış (kıdem, ihbar ve izin ücreti hesaplanmaz)."""
    missing = employee(manager, full_name="Ece Ak")
    low = employee(manager, full_name="Can Kaya")
    _wage(manager, low, "30000")
    leaver = employee(manager, full_name="Deniz Su", hire_date=date(2024, 1, 1))
    _wage(manager, leaver, "45000")
    services.terminate_employee(manager, leaver, date(2026, 9, 20))
    month = selectors.payroll_month(2026, 9)
    warnings = {row.employee.pk: row.warnings for row in month.rows}
    assert warnings[missing.pk] == (selectors.MISSING_WAGE,)
    assert warnings[low.pk] == (selectors.BELOW_MINIMUM_WAGE,)
    assert warnings[leaver.pk] == (selectors.EXIT_IN_MONTH,)
    assert _row(2026, 9, low).line.floor_applied
    # Ay içinde giren ya da ayrılan: karşılaştırılan aylık ücrettir (kıst brüt değil).
    joiner = employee(manager, full_name="Ali Can", hire_date=date(2026, 9, 16))
    _wage(manager, joiner, "30000", valid_from=date(2026, 9, 16))
    low_leaver = employee(manager, full_name="Ayşe Er", hire_date=date(2024, 1, 1))
    _wage(manager, low_leaver, "30000")
    services.terminate_employee(manager, low_leaver, date(2026, 9, 20))
    joined = _row(2026, 9, joiner)
    assert joined.warnings == (selectors.BELOW_MINIMUM_WAGE,)
    # 15 gün: brüt 15.000,00; SGK matrahı 15 × 1.101 = 16.515,00; fark %15 → 227,25.
    assert (joined.line.gross_total, joined.line.sgk_base) == (D("15000.00"), D("16515.00"))
    assert joined.line.floor_applied and joined.line.floor_gap == D("227.25")
    assert _row(2026, 9, low_leaver).warnings == (
        selectors.BELOW_MINIMUM_WAGE,
        selectors.EXIT_IN_MONTH,
    )
    # Fazla mesaiyle brüt alt sınırı aşarsa uyarı kalır ama matrah alt sınıra çıkmaz.
    for day in (date(2026, 9, 1), date(2026, 9, 2)):
        services.set_attendance_day(manager, low, day, status=S.WORKED, overtime_hours=D("10"))
    overtime = _row(2026, 9, low)
    assert overtime.warnings == (selectors.BELOW_MINIMUM_WAGE,)
    assert overtime.line.gross_total == D("34000.00") and not overtime.line.floor_applied
    # Ay içinde zam: zamdan önceki ücretli günler asgari ücretin altındaysa uyarılır; o günler
    # ücretsiz izinse (eski ücretle ödeme yok) uyarılmaz.
    raised = employee(manager, full_name="Mert Öz")
    _wage(manager, raised, "32000")
    _wage(manager, raised, "36000", valid_from=date(2026, 9, 16))
    row = _row(2026, 9, raised)
    assert row.warnings == (selectors.BELOW_MINIMUM_WAGE,)
    assert row.line.gross_total == D("34000.00") and not row.line.floor_applied
    services.set_attendance_range(
        manager,
        start=date(2026, 9, 1),
        end=date(2026, 9, 15),
        status=S.UNPAID_LEAVE,
        employee=raised,
    )
    assert _row(2026, 9, raised).warnings == ()


def test_external_payroll(manager: User) -> None:
    """Bordrosu mali müşavirde olan kişi ERP'de hesaplanmaz: o ayın rakamları girilir; girilmemişse
    uyarı verilir. Rakam yalnızca işaretli ve o ay işte olan kişiye girilir."""
    person = employee(manager, payroll_external=True)
    regular = employee(manager, full_name="Can Kaya")
    row = _row(2026, 9, person)
    assert row.external and row.warnings == (selectors.EXTERNAL_MISSING,)
    assert (row.gross_total, row.employer_cost) == (D(0), D(0))

    def put(target: Employee, gross: str, cost: str, **when: int) -> Callable[[], Any]:
        return lambda: services.set_external_payroll(
            manager,
            target,
            when.get("year", 2026),
            when.get("month", 9),
            gross_total=D(gross),
            employer_cost=D(cost),
        )

    assert _code(put(regular, "1", "2")) == "not_external"
    assert _code(put(person, "-1", "2")) == "invalid_amount"
    assert _code(put(person, "50000", "40000")) == "invalid_employer_cost"
    assert _code(put(person, "1", "2", month=13)) == "invalid_period"
    hired_later = employee(manager, full_name="Ali Can", hire_date=date(2026, 10, 1))
    services.update_employee(manager, hired_later, {"payroll_external": True})
    assert _code(put(hired_later, "1", "2")) == "not_employed"
    figure = put(person, "41000", "50123.45")()
    assert figure.updated_by == manager
    again = put(person, "42000", "51000")()
    assert again.pk == figure.pk and ExternalPayrollFigure.objects.count() == 1
    row = _row(2026, 9, person)
    assert row.warnings == () and (row.gross_total, row.employer_cost) == (
        D("42000.00"),
        D("51000.00"),
    )
    month = selectors.payroll_month(2026, 9)
    assert month.employer_cost == D("51000.00") and month.computed == [
        row for row in month.rows if row.employee.pk == regular.pk
    ]
    # Ayın tamamı raporlu ya da ücretsiz izinli kişide mali müşavirin rakamları 0 / 0 olabilir.
    put(person, "0", "0")()
    zero = _row(2026, 9, person)
    assert zero.warnings == () and (zero.gross_total, zero.employer_cost) == (D(0), D(0))


def test_payroll_month_queries_do_not_grow_with_external_figures(manager: User) -> None:
    """Mali müşavir rakamları (ve onları girenler) kişi başına ek sorgu açmaz."""

    def add_external(name: str) -> None:
        person = employee(manager, full_name=name, payroll_external=True)
        services.set_external_payroll(
            manager, person, 2026, 9, gross_total=D("40000"), employer_cost=D("48000")
        )

    def count() -> int:
        with CaptureQueriesContext(connection) as queries:
            assert PayrollMonthSerializer(selectors.payroll_month(2026, 9)).data
        return len(queries)

    add_external("Ali Can")
    one = count()
    add_external("Can Kaya")
    add_external("Ece Ak")
    assert count() == one


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_only_management_writes_payroll_data(
    make_user: Callable[..., User], manager: User, role: str
) -> None:
    person = employee(manager, payroll_external=True)
    record = parameter_set(manager)
    other = make_user(role)
    calls = [
        lambda: services.create_parameter_set(other, parameter_values(valid_from=date(2026, 7, 1))),
        lambda: services.update_parameter_set(other, record, {"incentive_points": D(0)}),
        lambda: services.remove_parameter_set(other, record, "X"),
        lambda: services.set_external_payroll(
            other, person, 2026, 9, gross_total=D(1), employer_cost=D(2)
        ),
        lambda: services.record_payroll_access(other, 2026, 9, "Excel"),
    ]
    for call in calls:
        with pytest.raises(PermissionDenied):
            call()
    assert PayrollParameterSet.objects.count() == 1


# --- çıktılar ----------------------------------------------------------------------------------


def test_employer_cost_rows_and_lines(manager: User) -> None:
    """İşveren maliyeti tablosunun satırları: birim birim kişiler, çok kişili birimin toplamı ve
    genel toplam; bordrosu mali müşavirde olan satırda yalnızca girilen rakamlar."""
    first = employee(manager, employee_no="S-1", department="Dolum")
    second = employee(manager, employee_no="S-2", full_name="Can Kaya", department="Dolum")
    third = employee(manager, employee_no="S-3", full_name="Ece Ak", department="Depo")
    external = employee(
        manager, employee_no="S-4", full_name="Ali Can", department="Depo", payroll_external=True
    )
    for person in (first, second, third):
        _wage(manager, person, "45000")
    services.set_external_payroll(
        manager, external, 2026, 9, gross_total=D("40000"), employer_cost=D("48000")
    )
    month = selectors.payroll_month(2026, 9)
    lines = pdf.employer_cost_rows(month)
    kinds = [kind for kind, _ in lines]
    assert kinds == ["row", "row", "subtotal", "row", "row", "subtotal", "total"]
    # Birim içinde ada göre (ekrandaki gibi): Depo'da Ali Can, sonra Ece Ak.
    assert lines[1][1][:5] == ["S-3", "Ece Ak", "Depo", "30", "45.000,00"]
    assert lines[1][1][6:] == ["9.787,50", "−2.250,00", "900,00", "0,00", "53.437,50", "%118,75"]
    depo_external = lines[0][1]
    assert depo_external[:6] == ["S-4", "Ali Can", "Depo", "—", "40.000,00", pdf.EXTERNAL_TEXT]
    assert depo_external[10:] == ["48.000,00", "%120"]
    assert lines[5][1][1] == "Dolum toplamı" and lines[5][1][10] == "106.875,00"
    total = lines[-1][1]
    assert total[1] == "Genel toplam"
    assert (total[4], total[10]) == ("175.000,00", "208.312,50")
    assert "parametreler kaydedilmedi (2026 yasal değerleriyle)" in pdf.status_line(month)
    assert pdf.status_line(month).startswith("Puantaj açık")
    line = pdf.parameter_line(month)
    assert "Asgari ücret 33.030,00 TL" in line and "etkin işveren oranı %18,75" in line


def test_employer_cost_pdf_draws_external_figures(
    manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF'te mali müşavirdeki kişinin brütü ve maliyeti çizilir: not yalnızca hesaplanmayan
    sütunları kaplar (birleşik hücrenin altında kalan hücreler çizilmez)."""
    _wage(manager, employee(manager, employee_no="S-1"), "45000")
    external = employee(manager, employee_no="S-2", full_name="Ali Can", payroll_external=True)
    services.set_external_payroll(
        manager, external, 2026, 9, gross_total=D("40000"), employer_cost=D("48000")
    )
    drawn: list[Any] = []
    original = Table._drawCell

    def spy(self: Table, cellval: Any, *args: Any) -> None:
        drawn.append(cellval)
        original(self, cellval, *args)

    monkeypatch.setattr(Table, "_drawCell", spy)
    content = pdf.employer_cost_pdf(selectors.payroll_month(2026, 9))
    assert content.startswith(b"%PDF")
    texts = {value for value in drawn if isinstance(value, str)}
    # Toplamlar 85.000,00 ve 101.437,50; bu rakamlar yalnızca kişinin satırından gelir.
    assert {"40.000,00", "48.000,00", pdf.EXTERNAL_TEXT} <= texts


def _sheet(workbook: Any, name: str) -> list[tuple[Any, ...]]:
    return list(workbook[name].iter_rows(values_only=True))


def test_payroll_excel(manager: User) -> None:
    person = employee(manager, employee_no="S-1")
    _wage(manager, person, "45000")
    workbook = load_workbook(BytesIO(exports.payroll_xlsx(selectors.payroll_month(2026, 9))))
    # Başlangıç ayından (Ekim 2026) önce brütten nete sayfalar yok.
    assert workbook.sheetnames == ["İşveren maliyeti", "Eksik gün", "Parametreler"]
    rows = _sheet(workbook, "İşveren maliyeti")
    assert rows[0][0] == "İşveren maliyeti — Eylül 2026 (ön bordro · TASLAK)"
    assert rows[1][0] == exports.DRAFT_NOTE
    assert _sheet(workbook, "Parametreler")[0] == ("Bordro parametreleri", "Eylül 2026 · TASLAK")
    header = rows.index(tuple(exports.EMPLOYER_COST_COLUMNS))
    data = dict(zip(exports.EMPLOYER_COST_COLUMNS, rows[header + 1], strict=True))
    assert data["Sicil no"] == "S-1" and data["SGK gün"] == 30
    assert D(str(data["İşverene maliyet (TL)"])) == D("53437.50")
    assert D(str(data["Teşvik (TL)"])) == D("-2250")
    assert rows[header + 2][1] == "Genel toplam"
    parameters = {row[0]: row[1] for row in _sheet(workbook, "Parametreler")}
    assert D(str(parameters["Etkin işveren oranı (%)"])) == D("18.75")
    assert D(str(parameters["Asgari ücret istisna matrahı (TL)"])) == D("28075.50")
    assert D(str(parameters["Nakit yemek SGK istisnası (günlük TL)"])) == D("0")
    # Onaylı bordronun (4. adım) Excel'inde TASLAK yazmaz.
    final = load_workbook(BytesIO(exports.payroll_xlsx(selectors.payroll_month(2026, 9), stamp="")))
    texts = [
        value
        for name in final.sheetnames
        for row in _sheet(final, name)
        for value in row
        if isinstance(value, str)
    ]
    assert not any("TASLAK" in value for value in texts)


def test_employer_cost_pdf_draft_stamp(manager: User, monkeypatch: pytest.MonkeyPatch) -> None:
    """Onaylanmamış bordronun PDF'inde her sayfada çapraz TASLAK damgası; onaylıda yok."""
    _wage(manager, employee(manager), "45000")
    stamped: list[str] = []
    original = Canvas.drawCentredString

    def spy(self: Canvas, x: float, y: float, text: str, *args: Any, **kwargs: Any) -> None:
        stamped.append(text)
        original(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Canvas, "drawCentredString", spy)
    month = selectors.payroll_month(2026, 9)
    pdf.employer_cost_pdf(month, stamp=pdf.DRAFT)
    assert stamped.count("TASLAK") == 1  # tek sayfa
    stamped.clear()
    pdf.employer_cost_pdf(month, stamp="")
    assert "TASLAK" not in stamped


def test_attendance_excel_marks_half_holiday_work(manager: User) -> None:
    services.add_fixed_holidays(manager, 2026)
    person = employee(manager)
    services.set_attendance_day(
        manager, person, date(2026, 10, 28), status=S.WORKED, holiday_half_worked=True
    )
    workbook = load_workbook(BytesIO(exports.attendance_xlsx(selectors.attendance_grid(2026, 10))))
    rows = _sheet(workbook, "Puantaj")
    header = list(rows[1])
    assert rows[2][header.index("28 Ça")] == exports.HALF_HOLIDAY_CODE
    legend = [row[0] for row in _sheet(workbook, "Kodlar")]
    assert exports.HALF_HOLIDAY_CODE in legend


# --- API ---------------------------------------------------------------------------------------


def test_payroll_month_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager, employee_no="S-1", department="Dolum", bes_enrolled=True)
    _wage(manager, person, "45000")
    body = client.get(f"{BASE}/payroll/2026/9/").json()
    assert body["period_label"] == "Eylül 2026" and body["attendance_approved"] is False
    parameters = body["parameters"]
    assert (parameters["origin"], parameters["year"], parameters["record"]) == (
        "legal_default",
        2026,
        None,
    )
    assert parameters["values"]["employer_rate"] == "18.75"
    assert parameters["values"]["tax_brackets"][0] == "190000.00"
    (row,) = body["rows"]
    assert row["employee"]["employee_no"] == "S-1" and row["employee"]["bes_enrolled"] is True
    assert row["external"] is False and row["figure"] is None and row["warnings"] == []
    # Eylül 2026 başlangıçtan önce: işveren maliyeti var, brütten nete kalemler boş.
    assert (body["net"], body["net_available"], body["start"]) == (False, False, "2026-10")
    assert row["line"]["employer_cost"] == "53437.50" and row["line"]["bes_deduction"] is None
    assert row["line"]["net_pay"] is None and row["line"]["income_tax"] is None
    assert row["employer_cost"] == "53437.50"
    assert body["totals"]["employer_cost"] == "53437.50" and body["totals"]["net_pay"] is None
    assert body["totals"]["computed_employer_cost"] == "53437.50"
    assert body["totals"]["employee_count"] == 1 and body["totals"]["external_count"] == 0
    assert client.get(f"{BASE}/payroll/2026/9/", {"department": "Depo"}).json()["rows"] == []
    assert client.get(f"{BASE}/payroll/2026/13/").status_code == 404


def test_payroll_outputs_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager)
    _wage(manager, person, "45000")
    response = client.get(f"{BASE}/payroll/2026/9/employer-cost.pdf")
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert response["Content-Disposition"] == (
        'inline; filename="isveren-maliyeti-2026-09-taslak.pdf"'
    )
    assert response["Cache-Control"] == "no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    excel = client.get(f"{BASE}/payroll/2026/9/xlsx/")
    assert excel.status_code == 200
    assert excel["Content-Disposition"] == 'attachment; filename="bordro-2026-09-taslak.xlsx"'
    assert excel["Cache-Control"] == "no-store"
    notes = list(
        AuditLog.objects.filter(note__startswith="Bordro çıktısı açıldı").values_list(
            "note", flat=True
        )
    )
    assert sorted(notes) == [
        "Bordro çıktısı açıldı: Bordro (Excel) · Eylül 2026",
        "Bordro çıktısı açıldı: İşveren maliyeti (PDF) · Eylül 2026",
    ]


def test_parameter_set_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    defaults = client.get(f"{BASE}/payroll/parameters/defaults/", {"year": 2026}).json()
    assert defaults["known"] is True and defaults["values_year"] == 2026
    assert defaults["values"]["minimum_wage"] == "33030.00" and defaults["legal_source"]
    future = client.get(f"{BASE}/payroll/parameters/defaults/", {"year": 2031}).json()
    assert (future["known"], future["values_year"], future["legal_source"]) == (False, 2026, "")
    payload = {
        key: (str(value) if not isinstance(value, date) else "2026-01")
        for key, value in parameter_values().items()
    }
    response = client.post(f"{BASE}/payroll/parameters/", payload, format="json")
    assert response.status_code == 201, response.json()
    created = response.json()
    assert created["valid_from"] == "2026-01-01" and created["year"] == 2026
    assert created["derived"]["employer_rate"] == "18.75"
    assert created["derived"]["daily_ceiling"] == "9909.00"
    response = client.post(f"{BASE}/payroll/parameters/", payload, format="json")
    assert response.status_code == 400 and response.json()["code"] == "duplicate_parameters"
    response = client.patch(
        f"{BASE}/payroll/parameters/{created['id']}/", {"incentive_points": "2"}, format="json"
    )
    assert response.status_code == 200 and response.json()["derived"]["employer_rate"] == "21.75"
    assert client.get(f"{BASE}/payroll/2026/9/").json()["parameters"]["origin"] == "saved"
    listed = client.get(f"{BASE}/payroll/parameters/").json()
    assert [item["id"] for item in listed] == [created["id"]]
    assert client.delete(f"{BASE}/payroll/parameters/{created['id']}/").status_code == 405
    response = client.post(
        f"{BASE}/payroll/parameters/{created['id']}/remove/", {"reason": "Yanlış"}, format="json"
    )
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert client.get(f"{BASE}/payroll/parameters/").json() == []


def test_external_payroll_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager, payroll_external=True)
    response = client.post(
        f"{BASE}/payroll/2026/9/external/",
        {"employee": person.pk, "gross_total": "41000", "employer_cost": "50000", "note": "Eylül"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["employer_cost"] == "50000.00"
    row = client.get(f"{BASE}/payroll/2026/9/").json()["rows"][0]
    assert row["external"] is True and row["figure"]["gross_total"] == "41000.00"
    assert row["employer_cost"] == "50000.00"
    response = client.post(
        f"{BASE}/payroll/2026/9/external/",
        {"employee": person.pk, "gross_total": "41000", "employer_cost": "1"},
        format="json",
    )
    assert response.status_code == 400 and response.json()["code"] == "invalid_employer_cost"


def test_card_payroll_flags_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager)
    response = client.patch(
        f"{BASE}/employees/{person.pk}/",
        {"payroll_external": True, "bes_enrolled": True},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["payroll_external"] is True and response.json()["bes_enrolled"] is True
    history = client.get(f"{BASE}/employees/{person.pk}/history/").json()
    assert history[0]["changes"]["payroll_external"] == [False, True]


def test_attendance_day_api_half_holiday(
    client_for: Callable[..., APIClient], manager: User
) -> None:
    services.add_fixed_holidays(manager, 2026)
    client = client_for("yonetim")
    person = employee(manager)
    response = client.post(
        f"{BASE}/attendance/days/",
        {
            "employee": person.pk,
            "date": "2026-10-28",
            "status": "WORKED",
            "holiday_half_worked": True,
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["holiday_half_worked"] is True
    grid = client.get(f"{BASE}/attendance/2026/10/").json()
    cell = next(cell for cell in grid["rows"][0]["cells"] if cell["date"] == "2026-10-28")
    assert cell["holiday_half_worked"] is True


def test_admin_reaches_payroll_and_anonymous_is_rejected(
    client_for: Callable[..., APIClient], api_client: APIClient, manager: User
) -> None:
    employee(manager)
    admin = client_for("admin")
    for url in (
        f"{BASE}/payroll/2026/9/",
        f"{BASE}/payroll/2026/9/employer-cost.pdf",
        f"{BASE}/payroll/2026/9/xlsx/",
        f"{BASE}/payroll/parameters/",
    ):
        assert admin.get(url).status_code == 200, url
        assert api_client.get(url).status_code in (401, 403), url


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_reach_payroll(
    client_for: Callable[..., APIClient], manager: User, role: str
) -> None:
    person = employee(manager, payroll_external=True)
    record = parameter_set(manager)
    client = client_for(role)
    checks = [
        client.get(f"{BASE}/payroll/2026/9/"),
        client.get(f"{BASE}/payroll/2026/9/employer-cost.pdf"),
        client.get(f"{BASE}/payroll/2026/9/xlsx/"),
        client.post(
            f"{BASE}/payroll/2026/9/external/",
            {"employee": person.pk, "gross_total": "1", "employer_cost": "2"},
        ),
        client.get(f"{BASE}/payroll/parameters/"),
        client.get(f"{BASE}/payroll/parameters/defaults/", {"year": 2026}),
        client.post(f"{BASE}/payroll/parameters/", {}),
        client.patch(f"{BASE}/payroll/parameters/{record.pk}/", {"incentive_points": "0"}),
        client.post(f"{BASE}/payroll/parameters/{record.pk}/remove/", {"reason": "X"}),
    ]
    assert [response.status_code for response in checks] == [403] * len(checks)
    assert not ExternalPayrollFigure.objects.exists()
    assert not AuditLog.objects.filter(note__startswith="Bordro çıktısı açıldı").exists()
