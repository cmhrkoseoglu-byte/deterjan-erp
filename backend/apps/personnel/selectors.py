"""Personel okuma sorguları: kartlar, belgeler, puantaj tablosu, ücretler ve ön bordro."""

import calendar
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.core.models import AuditLog, User
from apps.personnel import payroll
from apps.personnel.models import (
    ATTENDANCE_CODES,
    OVERTIME_STATUSES,
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeWage,
    ExternalPayrollFigure,
    PayrollParameterSet,
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


# Günün özetteki ayırt edici bilgisi: durum, fazla mesai ve not olup olmadığı.
_DayKey = tuple[str, Decimal, bool]


def _run_label(first: date, last: date, key: _DayKey) -> str:
    status, hours, noted = key
    extra = []
    if hours:
        extra.append(f"{'günde ' if first != last else ''}{format_hours(hours)} sa FM")
    if noted:
        extra.append("notlu")
    text = f"{day_span(first, last)} {ATTENDANCE_CODES.get(status, status)}"
    return f"{text} ({', '.join(extra)})" if extra else text


def summarize_days(entries: Iterable[AttendanceEntry]) -> str:
    """Kayıtlı günlerin kısa özeti, ay ay. Durumu, fazla mesaisi ve not işareti aynı ardışık günler
    aralık olur: "Eylül 2026: 21–23.09 Üİ, 24.09 Ç (2 sa FM, notlu); Ekim 2026: 05–06.10 Yİ".
    Çok günlük aralıkta fazla mesai gün başınadır ("günde 2 sa FM"); notun metni denetim
    kaydındadır."""
    months: dict[tuple[int, int], list[tuple[date, date, _DayKey]]] = {}
    for entry in sorted(entries, key=lambda item: item.date):
        key = (entry.status, Decimal(entry.overtime_hours or 0), bool(entry.note))
        runs = months.setdefault((entry.date.year, entry.date.month), [])
        if runs and runs[-1][2] == key and runs[-1][1] + timedelta(days=1) == entry.date:
            runs[-1] = (runs[-1][0], entry.date, key)
        else:
            runs.append((entry.date, entry.date, key))
    return "; ".join(
        f"{month_label(year, month)}: " + ", ".join(_run_label(*run) for run in runs)
        for (year, month), runs in months.items()
    )


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
    (değiştirilmiş ya da onayla yazılmış); değilse varsayılan. `holiday_half_worked`: yarım gün
    tatilde öğleden sonra da çalıştı."""

    date: date
    status: str
    overtime_hours: Decimal
    note: str
    explicit: bool
    editable: bool
    holiday_half_worked: bool = False

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
                    # İşaret yalnızca takvimde hâlâ yarım gün tatil olan günde sayılır; tatil
                    # kaldırılırsa saklı işaret durur ama tabloda, Excel'de ve bordroda görünmez.
                    holiday_half_worked=bool(entry and entry.holiday_half_worked and day.half_day),
                )
            )
        rows.append(AttendanceRow(employee=employee, cells=cells))
    return AttendanceGrid(year=year, month=month, record=record, days=days, rows=rows)


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
    )


def payroll_parameters(year: int, month: int) -> PayrollSettings:
    """Ayın parametreleri: aynı yılın, ayın ilk gününe kadar geçerli olmuş en son kayıtlı seti;
    yoksa yılın yasal değerleri; o da yoksa en yakın yılın yasal değerleri (tahmin)."""
    first = date(year, month, 1)
    record = (
        PayrollParameterSet.objects.filter(
            is_active=True, valid_from__year=year, valid_from__lte=first
        )
        .order_by("-valid_from", "-id")
        .first()
    )
    if record is not None:
        return PayrollSettings(engine_parameters(record), SAVED, record, year)
    legal = payroll.legal_parameters(year)
    if legal is not None:
        return PayrollSettings(legal, LEGAL_DEFAULT, None, year)
    nearest = payroll.nearest_legal_year(year)
    return PayrollSettings(payroll.LEGAL_DEFAULTS[nearest], FALLBACK, None, nearest)


def parameter_sets() -> QuerySet[PayrollParameterSet]:
    """Kayıtlı parametre setleri (kaldırılanlar hariç), en yenisi önce."""
    return PayrollParameterSet.objects.filter(is_active=True).order_by("-valid_from", "-id")


@dataclass(frozen=True)
class PayrollRow:
    """Bir kişinin ay bordrosu. `line` ERP hesabıdır; bordrosu mali müşavirde olan kişide
    (`external`) para tutarları yerine mali müşavirin rakamları (`figure`) kullanılır, `line`
    yalnızca günler içindir."""

    employee: Employee
    line: payroll.Result
    external: bool
    figure: ExternalPayrollFigure | None
    warnings: tuple[str, ...]

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
class PayrollMonth:
    """Ayın ön bordrosu: puantaj durumu, parametreler ve kişi satırları (canlı hesap)."""

    year: int
    month: int
    grid: AttendanceGrid
    settings: PayrollSettings
    rows: list[PayrollRow]

    @property
    def label(self) -> str:
        return self.grid.label

    @property
    def attendance_approved(self) -> bool:
        return self.grid.approved

    @property
    def attendance_number(self) -> str:
        return self.grid.record.number if self.grid.record else ""

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


def _month_input(
    row: AttendanceRow, days: list[AttendanceDay], wages: Sequence[EmployeeWage]
) -> payroll.MonthInput:
    """Puantaj satırından hesap girdisi: yalnızca kişinin işte olduğu (durumu olan) günler, her gün
    o gün geçerli ücretle; yarım gün tatil çalışması yalnızca takvimde yarım gün tatil olan güne
    sayılır."""
    half_days = {day.date for day in days if day.half_day}
    items = tuple(
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
    return payroll.MonthInput(days=items, days_in_month=len(days), bes=row.employee.bes_enrolled)


def _warnings(
    employee: Employee,
    line: payroll.Result,
    days: tuple[payroll.Day, ...],
    params: payroll.Parameters,
    last: date,
) -> tuple[str, ...]:
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
    return tuple(found)


def payroll_month(year: int, month: int, *, department: str = "") -> PayrollMonth:
    """Ayın ön bordrosu (isteğe bağlı birim süzgeciyle): puantajın günleri (açık ayda takvim
    varsayılanları, onaylı ayda kayıtlı günler) ve ücretlerden kişi başına brütten nete hesap ve
    işverene maliyet. Bordrosu mali müşavirde olan kişide o ayın girilmiş rakamları kullanılır."""
    grid = attendance_grid(year, month, department=department)
    settings = payroll_parameters(year, month)
    last = grid.days[-1].date
    people = [row.employee.pk for row in grid.rows]
    wages = wages_by_employee(people, last)
    figures = {
        figure.employee_id: figure
        for figure in ExternalPayrollFigure.objects.filter(
            year=year, month=month, employee_id__in=people
        ).select_related("updated_by")
    }
    rows = []
    for row in grid.rows:
        month_input = _month_input(row, grid.days, wages.get(row.employee.pk, []))
        if not month_input.days:
            continue  # kişi bu ay işte değil (yalnızca işte olmadığı günlerde kaydı var)
        line = payroll.compute(month_input, settings.params)
        warnings: tuple[str, ...]
        if row.employee.payroll_external:
            figure = figures.get(row.employee.pk)
            warnings = () if figure else (EXTERNAL_MISSING,)
            rows.append(PayrollRow(row.employee, line, True, figure, warnings))
            continue
        warnings = _warnings(row.employee, line, month_input.days, settings.params, last)
        rows.append(PayrollRow(row.employee, line, False, None, warnings))
    return PayrollMonth(year=year, month=month, grid=grid, settings=settings, rows=rows)
