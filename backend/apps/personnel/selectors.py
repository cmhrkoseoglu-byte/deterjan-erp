"""Personel okuma sorguları: kartlar, belgeler, puantaj tablosu, ücretler ve ön bordro."""

import calendar
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.core.audit import mask_identifier
from apps.core.formatting import format_money
from apps.core.models import AuditLog, User
from apps.personnel import payroll
from apps.personnel.models import (
    ATTENDANCE_CODES,
    OVERTIME_STATUSES,
    SHORT_DAY_CODE,
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeWage,
    ExternalPayrollFigure,
    PayrollApproval,
    PayrollItem,
    PayrollItemCategory,
    PayrollItemKind,
    PayrollOpeningBalance,
    PayrollParameterSet,
    PayrollRun,
    PayrollSlip,
    PublicHoliday,
    default_rest_weekdays,
)

MONTH_NAMES = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
# Eksik gün (SGK): ücretsiz izin, rapor ve devamsızlık.
MISSING_DAY_STATUSES = (
    AttendanceStatus.UNPAID_LEAVE,
    AttendanceStatus.SICK_LEAVE,
    AttendanceStatus.ABSENT,
)


def fold(text: str) -> str:
    """Türkçe büyük/küçük harf duyarsız karşılaştırma anahtarı ("İDARİ" = "idari", "I" = "ı")."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def departments() -> list[str]:
    """Kayıtlı birimler (ayrılan personelinkiler dahil), alfabetik."""
    names = Employee.objects.values_list("department", flat=True).distinct()
    return sorted(set(names), key=fold)


def canonical_department(name: str) -> str:
    """Birim daha önce farklı büyük/küçük harfle yazıldıysa o yazımı döner."""
    key = fold(name)
    return next((existing for existing in departments() if fold(existing) == key), name)


def employee_history(employee: Employee) -> QuerySet[AuditLog]:
    """Kartın denetim geçmişi (en yenisi önce)."""
    content_type = ContentType.objects.get_for_model(Employee)
    return (
        AuditLog.objects.filter(content_type=content_type, object_id=employee.pk)
        .select_related("actor")
        .order_by("-timestamp", "-id")
    )


def employee_documents(employee: Employee) -> QuerySet[EmployeeDocument]:
    """Kartın kaldırılmamış belgeleri: bordrolar dönemine, sözleşmeler başlangıcına, diğerleri
    eklenme zamanına göre en yenisi önce."""
    return (
        employee.documents.filter(is_active=True)
        .select_related("created_by")
        .order_by(
            F("period").desc(nulls_last=True),
            F("valid_from").desc(nulls_last=True),
            "-created_at",
            "-id",
        )
    )


def linkable_users(employee: Employee | None = None) -> QuerySet[User]:
    """Karta bağlanabilecek kullanıcılar: aktif ve başka bir karta bağlı olmayanlar. Düzenlenen
    kartın bağlı kullanıcısı (pasif olsa da) listede kalır."""
    condition = Q(is_active=True, employee__isnull=True)
    if employee is not None:
        condition |= Q(employee=employee)
    return User.objects.filter(condition).order_by("full_name", "username")


# --- puantaj -------------------------------------------------------------------------------------


def month_label(year: int, month: int) -> str:
    """ "Ekim 2026"."""
    return f"{MONTH_NAMES[month - 1]} {year}"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Ayın ilk ve son günü."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def day_span(first: date, last: date) -> str:
    """Aynı aydaki gün aralığı: "21.09" ya da "21–30.09"."""
    return f"{first:%d.%m}" if first == last else f"{first:%d}–{last:%d.%m}"


def format_hours(value: Decimal) -> str:
    """Saat, sondaki sıfırlar atılarak: Decimal("2.50") → "2,5"."""
    return f"{value.normalize():f}".replace(".", ",")


def round_hours(value: Decimal) -> Decimal:
    """Saat, 0,01'e yuvarlanır (yarım yukarı): günlük çalışma saati ve çalışılan saat."""
    return value.quantize(Decimal("0.01"), ROUND_HALF_UP)


# Günün özetteki ayırt edici bilgisi: durum, fazla mesai, not olup olmadığı, kayıtlı çalışılan saat
# ve yarım gün işareti.
_DayKey = tuple[str, Decimal, bool, Decimal | None, bool]


def _run_label(first: date, last: date, key: _DayKey) -> str:
    status, hours, noted, worked, short = key
    each = "günde " if first != last else ""
    extra = []
    if worked is not None:
        extra.append(f"{each}{format_hours(worked)} sa")
    if hours:
        extra.append(f"{each}{format_hours(hours)} sa FM")
    if noted:
        extra.append("notlu")
    code = SHORT_DAY_CODE if short else ATTENDANCE_CODES.get(status, status)
    text = f"{day_span(first, last)} {code}"
    return f"{text} ({', '.join(extra)})" if extra else text


def summarize_days(entries: Iterable[AttendanceEntry]) -> str:
    """Kayıtlı günlerin kısa özeti, ay ay. Durumu, fazla mesaisi, not işareti, çalışılan saati ve
    yarım gün işareti aynı ardışık günler aralık olur: "Eylül 2026: 21–23.09 Üİ, 24.09 Ç (2 sa FM,
    notlu), 25.09 YG (4,5 sa); Ekim 2026: 05–06.10 Yİ". Çok günlük aralıkta saatler gün başınadır
    ("günde 2 sa FM"); notun metni denetim kaydındadır. Çalışılan saat ve yarım gün kayıttaki
    haliyle yazılır (takvime göre sayılıp sayılmadığına bakılmaz)."""
    months: dict[tuple[int, int], list[tuple[date, date, _DayKey]]] = {}
    for entry in sorted(entries, key=lambda item: item.date):
        key = (
            entry.status,
            Decimal(entry.overtime_hours or 0),
            bool(entry.note),
            None if entry.worked_hours is None else Decimal(entry.worked_hours),
            bool(entry.short_day),
        )
        runs = months.setdefault((entry.date.year, entry.date.month), [])
        if runs and runs[-1][2] == key and runs[-1][1] + timedelta(days=1) == entry.date:
            runs[-1] = (runs[-1][0], entry.date, key)
        else:
            runs.append((entry.date, entry.date, key))
    return "; ".join(
        f"{month_label(year, month)}: " + ", ".join(_run_label(*run) for run in runs)
        for (year, month), runs in months.items()
    )


def attendance_settings() -> AttendanceSettings | None:
    """Puantaj ayarları kaydı, tek sorguyla; hiç kaydedilmediyse None (varsayılanlar geçerlidir)."""
    return AttendanceSettings.objects.order_by("pk").first()


def _rest_days(settings: AttendanceSettings | None) -> set[int]:
    return set(settings.rest_weekdays if settings else default_rest_weekdays())


def rest_weekdays() -> set[int]:
    """Ay önceden dolu açılırken hafta tatili sayılan günler (pazartesi 0 … pazar 6)."""
    return _rest_days(attendance_settings())


def daily_hours() -> Decimal | None:
    """Güncel günlük çalışma saati (ayardan); belirlenmediyse None."""
    settings = attendance_settings()
    return settings.daily_hours if settings else None


def holidays_between(start: date, end: date) -> dict[date, PublicHoliday]:
    """Aralıktaki resmi tatiller (kaldırılanlar hariç), tarihe göre."""
    rows = PublicHoliday.objects.filter(is_active=True, date__range=(start, end))
    return {holiday.date: holiday for holiday in rows}


def holidays_of_year(year: int) -> QuerySet[PublicHoliday]:
    return PublicHoliday.objects.filter(is_active=True, date__year=year).order_by("date")


def half_holiday_hours(daily: Decimal) -> Decimal:
    """Yarım gün tatilde (arife, 28 Ekim) günün çalışma saati: günlük çalışma saatinin yarısı."""
    return round_hours(daily / 2)


def expected_hours(daily: Decimal | None, holiday: PublicHoliday | None) -> Decimal | None:
    """Günün çalışma saati: günlük çalışma saati, takvimde yarım gün tatil olan günde yarısı.
    Tam gün tatile ya da hafta tatiline "Çalıştı" yazılmış günde de günlük çalışma saatidir.
    Günlük çalışma saati bilinmiyorsa None."""
    if daily is None:
        return None
    if holiday is not None and holiday.half_day:
        return half_holiday_hours(daily)
    return daily


def month_daily_hours(record: AttendanceMonth | None, current: Decimal | None) -> Decimal | None:
    """Ayın günlük çalışma saati: ay bir kez onaylandıysa onaydaki değer (yeniden açılınca da
    korunur); hiç onaylanmamış ayda güncel ayar (`current`). Değeri kaydedilmeden onaylanmış ay
    onaylıyken None'dır ("kayıtlı değil"); yeniden açılınca güncel ayarı kullanır."""
    if record is not None and record.daily_hours is not None:
        return record.daily_hours
    if record is not None and record.status == AttendanceMonth.Status.APPROVED:
        return None
    return current


def default_status(day: date, holiday: PublicHoliday | None, rest: set[int]) -> str:
    """Değiştirilmemiş günün durumu: tam gün tatil resmi tatil (pazara denk gelse de), hafta
    tatili günü hafta tatili, diğerleri (yarım gün tatil dahil) çalıştı."""
    if holiday is not None and not holiday.half_day:
        return AttendanceStatus.PUBLIC_HOLIDAY
    if day.weekday() in rest:
        return AttendanceStatus.WEEKLY_REST
    return AttendanceStatus.WORKED


def employed_on(employee: "Employee | PersonView", day: date) -> bool:
    """Kişi o gün işte mi (işe giriş ve çıkış tarihi dahil)? Tarih girilmemişse sınır yoktur."""
    if employee.hire_date and day < employee.hire_date:
        return False
    return not (employee.termination_date and day > employee.termination_date)


def employees_between(start: date, end: date, department: str = "") -> QuerySet[Employee]:
    """Aralıkta en az bir gün işte olan personel."""
    rows = Employee.objects.filter(
        Q(hire_date__isnull=True) | Q(hire_date__lte=end),
        Q(termination_date__isnull=True) | Q(termination_date__gte=start),
    )
    if department:
        rows = rows.filter(department=department)
    return rows.order_by("full_name", "id")


