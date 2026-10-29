"""Personel okuma sorguları: kartlar, belgeler ve puantaj tablosu."""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.core.models import AuditLog, User
from apps.personnel.models import (
    ATTENDANCE_CODES,
    OVERTIME_STATUSES,
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
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


def rest_weekdays() -> set[int]:
    """Ay önceden dolu açılırken hafta tatili sayılan günler (pazartesi 0 … pazar 6)."""
    settings = AttendanceSettings.objects.order_by("pk").first()
    return set(settings.rest_weekdays if settings else default_rest_weekdays())


def holidays_between(start: date, end: date) -> dict[date, PublicHoliday]:
    """Aralıktaki resmi tatiller (kaldırılanlar hariç), tarihe göre."""
    rows = PublicHoliday.objects.filter(is_active=True, date__range=(start, end))
    return {holiday.date: holiday for holiday in rows}


def holidays_of_year(year: int) -> QuerySet[PublicHoliday]:
    return PublicHoliday.objects.filter(is_active=True, date__year=year).order_by("date")


def default_status(day: date, holiday: PublicHoliday | None, rest: set[int]) -> str:
    """Değiştirilmemiş günün durumu: tam gün tatil resmi tatil (pazara denk gelse de), hafta
    tatili günü hafta tatili, diğerleri (yarım gün tatil dahil) çalıştı."""
    if holiday is not None and not holiday.half_day:
        return AttendanceStatus.PUBLIC_HOLIDAY
    if day.weekday() in rest:
        return AttendanceStatus.WEEKLY_REST
    return AttendanceStatus.WORKED


def employed_on(employee: Employee, day: date) -> bool:
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


@dataclass(frozen=True)
class AttendanceDay:
    """Tablonun bir günü (sütun)."""

    date: date
    rest: bool
    holiday: PublicHoliday | None

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
    (değiştirilmiş ya da onayla yazılmış); değilse varsayılan."""

    date: date
    status: str
    overtime_hours: Decimal
    note: str
    explicit: bool
    editable: bool

    @property
    def code(self) -> str:
        return ATTENDANCE_CODES.get(self.status, "")


@dataclass
class AttendanceTotals:
    """Kişinin ay toplamları: durum başına gün, eksik gün ve günün durumuna göre fazla mesai."""

    days: dict[str, int] = field(default_factory=dict)
    overtime: dict[str, Decimal] = field(default_factory=dict)

    @property
    def missing_days(self) -> int:
        return sum(self.days.get(status, 0) for status in MISSING_DAY_STATUSES)

    @property
    def overtime_total(self) -> Decimal:
        return sum(self.overtime.values(), Decimal(0))


def attendance_totals(cells: Iterable[AttendanceCell]) -> AttendanceTotals:
    totals = AttendanceTotals(
        days=dict.fromkeys(AttendanceStatus.values, 0),
        overtime={status.value: Decimal(0) for status in OVERTIME_STATUSES},
    )
    for cell in cells:
        if not cell.status:
            continue
        totals.days[cell.status] += 1
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
    yalnızca kayıtlı günler vardır."""

    year: int
    month: int
    record: AttendanceMonth | None
    days: list[AttendanceDay]
    rows: list[AttendanceRow]

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


def attendance_grid(year: int, month: int, *, department: str = "") -> AttendanceGrid:
    """Ayın puantaj tablosu (isteğe bağlı birim süzgeciyle)."""
    first, last = month_bounds(year, month)
    record = month_record(year, month)
    approved = record is not None and record.status == AttendanceMonth.Status.APPROVED
    holidays = holidays_between(first, last)
    rest = rest_weekdays()
    days = [
        AttendanceDay(date=day, rest=day.weekday() in rest, holiday=holidays.get(day))
        for day in days_between(first, last)
    ]
    entries = AttendanceEntry.objects.filter(date__range=(first, last)).select_related("employee")
    if department:
        entries = entries.filter(employee__department=department)
    saved: dict[tuple[int, date], AttendanceEntry] = {
        (entry.employee_id, entry.date): entry for entry in entries
    }
    people = {entry.employee_id: entry.employee for entry in saved.values()}
    if not approved:
        for employee in employees_between(first, last, department):
            people.setdefault(employee.pk, employee)
    rows = []
    for employee in sorted(people.values(), key=lambda person: (fold(person.full_name), person.pk)):
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
            cells.append(
                AttendanceCell(
                    date=day.date,
                    status=status,
                    overtime_hours=hours,
                    note=note,
                    explicit=entry is not None,
                    editable=working and not approved,
                )
            )
        rows.append(AttendanceRow(employee=employee, cells=cells))
    return AttendanceGrid(year=year, month=month, record=record, days=days, rows=rows)
