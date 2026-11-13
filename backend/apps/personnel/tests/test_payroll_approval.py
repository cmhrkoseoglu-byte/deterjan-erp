"""Bordro onayı (4. adım; docs/DECISIONS.md "Personel bordrosu", "4. adım kararları"): onay ve
denetimleri, saklanan satırlar, ay kilitleri, yeniden açma ve onaydaki işaretler, ödeme tarihi,
zincirin onaylı satırdan kurulması, ücret pusulası, çıktıların damgası, API ve yetki.

Bugün 20.01.2027 sayılır (Ekim–Aralık 2026 bitmiş aylardır). Örnek kişi: 50.000 TL brüt, Eylül sonu
devri 382.500 ve 9 ay asgari ücret istisnası. Ekim: GV 4.634,90, net 37.736,30; Kasım (Ekim'in
42.500 matrahıyla kümülatif 425.000): GV 5.859,90, net 36.511,30."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from openpyxl import load_workbook
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import exports, pdf, selectors, services
from apps.personnel.models import (
    AttendanceMonth,
    AttendanceStatus,
    Employee,
    PayrollApproval,
    PayrollItemCategory,
    PayrollParameterSet,
    PayrollRun,
    PayrollSlip,
)
from apps.personnel.tests.factories import employee, parameter_set

pytestmark = pytest.mark.django_db
D = Decimal
C = PayrollItemCategory
S = AttendanceStatus
BASE = "/api/v1/personnel"
OTHER_ROLES = ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]
VALID_TC = "10000000146"
TODAY = date(2027, 1, 20)


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Bugün 20.01.2027 (Ekim–Aralık 2026 onaylanabilir)."""
    original = timezone.localdate

    def fake(*args: Any, **kwargs: Any) -> date:
        return TODAY if not args and not kwargs else original(*args, **kwargs)

    monkeypatch.setattr(timezone, "localdate", fake)
    return TODAY


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


@pytest.fixture
def stamps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """PDF sayfalarına basılan çapraz damgalar (TASLAK, GEÇERSİZ)."""
    found: list[str] = []
    original = Canvas.drawCentredString

    def spy(self: Canvas, x: float, y: float, text: str, *args: Any, **kwargs: Any) -> None:
        found.append(text)
        original(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Canvas, "drawCentredString", spy)
    return found


def _pages(content: bytes) -> int:
    return content.count(b"/Type /Page") - content.count(b"/Type /Pages")


def _run_log(run: PayrollRun, **filters: Any) -> AuditLog:
    """Bordro kaydının denetim günlüğünden tek kayıt."""
    content_type = ContentType.objects.get_for_model(PayrollRun)
    return AuditLog.objects.get(content_type=content_type, object_id=run.pk, **filters)


def _code(call: Callable[[], Any]) -> str:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value.code


def _wage(actor: User, person: Employee, amount: str = "50000", since: date = date(2020, 1, 1)):
    return services.add_wage(
        actor, {"employee": person, "gross_monthly": D(amount), "valid_from": since}
    )


def _person(actor: User, name: str = "Ali Kaya", **extra: Any) -> Employee:
    """2020'den beri çalışan, 50.000 TL brüt, Eylül sonu devri girilmiş kişi."""
    person = employee(
        actor,
        full_name=name,
        department=extra.pop("department", "Üretim"),
        hire_date=date(2020, 1, 1),
        **extra,
    )
    _wage(actor, person)
    services.set_opening_balance(actor, person, 2026, 10, tax_base=D("382500"), exemption_months=9)
    return person


def _item(actor: User, person: Employee, category: str, amount: str, month: int = 10) -> Any:
    return services.add_payroll_item(
        actor,
        {
            "employee": person,
            "year": 2026,
            "month": month,
            "category": category,
            "description": "Avans" if category == C.ADVANCE else "",
            "amount": D(amount),
        },
    )


def _approve(
    actor: User,
    month: int = 10,
    *,
    year: int = 2026,
    acknowledged: tuple[str, ...] = (),
    payment: date | None = None,
    attendance: bool = True,
) -> PayrollRun:
    if attendance and not services._month_locked(year, month):
        services.approve_attendance_month(actor, year, month)
    fingerprint = selectors.payroll_fingerprint(selectors.payroll_month(year, month))
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    return services.approve_payroll_month(
        actor,
        year,
        month,
        payment_date=payment or date(next_year, next_month, 10),
        fingerprint=fingerprint,
        acknowledged=acknowledged,
    )


@pytest.fixture
def approved(manager: User) -> tuple[Employee, PayrollRun]:
    """Ekim 2026 bordrosu onaylı (parametreler kayıtlı, bir kişi)."""
    parameter_set(manager)
    person = _person(manager, national_id=VALID_TC, employee_no="S-1")
    return person, _approve(manager)


# --- onay ve saklanan satırlar ---------------------------------------------------------------


def test_approval_stores_the_month(manager: User, approved: tuple[Employee, PayrollRun]) -> None:
    person, run = approved
    assert (run.number, run.status, run.year, run.month) == ("BR-2026-00001", "APPROVED", 2026, 10)
    approval = run.current
    assert approval is not None and approval.sequence == 1
    assert (approval.approved_by, approval.payment_date) == (manager, date(2026, 11, 10))
    assert approval.attendance_number.startswith("PU-2026-")
    assert approval.engine_version == "2026.3"
    assert approval.parameters["origin"] == "saved"
    assert approval.parameters["values"]["minimum_wage"] == "33030.00"
    assert (approval.employee_count, approval.external_count) == (1, 0)
    assert (approval.gross_total, approval.income_tax, approval.net_pay) == (
        D("50000.00"),
        D("4634.90"),
        D("37736.30"),
    )
    slip = PayrollSlip.objects.get(approval=approval)
    assert (slip.employee, slip.external, slip.bes_enrolled) == (person, False, False)
    assert slip.person["masked_national_id"] == "*******0146"
    assert "national_id" not in slip.person and VALID_TC not in str(slip.person)
    assert (slip.net_pay, slip.payable, slip.income_tax) == (
        D("37736.30"),
        D("37736.30"),
        D("4634.90"),
    )
    assert (slip.tax_base_after, slip.exemption_base_after) == (D("425000.00"), D("280755.00"))
    assert slip.chain["entry_month"] == 10 and slip.chain["carry_months"][0]["source"] == "opening"
    assert slip.line["income_tax"] == "4634.90" and slip.warnings == []
    # Satır değiştirilmez ve silinmez.
    with pytest.raises(ValueError):
        slip.save()
    with pytest.raises(ValueError):
        slip.delete()
    assert _run_log(run, note__contains="1 kişi (0 mali müşavirde) · ödeme 10.11.2026")