def month_record(year: int, month: int) -> AttendanceMonth | None:
    return (
        AttendanceMonth.objects.select_related("approved_by").filter(year=year, month=month).first()
    )


def in_payroll(employee: Employee, year: int, month: int) -> bool:
    """Kişi o ay bordroda mı (ayın kendi görünümü ve zincirle aynı kural, `_works_in`): kartına
    göre işte olduğu bir günde puantajda durumu var. Açık puantajda işte olunan her günün
    varsayılan durumu vardır; onaylı puantajda yalnızca kayıtlı günler sayılır."""
    first, last = month_bounds(year, month)
    if not _overlaps(employee, first, last):
        return False
    record = month_record(year, month)
    if record is None or record.status != AttendanceMonth.Status.APPROVED:
        return True
    days = AttendanceEntry.objects.filter(employee=employee, date__range=(first, last)).values_list(
        "date", flat=True
    )
    return any(employed_on(employee, day) for day in days)


@dataclass(frozen=True)
class AttendanceDay:
    """Tablonun bir günü (sütun). `expected_hours`: günün çalışma saati (ayın günlük çalışma
    saati, yarım gün tatilde yarısı); günlük çalışma saati bilinmiyorsa None."""

    date: date
    rest: bool
    holiday: PublicHoliday | None
    expected_hours: Decimal | None = None

    @property
    def weekday(self) -> int:
        return self.date.weekday()

    @property
    def holiday_name(self) -> str:
        return self.holiday.name if self.holiday else ""

    @property
    def half_day(self) -> bool:
        return bool(self.holiday and self.holiday.half_day)


@dataclass(frozen=True)
class AttendanceCell:
    """Kişinin bir günü. `status` boşsa kişi o gün işte değil. `explicit`: kayıtlı gün
    (değiştirilmiş ya da onayla yazılmış); değilse varsayılan. `holiday_half_worked`: yarım gün
    tatilde öğleden sonra da çalıştı.

    `worked_hours` ve `short_day` sayılan değerlerdir (`_counted_hours`): kayıtlı çalışılan saat
    yalnızca günün çalışma saatinin altındaysa, yarım gün işareti yalnızca saat sayılıyorsa.
    `day_hours` çalışılan günün sayılan saatidir (fazla mesai hariç): sayılan çalışılan saat;
    yoksa günün çalışma saati, yarım gün tatilde öğleden sonra da çalışıldıysa günlük çalışma
    saatinin tamamı. Çalışılmayan günde ve günlük çalışma saati bilinmiyorsa None."""

    date: date
    status: str
    overtime_hours: Decimal
    note: str
    explicit: bool
    editable: bool
    holiday_half_worked: bool = False
    worked_hours: Decimal | None = None
    short_day: bool = False
    day_hours: Decimal | None = None

    @property
    def code(self) -> str:
        if self.short_day:
            return SHORT_DAY_CODE
        return ATTENDANCE_CODES.get(self.status, "")


@dataclass
class AttendanceTotals:
    """Kişinin ay toplamları: durum başına gün, eksik gün ve günün durumuna göre fazla mesai.

    Yarım gün çalışılan gün (`short_days`) `days` içinde "Çalıştı" sayılır; tam gün çalışılan gün
    `full_days`'tir. `hours`: günlerin sayılan çalışma saati toplamı (`AttendanceCell.day_hours`,
    fazla mesai hariç); hiçbir günün saati bilinmiyorsa None."""

    days: dict[str, int] = field(default_factory=dict)
    overtime: dict[str, Decimal] = field(default_factory=dict)
    short_days: int = 0
    hours: Decimal | None = None

    @property
    def missing_days(self) -> int:
        return sum(self.days.get(status, 0) for status in MISSING_DAY_STATUSES)

    @property
    def overtime_total(self) -> Decimal:
        return sum(self.overtime.values(), Decimal(0))

    @property
    def full_days(self) -> int:
        return self.days.get(AttendanceStatus.WORKED, 0) - self.short_days


def attendance_totals(cells: Iterable[AttendanceCell]) -> AttendanceTotals:
    totals = AttendanceTotals(
        days=dict.fromkeys(AttendanceStatus.values, 0),
        overtime={status.value: Decimal(0) for status in OVERTIME_STATUSES},
    )
    for cell in cells:
        if not cell.status:
            continue
        totals.days[cell.status] += 1
        if cell.short_day:
            totals.short_days += 1
        if cell.day_hours is not None:
            totals.hours = (totals.hours or Decimal(0)) + cell.day_hours
        if cell.overtime_hours:
            totals.overtime[cell.status] += cell.overtime_hours
    return totals


@dataclass
class AttendanceRow:
    employee: Employee
    cells: list[AttendanceCell]

    @property
    def totals(self) -> AttendanceTotals:
        return attendance_totals(self.cells)


@dataclass
class AttendanceGrid:
    """Aylık puantaj tablosu. Açık ayda değiştirilmemiş günler takvimden hesaplanır; onaylı ayda
    yalnızca kayıtlı günler vardır. `daily_hours` ayın günlük çalışma saatidir
    (`month_daily_hours`); günlerin çalışma saati bundan hesaplanır."""

    year: int
    month: int
    record: AttendanceMonth | None
    days: list[AttendanceDay]
    rows: list[AttendanceRow]
    daily_hours: Decimal | None

    @property
    def status(self) -> str:
        return self.record.status if self.record else AttendanceMonth.Status.OPEN

    @property
    def approved(self) -> bool:
        return self.status == AttendanceMonth.Status.APPROVED

    @property
    def finished(self) -> bool:
        """Ay bitti mi (onay ancak ay bitince verilir)?"""
        return self.days[-1].date < timezone.localdate()

    @property
    def label(self) -> str:
        return month_label(self.year, self.month)


def _overlaps(employee: Employee, first: date, last: date) -> bool:
    """Kişi aralıkta en az bir gün işte mi (`employees_between` ile aynı kural)?"""
    if employee.hire_date and employee.hire_date > last:
        return False
    return not (employee.termination_date and employee.termination_date < first)


def _counted_hours(entry: AttendanceEntry | None, day: AttendanceDay) -> Decimal | None:
    """Kayıtlı çalışılan saat, yalnızca günün çalışma saatinin altındaysa (sayılma kuralı). Tatil
    takvimi ya da günlük çalışma saati sonradan değişir ve kayıtlı saat eksik olmaktan çıkarsa
    kayıt durur ama gün tam gün sayılır; değişiklik geri alınırsa yeniden sayılır."""
    if entry is None or entry.worked_hours is None or day.expected_hours is None:
        return None
    return entry.worked_hours if entry.worked_hours < day.expected_hours else None


def _grid_rows(
    people: Iterable[Employee],
    days: list[AttendanceDay],
    saved: dict[tuple[int, date], AttendanceEntry],
    approved: bool,
    rest: set[int],
    daily: Decimal | None,
) -> list[AttendanceRow]:
    rows = []
    for employee in sorted(people, key=lambda person: (fold(person.full_name), person.pk)):
        cells = []
        for day in days:
            entry = saved.get((employee.pk, day.date))
            working = employed_on(employee, day.date)
            if entry is not None:
                status, hours, note = entry.status, entry.overtime_hours, entry.note
            elif working and not approved:
                status, hours, note = default_status(day.date, day.holiday, rest), Decimal(0), ""
            else:
                status, hours, note = "", Decimal(0), ""
            # İşaret yalnızca takvimde hâlâ yarım gün tatil olan günde sayılır; tatil
            # kaldırılırsa saklı işaret durur ama tabloda, Excel'de ve bordroda görünmez.
            half_worked = bool(entry and entry.holiday_half_worked and day.half_day)
            worked = _counted_hours(entry, day)
            if status != AttendanceStatus.WORKED:
                day_hours = None
            elif worked is not None:
                day_hours = worked
            else:
                # Öğleden sonra da çalışılan yarım gün tatil günlük çalışma saatinin tamamıdır.
                day_hours = daily if half_worked else day.expected_hours
            cells.append(
                AttendanceCell(
                    date=day.date,
                    status=status,
                    overtime_hours=hours,
                    note=note,
                    explicit=entry is not None,
                    editable=working and not approved,
                    holiday_half_worked=half_worked,
                    worked_hours=worked,
                    short_day=bool(entry and entry.short_day and worked is not None),
                    day_hours=day_hours,
                )
            )
        rows.append(AttendanceRow(employee=employee, cells=cells))
    return rows


def attendance_grids(
    year: int, months: Iterable[int], *, department: str = ""
) -> dict[int, AttendanceGrid]:
    """Bir yılın aylarının puantaj tabloları, ay sayısından bağımsız sabit sayıda sorguyla
    (bordronun kümülatif zinciri için). Her ay `attendance_grid` ile aynıdır."""
    wanted = sorted(set(months))
    if not wanted:
        return {}
    first = date(year, wanted[0], 1)
    last = month_bounds(year, wanted[-1])[1]
    records = {
        record.month: record
        for record in AttendanceMonth.objects.select_related("approved_by").filter(
            year=year, month__in=wanted
        )
    }
    holidays = holidays_between(first, last)
    # Ayar bir kez okunur: hafta tatili günleri ve güncel günlük çalışma saati.
    settings = attendance_settings()
    rest = _rest_days(settings)
    current = settings.daily_hours if settings else None
    entries = AttendanceEntry.objects.filter(date__range=(first, last)).select_related("employee")
    if department:
        entries = entries.filter(employee__department=department)
    saved_by_month: dict[int, dict[tuple[int, date], AttendanceEntry]] = defaultdict(dict)
    for entry in entries:
        saved_by_month[entry.date.month][(entry.employee_id, entry.date)] = entry
    candidates: list[Employee] | None = None
    grids = {}
    for month in wanted:
        month_first, month_last = month_bounds(year, month)
        record = records.get(month)
        approved = record is not None and record.status == AttendanceMonth.Status.APPROVED
        daily = month_daily_hours(record, current)
        days = [
            AttendanceDay(
                date=day,
                rest=day.weekday() in rest,
                holiday=holidays.get(day),
                expected_hours=expected_hours(daily, holidays.get(day)),
            )
            for day in days_between(month_first, month_last)
        ]
        saved = saved_by_month.get(month, {})
        people = {entry.employee_id: entry.employee for entry in saved.values()}
        if not approved:
            if candidates is None:
                candidates = list(employees_between(first, last, department))
            for employee in candidates:
                if _overlaps(employee, month_first, month_last):
                    people.setdefault(employee.pk, employee)
        rows = _grid_rows(people.values(), days, saved, approved, rest, daily)
        grids[month] = AttendanceGrid(
            year=year, month=month, record=record, days=days, rows=rows, daily_hours=daily
        )
    return grids


