"""Puantajda günlük çalışma saati ve yarım gün (docs/DECISIONS.md "Puantajda günlük çalışma saati
ve yarım gün"): ayar, güne çalışılan saat ve yarım gün işareti (YG), sayılma kuralı, ayın onaydaki
değeri, aralık girişi, toplamlar, Excel, ayrılış özeti ve API. Çalışılan saat yalnızca kayıttır;
sayılan YG günü bordroda ve personel maliyetinde yarım günlük ücret (brüt / 60) keser (2. adım;
ayrıntısı test_payroll_short_day.py)."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from apps.core.coding import registry
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import exports, payroll, pdf, selectors, services
from apps.personnel.models import (
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    PublicHoliday,
)
from apps.personnel.selectors import AttendanceCell, AttendanceGrid
from apps.personnel.tests.factories import employee, parameter_set

pytestmark = pytest.mark.django_db
BASE = "/api/v1/personnel/attendance"
OTHER_ROLES = ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]
D = Decimal
S = AttendanceStatus
INVALID_DAILY_HOURS = "Günlük çalışma saati 0'dan büyük, en çok 24 olmalı."
SHORT_DAY_LEGEND = (
    "Yarım gün çalıştı (yönetimce yarım gün sayıldı). Ç toplamına girmez; çalışılan gün = Ç + YG. "
    "Bordrosu onaylanmamış ayların ERP ön bordrosunda yarım gün çalışılan her gün için günlük "
    "ücretin yarısı (aylık brüt / 60) kesilir; hafta tatili ya da tam gün tatile Ç yazılan günde "
    "kesilmez; SGK günü değişmez. Bordrosu mali müşavirde olan kişide kesintiyi mali müşavir "
    "uygular."
)
WORKED_HOURS_LEGEND = (
    "Fazla mesai hariçtir. Saat girilmeyen gün günün çalışma saatiyle, yarım gün tatilde öğleden "
    "sonra da çalışılan gün günlük çalışma saatinin tamamıyla sayılır."
)


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


@pytest.fixture
def nine(manager: User) -> Decimal:
    """Günlük çalışma saati 9 (yarım gün tatilde 4,5); hafta tatili pazar."""
    services.update_attendance_settings(manager, [6], daily_hours=D("9"))
    return D("9")


@pytest.fixture
def api(manager: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(manager)
    return client


def _previous_month() -> tuple[int, int]:
    """Bitmiş bir ay (onay ancak ay bitince verilir; saat ileri bir güne girilemez)."""
    last = timezone.localdate().replace(day=1) - timedelta(days=1)
    return last.year, last.month


def _workdays(year: int, month: int) -> list[date]:
    """Ayın pazar dışındaki günleri (testler tatili kendileri ekler)."""
    first, last = selectors.month_bounds(year, month)
    return [day for day in selectors.days_between(first, last) if day.weekday() != 6]


def _cells(grid: AttendanceGrid, person: Employee) -> dict[date, AttendanceCell]:
    row = next(row for row in grid.rows if row.employee.pk == person.pk)
    return {cell.date: cell for cell in row.cells}


def _error(call: Callable[[], Any]) -> BusinessRuleError:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value


def _stored(person: Employee, day: date) -> tuple[str, Decimal | None, bool]:
    """Günün kayıttaki (ham) durumu, çalışılan saati ve yarım gün işareti."""
    entry = AttendanceEntry.objects.get(employee=person, date=day)
    return entry.status, entry.worked_hours, entry.short_day


def _half_holiday(actor: User, day: date) -> PublicHoliday:
    return services.add_holiday(actor, {"date": day, "name": "Arife", "half_day": True})


def _number(value: Any) -> Decimal | None:
    """Excel hücresindeki sayı, Decimal olarak (openpyxl tam sayı ya da kayan nokta okur)."""
    return None if value is None else D(str(value))


def _book(grid: AttendanceGrid) -> Workbook:
    return load_workbook(BytesIO(exports.attendance_xlsx(grid)))


def _row(book: Workbook, sheet: str, number: int) -> list[Any]:
    return [cell.value for cell in book[sheet][number]]


# --- ayar: günlük çalışma saati -------------------------------------------------------------------


def test_daily_hours_setting(manager: User) -> None:
    assert selectors.daily_hours() is None  # hiç belirlenmedi
    # Değer yokken boş göndermek değişiklik değildir.
    assert services.update_attendance_settings(manager, [6], daily_hours=None).daily_hours is None
    saved = services.update_attendance_settings(manager, [6], daily_hours=D("9"))
    assert saved.daily_hours == D("9") and selectors.daily_hours() == D("9")
    log = AuditLog.objects.filter(
        content_type__model="attendancesettings", object_id=saved.pk
    ).latest("timestamp", "id")
    assert log.changes == {"daily_hours": [None, "9.00"]} and log.actor == manager

    # Yalnızca hafta tatili verilince günlük çalışma saati korunur.
    kept = services.update_attendance_settings(manager, [5, 6])
    assert (kept.rest_weekdays, kept.daily_hours) == ([5, 6], D("9"))

    # Belirlenmiş değer boşaltılamaz, yalnızca değiştirilir; reddedilen istek hiçbir şey yazmaz.
    error = _error(lambda: services.update_attendance_settings(manager, [6], daily_hours=None))
    assert (error.code, error.message) == (
        "daily_hours_required",
        "Günlük çalışma saati boş bırakılamaz; yeni değeri yazın.",
    )
    current = services.get_attendance_settings()
    assert (current.rest_weekdays, current.daily_hours) == ([5, 6], D("9"))
    changed = services.update_attendance_settings(manager, [6], daily_hours=D("7.5"))
    assert changed.daily_hours == D("7.5") and selectors.rest_weekdays() == {6}


@pytest.mark.parametrize("value", ["0", "-1", "24.01", "0.004"])
def test_daily_hours_must_be_above_zero_and_at_most_24(manager: User, value: str) -> None:
    error = _error(lambda: services.update_attendance_settings(manager, [6], daily_hours=D(value)))
    assert (error.code, error.message) == ("invalid_daily_hours", INVALID_DAILY_HOURS)
    assert selectors.daily_hours() is None


def test_daily_hours_are_rounded_to_two_decimals(manager: User) -> None:
    saved = services.update_attendance_settings(manager, [6], daily_hours=D("24.004"))
    assert saved.daily_hours == D("24")  # üst sınır dahil
    saved = services.update_attendance_settings(manager, [6], daily_hours=D("7.495"))
    assert saved.daily_hours == D("7.5")  # yarım yukarı


def test_expected_hours_and_month_daily_hours() -> None:
    arife = PublicHoliday(date=date(2026, 10, 28), name="Arife", half_day=True)
    bayram = PublicHoliday(date=date(2026, 10, 29), name="Bayram", half_day=False)
    assert selectors.expected_hours(None, arife) is None
    assert selectors.expected_hours(D("9"), None) == D("9")
    assert selectors.expected_hours(D("9"), arife) == D("4.5")
    # Tam gün tatile "Çalıştı" yazılan günün çalışma saati günlük çalışma saatidir.
    assert selectors.expected_hours(D("9"), bayram) == D("9")
    assert selectors.expected_hours(D("8.25"), arife) == D("4.13")  # 4,125 yarım yukarı

    status = AttendanceMonth.Status
    never_approved = AttendanceMonth(year=2026, month=9, status=status.OPEN)
    approved = AttendanceMonth(year=2026, month=9, status=status.APPROVED, daily_hours=D("9"))
    reopened = AttendanceMonth(year=2026, month=9, status=status.OPEN, daily_hours=D("9"))
    approved_without = AttendanceMonth(year=2026, month=9, status=status.APPROVED)
    assert selectors.month_daily_hours(None, D("8")) == D("8")
    assert selectors.month_daily_hours(never_approved, D("8")) == D("8")
    assert selectors.month_daily_hours(never_approved, None) is None
    assert selectors.month_daily_hours(approved, D("8")) == D("9")
    assert selectors.month_daily_hours(reopened, D("8")) == D("9")
    assert selectors.month_daily_hours(approved_without, D("8")) is None  # "kayıtlı değil"


# --- güne çalışılan saat ve yarım gün işareti -----------------------------------------------------


def test_short_hours_with_and_without_the_short_day_mark(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    card = employee(manager)
    short, early, full = _workdays(year, month)[:3]
    marked = services.set_attendance_day(
        manager, card, short, status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    assert (marked.status, marked.worked_hours, marked.short_day) == (S.WORKED, D("4.5"), True)
    log = AuditLog.objects.get(
        object_id=marked.pk, action=AuditLog.Action.CREATE, content_type__model="attendanceentry"
    )
    assert log.changes["worked_hours"] == [None, "4.50"]
    assert log.changes["short_day"] == [None, True]
    # İşareti yalnızca kullanıcı verir: saat eksik diye gün kendiliğinden yarım gün olmaz.
    entry = services.set_attendance_day(
        manager, card, early, status=S.WORKED, worked_hours=D("8.5")
    )
    assert (entry.worked_hours, entry.short_day) == (D("8.5"), False)
    # Günün çalışma saatine eşit saat kaydedilmez (boş = tam gün).
    entry = services.set_attendance_day(manager, card, full, status=S.WORKED, worked_hours=D("9"))
    assert (entry.worked_hours, entry.short_day) == (None, False)

    grid = selectors.attendance_grid(year, month)
    assert grid.daily_hours == D("9") and {day.expected_hours for day in grid.days} == {D("9")}
    cells = _cells(grid, card)

    def shown(day: date) -> tuple[str, str, Decimal | None, bool, Decimal | None]:
        cell = cells[day]
        return cell.status, cell.code, cell.worked_hours, cell.short_day, cell.day_hours

    # YG bir durum değildir: gün "Çalıştı" kalır, yalnızca kodu değişir.
    assert shown(short) == (S.WORKED, "YG", D("4.5"), True, D("4.5"))
    assert shown(early) == (S.WORKED, "Ç", D("8.5"), False, D("8.5"))
    assert shown(full) == (S.WORKED, "Ç", None, False, D("9"))

    # Gün tam değiştirilir: saat ve işaret verilmezse silinir (eski değerler denetim kaydında).
    again = services.set_attendance_day(manager, card, short, status=S.WORKED, note="Düzeltme")
    assert (again.pk, again.worked_hours, again.short_day) == (marked.pk, None, False)
    log = AuditLog.objects.get(
        object_id=marked.pk, action=AuditLog.Action.UPDATE, content_type__model="attendanceentry"
    )
    assert log.changes["worked_hours"] == ["4.50", None]
    assert log.changes["short_day"] == [True, False]
    assert _cells(selectors.attendance_grid(year, month), card)[short].code == "Ç"


def test_worked_hours_are_rounded_before_the_rules(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    card = employee(manager)
    day = _workdays(year, month)[0]

    def write(value: str) -> AttendanceEntry:
        return services.set_attendance_day(
            manager, card, day, status=S.WORKED, worked_hours=D(value)
        )

    assert _error(lambda: write("0.004")).code == "invalid_worked_hours"  # 0,00 olur
    assert write("8.996").worked_hours is None  # 9,00 olur: tam gün
    assert write("8.994").worked_hours == D("8.99")
    assert write("4.505").worked_hours == D("4.51")  # yarım yukarı


def test_worked_hours_and_short_day_rules(manager: User) -> None:
    year, month = _previous_month()
    card = employee(manager)
    day, arife = _workdays(year, month)[:2]

    def refused(when: date = day, **values: Any) -> tuple[str, str]:
        values.setdefault("status", S.WORKED)
        error = _error(lambda: services.set_attendance_day(manager, card, when, **values))
        return error.code, error.message

    # Günlük çalışma saati belirlenmeden güne saat yazılamaz.
    assert refused(worked_hours=D("4")) == (
        "daily_hours_not_set",
        "Önce günlük çalışma saatini belirleyin (Personel > Tatil takvimi).",
    )
    services.update_attendance_settings(manager, [6], daily_hours=D("9"))
    _half_holiday(manager, arife)

    # Yarım gün ve çalışılan saat yalnızca çalışılan güne; işaretin hatası saatinkinden öncedir.
    assert refused(status=S.ANNUAL_LEAVE, worked_hours=D("4"), short_day=True) == (
        "short_day_not_allowed",
        "Yarım gün yalnızca çalışılan güne (Ç) yazılır.",
    )
    for status in (S.WEEKLY_REST, S.PUBLIC_HOLIDAY, S.ANNUAL_LEAVE, S.SICK_LEAVE, S.ABSENT):
        assert refused(status=status, worked_hours=D("4")) == (
            "worked_hours_not_allowed",
            "Çalışılan saat yalnızca çalışılan güne (Ç) girilir; hafta tatili ve resmi tatilde "
            "çalışılan saat fazla mesaiye yazılır.",
        )
    future = timezone.localdate() + timedelta(days=3)
    assert refused(future, worked_hours=D("4")) == (
        "future_day",
        "Çalışılan saat ileri bir güne girilemez.",
    )
    # 0'dan büyük, en çok günün çalışma saati: olağan günde 9, yarım gün tatilde 4,5.
    for value in ("0", "-1", "9.01", "24"):
        assert refused(worked_hours=D(value)) == (
            "invalid_worked_hours",
            "Çalışılan saat 0'dan büyük, en çok 9 olmalı. Fazlasını fazla mesaiye yazın.",
        )
    for value in ("0", "4.51", "9"):
        assert refused(arife, worked_hours=D(value)) == (
            "invalid_worked_hours",
            "Bu gün yarım gün tatil: çalışılan saat 0'dan büyük, en çok 4,5 olabilir. Öğleden "
            "sonra da çalışıldıysa saati boş bırakıp “Öğleden sonra da çalıştı”yı işaretleyin.",
        )
    assert refused(short_day=True) == (
        "short_day_requires_hours",
        "Yarım gün işareti için önce çalışılan saati yazın.",
    )
    assert refused(worked_hours=D("9"), short_day=True) == (
        "short_day_not_short",
        "Yarım gün yalnızca saati günün çalışma saatinin altında kalan güne yazılır.",
    )
    assert refused(arife, worked_hours=D("4.5"), short_day=True)[0] == "short_day_not_short"
    assert refused(worked_hours=D("8"), overtime_hours=D("1")) == (
        "overtime_with_short_hours",
        "Çalışılan saat günün çalışma saatinin altındayken fazla mesai girilmez.",
    )
    assert refused(arife, worked_hours=D("4"), holiday_half_worked=True) == (
        "half_holiday_with_short_hours",
        "“Öğleden sonra da çalıştı” işaretliyken çalışılan saat günün çalışma saatinin altında "
        "olamaz.",
    )
    # Reddedilen hiçbir istek gün ya da ay kaydı bırakmadı.
    assert not AttendanceEntry.objects.exists() and not AttendanceMonth.objects.exists()

    # Tam saatle birlikte fazla mesai girilebilir (saat kaydedilmez).
    entry = services.set_attendance_day(
        manager, card, day, status=S.WORKED, worked_hours=D("9"), overtime_hours=D("2")
    )
    assert (entry.worked_hours, entry.overtime_hours) == (None, D("2"))


def test_half_holiday_expects_half_the_daily_hours(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    card = employee(manager)
    arife, holiday = _workdays(year, month)[:2]
    _half_holiday(manager, arife)
    services.add_holiday(manager, {"date": holiday, "name": "Bayram"})

    entry = services.set_attendance_day(
        manager, card, arife, status=S.WORKED, worked_hours=D("4"), short_day=True
    )
    assert (entry.worked_hours, entry.short_day) == (D("4"), True)
    grid = selectors.attendance_grid(year, month)
    hours = {day.date: day.expected_hours for day in grid.days}
    assert (hours[arife], hours[holiday]) == (D("4.5"), D("9"))
    assert _cells(grid, card)[arife].code == "YG"

    # Yarım günün tamamı tam gündür; öğleden sonra da çalışıldıysa işaretiyle birlikte girilir ve
    # gün günlük çalışma saatinin tamamıyla sayılır.
    entry = services.set_attendance_day(
        manager, card, arife, status=S.WORKED, worked_hours=D("4.5"), holiday_half_worked=True
    )
    assert (entry.worked_hours, entry.holiday_half_worked) == (None, True)
    cell = _cells(selectors.attendance_grid(year, month), card)[arife]
    assert (cell.holiday_half_worked, cell.day_hours) == (True, D("9"))

    # Tam gün tatile "Çalıştı" yazılan günün çalışma saati günlük çalışma saatidir.
    entry = services.set_attendance_day(
        manager, card, holiday, status=S.WORKED, worked_hours=D("8"), short_day=True
    )
    assert entry.worked_hours == D("8")
    cell = _cells(selectors.attendance_grid(year, month), card)[holiday]
    assert (cell.code, cell.day_hours) == ("YG", D("8"))


def test_hours_are_recorded_for_people_paid_by_the_accountant(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    card = employee(manager, payroll_external=True)
    day = _workdays(year, month)[0]
    entry = services.set_attendance_day(
        manager, card, day, status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    assert (entry.worked_hours, entry.short_day) == (D("4.5"), True)
    assert _cells(selectors.attendance_grid(year, month), card)[day].code == "YG"


def test_day_with_hours_still_locks_the_card_first(manager: User, nine: Decimal) -> None:
    """Kilit sırası değişmez: önce kart; ayar ve tatil kart kilidinden sonra, kilitsiz okunur."""
    year, month = _previous_month()
    card = employee(manager)
    day = _workdays(year, month)[0]
    with CaptureQueriesContext(connection) as queries:
        services.set_attendance_day(
            manager, card, day, status=S.WORKED, worked_hours=D("4.5"), short_day=True
        )
    statements = [query["sql"] for query in queries.captured_queries]
    locks = [index for index, sql in enumerate(statements) if "FOR UPDATE" in sql]
    assert 'FROM "personnel_employee"' in statements[locks[0]]
    reads = [
        index
        for index, sql in enumerate(statements)
        if '"personnel_attendancesettings"' in sql or '"personnel_publicholiday"' in sql
    ]
    assert len(reads) == 2 and min(reads) > locks[0]
    assert not any("FOR UPDATE" in statements[index] for index in reads)


def test_database_refuses_inconsistent_hours(manager: User, nine: Decimal) -> None:
    """Kısıtlar servisin kurallarını veritabanında da tutar (servis dışı yazım kaçamaz)."""
    year, month = _previous_month()
    card = employee(manager)
    day = _workdays(year, month)[0]
    entry = services.set_attendance_day(
        manager, card, day, status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    broken: list[tuple[str, dict[str, Any]]] = [
        ("personnel_attendance_worked_hours_range", {"worked_hours": D("0")}),
        ("personnel_attendance_worked_hours_range", {"worked_hours": D("24.01")}),
        ("personnel_attendance_worked_hours_day", {"status": S.ANNUAL_LEAVE}),
        ("personnel_attendance_worked_hours_day", {"overtime_hours": D("1")}),
        ("personnel_attendance_worked_hours_day", {"holiday_half_worked": True}),
        ("personnel_attendance_short_day", {"worked_hours": None}),
    ]
    for constraint, values in broken:
        with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
            AttendanceEntry.objects.filter(pk=entry.pk).update(**values)
    for value in ("0", "24.01"):
        with (
            pytest.raises(IntegrityError, match="personnel_attendance_settings_daily_hours"),
            transaction.atomic(),
        ):
            AttendanceSettings.objects.update(daily_hours=D(value))


# --- aralık girişi --------------------------------------------------------------------------------


def test_range_keeps_hours_on_worked_days_and_clears_them_otherwise(
    manager: User, nine: Decimal
) -> None:
    year, month = _previous_month()
    card = employee(manager)
    short, early, leave = _workdays(year, month)[:3]
    services.set_attendance_day(
        manager, card, short, status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    services.set_attendance_day(manager, card, early, status=S.WORKED, worked_hours=D("8.5"))
    services.set_attendance_day(
        manager, card, leave, status=S.WORKED, worked_hours=D("4"), short_day=True
    )

    def apply(day: date, status: str, note: str = "") -> int:
        return services.set_attendance_range(
            manager, start=day, end=day, status=status, employee=card, note=note
        )

    # "Çalıştı" kalan günün saati ve işareti korunur; başka bir şey değişmiyorsa gün yazılmaz.
    assert apply(short, S.WORKED) == 0 and apply(early, S.WORKED) == 0
    assert apply(short, S.WORKED, "Vardiya") == 1 and apply(early, S.WORKED, "Vardiya") == 1
    assert _stored(card, short) == (S.WORKED, D("4.5"), True)
    assert _stored(card, early) == (S.WORKED, D("8.5"), False)
    assert AttendanceEntry.objects.get(employee=card, date=short).note == "Vardiya"

    # Başka duruma geçen günün saati ve işareti silinir; gün yeniden "Çalıştı" olunca geri gelmez.
    assert apply(leave, S.ANNUAL_LEAVE) == 1
    assert _stored(card, leave) == (S.ANNUAL_LEAVE, None, False)
    assert apply(leave, S.WORKED) == 1
    assert _stored(card, leave) == (S.WORKED, None, False)
    cells = _cells(selectors.attendance_grid(year, month), card)
    assert [cells[day].code for day in (short, early, leave)] == ["YG", "Ç", "Ç"]


# --- onay: ayın günlük çalışma saati --------------------------------------------------------------


def test_month_takes_daily_hours_at_first_approval_and_keeps_them(
    manager: User, nine: Decimal
) -> None:
    year, month = _previous_month()
    earlier = date(year, month, 1) - timedelta(days=1)
    card = employee(manager)
    day = _workdays(year, month)[0]
    assert selectors.attendance_grid(year, month).daily_hours == D("9")  # güncel ayar

    record = services.approve_attendance_month(manager, year, month)
    assert record.daily_hours == D("9")
    services.update_attendance_settings(manager, [6], daily_hours=D("8"))
    assert selectors.attendance_grid(year, month).daily_hours == D("9")  # onaylı ay değişmez
    # Hiç onaylanmamış ay güncel ayarı kullanır.
    assert selectors.attendance_grid(earlier.year, earlier.month).daily_hours == D("8")

    # Yeniden açılan ay onaydaki değeri korur: 8,5 saat güncel ayarın (8) üstünde, ayın saatinin
    # (9) altındadır.
    reopened = services.reopen_attendance_month(manager, record, "Saat düzeltmesi")
    assert reopened.daily_hours == D("9")
    grid = selectors.attendance_grid(year, month)
    assert grid.daily_hours == D("9") and {item.expected_hours for item in grid.days} == {D("9")}
    entry = services.set_attendance_day(manager, card, day, status=S.WORKED, worked_hours=D("8.5"))
    assert entry.worked_hours == D("8.5")
    cell = _cells(selectors.attendance_grid(year, month), card)[day]
    assert (cell.worked_hours, cell.day_hours) == (D("8.5"), D("8.5"))
    error = _error(
        lambda: services.set_attendance_day(
            manager, card, day, status=S.WORKED, worked_hours=D("9.5")
        )
    )
    assert "en çok 9 olmalı" in error.message

    again = services.approve_attendance_month(manager, year, month)
    assert again.daily_hours == D("9")  # yeniden onay ilk onaydaki değere dokunmaz
    cell = _cells(selectors.attendance_grid(year, month), card)[day]
    assert (cell.worked_hours, cell.editable) == (D("8.5"), False)
    # Onaylı ayda saat ve yarım gün de değişmez.
    locked = _error(
        lambda: services.set_attendance_day(
            manager, card, day, status=S.WORKED, worked_hours=D("4.5"), short_day=True
        )
    )
    assert locked.code == "month_locked"
    assert _stored(card, day) == (S.WORKED, D("8.5"), False)


def test_month_approved_without_daily_hours_shows_none_until_reopened(manager: User) -> None:
    """Günlük çalışma saati yokken (bu alandan önce) onaylanan ay: onaylıyken "kayıtlı değil",
    yeniden açılınca güncel ayar, yeniden onayda o değer."""
    year, month = _previous_month()
    card = employee(manager)
    day = _workdays(year, month)[0]
    record = services.approve_attendance_month(manager, year, month)
    assert record.daily_hours is None
    services.update_attendance_settings(manager, [6], daily_hours=D("9"))

    grid = selectors.attendance_grid(year, month)
    assert grid.approved and grid.daily_hours is None
    assert {item.expected_hours for item in grid.days} == {None}
    assert grid.rows[0].totals.hours is None
    assert {cell.day_hours for cell in grid.rows[0].cells} == {None}

    services.reopen_attendance_month(manager, record, "Saat girilecek")
    grid = selectors.attendance_grid(year, month)
    assert grid.daily_hours == D("9") and grid.rows[0].totals.hours is not None
    services.set_attendance_day(
        manager, card, day, status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    assert services.approve_attendance_month(manager, year, month).daily_hours == D("9")
    assert _cells(selectors.attendance_grid(year, month), card)[day].code == "YG"


# --- sayılma kuralı -------------------------------------------------------------------------------


def test_recorded_hours_count_only_while_the_day_is_short(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    card = employee(manager)
    day = _workdays(year, month)[0]
    services.set_attendance_day(
        manager, card, day, status=S.WORKED, worked_hours=D("5"), short_day=True
    )

    def counted() -> tuple[str, Decimal | None, bool, Decimal | None, int]:
        """Günün tablodaki kodu, sayılan saati ve işareti, günün saati ve ayın YG toplamı."""
        grid = selectors.attendance_grid(year, month)
        cell, totals = _cells(grid, card)[day], grid.rows[0].totals
        # Tablo ve Excel aynı kuralı uygular.
        assert _row(_book(grid), "Puantaj", 3)[3 + day.day - 1] == cell.code
        return cell.code, cell.worked_hours, cell.short_day, cell.day_hours, totals.short_days

    short = ("YG", D("5"), True, D("5"), 1)
    assert counted() == short

    # Gün sonradan yarım gün tatil olur: 5 saat artık günün çalışma saatinin (4,5) altında değil,
    # gün tam sayılır. Kayıt durur; tatil kaldırılınca yeniden sayılır.
    arife = _half_holiday(manager, day)
    assert counted() == ("Ç", None, False, D("4.5"), 0)
    assert _stored(card, day) == (S.WORKED, D("5"), True)
    services.remove_holiday(manager, arife)
    assert counted() == short

    # Günlük çalışma saati düşünce de (hiç onaylanmamış ay güncel ayarı kullanır) aynı kural.
    services.update_attendance_settings(manager, [6], daily_hours=D("5"))
    assert counted() == ("Ç", None, False, D("5"), 0)
    assert _stored(card, day) == (S.WORKED, D("5"), True)
    services.update_attendance_settings(manager, [6], daily_hours=D("9"))
    assert counted() == short

    # Aralık girişi kayıtlı değerleri güncel takvimle yeniden doğrulamaz, olduğu gibi korur.
    _half_holiday(manager, day)
    changed = services.set_attendance_range(
        manager, start=day, end=day, status=S.WORKED, employee=card, note="Arife"
    )
    assert changed == 1 and _stored(card, day) == (S.WORKED, D("5"), True)
    # Gün yeniden kaydedilince (ekran sayılan değeri, yani boş saati gönderir) kayıt temizlenir.
    services.set_attendance_day(manager, card, day, status=S.WORKED, note="Arife")
    assert _stored(card, day) == (S.WORKED, None, False)
    assert counted() == ("Ç", None, False, D("4.5"), 0)


# --- tablo, toplamlar ve Excel --------------------------------------------------------------------


def _sample_month(manager: User) -> tuple[Employee, list[date], date, date]:
    """Geçen ayda bir kişi: yarım gün (4,5), erken çıkış (8,5), fazla mesai (2), rapor, öğleden
    sonra da çalışılan yarım gün tatil (arife) ve çalışılmayan yarım gün tatil (eve)."""
    year, month = _previous_month()
    card = employee(manager, employee_no="S-1")
    days = _workdays(year, month)
    arife, eve = days[5], days[6]
    _half_holiday(manager, arife)
    services.add_holiday(manager, {"date": eve, "name": "Yılbaşı gecesi", "half_day": True})
    services.set_attendance_day(
        manager, card, days[0], status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    services.set_attendance_day(manager, card, days[1], status=S.WORKED, worked_hours=D("8.5"))
    services.set_attendance_day(manager, card, days[2], status=S.WORKED, overtime_hours=D("2"))
    services.set_attendance_day(manager, card, days[3], status=S.SICK_LEAVE)
    services.set_attendance_day(manager, card, arife, status=S.WORKED, holiday_half_worked=True)
    return card, days, arife, eve


def test_totals_count_short_days_and_hours(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    first, last = selectors.month_bounds(year, month)
    card, days, arife, eve = _sample_month(manager)
    grid = selectors.attendance_grid(year, month)
    totals = grid.rows[0].totals
    worked = len(days) - 1  # rapor günü dışındaki iş günleri

    # Yarım gün "Çalıştı" içinde sayılır (durum toplamı ayın günü kadardır); Ç tam günlerdir.
    assert totals.days[S.WORKED] == worked
    assert (totals.short_days, totals.full_days) == (1, worked - 1)
    assert sum(totals.days.values()) == (last - first).days + 1
    assert totals.missing_days == 1 and totals.overtime_total == D("2")  # Eksik ve FM değişmez

    cells = _cells(grid, card)
    assert cells[days[2]].day_hours == D("9")  # fazla mesai çalışılan saate girmez
    assert cells[days[3]].day_hours is None  # çalışılmayan gün
    assert cells[arife].day_hours == D("9")  # öğleden sonra da çalışıldı: günün tamamı
    assert cells[eve].day_hours == D("4.5")  # yarım gün tatil: günün çalışma saati
    sunday = next(day for day in cells if day.weekday() == 6)
    assert cells[sunday].day_hours is None
    # 4,5 + 8,5 + arife 9 + öteki yarım gün tatil 4,5; kalan çalışılan günler 9'ar saat.
    assert totals.hours == D("26.5") + (worked - 4) * D("9")


def test_totals_without_daily_hours(manager: User) -> None:
    year, month = _previous_month()
    employee(manager)
    grid = selectors.attendance_grid(year, month)
    totals = grid.rows[0].totals
    assert grid.daily_hours is None and {day.expected_hours for day in grid.days} == {None}
    assert (totals.short_days, totals.hours) == (0, None)
    assert totals.full_days == totals.days[S.WORKED] > 0


def test_grids_read_the_settings_once(manager: User, nine: Decimal) -> None:
    """Hafta tatili ve günlük çalışma saati, ay ve kişi sayısından bağımsız tek sorguyla okunur
    (bordronun kümülatif zinciri yılın bütün aylarını birlikte kurar)."""
    year, _ = _previous_month()
    for name in ("Ayşe Demir", "Can Kaya", "Ece Ak"):
        employee(manager, full_name=name)
    with CaptureQueriesContext(connection) as queries:
        grids = selectors.attendance_grids(year, range(1, 13))
    assert {grid.daily_hours for grid in grids.values()} == {D("9")}
    assert all(len(grid.rows) == 3 for grid in grids.values())
    reads = [
        query["sql"]
        for query in queries.captured_queries
        if '"personnel_attendancesettings"' in query["sql"]
    ]
    assert len(reads) == 1


def test_excel_shows_short_days_hours_and_legend(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    first = date(year, month, 1)
    card, days, arife, eve = _sample_month(manager)
    grid = selectors.attendance_grid(year, month)
    totals = grid.rows[0].totals
    length = len(grid.days)
    book = _book(grid)
    assert book.sheetnames == ["Puantaj", "Fazla mesai", "Çalışma saatleri", "Kodlar"]

    def of(row: list[Any], day: date) -> Any:
        return row[3 + (day - first).days]  # gün sütunları D'den başlar

    # "Puantaj": kişi sütunları ve günler yerinde; toplamlarda Ç'den hemen sonra YG, en sonda saat.
    headers = _row(book, "Puantaj", 2)
    assert headers[:3] == ["Sicil no", "Ad soyad", "Birim"] and headers[3].startswith("1 ")
    assert headers[3 + length :] == [
        "Ç",
        "YG",
        "HT",
        "RT",
        "Yİ",
        "Mİ",
        "Üİ",
        "R",
        "D",
        "Eksik gün",
        "FM iş günü",
        "FM hafta tatili",
        "FM resmi tatil",
        "FM toplam",
        "Çalışılan saat (FM hariç)",
    ]
    row = _row(book, "Puantaj", 3)
    assert row[:3] == ["S-1", "Ayşe Demir", "Dolum"]
    assert [of(row, day) for day in (days[0], days[1], days[3], arife, eve)] == [
        "YG",
        "Ç",
        "R",
        "Ç½",
        "Ç",
    ]
    tail = row[3 + length :]
    sundays = length - len(days)
    assert tail[:10] == [totals.full_days, 1, sundays, 0, 0, 0, 0, 1, 0, 1]
    assert [_number(value) for value in tail[10:]] == [D("2"), D("0"), D("0"), D("2"), totals.hours]
    assert totals.full_days == len(days) - 2 and totals.hours is not None

    # "Fazla mesai" değişmedi; "Çalışma saatleri" aynı düzende, fazla mesai hariç günlük saat.
    assert _row(book, "Fazla mesai", 1)[0] == f"Fazla mesai (saat) — {grid.label}"
    overtime = _row(book, "Fazla mesai", 3)
    assert (_number(of(overtime, days[2])), _number(overtime[-1])) == (D("2"), D("2"))
    assert _row(book, "Çalışma saatleri", 1)[0] == (
        f"Çalışma saatleri (saat, fazla mesai hariç) — {grid.label}"
    )
    assert _row(book, "Çalışma saatleri", 2) == _row(book, "Fazla mesai", 2)
    assert _row(book, "Çalışma saatleri", 2)[-1] == "Toplam"
    hours = _row(book, "Çalışma saatleri", 3)
    assert hours[:3] == ["S-1", "Ayşe Demir", "Dolum"]
    assert [_number(of(hours, day)) for day in (*days[:4], arife, eve)] == [
        D("4.5"),
        D("8.5"),
        D("9"),
        None,
        D("9"),
        D("4.5"),
    ]
    sunday = next(day.date for day in grid.days if day.date.weekday() == 6)
    assert of(hours, sunday) is None and _number(hours[-1]) == totals.hours
    assert book["Çalışma saatleri"].freeze_panes == "D3"

    # "Kodlar": Ç½'den sonra YG, günlük çalışma saati ve çalışılan saat; sonra tatiller.
    legend = [[cell.value for cell in line] for line in book["Kodlar"].iter_rows()]
    start = legend.index(["Ç½", "Yarım gün tatilde öğleden sonra da çalıştı"])
    assert legend[start + 1 : start + 8] == [
        ["YG", SHORT_DAY_LEGEND],
        ["Günlük çalışma saati", "9 saat (yarım gün tatilde 4,5)"],
        ["Çalışılan saat", WORKED_HOURS_LEGEND],
        [None, None],
        ["Tarih", "Resmi tatil"],
        [f"{arife:%d.%m.%Y}", "Arife (yarım gün)"],
        [f"{eve:%d.%m.%Y}", "Yılbaşı gecesi (yarım gün)"],
    ]
    assert book["Kodlar"].cell(row=start + 6, column=1).font.bold  # "Tarih" başlığı
    assert not book["Kodlar"].cell(row=start + 2, column=1).font.bold


def _daily_hours_legend(book: Workbook) -> str:
    lines = {line[0].value: line[1].value for line in book["Kodlar"].iter_rows()}
    return lines["Günlük çalışma saati"]


def test_excel_without_daily_hours_and_for_month_approved_without_them(manager: User) -> None:
    year, month = _previous_month()
    employee(manager)
    # Ayar yok, ay açık: saat sütunu ve sayfası boş, açıklama "belirlenmedi".
    book = _book(selectors.attendance_grid(year, month))
    assert _daily_hours_legend(book) == "belirlenmedi"
    assert _row(book, "Puantaj", 2)[-1] == "Çalışılan saat (FM hariç)"
    assert _row(book, "Puantaj", 3)[-1] is None
    assert set(_row(book, "Çalışma saatleri", 3)[3:]) == {None}

    # Ay değersiz onaylandı; ayar sonradan belirlense de onaylı ayın çıktısı değişmez.
    services.approve_attendance_month(manager, year, month)
    services.update_attendance_settings(manager, [6], daily_hours=D("7.5"))
    book = _book(selectors.attendance_grid(year, month))
    assert _daily_hours_legend(book) == "bu ay onaylanırken kayıtlı değildi"
    assert _row(book, "Puantaj", 3)[-1] is None
    assert set(_row(book, "Çalışma saatleri", 3)[3:]) == {None}

    # Değeri olan ay (hiç onaylanmamış: güncel ayar).
    earlier = date(year, month, 1) - timedelta(days=1)
    book = _book(selectors.attendance_grid(earlier.year, earlier.month))
    assert _daily_hours_legend(book) == "7,5 saat (yarım gün tatilde 3,75)"


def test_personnel_output_template_versions() -> None:
    """Şablon sürümleri (revizyon girilmişse ekran yenisini ister): "Puantaj çizelgesi" (FR-IK-001)
    2 (YG sütunu, 1. adım; Kodlar açıklaması 2. adımda yalnız metin), ön bordro (FR-IK-002) ve
    ücret hesap pusulası (FR-IK-004) 2 (yarım gün kesintisi satırları ve sütunları); işveren
    maliyeti tablosu (FR-IK-003) değişmedi, 1."""
    for key, code, version in (
        (pdf.ATTENDANCE_OUTPUT, "FR-IK-001", 2),
        (pdf.PAYROLL_OUTPUT, "FR-IK-002", 2),
        (pdf.EMPLOYER_COST_OUTPUT, "FR-IK-003", 1),
        (pdf.PAYSLIP_OUTPUT, "FR-IK-004", 2),
    ):
        output = registry.output_type(key)
        assert output is not None
        assert (output.suggested_code, output.template_version) == (code, version)


def test_short_day_deducts_half_a_day_in_payroll(manager: User, nine: Decimal) -> None:
    """2. adım: sayılan YG günü ön bordroda (Ekim 2026, brütten nete) ve personel maliyetinde
    yarım günlük ücret keser (45.000 / 60 = 750,00); normal ücret, SGK günü, ücretli ve fiilen
    çalışılan gün aynı kalır. İşaretsiz kısa gün ve artık sayılmayan YG kesmez. (1. adımda bu test
    "bordro değişmez" diyordu; bilerek tersine çevrildi.)"""
    parameter_set(manager)
    person = employee(manager, hire_date=date(2020, 1, 1))
    services.add_wage(
        manager,
        {"employee": person, "gross_monthly": D("45000"), "valid_from": date(2020, 1, 1)},
    )

    def figures() -> tuple[payroll.Result, Decimal, Decimal]:
        month = selectors.payroll_month(2026, 10)
        cost = selectors.payroll_month(2026, 10, net=False)  # personel maliyetinin okuduğu hesap
        return month.rows[0].line, cost.gross_total, cost.employer_cost

    before, gross, cost = figures()
    # İşaretsiz kısa gün yalnızca saattir: kesinti yok.
    services.set_attendance_day(
        manager, person, date(2026, 10, 6), status=S.WORKED, worked_hours=D("8.5")
    )
    assert figures() == (before, gross, cost)

    services.set_attendance_day(
        manager, person, date(2026, 10, 5), status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    assert _cells(selectors.attendance_grid(2026, 10), person)[date(2026, 10, 5)].code == "YG"
    line, short_gross, short_cost = figures()
    assert (line.short_days, line.short_day_deduction) == (1, D("750.00"))
    assert line.gross_total == before.gross_total - D("750.00")
    assert (line.salary, line.sgk_days, line.paid_days, line.worked_days) == (
        before.salary,
        before.sgk_days,
        before.paid_days,
        before.worked_days,
    )
    assert short_gross == gross - D("750.00") and short_cost < cost

    # Günlük çalışma saati düşünce 4,5 saat artık eksik değil: YG sayılmaz, kesinti kalkar.
    services.update_attendance_settings(manager, [6], daily_hours=D("4.5"))
    assert figures() == (before, gross, cost)


# --- ayrılış özeti --------------------------------------------------------------------------------


def test_day_summary_shows_hours_and_short_days() -> None:
    def day(
        on: int,
        *,
        worked: str | None = None,
        short: bool = False,
        hours: str = "0",
        note: str = "",
    ) -> AttendanceEntry:  # kaydedilmemiş gün yeter
        return AttendanceEntry(
            date=date(2026, 9, on),
            status=S.WORKED,
            overtime_hours=D(hours),
            worked_hours=None if worked is None else D(worked),
            short_day=short,
            note=note,
        )

    entries = [
        day(21, worked="4.5", short=True),
        day(22, worked="4.50", short=True),
        day(23, worked="4.5"),  # saat aynı, işaret yok: ayrı aralık
        day(24, worked="8.5", note="Erken çıktı"),
        day(25),
        day(26, hours="2"),
        day(28, worked="8.5"),
        day(29, worked="8.5"),
    ]
    assert selectors.summarize_days(entries) == (
        "Eylül 2026: 21–22.09 YG (günde 4,5 sa), 23.09 Ç (4,5 sa), 24.09 Ç (8,5 sa, notlu), "
        "25.09 Ç, 26.09 Ç (2 sa FM), 28–29.09 Ç (günde 8,5 sa)"
    )


def test_exit_lists_and_audits_removed_hours(manager: User, nine: Decimal) -> None:
    year, month = _previous_month()
    card = employee(manager, hire_date=date(2020, 1, 1))
    exit_day, later = _workdays(year, month)[:2]
    services.set_attendance_day(
        manager, card, later, status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    error = _error(lambda: services.terminate_employee(manager, card, exit_day))
    assert error.code == "attendance_after_exit"
    summary = f"{selectors.month_label(year, month)}: {later:%d.%m} YG (4,5 sa)"
    assert f"kayıtlı 1 gün var: {summary}." in error.message

    services.terminate_employee(manager, card, exit_day, remove_attendance=True)
    assert not AttendanceEntry.objects.filter(employee=card).exists()
    card_log = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(Employee), object_id=card.pk
    ).latest("timestamp", "id")
    assert card_log.note.endswith(f"puantaj günü kaldırıldı: {summary}")
    month_log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(AttendanceMonth),
        note__startswith="Çıkış tarihinden sonraki puantaj günü kaldırıldı",
    )
    before, after = month_log.changes["entry"]
    assert (before["worked_hours"], before["short_day"], after) == ("4.50", True, None)


# --- yetki ve API ---------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["depo", "planlama", "uretim", "laboratuvar", "sevkiyat"])
def test_only_management_and_admin_set_hours(
    make_user: Callable[..., User], manager: User, role: str
) -> None:
    year, month = _previous_month()
    card = employee(manager)
    day = _workdays(year, month)[0]
    other = make_user(role)
    with pytest.raises(PermissionDenied):
        services.update_attendance_settings(other, [6], daily_hours=D("9"))
    assert selectors.daily_hours() is None
    admin = make_user("admin")
    assert services.update_attendance_settings(admin, [6], daily_hours=D("9")).daily_hours == D("9")
    with pytest.raises(PermissionDenied):
        services.set_attendance_day(
            other, card, day, status=S.WORKED, worked_hours=D("4.5"), short_day=True
        )
    assert not AttendanceEntry.objects.exists()
    entry = services.set_attendance_day(
        admin, card, day, status=S.WORKED, worked_hours=D("4.5"), short_day=True
    )
    assert entry.short_day


def test_settings_api_keeps_daily_hours_unless_sent(api: APIClient) -> None:
    url = f"{BASE}/settings/"
    body = api.get(url).json()
    assert set(body) == {"rest_weekdays", "daily_hours", "updated_at"}
    assert body["daily_hours"] is None
    response = api.patch(url, {"rest_weekdays": [6], "daily_hours": "9"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["daily_hours"] == "9.00"

    # Yalnızca hafta tatili gönderen (eski) istemci günlük çalışma saatini değiştirmez.
    response = api.patch(url, {"rest_weekdays": [5, 6]}, format="json")
    assert response.status_code == 200
    assert (response.json()["rest_weekdays"], response.json()["daily_hours"]) == ([5, 6], "9.00")
    assert api.get(url).json()["daily_hours"] == "9.00"

    response = api.patch(url, {"rest_weekdays": [6], "daily_hours": None}, format="json")
    assert response.status_code == 400 and response.json() == {
        "code": "daily_hours_required",
        "detail": "Günlük çalışma saati boş bırakılamaz; yeni değeri yazın.",
    }
    for value in ("0", "-1", "24.01"):
        response = api.patch(url, {"rest_weekdays": [6], "daily_hours": value}, format="json")
        assert response.status_code == 400 and response.json() == {
            "code": "invalid_daily_hours",
            "detail": INVALID_DAILY_HOURS,
        }
    response = api.patch(url, {"rest_weekdays": [6], "daily_hours": "7.555"}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    # Reddedilen istekler hafta tatilini de değiştirmedi.
    body = api.get(url).json()
    assert (body["rest_weekdays"], body["daily_hours"]) == ([5, 6], "9.00")
    response = api.patch(url, {"rest_weekdays": [6], "daily_hours": "7.5"}, format="json")
    assert response.status_code == 200 and response.json()["daily_hours"] == "7.50"


def test_grid_and_day_api_carry_hours(api: APIClient, manager: User) -> None:
    year, month = _previous_month()
    first = date(year, month, 1)
    card = employee(manager)
    day, arife = _workdays(year, month)[:2]
    url = f"{BASE}/{year}/{month}/"

    # Günlük çalışma saati belirlenmeden ayın ve günlerin saati boştur.
    body = api.get(url).json()
    assert body["daily_hours"] is None and body["days"][0]["expected_hours"] is None
    services.update_attendance_settings(manager, [6], daily_hours=D("9"))
    _half_holiday(manager, arife)
    body = api.get(url).json()
    assert body["daily_hours"] == "9.00"
    assert set(body["days"][0]) == {
        "date",
        "weekday",
        "rest",
        "holiday_name",
        "half_day",
        "expected_hours",
    }
    columns = {column["date"]: column["expected_hours"] for column in body["days"]}
    assert (columns[day.isoformat()], columns[arife.isoformat()]) == ("9.00", "4.50")
    row = body["rows"][0]
    cell = row["cells"][(day - first).days]
    assert (cell["code"], cell["worked_hours"], cell["short_day"]) == ("Ç", None, False)
    assert set(row["totals"]) == {
        "days",
        "short_days",
        "full_days",
        "missing_days",
        "overtime",
        "overtime_total",
    }
    assert (row["totals"]["short_days"], row["totals"]["full_days"]) == (
        0,
        row["totals"]["days"]["WORKED"],
    )

    payload = {
        "employee": card.pk,
        "date": day.isoformat(),
        "status": "WORKED",
        "worked_hours": "4.5",
        "short_day": True,
    }
    response = api.post(f"{BASE}/days/", payload, format="json")
    assert response.status_code == 200, response.json()
    saved = response.json()
    assert (saved["status"], saved["code"], saved["worked_hours"], saved["short_day"]) == (
        "WORKED",
        "YG",
        "4.50",
        True,
    )
    row = api.get(url).json()["rows"][0]
    cell = row["cells"][(day - first).days]
    assert (cell["status"], cell["code"], cell["worked_hours"], cell["short_day"]) == (
        "WORKED",
        "YG",
        "4.50",
        True,
    )
    assert row["totals"]["short_days"] == 1
    assert row["totals"]["full_days"] == row["totals"]["days"]["WORKED"] - 1

    # İş kuralı ihlali 400 ve kodla döner; biçimi bozuk saat doğrulama hatasıdır.
    response = api.post(f"{BASE}/days/", {**payload, "worked_hours": "9.5"}, format="json")
    assert response.status_code == 400 and response.json() == {
        "code": "invalid_worked_hours",
        "detail": "Çalışılan saat 0'dan büyük, en çok 9 olmalı. Fazlasını fazla mesaiye yazın.",
    }
    response = api.post(f"{BASE}/days/", {**payload, "worked_hours": None}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "short_day_requires_hours"
    for value in ("4.555", "100", "dört"):
        response = api.post(f"{BASE}/days/", {**payload, "worked_hours": value}, format="json")
        assert response.status_code == 400 and response.json()["code"] == "validation_error"
        assert "worked_hours" in response.json()["errors"]
    assert _stored(card, day) == (S.WORKED, D("4.5"), True)

    # Alanları göndermeyen istek günü tam değiştirir: saat silinir, işaret kalkar.
    plain = {"employee": card.pk, "date": day.isoformat(), "status": "WORKED"}
    response = api.post(f"{BASE}/days/", plain, format="json")
    assert response.status_code == 200
    saved = response.json()
    assert (saved["code"], saved["worked_hours"], saved["short_day"]) == ("Ç", None, False)

    # Tablo sayılanı, gün yanıtı kayıttakini verir: saat artık eksik değilse hücrede görünmez.
    on_arife = {**payload, "date": arife.isoformat(), "worked_hours": "4"}
    response = api.post(f"{BASE}/days/", on_arife, format="json")
    assert response.status_code == 200 and response.json()["code"] == "YG"
    services.update_attendance_settings(manager, [6], daily_hours=D("8"))
    cell = api.get(url).json()["rows"][0]["cells"][(arife - first).days]
    assert (cell["code"], cell["worked_hours"], cell["short_day"]) == ("Ç", None, False)
    assert _stored(card, arife) == (S.WORKED, D("4"), True)


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_set_hours_or_daily_hours(
    client_for: Callable[..., APIClient], manager: User, role: str
) -> None:
    year, month = _previous_month()
    card = employee(manager)
    services.update_attendance_settings(manager, [6], daily_hours=D("9"))
    day = {
        "employee": card.pk,
        "date": _workdays(year, month)[0].isoformat(),
        "status": "WORKED",
        "worked_hours": "4.5",
        "short_day": True,
    }
    client = client_for(role)
    checks = [
        client.patch(
            f"{BASE}/settings/", {"rest_weekdays": [6], "daily_hours": "8"}, format="json"
        ),
        client.post(f"{BASE}/days/", day, format="json"),
        client.get(f"{BASE}/settings/"),
    ]
    assert [response.status_code for response in checks] == [403, 403, 403]
    assert selectors.daily_hours() == D("9") and not AttendanceEntry.objects.exists()