def test_approved_month_reads_stored_lines(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Onaydan sonra kart değişse de (ad, birim, mali müşavir ve BES işareti) onaylı ay onaydaki
    satırı gösterir."""
    person, run = approved
    services.update_employee(
        manager,
        person,
        {"full_name": "Ali Yılmaz", "department": "Depo", "bes_enrolled": True},
    )
    month = selectors.payroll_month(2026, 10)
    assert month.approved and month.approval == run.current and month.number == run.number
    row = month.rows[0]
    assert (row.person.full_name, row.person.department) == ("Ali Kaya", "Üretim")
    assert (row.line.net_pay, row.bes, row.external) == (D("37736.30"), False, False)
    assert row.opening is not None and row.opening.month == 10
    assert selectors.payroll_gates(month) == []
    # Personel maliyeti de onaydaki satırı ve birimi kullanır (net=False).
    cost = selectors.payroll_month(2026, 10, net=False)
    assert cost.approved and cost.rows[0].person.department == "Üretim"


def test_month_locks_after_approval(manager: User, approved: tuple[Employee, PayrollRun]) -> None:
    person, _ = approved
    assert _code(lambda: _item(manager, person, C.PREMIUM, "100")) == "payroll_approved"
    assert (
        _code(
            lambda: services.set_opening_balance(
                manager, person, 2026, 10, tax_base=D("1"), exemption_months=9
            )
        )
        == "payroll_approved"
    )
    record = AttendanceMonth.objects.get(year=2026, month=10)
    assert (
        _code(lambda: services.reopen_attendance_month(manager, record, "düzeltme"))
        == "payroll_approved"
    )
    # Ekim'in günlerine düşen ücret: reddedilir; Kasım'dan geçerli zam serbest.
    assert _code(lambda: _wage(manager, person, "60000", date(2026, 10, 15))) == "payroll_approved"
    raise_ = _wage(manager, person, "60000", date(2026, 11, 1))
    first = person.wages.get(valid_from=date(2020, 1, 1))
    assert _code(lambda: services.remove_wage(manager, first, "x")) == "payroll_approved"
    services.remove_wage(manager, raise_, "yanlış")
    # İşe giriş tarihi Ekim'i değiştirirse reddedilir; Ekim'e dokunmayan değişiklik serbest.
    assert (
        _code(lambda: services.update_employee(manager, person, {"hire_date": date(2026, 10, 5)}))
        == "payroll_approved"
    )
    services.update_employee(manager, person, {"hire_date": date(2019, 6, 1)})


def test_parameter_changes_that_touch_an_approved_month_are_refused(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    record = PayrollParameterSet.objects.get(is_active=True)
    assert (
        _code(lambda: services.update_parameter_set(manager, record, {"incentive_points": D("4")}))
        == "payroll_approved"
    )
    assert _code(lambda: services.remove_parameter_set(manager, record, "x")) == "payroll_approved"
    # Not ve kaynak düzeltmesi onaylı ayın değerlerini değiştirmez.
    services.update_parameter_set(manager, record, {"note": "mali müşavirle teyit"})
    # Kasım'dan geçerli yeni set Ekim'i değiştirmez; Ekim'den geçerli set değiştirir.
    values = {
        name: getattr(record, name)
        for name in services.PARAMETER_FIELDS
        if name not in ("valid_from", "source", "note")
    }
    created = services.create_parameter_set(
        manager, {**values, "valid_from": date(2026, 11, 1), "incentive_points": D("4")}
    )
    assert created.valid_from == date(2026, 11, 1)
    assert (
        _code(
            lambda: services.create_parameter_set(
                manager, {**values, "valid_from": date(2026, 10, 1), "incentive_points": D("4")}
            )
        )
        == "payroll_approved"
    )
    assert PayrollParameterSet.objects.filter(is_active=True).count() == 2


# --- onay denetimleri ---------------------------------------------------------------------------


def _gates(month: int = 10) -> dict[str, tuple[str, list[str]]]:
    found = selectors.payroll_gates(selectors.payroll_month(2026, month))
    return {gate.code: (gate.level, [person.full_name for person in gate.people]) for gate in found}


def test_month_level_gates(manager: User) -> None:
    person = employee(manager, full_name="Ali Kaya", hire_date=date(2026, 10, 1))
    _wage(manager, person)
    gates = _gates()
    assert gates[selectors.GATE_ATTENDANCE_OPEN] == ("block", [])
    assert gates[selectors.GATE_PARAMETERS] == ("block", [])
    assert selectors.GATE_PREVIOUS_OPEN not in gates  # başlangıç ayı
    assert selectors.GATE_PREVIOUS_OPEN in _gates(11)
    with pytest.raises(services.PayrollGateError) as exc:
        _approve(manager, attendance=False)
    assert exc.value.code == "payroll_not_ready"
    assert "puantaj onaylanmadı" in exc.value.message
    assert "parametreleri kaydedilmedi" in exc.value.message
    parameter_set(manager)
    run = _approve(manager)
    assert run.status == "APPROVED"
    # Kasım'da kimse yoksa "kişi yok"; Ekim onaylı olduğu için önceki ay engeli kalkar.
    services.terminate_employee(manager, person, date(2026, 10, 31))
    gates = _gates(11)
    assert selectors.GATE_PREVIOUS_OPEN not in gates
    assert gates[selectors.GATE_NO_EMPLOYEES] == ("block", [])
    assert selectors.payroll_gates(selectors.payroll_month(2026, 9)) == [
        selectors.Gate(selectors.GATE_BEFORE_START, "block")
    ]
    assert _code(lambda: _approve(manager, 9)) == "before_start"


def test_row_warnings_block_or_need_acknowledgement(manager: User) -> None:
    parameter_set(manager)
    missing = employee(manager, full_name="Ayşe Demir", hire_date=date(2020, 1, 1))  # devir yok
    low = employee(manager, full_name="Can Er", hire_date=date(2026, 10, 1))
    _wage(manager, low, "20000")
    leaver = _person(manager, "Deniz Ak")
    services.terminate_employee(manager, leaver, date(2026, 10, 20), remove_attendance=True)
    external = employee(
        manager, full_name="Ece Su", hire_date=date(2026, 10, 1), payroll_external=True
    )
    services.approve_attendance_month(manager, 2026, 10)
    gates = _gates()
    assert gates[selectors.MISSING_WAGE] == ("block", ["Ayşe Demir"])
    assert gates[selectors.OPENING_MISSING] == ("block", ["Ayşe Demir"])
    assert gates[selectors.BELOW_MINIMUM_WAGE] == ("block", ["Can Er"])
    assert gates[selectors.EXTERNAL_MISSING] == ("block", ["Ece Su"])
    assert gates[selectors.EXIT_IN_MONTH] == ("acknowledge", ["Deniz Ak"])
    with pytest.raises(services.PayrollGateError) as exc:
        _approve(manager)
    message = exc.value.message
    assert "ücret eksik: Ayşe Demir" in message and "asgari ücretin altında: Can Er" in message
    assert "mali müşavir rakamı girilmedi: Ece Su" in message
    # Engeller giderilince yalnızca "okudum" kalır.
    _wage(manager, missing)
    services.set_opening_balance(
        manager, missing, 2026, 10, tax_base=D("382500"), exemption_months=9
    )
    _wage(manager, low, "40000", date(2026, 10, 1))
    services.set_external_payroll(
        manager, external, 2026, 10, gross_total=D("40000"), employer_cost=D("47500")
    )
    with pytest.raises(services.PayrollGateError) as exc:
        _approve(manager)
    assert exc.value.code == "acknowledgement_required"
    assert "ay içinde çıkış: Deniz Ak" in exc.value.message
    run = _approve(manager, acknowledged=(selectors.EXIT_IN_MONTH,))
    approval = run.current
    assert approval is not None
    assert approval.acknowledged == [{"code": "exit_in_month", "employees": [leaver.pk]}]
    assert (approval.employee_count, approval.external_count) == (3, 1)
    slip = approval.slips.get(employee=external)
    assert slip.external and slip.net_pay is None and slip.tax_base_after is None
    assert slip.figure is not None and slip.figure["employer_cost"] == "47500.00"
    assert approval.employer_cost == sum(
        (item.employer_cost for item in approval.slips.all()), D(0)
    )


def test_negative_payable_and_orphan_items_block(manager: User) -> None:
    parameter_set(manager)
    person = _person(manager)
    _item(manager, person, C.ADVANCE, "45000")
    services.approve_attendance_month(manager, 2026, 10)
    assert _gates()[selectors.NEGATIVE_PAYABLE] == ("block", ["Ali Kaya"])
    services.remove_payroll_item(manager, person.payroll_items.get(), "yanlış")
    assert selectors.NEGATIVE_PAYABLE not in _gates()
    # Puantaj onaylandıktan sonra açılan kartın Ekim'de günü yok: kalemi bordroda görünmez.
    late = employee(manager, full_name="Geç Kart", hire_date=date(2026, 10, 1))
    _item(manager, late, C.PREMIUM, "100")
    assert _gates()[selectors.GATE_ORPHAN_ITEMS] == ("block", ["Geç Kart"])
    with pytest.raises(services.PayrollGateError) as exc:
        _approve(manager)
    assert "o ay işte olmayan kişiye girilmiş kalem var: Geç Kart" in exc.value.message


def test_external_items_are_a_notice(manager: User) -> None:
    """Mali müşavirdeki kişiye ERP'de girilmiş kalem onayı engellemez (2026-11-03 "Onaylansın,
    listede yazsın"): rakam girilince yalnızca bilgi kalır; onaylı bordro listesinin mali müşavir
    bölümünde kalem toplamlarıyla (açıklamasız) yazılır."""
    parameter_set(manager)
    person = _person(manager)
    _item(manager, person, C.PREMIUM, "1000")
    services.update_employee(manager, person, {"payroll_external": True})
    services.approve_attendance_month(manager, 2026, 10)
    gates = _gates()
    assert gates[selectors.EXTERNAL_ITEMS] == ("notice", ["Ali Kaya"])
    assert gates[selectors.EXTERNAL_MISSING] == ("block", ["Ali Kaya"])
    services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("51000"), employer_cost=D("60000")
    )
    assert _gates() == {selectors.EXTERNAL_ITEMS: ("notice", ["Ali Kaya"])}
    run = _approve(manager)
    approval = run.current
    assert approval is not None
    assert approval.acknowledged == [{"code": "external_items", "employees": [person.pk]}]
    slip = approval.slips.get(employee=person)
    assert slip.external and [item["category"] for item in slip.items] == ["PREMIUM"]
    month = selectors.payroll_month(2026, 10)
    assert month.approved
    assert pdf.external_rows(month)[0][3] == "ERP'de girilen kalemler hesaplanmadı: Prim 1.000,00"


def test_external_figure_after_following_the_card_in_a_reopened_month(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Onaylı ayda ERP'de hesaplanan kişinin kartı sonradan "mali müşavirde" işaretlenir; ay yeniden
    açılıp kişi kartı izleyince kalemi olsa da rakamı girilir ve ay onaylanır."""
    person, run = approved
    services.reopen_payroll_month(manager, run, "kontrol")
    _item(manager, person, C.PREMIUM, "1000")
    services.update_employee(manager, person, {"payroll_external": True})
    services.set_payroll_follow_card(manager, run, person, follow=True)
    services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("51000"), employer_cost=D("60000")
    )
    again = _approve(manager)
    assert again.current is not None and again.current.sequence == 2
    slip = again.current.slips.get(employee=person)
    assert slip.external and slip.figure is not None and slip.person["payroll_external"]