def attendance_grid(year: int, month: int, *, department: str = "") -> AttendanceGrid:
    """Ayın puantaj tablosu (isteğe bağlı birim süzgeciyle)."""
    return attendance_grids(year, [month], department=department)[month]


# --- ücretler ------------------------------------------------------------------------------------


def wages_by_employee(employee_ids: Iterable[int], last: date) -> dict[int, list[EmployeeWage]]:
    """Kişi başına `last` tarihine kadar başlamış geçerli (kaldırılmamış) ücretler, eskiden
    yeniye."""
    rows = EmployeeWage.objects.filter(
        employee_id__in=list(employee_ids), is_active=True, valid_from__lte=last
    ).order_by("employee_id", "valid_from", "id")
    result: dict[int, list[EmployeeWage]] = defaultdict(list)
    for wage in rows:
        result[wage.employee_id].append(wage)
    return result


def wage_on(wages: Sequence[EmployeeWage], day: date) -> Decimal | None:
    """Eskiden yeniye sıralı ücretlerden `day` günü geçerli brüt aylık ücret; yoksa None."""
    current = None
    for wage in wages:
        if wage.valid_from > day:
            break
        current = wage.gross_monthly
    return current


def wage_summary(day: date | None = None, *, include_former: bool = False) -> list[dict[str, Any]]:
    """Personel ve ücretleri: her biri için `day` (varsayılan bugün) tarihinde geçerli ücret ve
    ücret geçmişi (kaldırılanlar hariç, en yenisi önce). Varsayılan olarak çalışanlar (çıkış tarihi
    `day` ya da sonrası olanlar dahil); `include_former` ile ayrılanlar da (hesapta görünen eski
    personelin ücreti girilebilsin)."""
    day = day or timezone.localdate()
    people = Employee.objects.all()
    if not include_former:
        people = people.filter(Q(is_active=True) | Q(termination_date__gte=day))
    employees = list(people.order_by("-is_active", "full_name", "id"))
    history: dict[int, list[EmployeeWage]] = defaultdict(list)
    wages = EmployeeWage.objects.filter(employee__in=employees, is_active=True)
    wages = wages.select_related("created_by", "employee")
    for wage in wages.order_by("employee_id", "-valid_from", "-id"):
        history[wage.employee_id].append(wage)
    rows = []
    for employee in employees:
        items = history.get(employee.pk, [])
        current = next((wage for wage in items if wage.valid_from <= day), None)
        rows.append(
            {
                "employee": employee,
                "current_wage": current.gross_monthly if current else None,
                "current_valid_from": current.valid_from if current else None,
                "history": items,
            }
        )
    return rows


# --- ön bordro (docs/DECISIONS.md "Personel bordrosu") -------------------------------------------

# Parametrelerin kaynağı: kayıtlı set; o yılın yasal değerleri (set kaydedilmedi); yasal değerleri
# bilinmeyen yıl için en yakın yılın değerleri (yalnızca tahmin; onay için o yılın seti gerekir).
SAVED, LEGAL_DEFAULT, FALLBACK = "saved", "legal_default", "fallback"

# Bordro satırı uyarıları (ön yüz Türkçe metinle gösterir).
MISSING_WAGE = "missing_wage"
BELOW_MINIMUM_WAGE = "below_minimum_wage"
EXTERNAL_MISSING = "external_missing"
EXIT_IN_MONTH = "exit_in_month"
PAY_WITHOUT_SGK_DAYS = "pay_without_sgk_days"
# Brütten nete bordronun uyarıları (3. adım).
OPENING_MISSING = "opening_missing"
CARRY_INCOMPLETE = "carry_incomplete"
NEGATIVE_PAYABLE = "negative_payable"
CEILING_WITH_BONUS = "ceiling_with_bonus"
# Zincir halkasının bayrakları: parametreler başka yılın değerleriyle tahmin edildi; devrin
# kaydedilmiş istisna matrahı bugünkü parametrelerle hesaplanandan farklı (parametreler devirden
# sonra değişti: devir yeniden kaydedilmeli).
FALLBACK_PARAMETERS = "fallback_parameters"
OPENING_STALE = "opening_stale"

# Brütten nete bordronun başladığı ay (docs/DECISIONS.md "Başlangıç Ekim 2026"). Öncesinde bordro
# mali müşavirdedir: net kalemler hesaplanmaz; işveren maliyeti ve personel maliyeti hesaplanır.
PAYROLL_START = (2026, 10)
# SGK tavanını aşınca izleyen iki aya devreden kalemler (5510 m.80; hesaplanmaz, uyarılır).
BONUS_CATEGORIES = frozenset({PayrollItemCategory.PREMIUM, PayrollItemCategory.BONUS})
# Kümülatif zincir ayının kaynağı (döküm için).
CARRY_OPENING, CARRY_ERP, CARRY_EXTERNAL = "opening", "erp", "external"
CARRY_APPROVED = "approved"
# Kartına göre işte olduğu bir ayda bordroda satırı yok (kart ya da tarihleri onaydan sonra
# değişti): o ayın kümülatifi bilinmez, zincir kopar.
CARRY_MISSING = "missing"


@dataclass(frozen=True)
class PayrollSettings:
    """Ayın bordro parametreleri, kaynağı ve değerlerin ait olduğu yıl."""

    params: payroll.Parameters
    source: str
    record: PayrollParameterSet | None
    year: int


def engine_parameters(record: PayrollParameterSet) -> payroll.Parameters:
    """Kayıtlı setin hesap motoru biçimi."""
    return payroll.Parameters(
        minimum_wage=record.minimum_wage,
        ceiling_multiplier=record.ceiling_multiplier,
        employee_sgk_rate=record.employee_sgk_rate,
        employee_unemployment_rate=record.employee_unemployment_rate,
        employer_sgk_rate=record.employer_sgk_rate,
        employer_unemployment_rate=record.employer_unemployment_rate,
        incentive_points=record.incentive_points,
        stamp_tax_per_mille=record.stamp_tax_per_mille,
        tax_brackets=(
            record.tax_bracket_1,
            record.tax_bracket_2,
            record.tax_bracket_3,
            record.tax_bracket_4,
        ),
        tax_rates=(
            record.tax_rate_1,
            record.tax_rate_2,
            record.tax_rate_3,
            record.tax_rate_4,
            record.tax_rate_5,
        ),
        bes_rate=record.bes_rate,
        meal_exemption_daily=record.meal_exemption_daily,
    )


def parameter_settings(year: int, months: Iterable[int]) -> dict[int, PayrollSettings]:
    """Ayların parametreleri (yılın setleri tek sorguyla): her ay için aynı yılın, ayın ilk gününe
    kadar geçerli olmuş en son kayıtlı seti; yoksa yılın yasal değerleri; o da yoksa en yakın yılın
    yasal değerleri (tahmin)."""
    records = list(
        PayrollParameterSet.objects.filter(is_active=True, valid_from__year=year).order_by(
            "-valid_from", "-id"
        )
    )
    legal = payroll.legal_parameters(year)
    nearest = payroll.nearest_legal_year(year)
    found = {}
    for month in set(months):
        first = date(year, month, 1)
        record = next((item for item in records if item.valid_from <= first), None)
        if record is not None:
            found[month] = PayrollSettings(engine_parameters(record), SAVED, record, year)
        elif legal is not None:
            found[month] = PayrollSettings(legal, LEGAL_DEFAULT, None, year)
        else:
            found[month] = PayrollSettings(payroll.LEGAL_DEFAULTS[nearest], FALLBACK, None, nearest)
    return found


def payroll_parameters(year: int, month: int) -> PayrollSettings:
    """Ayın parametreleri (`parameter_settings`)."""
    return parameter_settings(year, [month])[month]


def parameter_sets() -> QuerySet[PayrollParameterSet]:
    """Kayıtlı parametre setleri (kaldırılanlar hariç), en yenisi önce."""
    return PayrollParameterSet.objects.filter(is_active=True).order_by("-valid_from", "-id")


def net_available(year: int, month: int) -> bool:
    """Brütten nete bordro bu ay için hesaplanır mı (başlangıç ayı ve sonrası)?"""
    return (year, month) >= PAYROLL_START


def chain_start(year: int) -> int | None:
    """Yılın kümülatif zincirinin varsayılan ilk ayı: başlangıç yılında başlangıç ayı, sonraki
    yıllarda Ocak; başlangıçtan önceki yıllarda yok."""
    if year < PAYROLL_START[0]:
        return None
    return PAYROLL_START[1] if year == PAYROLL_START[0] else 1


def months_employed_before(employee: Employee, year: int, month: int) -> int:
    """Kişinin bu yıl `month` ayından önce bu işverende işte olduğu ay sayısı (işe giriş ayı tam
    sayılır; GVGT 319 m.6/2, Örnek 7): devirde asgari ücret istisnası ay sayısının önerisi ve üst
    sınırı."""
    hire = employee.hire_date
    if hire and hire.year > year:
        return 0
    first = hire.month if hire and hire.year == year else 1
    return max(0, month - first)


def opening_exemption_base(settings: dict[int, PayrollSettings], month: int, count: int) -> Decimal:
    """Devir ayından önceki `count` ayın kendi parametrelerindeki asgari ücret matrahları toplamı
    (yıl içinde asgari ücret değişse de doğru)."""
    return sum(
        (settings[number].params.exemption_base for number in range(month - count, month)),
        Decimal(0),
    )


