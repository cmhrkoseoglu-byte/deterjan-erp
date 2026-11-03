"""Personel maliyeti: ön bordro hesabından kişi maliyeti (30 gün usulü brüt, fazla mesai ve resmi
tatil çalışması, SGK alt sınırı, 2026 işveren payları), aşama toplamları, üretilen kg ve işçilik
oranı önerisi (docs/DECISIONS.md "Personel maliyeti", "Personel bordrosu"). Ücretler ve bordro
hesabının kendisi personel modülündedir (personnel/tests/test_wages.py, test_payroll*.py).

2026 işveren payı (imalat, 5 puan teşvik): SGK %21,75 − %5 + işsizlik %2 = %18,75; 45.000 TL'lik tam
ayın maliyeti 45.000 + 7.537,50 + 900 = 53.437,50 TL."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.roles import ADMIN, ALL_ROLES, YONETIM
from apps.costing import exports, selectors, services
from apps.costing.models import CostRate, CostStage, DepartmentCostCenter
from apps.costing.tests.factories import build_chain
from apps.filling.models import FillingRun
from apps.personnel import services as personnel
from apps.personnel.models import AttendanceMonth, AttendanceStatus, Employee, EmployeeWage
from apps.personnel.tests.factories import employee, parameter_set
from apps.production.models import ProductionBatch

D = Decimal
S = AttendanceStatus
URL = "/api/v1/costing"
# Yönetim ve admin dışındaki bütün roller (dolum ve sevkiyat dahil).
OTHER_ROLES = tuple(role for role in ALL_ROLES if role not in (ADMIN, YONETIM))

pytestmark = pytest.mark.usefixtures("invariants")


@pytest.fixture
def manager(staff: dict[str, User]) -> User:
    return staff[YONETIM]


def _wage(actor: User, person: Employee, amount: str, valid_from: date) -> EmployeeWage:
    return personnel.add_wage(
        actor, {"employee": person, "gross_monthly": D(amount), "valid_from": valid_from}
    )


def _row(year: int, month: int, person: Employee) -> selectors.PersonnelCostRow:
    report = selectors.personnel_cost_report(year, month)
    return next(row for row in report.rows if row.employee.pk == person.pk)


def _code(call: Callable[[], Any]) -> str:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value.code


def _sheet_rows(sheet: Any) -> list[dict[str, Any]]:
    """Excel sayfasını başlık → değer sözlüklerine çevirir."""
    rows = list(sheet.iter_rows(values_only=True))
    return [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]


# --- aylık hesap -----------------------------------------------------------------------------


def test_full_month_and_unpaid_days(manager: User) -> None:
    """Ağustos 2026 (31 gün): tam ay 30 gün sayılır; ücretsiz izin, devamsızlık ve rapor günlük
    ücretle (45.000 / 30 = 1.500) düşülür; mazeret ve yıllık izin ücretlidir. İşveren payı 2026
    yasal değerleriyle (%18,75; parametre seti kaydedilmedi)."""
    person = employee(manager)
    _wage(manager, person, "45000", date(2020, 1, 1))
    report = selectors.personnel_cost_report(2026, 8)
    assert (report.employer_rate, report.parameters_origin) == (D("18.75"), "legal_default")
    row = _row(2026, 8, person)
    assert (row.employed_days, row.paid_days, row.unpaid_days) == (31, 30, 0)
    assert row.gross_salary == D("45000.00") and row.overtime_pay == D("0.00")
    assert row.employer_share == D("8437.50") and row.total_cost == D("53437.50")
    assert row.gross_monthly == D("45000.00") and not row.missing_wage

    for day, status in (
        (3, S.UNPAID_LEAVE),
        (4, S.ABSENT),
        (5, S.SICK_LEAVE),
        (6, S.PAID_LEAVE),
        (7, S.ANNUAL_LEAVE),
    ):
        personnel.set_attendance_day(manager, person, date(2026, 8, day), status=status)
    row = _row(2026, 8, person)
    assert (row.paid_days, row.unpaid_days) == (27, 3)
    assert row.gross_salary == D("40500.00")
    # SGK günü 31 − 3 = 28; matrah 40.500: 8.808,75 − 2.025,00 + 810,00.
    assert row.employer_share == D("7593.75") and row.total_cost == D("48093.75")


def test_wage_below_minimum_wage_raises_sgk_base_to_the_floor(manager: User) -> None:
    """Eylül 2026, tam ay 30.000 TL: SGK matrahı alt sınıra (33.030) çıkar; işveren payları alt
    sınırdan, işçi payları ücretten; farkın işçi payını da işveren öder (5510 m.82)."""
    person = employee(manager)
    _wage(manager, person, "30000", date(2020, 1, 1))
    row = _row(2026, 9, person)
    # 5.532,53 (SGK işveren, teşvik sonrası) + 660,60 (işsizlik) + 454,50 (fark: 424,20 + 30,30).
    assert row.employer_share == D("6647.63") and row.total_cost == D("36647.63")


def test_february_and_partial_months(manager: User) -> None:
    """Şubat 2026 (28 gün): tam ay yine aylık brüt; ay içinde giren ya da ayrılan takvim günü kadar
    ücret alır."""
    whole = employee(manager)
    newcomer = employee(manager, full_name="Can Kaya", hire_date=date(2026, 2, 15))
    leaver = employee(manager, full_name="Ece Ak", hire_date=date(2020, 1, 1))
    personnel.terminate_employee(manager, leaver, date(2026, 2, 10))
    for person in (whole, newcomer, leaver):
        _wage(manager, person, "30000", date(2020, 1, 1))
    assert _row(2026, 2, whole).gross_salary == D("30000.00")
    assert _row(2026, 2, whole).paid_days == 30
    assert (_row(2026, 2, newcomer).paid_days, _row(2026, 2, newcomer).gross_salary) == (
        14,
        D("14000.00"),
    )
    assert (_row(2026, 2, leaver).paid_days, _row(2026, 2, leaver).gross_salary) == (
        10,
        D("10000.00"),
    )
    # Ayın tamamı ücretsiz izin: 30 - 28 = 2 gün kalmaz, ücret sıfırdır.
    personnel.set_attendance_range(
        manager,
        start=date(2026, 2, 1),
        end=date(2026, 2, 28),
        status=S.UNPAID_LEAVE,
        employee=whole,
    )
    row = _row(2026, 2, whole)
    assert (row.paid_days, row.unpaid_days, row.gross_salary) == (0, 28, D("0.00"))
    assert row.total_cost == D("0.00")


def test_thirty_unpaid_days_in_a_31_day_month_pay_the_worked_day(manager: User) -> None:
    """Ağustos 2026 (31 gün): 1'inde çalışıp 2–31 ücretsiz izinli olan 30 - 30 = 0 değil, ücretli
    takvim günü kadar (1 gün) alır; 31 günün tamamı ücretsizse sıfır."""
    worker = employee(manager)
    idle = employee(manager, full_name="Can Kaya")
    for person in (worker, idle):
        _wage(manager, person, "30000", date(2020, 1, 1))
    personnel.set_attendance_range(
        manager,
        start=date(2026, 8, 2),
        end=date(2026, 8, 31),
        status=S.UNPAID_LEAVE,
        employee=worker,
    )
    personnel.set_attendance_range(
        manager, start=date(2026, 8, 1), end=date(2026, 8, 31), status=S.UNPAID_LEAVE, employee=idle
    )
    row = _row(2026, 8, worker)
    assert (row.paid_days, row.unpaid_days, row.gross_salary) == (1, 30, D("1000.00"))
    row = _row(2026, 8, idle)
    assert (row.paid_days, row.gross_salary) == (0, D("0.00"))


def test_half_kurus_rounds_up_without_drift(manager: User) -> None:
    """Eylül 2026: 147.404,15 TL'den 22 Eylül'de 161.300,50 TL'ye zam. Kesin değer
    (21 × 147.404,15 + 9 × 161.300,50) / 30 = 151.573,055 → yukarı yuvarlanır: 151.573,06."""
    person = employee(manager)
    _wage(manager, person, "147404.15", date(2020, 1, 1))
    _wage(manager, person, "161300.50", date(2026, 9, 22))
    assert _row(2026, 9, person).gross_salary == D("151573.06")


def test_overtime_by_day_type(manager: User) -> None:
    """Eylül 2026, brüt 45.000 → saat ücreti 200. İş günü ve hafta tatilinde 1,5 kat; resmi tatilde
    çalışana bir günlük ilave ücret (kısa çalışsa da), 7,5 saati aşan saatler 1,5 kat. Kayıtlı
    parametre seti teşvik puanını değiştirirse maliyet de değişir."""
    person = employee(manager)
    long_day = employee(manager, full_name="Can Kaya")
    for card in (person, long_day):
        _wage(manager, card, "45000", date(2020, 1, 1))
    personnel.add_holiday(manager, {"date": date(2026, 9, 15), "name": "Bayram"})
    personnel.set_attendance_day(
        manager, person, date(2026, 9, 1), status=S.WORKED, overtime_hours=D(2)
    )
    personnel.set_attendance_day(
        manager, person, date(2026, 9, 6), status=S.WEEKLY_REST, overtime_hours=D(4)
    )
    personnel.set_attendance_day(
        manager, person, date(2026, 9, 15), status=S.PUBLIC_HOLIDAY, overtime_hours=D(3)
    )
    personnel.set_attendance_day(
        manager, long_day, date(2026, 9, 15), status=S.PUBLIC_HOLIDAY, overtime_hours=D(10)
    )
    row = _row(2026, 9, person)
    assert row.overtime_hours == D(9)
    assert row.overtime_pay == D("3300.00")  # 600 + 1.200 + 1.500 (bir günlük ücret)
    assert row.gross_salary == D("45000.00") and row.gross_total == D("48300.00")
    assert row.employer_share == D("9056.25") and row.total_cost == D("57356.25")
    # 10 saat: bir günlük ücret (1.500) + 2,5 saat × 200 × 1,5 (750).
    assert _row(2026, 9, long_day).overtime_pay == D("2250.00")

    parameter_set(manager, incentive_points=D(2))
    report = selectors.personnel_cost_report(2026, 9)
    assert (report.employer_rate, report.parameters_origin) == (D("21.75"), "saved")
    row = _row(2026, 9, person)
    # 10.505,25 − 966,00 + 966,00.
    assert row.employer_share == D("10505.25") and row.total_cost == D("58805.25")


def test_mid_month_raise_and_missing_wage(manager: User) -> None:
    """Eylül 2026 (30 gün): 16 Eylül'den geçerli zamda her gün kendi ücretiyle; ücreti 11 Eylül'de
    başlayan kişinin ilk 10 günü sıfır sayılır ve kişi "ücret eksik" işaretlenir."""
    raised = employee(manager)
    _wage(manager, raised, "30000", date(2020, 1, 1))
    _wage(manager, raised, "36000", date(2026, 9, 16))
    late = employee(manager, full_name="Can Kaya")
    _wage(manager, late, "30000", date(2026, 9, 11))
    nobody = employee(manager, full_name="Ece Ak")

    row = _row(2026, 9, raised)
    assert row.gross_salary == D("33000.00") and row.gross_monthly == D("36000.00")
    assert not row.missing_wage
    row = _row(2026, 9, late)
    assert row.gross_salary == D("20000.00") and row.missing_wage
    row = _row(2026, 9, nobody)
    assert row.total_cost == D("0.00") and row.gross_monthly is None and row.missing_wage
    assert selectors.personnel_cost_report(2026, 9).missing_wage_count == 2


def test_stage_totals_follow_department_mapping(manager: User) -> None:
    filler = employee(manager, department="Dolum")
    maker = employee(manager, full_name="Can Kaya", department="Üretim")
    keeper = employee(manager, full_name="Ece Ak", department="Depo")
    for person, amount in ((filler, "45000"), (maker, "60000"), (keeper, "36000")):
        _wage(manager, person, amount, date(2020, 1, 1))
    services.set_department_cost_center(manager, " dolum ", CostStage.FILLING)
    services.set_department_cost_center(manager, "Üretim", CostStage.PRODUCTION)
    CostRate.objects.create(
        stage=CostStage.PRODUCTION,
        kind=CostRate.Kind.LABOR,
        rate_per_kg=D("2.5"),
        valid_from=date(2026, 9, 1),
    )

    report = selectors.personnel_cost_report(2026, 9)
    production = report.stage_cost(CostStage.PRODUCTION)
    filling = report.stage_cost(CostStage.FILLING)
    general = report.stage_cost(selectors.GENERAL)
    assert (production.cost, production.employee_count) == (D("71250.00"), 1)
    assert (filling.cost, filling.employee_count) == (D("53437.50"), 1)
    assert (general.cost, general.employee_count) == (D("42750.00"), 1)
    assert report.total_cost == D("167437.50")
    assert production.current_rate == D("2.5") and filling.current_rate is None
    # Bu ay üretim yok: öneri hesaplanmaz.
    assert production.kg == 0 and production.suggested_rate is None
    assert general.kg is None and general.suggested_rate is None
    # Eşleştirme büyük/küçük harf farkıyla güncellenir (yeni kayıt açılmaz); boş aşama genel
    # giderdir.
    services.set_department_cost_center(manager, "DOLUM", "")
    assert DepartmentCostCenter.objects.count() == 2
    assert DepartmentCostCenter.objects.get(key="dolum").stage == ""
    rows = {row["department"]: row["stage"] for row in selectors.cost_centers()}
    assert rows == {"Depo": "", "Dolum": "", "Üretim": "PRODUCTION"}
    report = selectors.personnel_cost_report(2026, 9)
    assert report.stage_cost(selectors.GENERAL).employee_count == 2
    # Türkçe İ/ı: "İDARİ İŞLER" ile "İdari İşler" aynı birimdir.
    clerk = employee(manager, full_name="Deniz Su", department="İdari İşler")
    _wage(manager, clerk, "25000", date(2020, 1, 1))
    services.set_department_cost_center(manager, "İDARİ İŞLER", CostStage.PRODUCTION)
    services.set_department_cost_center(manager, "idari işler", CostStage.PRODUCTION)
    assert DepartmentCostCenter.objects.count() == 3
    assert _row(2026, 9, clerk).stage == CostStage.PRODUCTION


# --- üretilen kg ve işçilik oranı ------------------------------------------------------------


def test_produced_kg_and_labor_rate_from_approved_month(
    staff: dict[str, User], commit: Callable[[], Any], manager: User
) -> None:
    chain = build_chain(staff, commit)
    assert chain.batch is not None and chain.run is not None
    today = timezone.localdate()
    previous = today.replace(day=1) - timedelta(days=1)
    moment = timezone.make_aware(datetime.combine(previous.replace(day=15), time(12)))
    ProductionBatch.objects.filter(pk=chain.batch.pk).update(finished_at=moment)
    FillingRun.objects.filter(pk=chain.run.pk).update(finished_at=moment)

    produced = selectors.monthly_produced_kg(previous.year, previous.month)
    assert produced[CostStage.PRODUCTION].kg == D("980")
    assert produced[CostStage.FILLING].kg == D("780")
    assert produced[CostStage.PRODUCTION].unconverted == 0
    assert selectors.monthly_produced_kg(today.year, today.month)[CostStage.PRODUCTION].kg == 0

    maker = employee(manager, full_name="Can Kaya", department="Üretim")
    _wage(manager, maker, "45000", date(2020, 1, 1))
    services.set_department_cost_center(manager, "Üretim", CostStage.PRODUCTION)
    report = selectors.personnel_cost_report(previous.year, previous.month)
    production = report.stage_cost(CostStage.PRODUCTION)
    assert production.cost == D("53437.50") and production.kg == D("980")
    assert production.suggested_rate == D("54.5281")  # 53.437,50 / 980

    start = today + timedelta(days=2)

    def add(stage: str = CostStage.PRODUCTION, **when: int) -> Callable[[], Any]:
        year = when.get("year", previous.year)
        month = when.get("month", previous.month)
        return lambda: services.add_labor_rate_from_personnel_cost(
            manager, year, month, stage, start
        )

    assert _code(add()) == "attendance_not_approved"
    personnel.approve_attendance_month(manager, previous.year, previous.month)
    rate = add()()
    assert (rate.stage, rate.kind, rate.rate_per_kg, rate.valid_from) == (
        CostStage.PRODUCTION,
        CostRate.Kind.LABOR,
        D("54.5281"),
        start,
    )
    assert rate.note == f"Personel maliyeti {report.label}: 53.437,50 TL / 980,00 kg"
    assert rate.created_by == manager
    assert _code(add()) == "duplicate_rate"
    assert _code(add(CostStage.FILLING)) == "no_labor_rate"  # dolumda personel yok
    assert _code(add("")) == "invalid_stage"
    assert _code(add(year=today.year, month=today.month)) == "attendance_not_approved"
    # Personel maliyeti var ama o ay üretim yok: oran hesaplanamaz.
    earlier = previous.replace(day=1) - timedelta(days=1)
    personnel.approve_attendance_month(manager, earlier.year, earlier.month)
    assert _code(add(year=earlier.year, month=earlier.month)) == "no_labor_rate"
    # API: 201 ve oran kaydı.
    client = APIClient()
    client.force_authenticate(manager)
    response = client.post(
        f"{URL}/personnel-costs/{previous.year}/{previous.month}/labor-rate/",
        {"stage": "PRODUCTION", "valid_from": str(start + timedelta(days=1))},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["rate_per_kg"] == "54.5281" and response.json()["kind"] == "LABOR"


def test_produced_kg_follows_istanbul_month_and_completed_status(
    staff: dict[str, User], commit: Callable[[], Any]
) -> None:
    chain = build_chain(staff, commit)
    assert chain.batch is not None and chain.run is not None
    # 30.09.2026 21:30 UTC = 01.10.2026 00:30 İstanbul; 20:30 UTC = 30.09.2026 23:30 İstanbul.
    ProductionBatch.objects.filter(pk=chain.batch.pk).update(
        finished_at=datetime(2026, 9, 30, 21, 30, tzinfo=UTC)
    )
    FillingRun.objects.filter(pk=chain.run.pk).update(
        finished_at=datetime(2026, 9, 30, 20, 30, tzinfo=UTC)
    )
    september = selectors.monthly_produced_kg(2026, 9)
    october = selectors.monthly_produced_kg(2026, 10)
    assert (september[CostStage.PRODUCTION].kg, october[CostStage.PRODUCTION].kg) == (0, D("980"))
    assert (september[CostStage.FILLING].kg, october[CostStage.FILLING].kg) == (D("780"), 0)
    # Bitmemiş şarj ve parti sayılmaz.
    ProductionBatch.objects.filter(pk=chain.batch.pk).update(
        status=ProductionBatch.Status.IN_PROGRESS
    )
    FillingRun.objects.filter(pk=chain.run.pk).update(status=FillingRun.Status.IN_PROGRESS)
    assert selectors.monthly_produced_kg(2026, 10)[CostStage.PRODUCTION].kg == 0
    assert selectors.monthly_produced_kg(2026, 9)[CostStage.FILLING].kg == 0


def test_approved_month_uses_stored_days_within_employment(manager: User) -> None:
    """Onaylı ay kayıtlı günlerle hesaplanır: onaydan sonra açılan kart o aya girmez. Onaylı aya
    düşen ayrılış ay yeniden açılınca kaydedilir; yeniden onayda çıkıştan sonraki günler yoktur."""
    person = employee(manager)
    _wage(manager, person, "30000", date(2020, 1, 1))
    personnel.set_attendance_day(manager, person, date(2026, 9, 3), status=S.UNPAID_LEAVE)
    personnel.approve_attendance_month(manager, 2026, 9)
    # Giriş tarihi yok: onaylı aydan onu yalnızca onay kuralı (kayıtlı günler) dışarıda tutar.
    newcomer = employee(manager, full_name="Can Kaya")
    report = selectors.personnel_cost_report(2026, 9)
    assert [row.employee.pk for row in report.rows] == [person.pk]
    assert report.rows[0].gross_salary == D("29000.00")
    with pytest.raises(BusinessRuleError) as exc:
        personnel.terminate_employee(manager, person, date(2026, 9, 20), remove_attendance=True)
    assert exc.value.code == "approved_attendance_after_exit"
    record = AttendanceMonth.objects.get(year=2026, month=9)
    personnel.reopen_attendance_month(manager, record, "Geç bildirilen ayrılış")
    personnel.terminate_employee(manager, person, date(2026, 9, 20), remove_attendance=True)
    personnel.approve_attendance_month(manager, 2026, 9)
    row = _row(2026, 9, person)
    assert (row.employed_days, row.unpaid_days, row.paid_days) == (20, 1, 19)
    assert row.gross_salary == D("19000.00")
    october = selectors.personnel_cost_report(2026, 10)
    assert [row.employee.pk for row in october.rows] == [newcomer.pk]


def test_stored_days_after_exit_are_not_costed(manager: User) -> None:
    """Çıkıştan sonra kayıtlı kalmış eski günler (ör. bu kural yokken onaylanmış ay) maliyete
    girmez: yalnızca işte olduğu takvim günleri sayılır."""
    person = employee(manager)
    _wage(manager, person, "30000", date(2020, 1, 1))
    personnel.approve_attendance_month(manager, 2026, 9)
    # Eski kayıt: kart, servisi atlayarak ayrılmış gösterilir; onaylı ayda 21–30.09 kayıtlı kalır.
    Employee.objects.filter(pk=person.pk).update(
        is_active=False, termination_date=date(2026, 9, 20)
    )
    person.refresh_from_db()
    row = _row(2026, 9, person)
    assert (row.employed_days, row.paid_days) == (20, 20)
    assert row.gross_salary == D("20000.00")


# --- ayarlar, yetki --------------------------------------------------------------------------


def test_removed_wage_is_not_costed(manager: User) -> None:
    """Kaldırılan ücret hesaba girmez; aynı tarihe yeniden girilen ücret kullanılır."""
    person = employee(manager)
    wage = _wage(manager, person, "30000", date(2026, 1, 1))
    personnel.remove_wage(manager, wage, "Yanlış tutar")
    assert _row(2026, 3, person).missing_wage
    _wage(manager, person, "31000", date(2026, 1, 1))
    row = _row(2026, 3, person)
    assert row.gross_salary == D("31000.00") and not row.missing_wage


def test_cost_center_rules(manager: User) -> None:
    assert (
        _code(lambda: services.set_department_cost_center(manager, "Dolum", "SALES"))
        == "invalid_stage"
    )


def test_extras_are_reported_separately(manager: User) -> None:
    """Ek ödeme (ör. ikramiye) brüt ücrete karışmaz: ayrı sütun; maliyete (SGK'sıyla) girer."""
    person = employee(manager)
    _wage(manager, person, "45000", date(2020, 1, 1))
    personnel.add_payroll_item(
        manager,
        {
            "employee": person,
            "year": 2026,
            "month": 10,
            "category": "BONUS",
            "description": "",
            "amount": D("10000"),
        },
    )
    row = _row(2026, 10, person)
    assert (row.gross_salary, row.extras_total, row.gross_total) == (
        D("45000.00"),
        D("10000"),
        D("55000.00"),
    )
    assert row.total_cost == D("65312.50")  # 55.000 × %118,75
    report = selectors.personnel_cost_report(2026, 10)
    assert report.extras_total == D("10000")
    workbook = load_workbook(BytesIO(exports.personnel_cost_xlsx(report)))
    (sheet_row,) = _sheet_rows(workbook["Personel maliyeti"])
    assert D(str(sheet_row["Ek ödeme (TL)"])) == D("10000")


def test_external_payroll_uses_entered_figures(manager: User) -> None:
    """Bordrosu mali müşavirde olan kişide maliyet o ayın girilmiş rakamlarıdır; girilmemişse sıfır
    ve eksik görünür."""
    person = employee(manager, payroll_external=True)
    _wage(manager, person, "45000", date(2020, 1, 1))
    row = _row(2026, 9, person)
    assert row.payroll_external and row.missing_wage and row.total_cost == D("0.00")
    # Excel ekran gibi ayırır: ücret değil mali müşavir rakamı eksik (Bordro'da girilir).
    workbook = load_workbook(
        BytesIO(exports.personnel_cost_xlsx(selectors.personnel_cost_report(2026, 9)))
    )
    (sheet_row,) = _sheet_rows(workbook["Personel maliyeti"])
    assert sheet_row["Ücret eksik"] in ("", None)
    assert sheet_row["Bordrosu mali müşavirde"] == "Evet"
    assert sheet_row["Mali müşavir rakamı girilmedi"] == "Evet"
    summary = {item["Bilgi"]: item["Değer"] for item in _sheet_rows(workbook["Özet"])}
    assert summary["Ücreti eksik kişi"] == 0
    assert summary["Mali müşavir rakamı girilmemiş kişi"] == 1
    (stage_row,) = [item for item in _sheet_rows(workbook["Aşamalar"]) if item["Kişi"]]
    assert stage_row["Ücreti ya da mali müşavir rakamı eksik kişi"] == 1
    personnel.set_external_payroll(
        manager, person, 2026, 9, gross_total=D("41000"), employer_cost=D("50123.45")
    )
    row = _row(2026, 9, person)
    assert row.payroll_external and not row.missing_wage
    assert (row.gross_salary, row.employer_share, row.total_cost) == (
        D("41000.00"),
        D("9123.45"),
        D("50123.45"),
    )


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_only_management_handles_personnel_costs(
    make_user: Callable[..., User], manager: User, role: str
) -> None:
    other = make_user(role)
    calls = [
        lambda: services.set_department_cost_center(other, "Dolum", CostStage.FILLING),
        lambda: services.add_labor_rate_from_personnel_cost(
            other, 2026, 9, CostStage.PRODUCTION, date(2026, 10, 1)
        ),
    ]
    for call in calls:
        with pytest.raises(PermissionDenied):
            call()


# --- API -------------------------------------------------------------------------------------


def test_report_and_centers_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for(YONETIM)
    person = employee(manager, employee_no="S-1", department="Dolum")
    _wage(manager, person, "45000", date(2020, 1, 1))
    # Ücretler personele taşındı; tek işveren payı ayarının yerini bordro parametreleri aldı.
    assert client.get(f"{URL}/wages/summary/").status_code == 404
    assert client.get(f"{URL}/personnel-cost-settings/").status_code == 404

    response = client.put(
        f"{URL}/cost-centers/", {"department": "dolum", "stage": "FILLING"}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert client.get(f"{URL}/cost-centers/").json() == [
        {"department": "Dolum", "stage": "FILLING"}
    ]

    report = client.get(f"{URL}/personnel-costs/2026/9/").json()
    assert report["period_label"] == "Eylül 2026" and report["attendance_approved"] is False
    assert report["total_cost"] == "53437.50" and report["employer_rate"] == "18.75"
    assert (report["parameters_origin"], report["parameters_year"]) == ("legal_default", 2026)
    row = report["rows"][0]
    assert row["employee"]["employee_no"] == "S-1" and row["stage"] == "FILLING"
    assert row["paid_days"] == 30 and row["gross_total"] == "45000.00"
    assert row["payroll_external"] is False
    stages = {item["stage"]: item for item in report["stages"]}
    assert stages["FILLING"]["cost"] == "53437.50" and stages["FILLING"]["suggested_rate"] is None
    assert client.get(f"{URL}/personnel-costs/2026/13/").status_code == 404

    excel = client.get(f"{URL}/personnel-costs/2026/9/xlsx/")
    assert excel.status_code == 200
    assert excel["Content-Disposition"].startswith(
        'attachment; filename="personel-maliyeti-2026-09-'
    )
    # Kişi başına ön bordro rakamları: önbelleğe alınmaz, açılışı denetim günlüğüne yazılır.
    assert excel["Cache-Control"] == "no-store"
    assert AuditLog.objects.filter(
        note="Bordro çıktısı açıldı: Personel maliyeti (Excel) · Eylül 2026"
    ).exists()
    workbook = load_workbook(BytesIO(excel.content))
    assert workbook.sheetnames == ["Personel maliyeti", "Aşamalar", "Özet"]
    (person_row,) = _sheet_rows(workbook["Personel maliyeti"])
    assert person_row["Sicil no"] == "S-1" and person_row["Ad soyad"] == "Ayşe Demir"
    assert person_row["Maliyet merkezi"] == "Dolum (mamul)"
    assert person_row["Ödenen gün"] == 30 and person_row["Ücret eksik"] in ("", None)
    assert D(str(person_row["Brüt ücret (TL)"])) == D("45000")
    assert D(str(person_row["İşveren payı (TL)"])) == D("8437.5")
    assert D(str(person_row["Toplam maliyet (TL)"])) == D("53437.5")
    assert person_row["Bordrosu mali müşavirde"] in ("", None)
    stage_rows = {row["Maliyet merkezi"]: row for row in _sheet_rows(workbook["Aşamalar"])}
    assert list(stage_rows) == ["Üretim (bulk)", "Dolum (mamul)", "Genel gider"]
    assert D(str(stage_rows["Dolum (mamul)"]["Personel maliyeti (TL)"])) == D("53437.5")
    assert stage_rows["Genel gider"]["Kişi"] == 0
    assert workbook["Özet"]["B3"].value == "Açık (taslak)"
    summary = {row["Bilgi"]: row["Değer"] for row in _sheet_rows(workbook["Özet"])}
    assert D(str(summary["Etkin işveren oranı (%)"])) == D("18.75")
    assert summary["Bordro parametreleri"] == "Kaydedilmedi (2026 yasal değerleri)"

    response = client.post(
        f"{URL}/personnel-costs/2026/9/labor-rate/",
        {"stage": "FILLING", "valid_from": "2026-10-01"},
        format="json",
    )
    assert response.status_code == 400 and response.json()["code"] == "attendance_not_approved"


def test_admin_reaches_personnel_costs_and_anonymous_is_rejected(
    client_for: Callable[..., APIClient], api_client: APIClient, manager: User
) -> None:
    person = employee(manager)
    _wage(manager, person, "30000", date(2020, 1, 1))
    admin = client_for(ADMIN)
    assert admin.get(f"{URL}/personnel-costs/2026/9/").status_code == 200
    assert admin.get(f"{URL}/personnel-costs/2026/9/xlsx/").status_code == 200
    response = admin.put(
        f"{URL}/cost-centers/", {"department": "Dolum", "stage": "FILLING"}, format="json"
    )
    assert response.status_code == 200
    for url in (f"{URL}/personnel-costs/2026/9/", f"{URL}/cost-centers/"):
        assert api_client.get(url).status_code in (401, 403)


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_reach_personnel_costs(
    client_for: Callable[..., APIClient], manager: User, role: str
) -> None:
    person = employee(manager)
    _wage(manager, person, "30000", date(2026, 1, 1))
    client = client_for(role)
    checks = [
        client.get(f"{URL}/personnel-costs/2026/9/"),
        client.get(f"{URL}/personnel-costs/2026/9/xlsx/"),
        client.post(
            f"{URL}/personnel-costs/2026/9/labor-rate/",
            {"stage": "PRODUCTION", "valid_from": "2026-10-01"},
        ),
        client.get(f"{URL}/cost-centers/"),
        client.put(f"{URL}/cost-centers/", {"department": "Dolum", "stage": "FILLING"}),
    ]
    assert [response.status_code for response in checks] == [403] * len(checks)
    assert not DepartmentCostCenter.objects.exists()