def test_fingerprint_and_payment_date(manager: User) -> None:
    parameter_set(manager)
    person = _person(manager)
    services.approve_attendance_month(manager, 2026, 10)
    seen = selectors.payroll_fingerprint(selectors.payroll_month(2026, 10))
    _item(manager, person, C.PREMIUM, "500")  # pencere açıkken değişti

    def approve(fingerprint: str, payment: date | None) -> PayrollRun:
        return services.approve_payroll_month(
            manager, 2026, 10, payment_date=payment, fingerprint=fingerprint
        )

    assert _code(lambda: approve(seen, date(2026, 11, 10))) == "payroll_changed"
    fresh = selectors.payroll_fingerprint(selectors.payroll_month(2026, 10))
    assert fresh != seen
    assert _code(lambda: approve(fresh, None)) == "payment_date_required"
    assert _code(lambda: approve(fresh, date(2026, 9, 30))) == "invalid_payment_date"
    assert _code(lambda: approve(fresh, date(2027, 2, 1))) == "invalid_payment_date"
    assert not PayrollRun.objects.exists()  # reddedilen onay numara harcamaz
    run = approve(fresh, date(2027, 1, 31))
    assert run.current is not None and run.current.payment_date == date(2027, 1, 31)


# --- sıra, yeniden açma ve onaydaki işaretler --------------------------------------------------