@dataclass(frozen=True)
class CarryMonth:
    """Kümülatif zincirin bir halkası (döküm için). `source` "opening" (devir; `month` devrin
    ayıdır, tutarlar o aydan önceki kümülatiftir), "approved" (onaylı bordro; tutarlar o ayın
    sonundaki kümülatiftir), "erp" (ERP'de hesaplanan ay; eklenen GV matrahı ve asgari ücret istisna
    matrahı), "external" (bordrosu mali müşavirdeydi; zincir burada kopar) ya da "missing" (kartına
    göre işteydi ama bordroda satırı yok; o ayın kümülatifi bilinmez, zincir kopar)."""

    month: int
    source: str
    tax_base: Decimal
    exemption_base: Decimal
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonView:
    """Bordroda kişi bilgisi: açık ayda kartın bugünkü hali, onaylı ayda onay anındaki hali. TC
    kimlik no yalnızca maskeli tutulur (KVKK). `payroll_external` ve `bes_enrolled` kartın
    işaretleridir (onaylı ayda onay anındaki)."""

    pk: int
    employee_no: str
    full_name: str
    department: str
    title: str
    hire_date: date | None
    termination_date: date | None
    is_active: bool
    masked_national_id: str
    payroll_external: bool
    bes_enrolled: bool


def person_view(employee: Employee) -> PersonView:
    """Kartın bugünkü hali."""
    return PersonView(
        pk=employee.pk,
        employee_no=employee.employee_no,
        full_name=employee.full_name,
        department=employee.department,
        title=employee.title,
        hire_date=employee.hire_date,
        termination_date=employee.termination_date,
        is_active=employee.is_active,
        masked_national_id=mask_identifier(employee.national_id),
        payroll_external=employee.payroll_external,
        bes_enrolled=employee.bes_enrolled,
    )


def person_snapshot(person: PersonView) -> dict[str, Any]:
    """Onayda saklanan kişi bilgisi (JSON; TC kimlik no maskeli)."""
    return {
        "employee_no": person.employee_no,
        "full_name": person.full_name,
        "department": person.department,
        "title": person.title,
        "hire_date": person.hire_date.isoformat() if person.hire_date else None,
        "termination_date": (
            person.termination_date.isoformat() if person.termination_date else None
        ),
        "is_active": person.is_active,
        "masked_national_id": person.masked_national_id,
        "payroll_external": person.payroll_external,
        "bes_enrolled": person.bes_enrolled,
    }


def _iso(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


def person_from_snapshot(employee_id: int, data: Mapping[str, Any]) -> PersonView:
    """Saklanan kişi bilgisinden görünüm (`person_snapshot`un tersi)."""
    return PersonView(
        pk=employee_id,
        employee_no=str(data.get("employee_no") or ""),
        full_name=str(data.get("full_name") or ""),
        department=str(data.get("department") or ""),
        title=str(data.get("title") or ""),
        hire_date=_iso(data.get("hire_date")),
        termination_date=_iso(data.get("termination_date")),
        is_active=bool(data.get("is_active", True)),
        masked_national_id=str(data.get("masked_national_id") or ""),
        payroll_external=bool(data.get("payroll_external")),
        bes_enrolled=bool(data.get("bes_enrolled")),
    )


def _person_order(person: PersonView) -> tuple[str, int]:
    return fold(person.full_name), person.pk


@dataclass(frozen=True)
class PayrollRow:
    """Bir kişinin ay bordrosu. `line` ERP hesabıdır; bordrosu mali müşavirde olan kişide
    (`external`) para tutarları yerine mali müşavirin rakamları (`figure`) kullanılır, `line`
    yalnızca günler içindir.

    Brütten nete hesapta (`PayrollMonth.net`): `opening` zincirin çapası olan devir, `openings`
    kişinin bu yıl bu aya kadarki etkin devirleri (ay sırasıyla; devir penceresi önceki ayların
    devirlerini de görsün), `entry_month` devrin beklendiği giriş ayı, `opening_needed` giriş ayının
    devri girilmemiş mi, `suggestion_months` / `suggestion_base` giriş ayının devri için asgari
    ücret istisnası önerisi, `carry_months` ay başı kümülatifin nasıl kurulduğu.

    `snapshot` kişinin bordrodaki bilgisidir (`person`; onaylı ayda onay anındaki), `bes` hesapta
    BES kesintisi uygulandı mı (kartın ya da yeniden açılan ayda onaydaki işaret)."""

    employee: Employee
    line: payroll.Result
    external: bool
    figure: ExternalPayrollFigure | None
    warnings: tuple[str, ...]
    items: tuple[PayrollItem, ...] = ()
    opening: PayrollOpeningBalance | None = None
    openings: tuple[PayrollOpeningBalance, ...] = ()
    entry_month: int | None = None
    opening_needed: bool = False
    suggestion_months: int = 0
    suggestion_base: Decimal = Decimal(0)
    carry_months: tuple[CarryMonth, ...] = ()
    snapshot: PersonView | None = None
    bes: bool = False

    @property
    def person(self) -> PersonView:
        return self.snapshot if self.snapshot is not None else person_view(self.employee)

    @property
    def gross_total(self) -> Decimal:
        if self.external:
            return self.figure.gross_total if self.figure else Decimal(0)
        return self.line.gross_total

    @property
    def employer_cost(self) -> Decimal:
        if self.external:
            return self.figure.employer_cost if self.figure else Decimal(0)
        return self.line.employer_cost


@dataclass(frozen=True)
class CardChange:
    """Yeniden açılan ayda kartın işaretleri ("Bordrosu mali müşavirde", "BES'e dahil") son
    onaydakinden farklı kişi. Kişi onaydaki işaretlerle hesaplanır; `following` ise kartın bugünkü
    işaretlerine geçirildi (ayrıca seçildi, kayda geçti). `stored_external` / `stored_bes` onayda
    saklanacak hal: o aya girilmiş mali müşavir rakamı kişiyi işaretlerden bağımsız mali müşavirde
    tutar (`figure_keeps_external`: işaretler ERP derken rakam yüzünden mali müşavirde)."""

    employee: Employee
    approved_external: bool
    approved_bes: bool
    following: bool
    stored_external: bool = False
    stored_bes: bool = False
    figure_keeps_external: bool = False


@dataclass(frozen=True)
class PayrollMonth:
    """Ayın ön bordrosu: puantaj durumu, parametreler ve kişi satırları. `net`: brütten nete
    (kümülatif zincir, devir, vergiler) hesaplandı mı; başlangıç ayından önce ve personel
    maliyetinde hesaplanmaz. `orphan_items`: o ay işte olmayan kişilere girilmiş kalemler.

    `run` ayın bordro kaydı (yoksa None). `approval` gösterilen onaydır: onaylı ayda geçerli onay,
    istenirse yeniden açılmış eski bir onay (`superseded`); açık ayda None (canlı hesap).
    `previous_open` bir önceki bordro ayı onaylanmadı (aylar sırayla onaylanır), `history` ayın
    onayları (eskiden yeniye), `card_changes` yeniden açılan ayda kartı onaydakinden farklı
    kişiler."""

    year: int
    month: int
    grid: AttendanceGrid
    settings: PayrollSettings
    rows: list[PayrollRow]
    net: bool = False
    orphan_items: tuple[PayrollItem, ...] = ()
    run: PayrollRun | None = None
    approval: PayrollApproval | None = None
    previous_open: bool = False
    history: tuple[PayrollApproval, ...] = ()
    card_changes: tuple[CardChange, ...] = ()

    @property
    def label(self) -> str:
        return self.grid.label

    @property
    def approved(self) -> bool:
        """Geçerli onayın saklı satırları gösteriliyor (ay kilitli)."""
        return self.approval is not None and self.approval.reopened_at is None

    @property
    def superseded(self) -> bool:
        """Yeniden açılmış (geçersiz) bir onayın satırları gösteriliyor."""
        return self.approval is not None and self.approval.reopened_at is not None

    @property
    def number(self) -> str:
        return self.run.number if self.run else ""

    @property
    def attendance_approved(self) -> bool:
        # Saklı ay onaydaki puantajla hesaplandı (onay ancak puantaj onaylıyken verilir).
        return self.approval is not None or self.grid.approved

    @property
    def attendance_number(self) -> str:
        if self.approval is not None:
            return self.approval.attendance_number
        return self.grid.record.number if self.grid.record else ""

    @property
    def net_available(self) -> bool:
        return net_available(self.year, self.month)

    @property
    def computed(self) -> list[PayrollRow]:
        """ERP'de hesaplanan satırlar (bordrosu mali müşavirde olanlar hariç)."""
        return [row for row in self.rows if not row.external]

    def total(self, field_name: str) -> Decimal:
        """ERP'de hesaplanan satırların bir kalemi toplamı."""
        return sum((getattr(row.line, field_name) for row in self.computed), Decimal(0))

    @property
    def gross_total(self) -> Decimal:
        """Brüt toplam (mali müşavirde hesaplananların rakamları dahil)."""
        return sum((row.gross_total for row in self.rows), Decimal(0))

    @property
    def employer_cost(self) -> Decimal:
        """İşverene maliyet (mali müşavirde hesaplananların rakamları dahil)."""
        return sum((row.employer_cost for row in self.rows), Decimal(0))


def _engine_item(item: PayrollItem) -> payroll.Item:
    """Kalemin hesap motoru biçimi (tür kategori kodudur; ad açıklama ya da kategori)."""
    return payroll.Item(
        kind=item.category,
        label=item.description or item.get_category_display(),
        amount=item.amount,
    )


def _month_input(
    row: AttendanceRow,
    days: list[AttendanceDay],
    wages: Sequence[EmployeeWage],
    *,
    items: Sequence[PayrollItem] = (),
    carry: payroll.Carry | None = None,
    bes: bool | None = None,
) -> payroll.MonthInput:
    """Puantaj satırından hesap girdisi: yalnızca kişinin işte olduğu (durumu olan) günler, her gün
    o gün geçerli ücretle; yarım gün tatil çalışması yalnızca takvimde yarım gün tatil olan güne
    sayılır. Ayın ek ödemeleri brüte, kesintileri netten. BES verilmezse kartın işareti."""
    half_days = {day.date for day in days if day.half_day}
    selected = tuple(
        payroll.Day(
            date=cell.date,
            status=cell.status,
            overtime_hours=cell.overtime_hours,
            wage=wage_on(wages, cell.date),
            half_holiday_worked=cell.holiday_half_worked and cell.date in half_days,
        )
        for cell in row.cells
        if cell.status and employed_on(row.employee, cell.date)
    )
    return payroll.MonthInput(
        days=selected,
        days_in_month=len(days),
        extras=tuple(_engine_item(item) for item in items if item.kind == PayrollItemKind.EXTRA),
        deductions=tuple(
            _engine_item(item) for item in items if item.kind == PayrollItemKind.DEDUCTION
        ),
        bes=row.employee.bes_enrolled if bes is None else bes,
        carry=carry or payroll.Carry(),
    )


def _works_in(row: AttendanceRow) -> bool:
    """Kişi bu ay bordroda mı: kartına göre işte olduğu bir günde puantajda durumu var
    (`_month_input` ile aynı gün seçimi; işe giriş tarihi sonradan düzeltilirse eski günlerin kaydı
    kalabilir)."""
    return any(cell.status and employed_on(row.employee, cell.date) for cell in row.cells)


def _warnings(
    employee: Employee,
    line: payroll.Result,
    days: tuple[payroll.Day, ...],
    params: payroll.Parameters,
    last: date,
) -> list[str]:
    found = []
    if line.missing_wage:
        found.append(MISSING_WAGE)
    # Ücretli bir günde geçerli aylık brüt ücretlerden biri asgari ücretin altında (İş Kanunu m.39):
    # ay içinde giriş, çıkış ve zamda da (zamdan önceki günler dahil). Karşılaştırılan aylık
    # ücrettir, kıst brüt değil; ücretli gün yoksa son ücrete bakılır. Brüt SGK alt sınırının
    # altında kalırsa matrah alt sınıra çıkar ("Alt sınır"); fazla mesaiyle aşarsa çıkmaz.
    paid = [
        day.wage
        for day in days
        if day.wage is not None and day.status not in payroll.UNPAID_STATUSES
    ]
    lowest = min(paid, default=line.monthly_wage)
    if lowest is not None and lowest < params.minimum_wage:
        found.append(BELOW_MINIMUM_WAGE)
    if employee.termination_date and employee.termination_date <= last:
        found.append(EXIT_IN_MONTH)
    if line.gross_total > 0 and not line.sgk_days:
        found.append(PAY_WITHOUT_SGK_DAYS)
    return found


# --- onaylı bordro (4. adım): saklı satırlar, zincirin çapası, onaydaki işaretler ---------------


def previous_period(year: int, month: int) -> tuple[int, int]:
    return (year, month - 1) if month > 1 else (year - 1, 12)


def payroll_run(year: int, month: int) -> PayrollRun | None:
    """Ayın bordro kaydı (yoksa None)."""
    return (
        PayrollRun.objects.select_related("current", "current__approved_by")
        .filter(year=year, month=month)
        .first()
    )


def latest_approved_run() -> PayrollRun | None:
    """En son onaylı bordro ayı (yeniden açılabilecek tek ay)."""
    return (
        PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED)
        .order_by("-year", "-month")
        .first()
    )


def previous_open(year: int, month: int) -> bool:
    """Bir önceki bordro ayı onaylanmadı mı (başlangıç ayında ve öncesinde hayır)?"""
    if not net_available(year, month) or (year, month) == PAYROLL_START:
        return False
    before_year, before_month = previous_period(year, month)
    return not PayrollRun.objects.filter(
        year=before_year, month=before_month, status=PayrollRun.Status.APPROVED
    ).exists()


@dataclass(frozen=True)
class _Kept:
    """Yeniden açılan ayda kişinin son onaydaki kart işaretleri; `following`: kartı izliyor."""

    external: bool
    bes: bool
    following: bool


def _kept_flags(runs: Iterable[PayrollRun]) -> dict[tuple[int, int], _Kept]:
    """Yeniden açılmış (açık ve önceki onayı olan) aylarda kişilerin son onaydaki işaretleri:
    (kişi, ay) → işaretler."""
    reopened = {run.pk: run for run in runs if run.status == PayrollRun.Status.OPEN}
    if not reopened:
        return {}
    latest: dict[int, int] = {}
    for run_id, approval_id in (
        PayrollApproval.objects.filter(run_id__in=reopened)
        .order_by("run_id", "sequence")
        .values_list("run_id", "id")
    ):
        latest[run_id] = approval_id
    found = {}
    slips = PayrollSlip.objects.filter(approval_id__in=latest.values()).values_list(
        "approval__run_id", "employee_id", "person", "bes_enrolled"
    )
    for run_id, employee_id, person, bes in slips:
        run = reopened[run_id]
        found[(employee_id, run.month)] = _Kept(
            external=bool((person or {}).get("payroll_external")),
            bes=bes,
            following=employee_id in set(run.follow_card or ()),
        )
    return found


def month_flags(employee: Employee, year: int, month: int) -> tuple[bool, bool]:
    """Kişinin o ayın hesabında kullanılan kart işaretleri (mali müşavirde, BES'e dahil): yeniden
    açılan ayda son onaydaki işaretler (kartı izlemeye geçirilmediyse), değilse kartınki."""
    runs = PayrollRun.objects.filter(year=year, month=month, status=PayrollRun.Status.OPEN)
    kept = _kept_flags(runs).get((employee.pk, month))
    if kept is not None and not kept.following:
        return kept.external, kept.bes
    return employee.payroll_external, employee.bes_enrolled


def external_in_month(employee: Employee, year: int, month: int) -> bool:
    """Kişinin o ay bordrosu mali müşavirde mi: o aya rakam girilmiş ya da (yeniden açılan ayda
    onaydaki) kart işareti."""
    figure = ExternalPayrollFigure.objects.filter(
        employee=employee, year=year, month=month, is_active=True
    )
    return figure.exists() or month_flags(employee, year, month)[0]


def approved_slip_months(
    employee: Employee, *, computed_only: bool = False
) -> list[tuple[int, int, str]]:
    """Kişinin onaylı bordrolarda satırı olan aylar (yıl, ay, BR no), eskiden yeniye."""
    slips = PayrollSlip.objects.filter(
        employee=employee,
        approval__reopened_at__isnull=True,
        approval__run__status=PayrollRun.Status.APPROVED,
    )
    if computed_only:
        slips = slips.filter(external=False)
    return list(
        slips.order_by("approval__run__year", "approval__run__month").values_list(
            "approval__run__year", "approval__run__month", "approval__run__number"
        )
    )


KEPT_ERP_NOTE = "yeniden açılan ay: onaydaki haliyle ERP'de"


def _unapproved_records(employee: Employee) -> list[tuple[int, int, int, int, str]]:
    start_year, start_month = PAYROLL_START
    after_start = Q(year__gt=start_year) | Q(year=start_year, month__gte=start_month)
    approved = set(
        PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED).values_list("year", "month")
    )
    items = PayrollItem.objects.filter(after_start, employee=employee, is_active=True)
    openings = PayrollOpeningBalance.objects.filter(after_start, employee=employee, is_active=True)
    found: list[tuple[int, int, int, int, str]] = []
    for item in items.order_by("year", "month", "id"):
        if (item.year, item.month) not in approved:
            text = f"{item.get_category_display()} {format_money(item.amount)} TL"
            found.append((item.year, item.month, 0, item.pk, text))
    for opening in openings.order_by("year", "month"):
        if (opening.year, opening.month) not in approved:
            found.append((opening.year, opening.month, 1, opening.pk, "devri"))
    return sorted(found)


def _kept_erp(employee: Employee, months: Iterable[tuple[int, int]]) -> set[tuple[int, int]]:
    """Verilen aylardan yeniden açılmış olup kişinin son onaydaki işaretlerle (kartı izlemeden)
    ERP'de hesaplandıkları. O aya mali müşavir rakamı girilmişse kişi mali müşavirdedir
    (`external_in_month`; ayın kendi satırıyla aynı kural)."""
    found = set()
    for year, month in sorted(set(months)):
        runs = PayrollRun.objects.filter(year=year, month=month, status=PayrollRun.Status.OPEN)
        kept = _kept_flags(runs).get((employee.pk, month))
        if kept is not None and not kept.following and not external_in_month(employee, year, month):
            found.add((year, month))
    return found


def unapproved_payroll_records(employee: Employee) -> list[str]:
    """Kişinin onaylanmamış bordro aylarındaki (başlangıç ayından) etkin ek ödeme, kesinti ve
    devirleri, ay sırasıyla: "Kasım 2026 Prim 5.000,00 TL", "Kasım 2026 devri" (açıklama
    yazılmaz). Yeniden açılan ayda kişi son onaydaki haliyle ERP'de hesaplanıyorsa (kartı
    izlemiyor, o aya mali müşavir rakamı girilmemiş) kayıt bunu yazar: "Ekim 2026 Prim 5.000,00 TL
    (yeniden açılan ay: ...)"."""
    found = _unapproved_records(employee)
    kept = _kept_erp(employee, ((year, month) for year, month, *_ in found))
    return [
        f"{month_label(year, month)} {text}"
        + (f" ({KEPT_ERP_NOTE})" if (year, month) in kept else "")
        for year, month, _, _, text in found
    ]


def kept_erp_months(employee: Employee) -> list[str]:
    """Onaylanmamış bordro kaydı olan aylardan yeniden açılmış olup kişinin son onaydaki
    işaretlerle ERP'de hesaplandıkları ("Ekim 2026"), ay sırasıyla: kart "mali müşavirde"
    işaretlense de bu aylar "Kartı izle" seçilene kadar ERP'dedir."""
    found = _unapproved_records(employee)
    kept = _kept_erp(employee, ((year, month) for year, month, *_ in found))
    return [month_label(year, month) for year, month in sorted(kept)]


@dataclass(frozen=True)
class _SlipAnchor:
    """Kişinin yılın onaylı aylarındaki son satırı (zincirin çapası)."""

    month: int
    external: bool
    tax_base: Decimal
    exemption_base: Decimal
    entry_month: int | None