def test_months_are_approved_in_order_and_reopened_from_the_end(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    person, october = approved
    november = _approve(manager, 11)
    assert november.number == "BR-2026-00002"
    assert _code(lambda: services.reopen_payroll_month(manager, october, "x")) == (
        "later_payroll_approved"
    )
    assert _code(lambda: services.reopen_payroll_month(manager, november, " ")) == "reason_required"
    reopened = services.reopen_payroll_month(manager, november, "prim eksik")
    assert reopened.status == "OPEN" and reopened.current is None
    first = PayrollApproval.objects.get(run=november, sequence=1)
    assert (first.reopened_by, first.reopen_reason) == (manager, "prim eksik")
    assert first.reopened_at is not None
    # Açılan ay canlı hesaplanır; düzeltilip yeniden onaylanır (aynı numara, 2. onay).
    _item(manager, person, C.PREMIUM, "1000", month=11)
    again = _approve(manager, 11)
    assert again.number == "BR-2026-00002" and again.current is not None
    assert again.current.sequence == 2 and again.current.gross_total == D("51000.00")
    month = selectors.payroll_month(2026, 11)
    assert [item.sequence for item in month.history] == [1, 2]
    # Eski onay saklanır: istenirse onun satırları (kalem yok, brüt 50.000).
    old = selectors.payroll_month(2026, 11, approval=1)
    assert old.superseded and old.rows[0].line.gross_total == D("50000.00")
    assert old.rows[0].items == ()
    with pytest.raises(LookupError):
        selectors.payroll_month(2026, 11, approval=9)
    # Ekim yeniden açılınca puantajı da açılabilir.
    services.reopen_payroll_month(manager, again, "kontrol")
    services.reopen_payroll_month(manager, october, "kontrol")
    record = AttendanceMonth.objects.get(year=2026, month=10)
    assert services.reopen_attendance_month(manager, record, "düzeltme").status == "OPEN"


def test_reopened_month_keeps_the_approval_flags(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Yeniden açılan ayda kişi onaydaki işaretlerle hesaplanır; kartın bugünkü işaretlerine
    geçirmek ayrıca seçilir ve kayda geçer."""
    person, run = approved
    services.update_employee(manager, person, {"payroll_external": True, "bes_enrolled": True})
    reopened = services.reopen_payroll_month(manager, run, "kontrol")
    month = selectors.payroll_month(2026, 10)
    row = month.rows[0]
    assert not row.external and not row.bes and row.line.net_pay == D("37736.30")
    assert [
        (change.employee, change.approved_external, change.approved_bes, change.following)
        for change in month.card_changes
    ] == [(person, False, False, False)]
    # Kalem girilebilir (kişi bu ay ERP'de hesaplanıyor).
    item = _item(manager, person, C.PREMIUM, "100")
    services.remove_payroll_item(manager, item, "deneme")
    followed = services.set_payroll_follow_card(manager, reopened, person, follow=True)
    assert followed.follow_card == [person.pk]
    row = selectors.payroll_month(2026, 10).rows[0]
    assert row.external and row.warnings == (selectors.EXTERNAL_MISSING,)
    note = selectors.employee_history(person).first()
    assert note is not None and "kartın bugünkü işaretleriyle" in note.note
    services.set_payroll_follow_card(manager, reopened, person, follow=False)
    assert not selectors.payroll_month(2026, 10).rows[0].external
    stranger = employee(manager, full_name="Yeni Kişi")
    assert (
        _code(lambda: services.set_payroll_follow_card(manager, reopened, stranger, follow=True))
        == "not_in_approval"
    )
    # Yeniden onayda işaretler onaydaki haliyle saklanır (kart "mali müşavirde" olsa da ERP).
    again = _approve(manager)
    slip = again.current.slips.get(employee=person) if again.current else None
    assert slip is not None and not slip.external and not slip.person["payroll_external"]


def test_payment_date_correction(manager: User, approved: tuple[Employee, PayrollRun]) -> None:
    _, run = approved
    assert (
        _code(lambda: services.set_payroll_payment_date(manager, run, date(2026, 11, 12), ""))
        == "reason_required"
    )
    assert (
        _code(lambda: services.set_payroll_payment_date(manager, run, date(2027, 3, 1), "banka"))
        == "invalid_payment_date"
    )
    services.set_payroll_payment_date(manager, run, date(2026, 11, 12), "banka tatili")
    approval = PayrollApproval.objects.get(run=run)
    assert approval.payment_date == date(2026, 11, 12) and approval.net_pay == D("37736.30")
    log = _run_log(run, note__contains="banka tatili")
    assert log.changes == {"payment_date": ["2026-11-10", "2026-11-12"]}
    services.reopen_payroll_month(manager, run, "x")
    assert (
        _code(lambda: services.set_payroll_payment_date(manager, run, date(2026, 11, 12), "x"))
        == "payroll_not_approved"
    )


# --- zincir onaylı satırdan ----------------------------------------------------------------------


def test_next_month_anchors_on_the_approved_slip(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    person, run = approved
    row = next(item for item in selectors.payroll_month(2026, 11).rows if item.employee == person)
    assert (row.line.income_tax, row.line.net_pay) == (D("5859.90"), D("36511.30"))
    assert [(link.month, link.source) for link in row.carry_months] == [(10, "approved")]
    assert (row.entry_month, row.opening_needed, row.opening) == (10, False, None)
    # Kümülatif saklı satırdan okunur (Ekim yeniden hesaplanmaz).
    PayrollSlip.objects.filter(approval=run.current).update(tax_base_after=D("500000"))
    row = next(item for item in selectors.payroll_month(2026, 11).rows if item.employee == person)
    assert row.line.cumulative_tax_base_before == D("500000.00")
    # Kasım'a girilen devir onaylı satırın yerine geçer (mali müşavirle eşitleme).
    assert (
        _code(
            lambda: services.set_opening_balance(
                manager, person, 2026, 11, tax_base=D("425000"), exemption_months=10
            )
        )
        == "opening_overrides_chain"
    )
    services.set_opening_balance(
        manager,
        person,
        2026,
        11,
        tax_base=D("425000"),
        exemption_months=10,
        confirm_override=True,
    )
    row = next(item for item in selectors.payroll_month(2026, 11).rows if item.employee == person)
    assert row.line.cumulative_tax_base_before == D("425000.00")
    assert [(link.month, link.source) for link in row.carry_months] == [(11, "opening")]
    # Eşitleme devri: giriş ayı zincirin devirden önceki girişidir (ekran devri düzeltirken de
    # eşitleme onayı ister; sunucu Ekim ERP'de olduğu için ister).
    assert row.entry_month == 10 and not row.opening_needed


def test_approved_external_slip_breaks_the_chain(manager: User) -> None:
    parameter_set(manager)
    person = _person(manager)
    services.update_employee(manager, person, {"payroll_external": True})
    services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("50000"), employer_cost=D("59375")
    )
    _approve(manager)
    services.update_employee(manager, person, {"payroll_external": False})
    row = next(item for item in selectors.payroll_month(2026, 11).rows if item.employee == person)
    assert row.entry_month == 11 and row.opening_needed
    assert selectors.OPENING_MISSING in row.warnings


def test_query_count_of_an_approved_month(manager: User) -> None:
    """Onaylı ayın okunması kişi sayısından bağımsız sabit sayıda sorgudur."""
    parameter_set(manager)
    for index in range(2):
        _person(manager, f"Kişi {index}")
    run = _approve(manager)
    with CaptureQueriesContext(connection) as few:
        selectors.payroll_month(2026, 10)
    services.reopen_payroll_month(manager, run, "ekle")
    record = AttendanceMonth.objects.get(year=2026, month=10)
    services.reopen_attendance_month(manager, record, "ekle")
    for index in range(2, 6):
        _person(manager, f"Kişi {index}")
    _approve(manager)
    with CaptureQueriesContext(connection) as many:
        month = selectors.payroll_month(2026, 10)
    assert len(month.rows) == 6 and month.approved
    assert len(many) == len(few)


# --- kart ve ayrılış ---------------------------------------------------------------------------


def test_switching_a_card_to_external_lists_unapproved_records(
    manager: User, client_for: Callable[..., APIClient], approved: tuple[Employee, PayrollRun]
) -> None:
    person, _ = approved
    _item(manager, person, C.PREMIUM, "5000", month=11)
    client = client_for("yonetim")
    response = client.patch(
        f"{BASE}/employees/{person.pk}/", {"payroll_external": True}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["payroll_external_records"] == ["Kasım 2026 Prim 5.000,00 TL"]
    note = selectors.employee_history(person).first()
    assert note is not None and "Kasım 2026 Prim 5.000,00 TL" in note.note
    assert "Ekim" not in note.note  # onaylı ay saklı satırıyla korunur
    again = client.patch(f"{BASE}/employees/{person.pk}/", {"title": "Usta"}, format="json")
    assert "payroll_external_records" not in again.json()


def test_exit_after_approved_attendance_says_reopen_the_payroll_first(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    person, run = approved
    # Çıkıştan sonraki aya kalem de var: önce onaylı puantaj denetlenir (bordroyu açma mesajı).
    _item(manager, person, C.PREMIUM, "100", month=11)
    with pytest.raises(services.ApprovedAttendanceAfterExit) as exc:
        services.terminate_employee(manager, person, date(2026, 10, 20))
    assert f"önce bordroyu Personel > Bordro'dan (Ekim 2026 {run.number}), sonra bu ayı" in (
        exc.value.message
    )


# --- çıktılar -----------------------------------------------------------------------------------


def test_outputs_of_an_approved_month(
    manager: User, approved: tuple[Employee, PayrollRun], stamps: list[str]
) -> None:
    _, run = approved
    month = selectors.payroll_month(2026, 10)
    assert pdf.heading_status(month, "") == f"Ön bordro · {run.number} · 1. onay"
    assert pdf.status_line(month).startswith(f"Bordro onaylı: {run.number} · 1. onay")
    assert "ödeme 10.11.2026" in pdf.status_line(month)
    assert pdf.register_rows(month)[0][1][0].endswith("TC *******0146")
    assert pdf.register_pdf(month, stamp="").startswith(b"%PDF") and stamps == []
    workbook = load_workbook(BytesIO(exports.payroll_xlsx(month, stamp="")))
    texts = [
        str(value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows(values_only=True)
        for value in row
        if value
    ]
    assert not any("TASLAK" in value for value in texts)
    assert any(run.number in value for value in texts)
    services.reopen_payroll_month(manager, run, "kontrol")
    old = selectors.payroll_month(2026, 10, approval=1)
    assert "GEÇERSİZ" in pdf.approval_line(old)
    assert pdf.heading_status(old, pdf.SUPERSEDED).endswith("· GEÇERSİZ")
    pdf.register_pdf(old, stamp=pdf.SUPERSEDED)
    assert stamps == ["GEÇERSİZ", "GEÇERSİZ"]  # liste + icmal


def test_payslips(manager: User, approved: tuple[Employee, PayrollRun], stamps: list[str]) -> None:
    person, run = approved
    month = selectors.payroll_month(2026, 10)
    row = month.rows[0]
    sections = pdf.payslip_lines(row)
    assert sections["earnings"][0] == ("Normal ücret", "30 gün", "50.000,00")
    assert ("Kesilen gelir vergisi", "", "4.634,90") in sections["taxes"]
    assert sections["payable"] == [("Ödenecek", "", "37.736,30")]
    assert sections["deductions"] == [("Kesinti yok", "", "0,00")]
    person_block = dict(pdf.payslip_person(month, row))
    assert person_block["TC kimlik no"] == "*******0146" and person_block["Sicil no"] == "S-1"
    assert VALID_TC not in str(person_block)
    content = pdf.payslips_pdf(month)
    assert content.startswith(b"%PDF") and _pages(content) == 1 and stamps == []
    with pytest.raises(ValueError):
        pdf.payslips_pdf(selectors.payroll_month(2026, 11))
    # Mali müşavirdeki kişinin pusulası yok; hepsinin pusulasında son sayfada adı yazar.
    services.reopen_payroll_month(manager, run, "ekle")
    other = employee(
        manager, full_name="Ece Su", hire_date=date(2026, 10, 1), payroll_external=True
    )
    services.set_external_payroll(
        manager, other, 2026, 10, gross_total=D("40000"), employer_cost=D("47500")
    )
    record = AttendanceMonth.objects.get(year=2026, month=10)
    services.reopen_attendance_month(manager, record, "ekle")
    again = _approve(manager)
    month = selectors.payroll_month(2026, 10)
    assert [row.person.full_name for row in month.computed] == ["Ali Kaya"]
    assert _pages(pdf.payslips_pdf(month)) == 2  # Ali Kaya + mali müşavirdekiler
    assert _pages(pdf.payslips_pdf(month, employee_id=person.pk)) == 1
    assert again.current is not None and again.current.sequence == 2
    pdf.payslips_pdf(selectors.payroll_month(2026, 10, approval=1))
    assert stamps == ["GEÇERSİZ"]


def test_payslip_api_and_access_trail(
    manager: User, client_for: Callable[..., APIClient], approved: tuple[Employee, PayrollRun]
) -> None:
    person, run = approved
    # Sicil onaydan sonra değişse de dosya adında onaydaki sicil yazar.
    services.update_employee(manager, person, {"employee_no": "S-9"})
    client = client_for("yonetim")
    response = client.get(f"{BASE}/payroll/2026/10/payslips.pdf", {"employee": person.pk})
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response["Cache-Control"] == "no-store"
    assert "ucret-pusulasi-2026-10-S-1-BR-2026-00001-onay1.pdf" in (response["Content-Disposition"])
    log = _run_log(run, note__contains="Ücret hesap pusulası (PDF)")
    assert log.changes == {"year": 2026, "month": 10, "employee": person.pk}
    note = selectors.employee_history(person).first()
    assert note is not None and note.note == "Ücret hesap pusulası açıldı: Ekim 2026"
    unknown = client.get(f"{BASE}/payroll/2026/10/payslips.pdf", {"employee": 999999})
    assert unknown.status_code == 404
    open_month = client.get(f"{BASE}/payroll/2026/11/payslips.pdf")
    assert open_month.status_code == 400 and open_month.json()["code"] == "payroll_not_approved"
    services.reopen_payroll_month(manager, run, "kontrol")
    old = client.get(f"{BASE}/payroll/2026/10/payslips.pdf", {"approval": 1})
    assert old.status_code == 200
    assert client.get(f"{BASE}/payroll/2026/10/register.pdf", {"approval": 7}).status_code == 404


# --- API ----------------------------------------------------------------------------------------


def test_approval_api(manager: User, client_for: Callable[..., APIClient]) -> None:
    parameter_set(manager)
    person = _person(manager, national_id=VALID_TC)
    services.approve_attendance_month(manager, 2026, 10)
    client = client_for("yonetim")
    body = client.get(f"{BASE}/payroll/2026/10/").json()
    state = body["payroll"]
    assert (state["status"], state["approved"], state["number"], state["run"]) == (
        "OPEN",
        False,
        "",
        None,
    )
    assert state["gates"] == [] and len(state["fingerprint"]) == 24
    assert (
        client.get(f"{BASE}/payroll/2026/10/", {"department": "Üretim"}).json()["payroll"]["gates"]
        is None
    )
    rejected = client.post(
        f"{BASE}/payroll/2026/10/approve/",
        {"payment_date": "2026-11-10", "fingerprint": "eski"},
        format="json",
    )
    assert rejected.status_code == 400 and rejected.json()["code"] == "payroll_changed"
    approved = client.post(
        f"{BASE}/payroll/2026/10/approve/",
        {"payment_date": "2026-11-10", "fingerprint": state["fingerprint"]},
        format="json",
    )
    assert approved.status_code == 200, approved.json()
    assert approved.json()["number"] == "BR-2026-00001" and approved.json()["status"] == "APPROVED"
    state = client.get(f"{BASE}/payroll/2026/10/").json()["payroll"]
    assert state["approved"] and state["can_reopen"] and state["gates"] is None
    assert state["approval"]["payment_date"] == "2026-11-10"
    assert state["approval"]["approved_by_name"] and len(state["history"]) == 1
    grid = client.get(f"{BASE}/attendance/2026/10/").json()
    assert grid["payroll"] == {"number": "BR-2026-00001", "status": "APPROVED"}
    blocked = client.post(
        f"{BASE}/payroll/items/",
        {"employee": person.pk, "year": 2026, "month": 10, "category": "PREMIUM", "amount": "5"},
        format="json",
    )
    assert blocked.status_code == 400 and blocked.json()["code"] == "payroll_approved"
    moved = client.post(
        f"{BASE}/payroll/2026/10/payment-date/",
        {"payment_date": "2026-11-11", "reason": "banka"},
        format="json",
    )
    assert moved.status_code == 200 and moved.json()["current"]["payment_date"] == "2026-11-11"
    reopened = client.post(f"{BASE}/payroll/2026/10/reopen/", {"reason": "kontrol"}, format="json")
    assert reopened.status_code == 200 and reopened.json()["status"] == "OPEN"
    follow = client.post(
        f"{BASE}/payroll/2026/10/follow-card/",
        {"employee": person.pk, "follow": True},
        format="json",
    )
    assert follow.status_code == 200 and follow.json()["status"] == "OPEN"
    assert client.post(f"{BASE}/payroll/2026/12/reopen/", {"reason": "x"}).status_code == 404


def test_approval_gate_errors_in_the_api(
    manager: User, client_for: Callable[..., APIClient]
) -> None:
    person = employee(manager, full_name="Ali Kaya", hire_date=date(2020, 1, 1))
    client = client_for("yonetim")
    body = client.get(f"{BASE}/payroll/2026/10/").json()
    codes = [gate["code"] for gate in body["payroll"]["gates"]]
    assert codes[:2] == ["attendance_open", "parameters_not_saved"]
    missing = next(gate for gate in body["payroll"]["gates"] if gate["code"] == "missing_wage")
    assert missing == {
        "code": "missing_wage",
        "level": "block",
        "employees": [{"id": person.pk, "full_name": "Ali Kaya"}],
    }
    response = client.post(
        f"{BASE}/payroll/2026/10/approve/",
        {"payment_date": "2026-11-10", "fingerprint": body["payroll"]["fingerprint"]},
        format="json",
    )
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "payroll_not_ready" and "ücret eksik: Ali Kaya" in data["detail"]
    assert {gate["code"] for gate in data["gates"]} >= {"attendance_open", "missing_wage"}


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_approval_endpoints_need_the_personnel_role(
    role: str, client_for: Callable[..., APIClient]
) -> None:
    client = client_for(role)
    assert client.post(f"{BASE}/payroll/2026/10/approve/", {}).status_code == 403
    assert client.post(f"{BASE}/payroll/2026/10/reopen/", {}).status_code == 403
    assert client.post(f"{BASE}/payroll/2026/10/payment-date/", {}).status_code == 403
    assert client.post(f"{BASE}/payroll/2026/10/follow-card/", {}).status_code == 403
    assert client.get(f"{BASE}/payroll/2026/10/payslips.pdf").status_code == 403


def test_services_need_the_personnel_role(
    make_user: Callable[..., User], approved: tuple[Employee, PayrollRun]
) -> None:
    from django.core.exceptions import PermissionDenied

    person, run = approved
    other = make_user("depo")
    for call in (
        lambda: services.approve_payroll_month(
            other, 2026, 11, payment_date=date(2026, 12, 10), fingerprint=""
        ),
        lambda: services.reopen_payroll_month(other, run, "x"),
        lambda: services.set_payroll_payment_date(other, run, date(2026, 11, 12), "x"),
        lambda: services.set_payroll_follow_card(other, run, person, follow=True),
    ):
        with pytest.raises(PermissionDenied):
            call()


def test_payslip_items_show_category_and_description(manager: User) -> None:
    """Pusula kişinin kendi belgesidir: ek ödeme ve kesintiler kategori sırasıyla, açıklamasıyla
    yazılır; eski (yeniden açılmış) onayın pusulası saklanan kalemlerden kurulur."""
    parameter_set(manager)
    person = _person(manager)
    for category, amount, text in (
        (C.MEAL, "2200", ""),
        (C.PREMIUM, "5000", ""),
        (C.GARNISHMENT, "2500", "2026/1234 E."),
        (C.ADVANCE, "3000", "Ekim avansı"),
    ):
        services.add_payroll_item(
            manager,
            {
                "employee": person,
                "year": 2026,
                "month": 10,
                "category": category,
                "description": text,
                "amount": D(amount),
            },
        )
    run = _approve(manager)
    expected_extras = [("Prim", "", "5.000,00"), ("Yemek (nakit)", "", "2.200,00")]
    expected_deductions = [
        ("Avans (Ekim avansı)", "", "3.000,00"),
        ("İcra / nafaka (2026/1234 E.)", "", "2.500,00"),
    ]
    sections = pdf.payslip_lines(selectors.payroll_month(2026, 10).rows[0])
    assert sections["earnings"][1:3] == expected_extras
    assert sections["deductions"] == expected_deductions
    services.reopen_payroll_month(manager, run, "kontrol")
    for item in person.payroll_items.filter(is_active=True):
        services.remove_payroll_item(manager, item, "deneme")
    old = selectors.payroll_month(2026, 10, approval=1).rows[0]
    assert pdf.payslip_lines(old)["deductions"] == expected_deductions


# --- inceleme düzeltmeleri ---------------------------------------------------------------------


def _row_of(month: int, person: Employee) -> selectors.PayrollRow:
    return next(row for row in selectors.payroll_month(2026, month).rows if row.employee == person)


def test_person_missing_from_an_approved_month_needs_an_opening_in_the_first_open_month(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Ekim onaylandıktan sonra açılan (ya da tarihleri değişen) kartın Ekim'de satırı yok: o ayın
    kümülatifi bilinmez, zincir kopar ve devir ilk açık aya (Kasım) istenir; Ekim'e (kilitli)
    istenmez."""
    _, run = approved
    june = employee(manager, full_name="Ayşe Demir", hire_date=date(2026, 6, 1))
    _wage(manager, june, "50000", date(2026, 6, 1))
    late = employee(manager, full_name="Deniz Ak", hire_date=date(2026, 10, 20))
    _wage(manager, late, "200000", date(2026, 10, 20))
    new = employee(manager, full_name="Ece Su", hire_date=date(2026, 11, 2))
    _wage(manager, new, "40000", date(2026, 11, 2))
    for person, months in ((june, 5), (late, 1)):
        row = _row_of(11, person)
        assert [(link.month, link.source) for link in row.carry_months] == [(10, "missing")]
        assert (row.entry_month, row.opening_needed, row.suggestion_months) == (11, True, months)
        assert selectors.OPENING_MISSING in row.warnings
    row = _row_of(11, new)
    assert (row.entry_month, row.opening_needed, row.carry_months) == (11, False, ())
    # Kasım devri eşitleme onayı istemeden girilir (Ekim'de satırı yok).
    services.set_opening_balance(manager, june, 2026, 11, tax_base=D("212500"), exemption_months=5)
    row = _row_of(11, june)
    assert selectors.OPENING_MISSING not in row.warnings
    assert [(link.month, link.source) for link in row.carry_months] == [(11, "opening")]
    # Ekim yeniden açılıp kişiye Ekim devri girilse de (puantajda günü yok) zincir Ekim'i bilmez.
    services.reopen_payroll_month(manager, run, "devir")
    services.set_opening_balance(manager, june, 2026, 10, tax_base=D("170000"), exemption_months=4)
    _approve(manager)
    row = _row_of(11, june)
    assert row.opening is not None and row.opening.month == 11  # Kasım devri çapa
    services.remove_opening_balance(manager, row.opening, "deneme")
    row = _row_of(11, june)
    assert selectors.OPENING_MISSING in row.warnings and row.entry_month == 11


def test_chain_follows_the_month_flags_of_a_reopened_month(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Ekim ve Kasım onaylı, kişi ERP'de; kart "mali müşavirde" işaretlenir, iki ay yeniden açılır
    ve Ekim'de kişi kartı izler: Ekim mali müşavirde sayılır, Kasım (onaydaki işaretle ERP'de)
    zinciri Ekim'de koparak devir ister."""
    person, october = approved
    november = _approve(manager, 11)
    services.update_employee(manager, person, {"payroll_external": True})
    services.reopen_payroll_month(manager, november, "kontrol")
    services.reopen_payroll_month(manager, october, "kontrol")
    services.set_payroll_follow_card(manager, october, person, follow=True)
    assert _row_of(10, person).external
    row = _row_of(11, person)
    assert not row.external
    assert [(link.month, link.source) for link in row.carry_months] == [
        (10, "opening"),
        (10, "external"),
    ]
    assert row.entry_month == 11 and selectors.OPENING_MISSING in row.warnings


def test_chain_skips_a_month_the_person_was_not_in_after_a_hire_date_fix(manager: User) -> None:
    """İşe giriş tarihi sonradan ileri alınan kişinin eski günlerinin puantaj kaydı kalır; o ay
    bordroda değildir: kartı izlese de zincir o ayı mali müşavirde saymaz, ay da kişiyi kartı
    değişenler arasında yazmaz."""
    parameter_set(manager)
    _person(manager)
    person = employee(manager, full_name="Ayşe Demir", hire_date=date(2026, 10, 1))
    _wage(manager, person, "40000", date(2026, 10, 1))
    october = _approve(manager)
    november = _approve(manager, 11)
    services.update_employee(manager, person, {"payroll_external": True})
    services.reopen_payroll_month(manager, november, "kontrol")
    services.reopen_payroll_month(manager, october, "kontrol")
    services.update_employee(manager, person, {"hire_date": date(2026, 11, 1)})
    services.set_payroll_follow_card(manager, october, person, follow=True)
    month = selectors.payroll_month(2026, 10)
    assert person not in [row.employee for row in month.rows]
    assert person not in [change.employee for change in month.card_changes]
    row = _row_of(11, person)
    assert not row.external
    assert (row.carry_months, row.entry_month, row.opening_needed) == ((), 10, False)


def test_hire_date_moved_back_keeps_a_later_approved_slip(manager: User) -> None:
    """Ekim onaylı (kişi yok), Kasım onaylı (kişi 01.11'de girdi, zincir sıfırdan): işe giriş
    20.10'a alınırsa Kasım'ın kümülatifi Ekim'i saymadan kuruldu; reddedilir. Kasım yeniden
    açılınca kaydedilir ve Kasım devir ister. Ekim'i kapsayan bir devirle onaylanmış kişide ise
    tarih geri alınabilir."""
    parameter_set(manager)
    _person(manager)
    services.approve_attendance_month(manager, 2026, 10)
    late = employee(manager, full_name="Deniz Ak", hire_date=date(2026, 10, 20))
    _wage(manager, late, "60000", date(2026, 10, 20))
    _approve(manager)
    person = employee(manager, full_name="Ayşe Demir", hire_date=date(2026, 11, 1))
    _wage(manager, person, "200000", date(2026, 11, 1))
    # Ekim'in kümülatifi bilinmeyen kişiye Kasım devri (Ekim'i kapsar), sonra Kasım onayı.
    services.set_opening_balance(manager, late, 2026, 11, tax_base=D("20000"), exemption_months=1)
    november = _approve(manager, 11)
    with pytest.raises(BusinessRuleError) as exc:
        services.update_employee(manager, person, {"hire_date": date(2026, 10, 20)})
    assert exc.value.code == "payroll_approved"
    assert "Ekim 2026 ayında işte sayılır" in exc.value.message
    assert f"Kasım 2026 bordrosunun ({november.number}) kümülatifi" in exc.value.message
    # Devir Ekim'i kapsıyor: tarih geri alınabilir.
    services.update_employee(manager, late, {"hire_date": date(2026, 10, 1)})
    services.reopen_payroll_month(manager, november, "işe giriş")
    services.update_employee(manager, person, {"hire_date": date(2026, 10, 20)})
    row = _row_of(11, person)
    assert [(link.month, link.source) for link in row.carry_months] == [(10, "missing")]
    assert (row.entry_month, row.opening_needed, row.suggestion_months) == (11, True, 1)
    assert selectors.OPENING_MISSING in row.warnings


def test_hire_date_moved_before_the_payroll_start_keeps_the_first_slip(manager: User) -> None:
    """01.10.2026'da giren kişinin Ekim satırı devirsiz onaylandı: işe giriş Eylül'e, daha önceye
    alınır ya da silinirse Ekim'in kümülatifi Ocak–Eylül'ü saymadan kuruldu; reddedilir. Ekim
    yeniden açılınca kaydedilir ve Ekim devir ister."""
    parameter_set(manager)
    person = employee(manager, full_name="Ayşe Demir", hire_date=date(2026, 10, 1))
    _wage(manager, person, "50000", date(2026, 10, 1))
    october = _approve(manager)
    for hire in (date(2026, 9, 1), date(2015, 3, 1), None):
        with pytest.raises(BusinessRuleError) as exc:
            services.update_employee(manager, person, {"hire_date": hire})
        assert exc.value.code == "payroll_approved", hire
        assert f"Ekim 2026 bordrosunun ({october.number}) kümülatifi" in exc.value.message
    services.reopen_payroll_month(manager, october, "işe giriş")
    services.update_employee(manager, person, {"hire_date": date(2026, 9, 1)})
    row = _row_of(10, person)
    assert (row.entry_month, row.opening_needed, row.suggestion_months) == (10, True, 1)
    assert selectors.OPENING_MISSING in row.warnings


def test_devir_after_an_external_and_a_missing_month_enters_at_the_devir(manager: User) -> None:
    """Ekim mali müşavirde (rakam), Kasım bordroda yok (puantajı onaylı, günü yok): Aralık devri
    eşitleme onayı istemeden girilir ve giriş ayı Aralık kalır (devir penceresi kişiyi listeler)."""
    parameter_set(manager)
    _person(manager)
    services.approve_attendance_month(manager, 2026, 10)
    services.approve_attendance_month(manager, 2026, 11)
    late = employee(
        manager, full_name="Deniz Ak", hire_date=date(2020, 1, 1), payroll_external=True
    )
    _wage(manager, late, "60000")
    october = AttendanceMonth.objects.get(year=2026, month=10)
    services.reopen_attendance_month(manager, october, "kart geç açıldı")
    services.set_external_payroll(
        manager, late, 2026, 10, gross_total=D("60000"), employer_cost=D("71250")
    )
    services.update_employee(manager, late, {"payroll_external": False})
    row = _row_of(12, late)
    assert [(link.month, link.source) for link in row.carry_months] == [
        (10, "external"),
        (11, "missing"),
    ]
    assert row.entry_month == 12 and selectors.OPENING_MISSING in row.warnings
    services.set_opening_balance(manager, late, 2026, 12, tax_base=D("650000"), exemption_months=11)
    row = _row_of(12, late)
    assert (row.entry_month, row.opening_needed) == (12, False)


def test_switch_warning_counts_a_figure_as_external(
    manager: User, client_for: Callable[..., APIClient]
) -> None:
    """Yeniden açılan ayda o aya mali müşavir rakamı girilmiş kişi mali müşavirdedir: kart "mali
    müşavirde" işaretlenince o ayın kaydı ERP'de kalıyor diye yazılmaz, mali müşavire bildirilir."""
    parameter_set(manager)
    person = _person(manager)
    services.update_employee(manager, person, {"payroll_external": True})
    services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("50000"), employer_cost=D("59375")
    )
    services.update_employee(manager, person, {"payroll_external": False})
    run = _approve(manager)
    slip = PayrollSlip.objects.get(approval=run.current, employee=person)
    assert slip.external and not slip.person["payroll_external"]
    services.reopen_payroll_month(manager, run, "kontrol")
    response = client_for("yonetim").patch(
        f"{BASE}/employees/{person.pk}/", {"payroll_external": True}, format="json"
    )
    body = response.json()
    assert body["payroll_external_records"] == ["Ekim 2026 devri"]
    assert body["payroll_external_kept"] == []
    note = selectors.employee_history(person).first()
    assert note is not None
    assert "Mali müşavire bildirin" in note.note and "Yeniden açılan" not in note.note
    month = selectors.payroll_month(2026, 10)
    assert month.rows[0].external and month.card_changes[0].figure_keeps_external


def test_devir_after_a_month_the_person_was_not_in_needs_no_confirmation(manager: User) -> None:
    """Ekim puantajı onaylı, bordrosu açık; kart sonradan 20.10 girişle açıldı (Ekim'de günü yok):
    zincir Ekim'de kopar, Kasım devri eşitleme onayı istemeden girilir. Ekim'de günü olan kişide
    eşitleme onayı istenir."""
    parameter_set(manager)
    regular = _person(manager)
    services.approve_attendance_month(manager, 2026, 10)
    late = employee(manager, full_name="Deniz Ak", hire_date=date(2026, 10, 20))
    _wage(manager, late, "60000", date(2026, 10, 20))
    assert not selectors.in_payroll(late, 2026, 10) and selectors.in_payroll(regular, 2026, 10)
    row = _row_of(11, late)
    assert [(link.month, link.source) for link in row.carry_months] == [(10, "missing")]
    assert row.entry_month == 11 and selectors.OPENING_MISSING in row.warnings
    services.set_opening_balance(manager, late, 2026, 11, tax_base=D("20000"), exemption_months=1)
    row = _row_of(11, late)
    assert (row.entry_month, row.opening_needed) == (11, False)
    assert (
        _code(
            lambda: services.set_opening_balance(
                manager, regular, 2026, 11, tax_base=D("425000"), exemption_months=10
            )
        )
        == "opening_overrides_chain"
    )


def test_card_change_tells_a_figure_keeps_the_person_external(manager: User) -> None:
    """Ekim'de mali müşavirde onaylanan kişinin kartı ERP'ye alınıp yeniden açılan ayda kartı
    izlenir: girilmiş rakam kişiyi mali müşavirde tutar; kart değişikliği bunu yazar."""
    parameter_set(manager)
    person = _person(manager)
    services.update_employee(manager, person, {"payroll_external": True})
    services.set_external_payroll(
        manager, person, 2026, 10, gross_total=D("50000"), employer_cost=D("59375")
    )
    run = _approve(manager)
    services.reopen_payroll_month(manager, run, "kontrol")
    services.update_employee(manager, person, {"payroll_external": False})
    [change] = selectors.payroll_month(2026, 10).card_changes
    assert (change.following, change.stored_external, change.figure_keeps_external) == (
        False,
        True,
        False,
    )
    services.set_payroll_follow_card(manager, run, person, follow=True)
    month = selectors.payroll_month(2026, 10)
    [change] = month.card_changes
    assert (change.following, change.stored_external, change.figure_keeps_external) == (
        True,
        True,
        True,
    )
    assert month.rows[0].external
    again = _approve(manager)
    assert again.current is not None and again.current.slips.get(employee=person).external


def test_switch_warning_tells_reopened_months_stay_in_erp(
    manager: User, client_for: Callable[..., APIClient], approved: tuple[Employee, PayrollRun]
) -> None:
    """Kart "mali müşavirde" işaretlenince yeniden açılan ayın kaydı (kişi onaydaki haliyle
    ERP'de) ayrıca yazılır ve "Kartı izle" gösterilir; diğer ayların kaydı mali müşavire
    bildirilir."""
    person, run = approved
    services.reopen_payroll_month(manager, run, "prim")
    _item(manager, person, C.PREMIUM, "5000")
    _item(manager, person, C.PREMIUM, "700", month=11)
    response = client_for("yonetim").patch(
        f"{BASE}/employees/{person.pk}/", {"payroll_external": True}, format="json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["payroll_external_records"] == [
        f"Ekim 2026 Prim 5.000,00 TL ({selectors.KEPT_ERP_NOTE})",
        f"Ekim 2026 devri ({selectors.KEPT_ERP_NOTE})",
        "Kasım 2026 Prim 700,00 TL",
    ]
    assert body["payroll_external_kept"] == ["Ekim 2026"]
    note = selectors.employee_history(person).first()
    assert note is not None
    assert "Yeniden açılan Ekim 2026 son onaydaki haliyle ERP'de hesaplanır" in note.note
    assert "Diğer aylardakileri mali müşavire bildirin" in note.note
    # Kartı izleyince Ekim de kartın işaretine uyar.
    services.set_payroll_follow_card(manager, run, person, follow=True)
    assert selectors.kept_erp_months(person) == []
    assert services.external_switch_note(["Kasım 2026 Prim 700,00 TL"], []).endswith(
        "Mali müşavire bildirin; gerekmiyorsa Personel > Bordro'dan gerekçeyle kaldırın."
    )
    # Kayıtların hepsi yeniden açılan ayda ERP'de kalıyorsa bildirme ya da kaldırma denmez.
    kept_only = services.external_switch_note(
        [f"Ekim 2026 Prim 5.000,00 TL ({selectors.KEPT_ERP_NOTE})"], ["Ekim 2026"]
    )
    assert '"Kartı izle"' in kept_only
    assert "bildirin" not in kept_only and "kaldırın" not in kept_only


def test_messages_name_the_step_that_unlocks_the_write(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Onaylı aydaki devir işe giriş tarihine sığmıyorsa mesaj önce bordroyu yeniden açmayı söyler;
    yeniden açılan ayda onaydaki haliyle ERP'de olan kişiye mali müşavir rakamı girilmez, mesaj
    "Kartı izle"yi gösterir."""
    person, run = approved
    with pytest.raises(BusinessRuleError) as exc:
        services.update_employee(manager, person, {"hire_date": date(2026, 3, 1)})
    assert exc.value.code == "opening_months_exceed_hire"
    assert "Ekim 2026 devri (9 ay; en çok 7)" in exc.value.message
    assert "Ekim 2026 bordrosu onaylı: önce Personel > Bordro'dan gerekçeyle yeniden açın" in (
        exc.value.message
    )

    def figure() -> Any:
        return services.set_external_payroll(
            manager, person, 2026, 10, gross_total=D("1"), employer_cost=D("1")
        )

    services.reopen_payroll_month(manager, run, "kontrol")
    with pytest.raises(BusinessRuleError) as exc:
        figure()
    assert exc.value.code == "not_external"
    assert 'kartında "Bordrosu mali müşavirde" işaretli değil' in exc.value.message
    services.update_employee(manager, person, {"payroll_external": True})
    with pytest.raises(BusinessRuleError) as exc:
        figure()
    assert exc.value.code == "not_external"
    assert (
        "onaydaki haliyle ERP'de; kartın bugünkü işaretiyle hesaplamak için Ay hazırlığında "
        '"Kartı izle"'
    ) in exc.value.message


def test_writes_to_an_approved_month_report_the_lock_first(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Onaylı aya yazımda önce bordro kilidi söylenir (kartın bugünkü işareti değil)."""
    person, _ = approved
    services.update_employee(manager, person, {"payroll_external": True})
    assert _code(lambda: _item(manager, person, C.PREMIUM, "100")) == "payroll_approved"
    assert (
        _code(
            lambda: services.set_opening_balance(
                manager, person, 2026, 10, tax_base=D("1"), exemption_months=9
            )
        )
        == "payroll_approved"
    )
    services.update_employee(manager, person, {"payroll_external": False})
    assert (
        _code(
            lambda: services.set_external_payroll(
                manager, person, 2026, 10, gross_total=D("1"), employer_cost=D("1")
            )
        )
        == "payroll_approved"
    )


def test_bordro_writes_take_the_shared_year_lock(manager: User) -> None:
    """Bordro yazımı onayla sıraya girer: yılın kilidi paylaşımlı alınır (onay özel alır)."""
    services._require_payroll_open(2026, 11)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT mode FROM pg_locks WHERE locktype = 'advisory' AND classid = %s "
            "AND objid = %s AND objsubid = 2 AND pid = pg_backend_pid()",
            [services.PAYROLL_LOCK_NAMESPACE, 2026],
        )
        modes = {mode for (mode,) in cursor.fetchall()}
    assert modes == {"ShareLock"}


def test_gate_error_lists_only_the_offending_gates(manager: User) -> None:
    parameter_set(manager)
    missing = employee(manager, full_name="Ayşe Demir", hire_date=date(2026, 10, 1))
    leaver = _person(manager, "Deniz Ak")
    services.terminate_employee(manager, leaver, date(2026, 10, 20), remove_attendance=True)
    services.approve_attendance_month(manager, 2026, 10)
    with pytest.raises(services.PayrollGateError) as exc:
        _approve(manager)
    assert [gate.code for gate in exc.value.gates] == [selectors.MISSING_WAGE]
    _wage(manager, missing, "40000", date(2026, 10, 1))
    with pytest.raises(services.PayrollGateError) as exc:
        _approve(manager)
    assert exc.value.code == "acknowledgement_required"
    assert [gate.code for gate in exc.value.gates] == [selectors.EXIT_IN_MONTH]


def test_query_numbers_must_be_plain_digits(
    manager: User, client_for: Callable[..., APIClient], approved: tuple[Employee, PayrollRun]
) -> None:
    client = client_for("yonetim")
    for query in ({"approval": "²"}, {"approval": "0"}, {"employee": "①"}, {"employee": "1" * 50}):
        response = client.get(f"{BASE}/payroll/2026/10/payslips.pdf", query)
        assert response.status_code == 404, query
    assert client.get(f"{BASE}/payroll/2026/10/xlsx/", {"approval": "²"}).status_code == 404


def test_output_names_tell_the_state(
    manager: User, client_for: Callable[..., APIClient], approved: tuple[Employee, PayrollRun]
) -> None:
    _, run = approved
    client = client_for("yonetim")

    def name(path: str, **query: Any) -> str:
        response = client.get(f"{BASE}/payroll/2026/{path}", query)
        assert response.status_code == 200, response.content[:200]
        return response["Content-Disposition"].split('filename="')[1].rstrip('"')

    assert name("10/register.pdf") == "bordro-listesi-2026-10-BR-2026-00001-onay1.pdf"
    assert name("10/xlsx/") == "bordro-2026-10-BR-2026-00001-onay1.xlsx"
    assert name("11/employer-cost.pdf") == "isveren-maliyeti-2026-11-taslak.pdf"
    services.reopen_payroll_month(manager, run, "kontrol")
    assert name("10/xlsx/", approval=1) == "bordro-2026-10-BR-2026-00001-onay1-gecersiz.xlsx"
    assert name("10/register.pdf") == "bordro-listesi-2026-10-taslak.pdf"


def test_heavy_payslip_stays_on_one_page(manager: User, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fazla mesai, tatil çalışması, yarım gün (YG) kesintisi, BES, çok sayıda ek ödeme ve
    kesintisi olan kişinin pusulası da tek sayfadır: sığmazsa bütünüyle küçültülür ve ortalanır
    (tablolar ile notlar aynı hizada)."""
    parameter_set(manager)
    person = _person(manager, employee_no="S-1", bes_enrolled=True)
    services.update_attendance_settings(manager, [6], daily_hours=D("9"))
    services.add_holiday(manager, {"date": date(2026, 10, 29), "name": "Cumhuriyet Bayramı"})
    services.set_attendance_day(
        manager, person, date(2026, 10, 29), status=S.PUBLIC_HOLIDAY, overtime_hours=D("8")
    )
    services.set_attendance_day(
        manager, person, date(2026, 10, 7), status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    for day, hours in ((5, "3"), (6, "2"), (12, "4")):
        services.set_attendance_day(
            manager, person, date(2026, 10, day), status=S.WORKED, overtime_hours=D(hours)
        )
    services.set_attendance_day(
        manager, person, date(2026, 10, 4), status=S.WEEKLY_REST, overtime_hours=D("8")
    )
    services.set_attendance_day(manager, person, date(2026, 10, 14), status=S.UNPAID_LEAVE)
    services.set_attendance_day(manager, person, date(2026, 10, 15), status=S.SICK_LEAVE)
    services.set_attendance_day(manager, person, date(2026, 10, 16), status=S.ABSENT)
    long_text = "Ekim ayı vardiya ve hat değişikliği nedeniyle ödenen ek tutar (açıklama uzun)"
    for index in range(6):
        pairs = ((C.OTHER_EXTRA, f"{long_text} {index}"), (C.OTHER_DEDUCTION, f"Kesinti {index}"))
        for category, text in pairs:
            services.add_payroll_item(
                manager,
                {
                    "employee": person,
                    "year": 2026,
                    "month": 10,
                    "category": category,
                    "description": text,
                    "amount": D("150"),
                },
            )
    _approve(manager)
    row = selectors.payroll_month(2026, 10).rows[0]
    labels = [label for label, _, _ in pdf.payslip_lines(row)["earnings"]]
    assert labels[:3] == ["Normal ücret", "Yarım gün kesintisi", "Fazla mesai (iş günü, %50 zamlı)"]
    assert "Resmî tatil çalışması" in labels and row.line.bes_deduction > 0
    blocks: list[Any] = []
    real = pdf._payslip_block

    def spy(*args: Any) -> Any:
        blocks.append(real(*args))
        return blocks[-1]

    monkeypatch.setattr(pdf, "_payslip_block", spy)
    content = pdf.payslips_pdf(selectors.payroll_month(2026, 10))
    assert _pages(content) == 1
    # Küçültülen pusula tek parçadır ve ortalanır: içindeki her şey pusulanın genişliğinde.
    [block] = blocks
    assert getattr(block, "_scale", 1) > 1 and block.hAlign == "CENTER"
    [inner] = block._content
    assert inner._width == pytest.approx(pdf.PAYSLIP_WIDTH * mm)
    for widths in (pdf.PAYSLIP_HEADER_WIDTHS, pdf.PAYSLIP_PAIR_WIDTHS, pdf.PAYSLIP_AMOUNT_WIDTHS):
        assert sum(widths) == pytest.approx(pdf.PAYSLIP_WIDTH)


def test_superseded_approval_keeps_its_opening(
    manager: User, approved: tuple[Employee, PayrollRun]
) -> None:
    """Eski onayın çıktısı onaydaki devirle kurulur (yeniden açılınca düzeltilen devir değil)."""
    person, run = approved
    services.reopen_payroll_month(manager, run, "devir")
    services.set_opening_balance(
        manager, person, 2026, 10, tax_base=D("400000"), exemption_months=9
    )
    old = selectors.payroll_month(2026, 10, approval=1)
    opening = old.rows[0].opening
    assert opening is not None and opening.pk is not None
    assert (opening.month, opening.tax_base, opening.exemption_months) == (10, D("382500"), 9)
    workbook = load_workbook(BytesIO(exports.payroll_xlsx(old, stamp=pdf.SUPERSEDED)))
    sheet = workbook["Bordro"]
    rows = list(sheet.iter_rows(values_only=True))
    # Eski onayın notu geçerli onayı gösterir.
    assert rows[1][0] == exports.SUPERSEDED_NOTE
    assert "yeniden açılmamış (geçerli) onaydadır" in rows[1][0]
    header = next(index for index, row in enumerate(rows) if row and row[0] == "Sicil no")
    data = dict(zip(rows[header], rows[header + 1], strict=False))
    assert data["Devir ayı"] == "Ekim 2026"
    assert D(str(data["Devir GV matrahı (TL)"])) == D("382500")
    assert data["Devir istisna ay"] == 9


def test_department_filtered_stored_month_keeps_moved_people(manager: User) -> None:
    """Saklı ayda puantaj tablosu birim süzgeçsiz kurulur: onaydan sonra birimi değişen kişinin
    günleri Eksik gün sayfasında bulunur."""
    parameter_set(manager)
    person = _person(manager)
    services.set_attendance_day(manager, person, date(2026, 10, 14), status=S.UNPAID_LEAVE)
    _approve(manager)
    services.update_employee(manager, person, {"department": "Depo"})
    month = selectors.payroll_month(2026, 10, department="Üretim")
    assert [row.person.department for row in month.rows] == ["Üretim"]
    workbook = load_workbook(BytesIO(exports.payroll_xlsx(month, stamp="")))
    names = [row[1] for row in workbook["Eksik gün"].iter_rows(values_only=True)]
    assert "Ali Kaya" in names