def _slip_anchors(
    year: int, months: Iterable[int]
) -> tuple[dict[int, _SlipAnchor], frozenset[tuple[int, int]]]:
    """Onaylı ayların geçerli onaylarından kişi başına en son satır ve satırı olan (kişi, ay)
    çiftleri."""
    wanted = sorted(set(months))
    if not wanted:
        return {}, frozenset()
    slips = (
        PayrollSlip.objects.filter(
            approval__run__year=year,
            approval__run__month__in=wanted,
            approval__run__status=PayrollRun.Status.APPROVED,
            approval__reopened_at__isnull=True,
        )
        .order_by("approval__run__month")
        .values_list(
            "employee_id",
            "approval__run__month",
            "external",
            "tax_base_after",
            "exemption_base_after",
            "chain",
        )
    )
    found = {}
    present = set()
    for employee_id, month, external, tax_base, exemption, chain in slips:
        present.add((employee_id, month))
        found[employee_id] = _SlipAnchor(
            month=month,
            external=external,
            tax_base=tax_base or Decimal(0),
            exemption_base=exemption or Decimal(0),
            entry_month=(chain or {}).get("entry_month"),
        )
    return found, frozenset(present)


@dataclass(frozen=True)
class _Chain:
    """Kişinin ay başı kümülatifi ve nasıl kurulduğu."""

    carry: payroll.Carry
    months: tuple[CarryMonth, ...]
    entry_month: int
    opening_needed: bool
    incomplete: bool


@dataclass(frozen=True)
class _ChainData:
    """Zincir aylarının önceden yüklenmiş verisi (açık aylar bellekte hesaplanır; onaylı aylar
    saklı satırlardır)."""

    year: int
    month: int
    start: int
    grids: dict[int, AttendanceGrid]
    rows: dict[int, dict[int, AttendanceRow]]
    settings: dict[int, PayrollSettings]
    wages: dict[int, list[EmployeeWage]]
    items: dict[tuple[int, int], list[PayrollItem]]
    figures: dict[tuple[int, int], ExternalPayrollFigure]
    approved: frozenset[int] = frozenset()
    anchors: dict[int, _SlipAnchor] = field(default_factory=dict)
    slip_months: frozenset[tuple[int, int]] = frozenset()
    kept: dict[tuple[int, int], _Kept] = field(default_factory=dict)

    def external(self, employee: Employee, month: int) -> bool:
        """Açık ay mali müşavirde mi; ayın kendi satırıyla aynı kural: kişi o ay bordroda değilse
        (kartına göre işte olduğu günde puantajda yok) hayır, zincir ayrıca bakar; bordrodaysa rakam
        girilmiş ya da yeniden açılan ayda onaydaki işaret, kartı izliyorsa ya da onayda yoksa
        kartın işareti."""
        row = self.rows.get(month, {}).get(employee.pk)
        if row is None or not _works_in(row):
            return False
        if (employee.pk, month) in self.figures:
            return True
        kept = self.kept.get((employee.pk, month))
        if kept is not None and not kept.following:
            return kept.external
        return employee.payroll_external

    @property
    def first_open(self) -> int:
        """Zincirin ilk açık ayı (onaylı ayların hemen sonrası; devir ancak açık aya girilir)."""
        return max(self.approved) + 1 if self.approved else self.start


def _erp_in(employee: Employee, number: int, data: _ChainData, slip: _SlipAnchor | None) -> bool:
    """Kişinin zincirdeki o ayı ERP'de mi hesaplandı (devrin eşitleme sayılması için sunucunun
    kuralıyla aynı): onaylı ayda ERP satırı var (en son satırı o aydadır), açık ayda bordroda ve
    mali müşavirde değil."""
    if not data.start <= number < data.month:
        return False
    if number in data.approved:
        return slip is not None and slip.month == number and not slip.external
    row = data.rows.get(number, {}).get(employee.pk)
    return row is not None and _works_in(row) and not data.external(employee, number)


def _chain(employee: Employee, opening: PayrollOpeningBalance | None, data: _ChainData) -> _Chain:
    """Kişinin ay başı kümülatif GV matrahı ve asgari ücret istisna matrahı.

    Çapa, kişinin bu yılın onaylı aylarındaki son satırıdır (ay sonu kümülatifi saklıdır; çapa ayı
    o aydan sonraki aydır); o satır mali müşavirdeyse zincir orada kopar. Çapa ayından ya da
    sonrasından bir devir varsa (ya da onaylı satır yoksa) kişinin bu ay ya da önceki aylardaki en
    son devri çapa olur (devrin tutarları devir ayından önceki kümülatiftir); hiçbiri yoksa
    zincirin varsayılan ilk ayından (başlangıç yılında Ekim, sonra Ocak) sıfırla başlanır. Çapadan
    bu aya kadarki açık ERP aylarının GV matrahı ve istisna matrahı eklenir (bunlar kümülatife bağlı
    değildir); onaylı aylar yeniden hesaplanmaz. Bordrosu mali müşavirde geçen ay zinciri keser:
    sonraki ilk ERP ayı giriş ayıdır ve devir ister. Kartına göre işte olduğu bir ayda bordroda
    satırı olmayan kişide (kart ya da tarihleri onaydan sonra değişti) de zincir kopar. Giriş ayı
    hiçbir zaman onaylı (kilitli) bir ay olmaz: devir ilk açık aya istenir."""
    anchor = data.start
    tax_base = exemption = Decimal(0)
    links: list[CarryMonth] = []
    incomplete = False
    last_external: int | None = None
    slip = data.anchors.get(employee.pk)
    approved_anchor = opening_anchor = False
    if slip is not None:
        anchor = slip.month + 1
        if slip.external:
            last_external = slip.month
        else:
            tax_base, exemption = slip.tax_base, slip.exemption_base
            approved_anchor = True
            links.append(CarryMonth(slip.month, CARRY_APPROVED, tax_base, exemption))
    if opening is not None and opening.month >= anchor:
        # Devir onaylı satırdan sonraki aya girildi: çapa devirdir (mali müşavirle eşitleme).
        anchor = opening.month
        tax_base, exemption = opening.tax_base, opening.exemption_base
        approved_anchor, opening_anchor = False, True
        # Devrin istisna matrahı kayıtta saklıdır; kapsadığı ayların parametreleri tahminse ya da
        # sonradan değiştiyse zincir eksik sayılır (devir yeniden kaydedilince düzelir).
        covered = range(opening.month - opening.exemption_months, opening.month)
        opening_flags = []
        if any(data.settings[number].source == FALLBACK for number in covered):
            opening_flags.append(FALLBACK_PARAMETERS)
        expected = opening_exemption_base(data.settings, opening.month, opening.exemption_months)
        if expected != opening.exemption_base:
            opening_flags.append(OPENING_STALE)
        incomplete = bool(opening_flags)
        links = [
            CarryMonth(opening.month, CARRY_OPENING, tax_base, exemption, tuple(opening_flags))
        ]
    for number in range(data.start, data.month):
        employed = _overlaps(employee, *month_bounds(data.year, number))
        if number in data.approved:
            # Onaylı ay yeniden hesaplanmaz: kişinin satırı varsa çapadadır. Kartına göre o ay işte
            # ama satırı yoksa o ayın kümülatifi bilinmez; zincir kopar.
            if number >= anchor and employed and (employee.pk, number) not in data.slip_months:
                last_external = number
                links.append(CarryMonth(number, CARRY_MISSING, Decimal(0), Decimal(0)))
            continue
        if data.external(employee, number):
            last_external = number
            if number >= anchor:
                links.append(CarryMonth(number, CARRY_EXTERNAL, Decimal(0), Decimal(0)))
            continue
        if number < anchor:
            continue  # çapadan önceki aylar çapanın içindedir
        row = data.rows[number].get(employee.pk)
        month_input = (
            _month_input(
                row,
                data.grids[number].days,
                data.wages.get(employee.pk, []),
                items=data.items.get((employee.pk, number), []),
            )
            if row is not None
            else None
        )
        if month_input is None or not month_input.days:
            if employed:
                # Kartına göre işte ama onaylı puantajda günü yok: o ayın kümülatifi bilinmez.
                last_external = number
                links.append(CarryMonth(number, CARRY_MISSING, Decimal(0), Decimal(0)))
            continue
        settings = data.settings[number]
        line = payroll.compute(month_input, settings.params)
        flags = []
        if line.missing_wage:
            flags.append(MISSING_WAGE)
        if settings.source == FALLBACK:
            flags.append(FALLBACK_PARAMETERS)
        incomplete = incomplete or bool(flags)
        tax_base += line.tax_base
        exemption += line.exemption_base_added
        links.append(
            CarryMonth(number, CARRY_ERP, line.tax_base, line.exemption_base_added, tuple(flags))
        )
    if (
        opening_anchor
        and opening is not None
        and (last_external is None or last_external < opening.month)
        and not _erp_in(employee, opening.month - 1, data, slip)
    ):
        # Devirden önceki ay ERP'de değil (kopukluk devirden önceyse de): zincir devirle girer.
        entry = opening.month
    elif last_external is not None:
        entry = max(last_external + 1, data.first_open)
    elif approved_anchor and slip is not None:
        entry = slip.entry_month or data.start
    elif slip is not None and not slip.external:
        # Devir onaylı ERP satırından sonra girildi (eşitleme): giriş ayı o satırın zincirininki.
        entry = slip.entry_month or data.start
    else:
        # Devir açık bir ERP ayından sonra girildiyse (eşitleme) de giriş ayı devirden öncedir.
        entry = max(data.start, data.first_open)
    if approved_anchor and last_external is None:
        needed = False  # onaylı satırın kümülatifi tamdır (onay, devri eksik ayı kabul etmez)
    else:
        has_opening = opening is not None and opening.month >= entry
        needed = months_employed_before(employee, data.year, entry) > 0 and not has_opening
    return _Chain(payroll.Carry(tax_base, exemption), tuple(links), entry, needed, incomplete)


def payroll_month(
    year: int,
    month: int,
    *,
    department: str = "",
    net: bool = True,
    approval: int | None = None,
) -> PayrollMonth:
    """Ayın ön bordrosu (isteğe bağlı birim süzgeciyle).

    Açık ayda canlı hesaptır: puantajın günleri (açık ayda takvim varsayılanları, onaylı ayda
    kayıtlı günler), ücretler ve ayın ek ödeme ve kesintilerinden kişi başına brütten nete hesap ve
    işverene maliyet. Bordrosu mali müşavirde olan kişide (o ay için rakamı girilmiş ya da kartı
    işaretli; yeniden açılan ayda onaydaki işaret) o ayın girilmiş rakamları kullanılır. `net=True`
    ve başlangıç ayından sonraki ayda gelir vergisi kişinin kümülatif zinciriyle hesaplanır; sorgu
    sayısı ay ve kişi sayısından bağımsızdır. Personel maliyeti `net=False` ile çağırır (işveren
    maliyeti kümülatife bağlı değildir).

    Bordrosu onaylı ayda satırlar onayda saklananlardır (`_stored_month`): kart, ücret ya da
    parametre sonradan değişse de onaydaki rakamlar ve kişi bilgisi döner. `approval` (onay sırası)
    verilirse o onayın satırları döner (yeniden açılmış eski onay dahil); yoksa `LookupError`."""
    run = payroll_run(year, month)
    if approval is not None:
        record = None
        if run is not None:
            record = (
                run.approvals.select_related("approved_by", "reopened_by")
                .filter(sequence=approval)
                .first()
            )
        if run is None or record is None:
            raise LookupError(f"{month_label(year, month)} bordrosunun {approval}. onayı yok.")
        return _stored_month(run, record, department=department)
    if run is not None and run.status == PayrollRun.Status.APPROVED and run.current is not None:
        return _stored_month(run, run.current, department=department)
    return _live_month(year, month, run, department=department, net=net)


def _history(run: PayrollRun | None) -> tuple[PayrollApproval, ...]:
    if run is None:
        return ()
    return tuple(run.approvals.select_related("approved_by", "reopened_by").order_by("sequence"))


def _live_month(
    year: int, month: int, run: PayrollRun | None, *, department: str, net: bool
) -> PayrollMonth:
    net = net and net_available(year, month)
    start = chain_start(year) if net else None
    first_month = start if start is not None else month
    runs = {
        item.month: item
        for item in PayrollRun.objects.filter(year=year, month__gte=first_month, month__lte=month)
    }
    approved = frozenset(
        number
        for number, item in runs.items()
        if number < month and item.status == PayrollRun.Status.APPROVED
    )
    months = [number for number in range(first_month, month + 1) if number not in approved]
    grids = attendance_grids(year, months, department=department)
    grid = grids[month]
    settings_by_month = parameter_settings(year, range(1, month + 1) if net else [month])
    settings = settings_by_month[month]
    last = grid.days[-1].date
    people = sorted({row.employee.pk for number in months for row in grids[number].rows})
    wages = wages_by_employee(people, last)
    figures = {
        (figure.employee_id, figure.month): figure
        for figure in ExternalPayrollFigure.objects.filter(
            is_active=True, year=year, month__in=months, employee_id__in=people
        ).select_related("updated_by")
    }
    item_query = PayrollItem.objects.filter(is_active=True, year=year, month__in=months)
    if department:
        item_query = item_query.filter(employee__department=department)
    items: dict[tuple[int, int], list[PayrollItem]] = defaultdict(list)
    for item in item_query.select_related(
        "employee", "created_by", "updated_by", "removed_by"
    ).order_by("month", "kind", "category", "id"):
        items[(item.employee_id, item.month)].append(item)
    openings: dict[int, list[PayrollOpeningBalance]] = defaultdict(list)
    if net:
        for opening in (
            PayrollOpeningBalance.objects.filter(
                is_active=True, year=year, month__lte=month, employee_id__in=people
            )
            .select_related("employee", "created_by", "updated_by", "removed_by")
            .order_by("month", "id")
        ):
            openings[opening.employee_id].append(opening)  # en son devir çapadır
    kept = _kept_flags(runs.values())
    anchors, slip_months = _slip_anchors(year, approved) if net else ({}, frozenset())
    data = _ChainData(
        year=year,
        month=month,
        start=start if start is not None else month,
        grids=grids,
        rows={number: {row.employee.pk: row for row in grids[number].rows} for number in months},
        settings=settings_by_month,
        wages=wages,
        items=items,
        figures=figures,
        approved=approved,
        anchors=anchors,
        slip_months=slip_months,
        kept=kept,
    )
    rows = []
    changes = []
    for row in grid.rows:
        employee = row.employee
        flags = kept.get((employee.pk, month))
        card_external, bes = employee.payroll_external, employee.bes_enrolled
        if flags is not None and not flags.following:
            card_external, bes = flags.external, flags.bes
        own_items = items.get((employee.pk, month), [])
        month_input = _month_input(
            row, grid.days, wages.get(employee.pk, []), items=own_items, bes=bes
        )
        if not month_input.days:
            continue  # kişi bu ay işte değil (yalnızca işte olmadığı günlerde kaydı var)
        figure = figures.get((employee.pk, month))
        if flags is not None and (
            flags.following
            or (flags.external, flags.bes) != (employee.payroll_external, employee.bes_enrolled)
        ):
            # Kartı onaydakinden farklı ya da kartı izleyen kişi (yalnızca bu ay bordroda olanlar);
            # onayda saklanacak hal: girilmiş mali müşavir rakamı kişiyi mali müşavirde tutar.
            changes.append(
                CardChange(
                    employee,
                    flags.external,
                    flags.bes,
                    flags.following,
                    stored_external=card_external or figure is not None,
                    stored_bes=bes,
                    figure_keeps_external=figure is not None and not card_external,
                )
            )
        # Kişinin işaretleri hesapta kullanılanlardır (onayda bu haliyle saklanır).
        person = replace(person_view(employee), payroll_external=card_external, bes_enrolled=bes)
        if card_external or figure is not None:
            line = payroll.compute(month_input, settings.params)
            rows.append(
                PayrollRow(
                    employee,
                    line,
                    True,
                    figure,
                    () if figure else (EXTERNAL_MISSING,),
                    items=tuple(own_items),
                    snapshot=person,
                    bes=bes,
                )
            )
            continue
        own_openings = openings.get(employee.pk, [])
        anchor = own_openings[-1] if own_openings else None
        chain = _chain(employee, anchor, data) if net else None
        if chain is not None:
            month_input = replace(month_input, carry=chain.carry)
        line = payroll.compute(month_input, settings.params)
        warnings = _warnings(employee, line, month_input.days, settings.params, last)
        extras = [item for item in own_items if item.kind == PayrollItemKind.EXTRA]
        if line.ceiling_applied and any(item.category in BONUS_CATEGORIES for item in extras):
            warnings.append(CEILING_WITH_BONUS)
        if chain is None:
            rows.append(
                PayrollRow(
                    employee,
                    line,
                    False,
                    None,
                    tuple(warnings),
                    tuple(own_items),
                    snapshot=person,
                    bes=bes,
                )
            )
            continue
        if chain.opening_needed:
            warnings.append(OPENING_MISSING)
        if chain.incomplete:
            warnings.append(CARRY_INCOMPLETE)
        if line.payable < 0:
            warnings.append(NEGATIVE_PAYABLE)
        suggestion = months_employed_before(employee, year, chain.entry_month)
        in_chain = any(link.source == CARRY_OPENING for link in chain.months)
        rows.append(
            PayrollRow(
                employee,
                line,
                False,
                None,
                tuple(warnings),
                tuple(own_items),
                opening=anchor if in_chain else None,
                openings=tuple(own_openings),
                entry_month=chain.entry_month,
                opening_needed=chain.opening_needed,
                suggestion_months=suggestion,
                suggestion_base=opening_exemption_base(
                    settings_by_month, chain.entry_month, suggestion
                ),
                carry_months=chain.months,
                snapshot=person,
                bes=bes,
            )
        )
    listed = {row.employee.pk for row in rows}
    orphans = tuple(
        item
        for (employee_id, number), found in items.items()
        if number == month and employee_id not in listed
        for item in found
    )
    return PayrollMonth(
        year=year,
        month=month,
        grid=grid,
        settings=settings,
        rows=rows,
        net=net,
        orphan_items=orphans,
        run=run,
        previous_open=previous_open(year, month),
        history=_history(run),
        card_changes=tuple(changes),
    )


def settings_snapshot(settings: PayrollSettings) -> dict[str, Any]:
    """Onayda saklanan parametreler: değerler, kaynak, set ve geçerlilik başlangıcı."""
    record = settings.record
    return {
        "origin": settings.source,
        "year": settings.year,
        "record": record.pk if record else None,
        "valid_from": record.valid_from.isoformat() if record and record.valid_from else None,
        "source": record.source if record else "",
        "values": payroll.parameters_to_dict(settings.params),
    }


def _snapshot_settings(approval: PayrollApproval, year: int) -> PayrollSettings:
    data = approval.parameters or {}
    record = None
    if data.get("record") is not None:
        # Kaydedilmemiş kopya: yalnızca kimlik, geçerlilik ve kaynak (onaydaki haliyle).
        record = PayrollParameterSet(
            id=data["record"],
            valid_from=_iso(data.get("valid_from")) or date(year, 1, 1),
            source=data.get("source") or "",
        )
    return PayrollSettings(
        payroll.parameters_from_dict(data.get("values") or {}),
        str(data.get("origin") or SAVED),
        record,
        int(data.get("year") or year),
    )


def _stored_item(year: int, month: int, employee_id: int, data: Mapping[str, Any]) -> PayrollItem:
    """Saklanan kalemden kaydedilmemiş kalem (eski onayın çıktıları için)."""
    return PayrollItem(
        id=data.get("id"),
        employee_id=employee_id,
        year=year,
        month=month,
        kind=data.get("kind") or "",
        category=data.get("category") or "",
        description=data.get("description") or "",
        amount=Decimal(data.get("amount") or 0),
    )


def _stored_figure(
    year: int, month: int, employee_id: int, data: Mapping[str, Any] | None
) -> ExternalPayrollFigure | None:
    if not data:
        return None
    return ExternalPayrollFigure(
        id=data.get("id"),
        employee_id=employee_id,
        year=year,
        month=month,
        gross_total=Decimal(data.get("gross_total") or 0),
        employer_cost=Decimal(data.get("employer_cost") or 0),
        note=data.get("note") or "",
    )


def _stored_carry(data: Mapping[str, Any]) -> CarryMonth:
    return CarryMonth(
        month=int(data.get("month") or 0),
        source=str(data.get("source") or ""),
        tax_base=Decimal(data.get("tax_base") or 0),
        exemption_base=Decimal(data.get("exemption_base") or 0),
        flags=tuple(data.get("flags") or ()),
    )


def opening_snapshot(opening: PayrollOpeningBalance | None) -> dict[str, Any] | None:
    """Zincirin çapası olan devir onaydaki haliyle (yeniden açılan ayda devir yerinde düzeltilir;
    eski onayın çıktısı saklanandan kurulur)."""
    if opening is None:
        return None
    return {
        "id": opening.pk,
        "year": opening.year,
        "month": opening.month,
        "tax_base": str(opening.tax_base),
        "exemption_months": opening.exemption_months,
        "exemption_base": str(opening.exemption_base),
        "note": opening.note,
    }


def _stored_opening(employee_id: int, data: Any) -> PayrollOpeningBalance | None:
    """Saklanan devirden kaydedilmemiş devir (eski onayın çıktıları için)."""
    if not isinstance(data, Mapping):
        return None
    return PayrollOpeningBalance(
        id=data.get("id"),
        employee_id=employee_id,
        year=int(data.get("year") or 0),
        month=int(data.get("month") or 0),
        tax_base=Decimal(data.get("tax_base") or 0),
        exemption_months=int(data.get("exemption_months") or 0),
        exemption_base=Decimal(data.get("exemption_base") or 0),
        note=data.get("note") or "",
    )


def carry_snapshot(row: PayrollRow) -> dict[str, Any]:
    """Satırın kümülatif kuruluşu (onayda saklanır): giriş ayı, çapa devri ve halkalar."""
    return {
        "entry_month": row.entry_month,
        "opening": opening_snapshot(row.opening),
        "carry_months": [
            {
                "month": link.month,
                "source": link.source,
                "tax_base": str(link.tax_base),
                "exemption_base": str(link.exemption_base),
                "flags": list(link.flags),
            }
            for link in row.carry_months
        ],
    }


def item_snapshot(item: PayrollItem) -> dict[str, Any]:
    """Onayda saklanan kalem (açıklama dahil; yalnızca yönetim ve admin görür)."""
    return {
        "id": item.pk,
        "kind": item.kind,
        "category": item.category,
        "description": item.description,
        "amount": str(item.amount),
    }


def figure_snapshot(figure: ExternalPayrollFigure | None) -> dict[str, Any] | None:
    """Onayda saklanan mali müşavir rakamı."""
    if figure is None:
        return None
    return {
        "id": figure.pk,
        "gross_total": str(figure.gross_total),
        "employer_cost": str(figure.employer_cost),
        "note": figure.note,
    }


def _stored_month(
    run: PayrollRun, approval: PayrollApproval, *, department: str = ""
) -> PayrollMonth:
    """Onayda saklanan ay: satırlar, kişi bilgisi, parametreler ve uyarılar onay anındaki haliyle.
    Geçerli onayda kalemler, devirler ve mali müşavir rakamları kayıtlardan okunur (ay kilitli
    olduğu için onaydakiyle aynıdır; kaydı kimin girdiği de görünür); eski onayda saklananlardan
    kurulur."""
    year, month = run.year, run.month
    # Puantaj tablosu birim süzgeçsiz kurulur: satırlar onaydaki birime göre süzülür, kişinin birimi
    # sonradan değişse de günleri (Excel'in Eksik gün sayfası) bulunur.
    grid = attendance_grid(year, month)
    slips_query = approval.slips.select_related("employee")
    if department:
        slips_query = slips_query.filter(person__department=department)
    slips = list(slips_query)
    current = approval.reopened_at is None
    ids = [slip.employee_id for slip in slips]
    items: dict[int, list[PayrollItem]] = defaultdict(list)
    figures: dict[int, ExternalPayrollFigure] = {}
    openings: dict[int, list[PayrollOpeningBalance]] = defaultdict(list)
    if current:
        for item in (
            PayrollItem.objects.filter(is_active=True, year=year, month=month, employee_id__in=ids)
            .select_related("employee", "created_by", "updated_by", "removed_by")
            .order_by("kind", "category", "id")
        ):
            items[item.employee_id].append(item)
        for record in ExternalPayrollFigure.objects.filter(
            is_active=True, year=year, month=month, employee_id__in=ids
        ).select_related("updated_by"):
            figures[record.employee_id] = record
        for opening in (
            PayrollOpeningBalance.objects.filter(
                is_active=True, year=year, month__lte=month, employee_id__in=ids
            )
            .select_related("employee", "created_by", "updated_by", "removed_by")
            .order_by("month", "id")
        ):
            openings[opening.employee_id].append(opening)
    rows = []
    for slip in slips:
        chain = slip.chain or {}
        if current:
            own_items = items.get(slip.employee_id, [])
            figure = figures.get(slip.employee_id)
        else:
            own_items = [
                _stored_item(year, month, slip.employee_id, entry) for entry in slip.items or ()
            ]
            figure = _stored_figure(year, month, slip.employee_id, slip.figure)
        stored_opening = chain.get("opening")
        if current:
            own_openings = openings.get(slip.employee_id, [])
            anchor_id = stored_opening.get("id") if isinstance(stored_opening, Mapping) else None
            anchor = next((item for item in own_openings if item.pk == anchor_id), None)
        else:
            anchor = _stored_opening(slip.employee_id, stored_opening)
            own_openings = [anchor] if anchor is not None else []
        rows.append(
            PayrollRow(
                employee=slip.employee,
                line=payroll.result_from_dict(slip.line or {}),
                external=slip.external,
                figure=figure,
                warnings=tuple(slip.warnings or ()),
                items=tuple(own_items),
                opening=anchor,
                openings=tuple(own_openings),
                entry_month=chain.get("entry_month"),
                carry_months=tuple(_stored_carry(link) for link in chain.get("carry_months", ())),
                snapshot=person_from_snapshot(slip.employee_id, slip.person or {}),
                bes=slip.bes_enrolled,
            )
        )
    rows.sort(key=lambda row: _person_order(row.person))
    return PayrollMonth(
        year=year,
        month=month,
        grid=grid,
        settings=_snapshot_settings(approval, year),
        rows=rows,
        net=True,
        run=run,
        approval=approval,
        history=_history(run),
    )


# Onayı engelleyen satır uyarıları ve onay penceresinde "okudum" istenenler (docs/DECISIONS.md
# "4. adım kararları").
BLOCKING_WARNINGS = (
    OPENING_MISSING,
    CARRY_INCOMPLETE,
    MISSING_WAGE,
    EXTERNAL_MISSING,
    NEGATIVE_PAYABLE,
    BELOW_MINIMUM_WAGE,
    PAY_WITHOUT_SGK_DAYS,
)
ACKNOWLEDGE_WARNINGS = (EXIT_IN_MONTH, CEILING_WITH_BONUS)
# Ay düzeyindeki onay denetimleri.
GATE_BEFORE_START = "before_start"
GATE_ATTENDANCE_OPEN = "attendance_open"
GATE_PREVIOUS_OPEN = "previous_month_open"
GATE_PARAMETERS = "parameters_not_saved"
GATE_NO_EMPLOYEES = "no_employees"
GATE_ORPHAN_ITEMS = "orphan_items"
# Bilgi: bordrosu mali müşavirde olan kişiye ERP'de girilmiş kalemler (hesaplanmaz; listede yazar).
EXTERNAL_ITEMS = "external_items"
BLOCK, ACKNOWLEDGE, NOTICE = "block", "acknowledge", "notice"


@dataclass(frozen=True)
class Gate:
    """Onay denetimi. `level` "block" (onayı engeller), "acknowledge" (onay penceresinde "okudum"
    istenir) ya da "notice" (yalnızca bilgi); `people` ilgili kişiler (ad sırasıyla)."""

    code: str
    level: str
    people: tuple[PersonView, ...] = ()


def payroll_gates(month: PayrollMonth) -> list[Gate]:
    """Açık ayın onay denetimleri: ay düzeyi, engelleyen, "okudum" istenen ve bilgi. Onay tüm ay
    için verilir; birim süzgeçli ay için kullanılmaz."""
    if month.approval is not None:
        return []
    if not month.net_available:
        return [Gate(GATE_BEFORE_START, BLOCK)]
    gates = []
    if not month.attendance_approved:
        gates.append(Gate(GATE_ATTENDANCE_OPEN, BLOCK))
    if month.previous_open:
        gates.append(Gate(GATE_PREVIOUS_OPEN, BLOCK))
    if month.settings.source != SAVED:
        gates.append(Gate(GATE_PARAMETERS, BLOCK))
    if not month.rows:
        gates.append(Gate(GATE_NO_EMPLOYEES, BLOCK))
    if month.orphan_items:
        owners = {item.employee_id: person_view(item.employee) for item in month.orphan_items}
        gates.append(
            Gate(GATE_ORPHAN_ITEMS, BLOCK, tuple(sorted(owners.values(), key=_person_order)))
        )
    for codes, level in ((BLOCKING_WARNINGS, BLOCK), (ACKNOWLEDGE_WARNINGS, ACKNOWLEDGE)):
        for code in codes:
            people = [row.person for row in month.rows if code in row.warnings]
            if people:
                gates.append(Gate(code, level, tuple(sorted(people, key=_person_order))))
    external = [row.person for row in month.rows if row.external and row.items]
    if external:
        gates.append(Gate(EXTERNAL_ITEMS, NOTICE, tuple(sorted(external, key=_person_order))))
    return gates


def payroll_fingerprint(month: PayrollMonth) -> str:
    """Açık ayın hesabının özeti: onay penceresi açıldıktan sonra bir şey değiştiyse (gün, ücret,
    kalem, devir, kart, parametre) onay reddedilir, ay yeniden incelenir."""
    data = {
        "period": [month.year, month.month],
        "attendance": month.attendance_number,
        "origin": month.settings.source,
        "parameters": payroll.parameters_to_dict(month.settings.params),
        "orphans": sorted(item.pk for item in month.orphan_items),
        "rows": [
            {
                "employee": row.employee.pk,
                "person": person_snapshot(row.person),
                "external": row.external,
                "bes": row.bes,
                "figure": figure_snapshot(row.figure),
                "items": [item_snapshot(item) for item in row.items],
                "warnings": list(row.warnings),
                "line": payroll.result_to_dict(row.line),
                "chain": carry_snapshot(row),
            }
            for row in sorted(month.rows, key=lambda item: item.employee.pk)
        ],
    }
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
