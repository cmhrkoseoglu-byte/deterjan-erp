"""Personel okuma sorguları: kartlar, belgeler, puantaj tablosu, ücretler ve ön bordro."""

import calendar
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
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
    PayrollItem,
    PayrollItemCategory,
    PayrollItemKind,
    PayrollOpeningBalance,
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


def _overlaps(employee: Employee, first: date, last: date) -> bool:
    """Kişi aralıkta en az bir gün işte mi (`employees_between` ile aynı kural)?"""
    if employee.hire_date and employee.hire_date > last:
        return False
    return not (employee.termination_date and employee.termination_date < first)


def _grid_rows(
    people: Iterable[Employee],
    days: list[AttendanceDay],
    saved: dict[tuple[int, date], AttendanceEntry],
    approved: bool,
    rest: set[int],
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
    rest = rest_weekdays()
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
        days = [
            AttendanceDay(date=day, rest=day.weekday() in rest, holiday=holidays.get(day))
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
        rows = _grid_rows(people.values(), days, saved, approved, rest)
        grids[month] = AttendanceGrid(year=year, month=month, record=record, days=days, rows=rows)
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
    ayıdır, tutarlar o aydan önceki kümülatiftir), "erp" (ERP'de hesaplanan ay; eklenen GV matrahı
    ve asgari ücret istisna matrahı) ya da "external" (bordrosu mali müşavirdeydi; zincir burada
    kopar)."""

    month: int
    source: str
    tax_base: Decimal
    exemption_base: Decimal
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PayrollRow:
    """Bir kişinin ay bordrosu. `line` ERP hesabıdır; bordrosu mali müşavirde olan kişide
    (`external`) para tutarları yerine mali müşavirin rakamları (`figure`) kullanılır, `line`
    yalnızca günler içindir.

    Brütten nete hesapta (`PayrollMonth.net`): `opening` zincirin çapası olan devir, `openings`
    kişinin bu yıl bu aya kadarki etkin devirleri (ay sırasıyla; devir penceresi önceki ayların
    devirlerini de görsün), `entry_month` devrin beklendiği giriş ayı, `opening_needed` giriş ayının
    devri girilmemiş mi, `suggestion_months` / `suggestion_base` giriş ayının devri için asgari
    ücret istisnası önerisi, `carry_months` ay başı kümülatifin nasıl kurulduğu."""

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
    """Ayın ön bordrosu: puantaj durumu, parametreler ve kişi satırları (canlı hesap). `net`:
    brütten nete (kümülatif zincir, devir, vergiler) hesaplandı mı; başlangıç ayından önce ve
    personel maliyetinde hesaplanmaz. `orphan_items`: o ay işte olmayan kişilere girilmiş
    kalemler."""

    year: int
    month: int
    grid: AttendanceGrid
    settings: PayrollSettings
    rows: list[PayrollRow]
    net: bool = False
    orphan_items: tuple[PayrollItem, ...] = ()

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
) -> payroll.MonthInput:
    """Puantaj satırından hesap girdisi: yalnızca kişinin işte olduğu (durumu olan) günler, her gün
    o gün geçerli ücretle; yarım gün tatil çalışması yalnızca takvimde yarım gün tatil olan güne
    sayılır. Ayın ek ödemeleri brüte, kesintileri netten."""
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
        bes=row.employee.bes_enrolled,
        carry=carry or payroll.Carry(),
    )


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
    """Zincir aylarının önceden yüklenmiş verisi (aylar bellekte hesaplanır)."""

    year: int
    month: int
    start: int
    grids: dict[int, AttendanceGrid]
    rows: dict[int, dict[int, AttendanceRow]]
    settings: dict[int, PayrollSettings]
    wages: dict[int, list[EmployeeWage]]
    items: dict[tuple[int, int], list[PayrollItem]]
    figures: dict[tuple[int, int], ExternalPayrollFigure]


def _chain(employee: Employee, opening: PayrollOpeningBalance | None, data: _ChainData) -> _Chain:
    """Kişinin ay başı kümülatif GV matrahı ve asgari ücret istisna matrahı.

    Çapa, kişinin bu yıl bu ay ya da önceki aylardaki en son devridir (devrin tutarları devir
    ayından önceki kümülatiftir); yoksa zincirin varsayılan ilk ayından (başlangıç yılında Ekim,
    sonra Ocak) sıfırla başlanır. Çapadan bu aya kadarki ERP aylarının GV matrahı ve istisna matrahı
    eklenir (bunlar kümülatife bağlı değildir). Bordrosu mali müşavirde geçen ay zinciri keser:
    sonraki ilk ERP ayı giriş ayıdır ve devir ister. 4. adımda onaylı ayın saklı kümülatifi de
    çapa olacak."""
    anchor = opening.month if opening is not None else data.start
    tax_base = opening.tax_base if opening is not None else Decimal(0)
    exemption = opening.exemption_base if opening is not None else Decimal(0)
    links: list[CarryMonth] = []
    incomplete = False
    if opening is not None:
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
        links.append(
            CarryMonth(opening.month, CARRY_OPENING, tax_base, exemption, tuple(opening_flags))
        )
    last_external: int | None = None
    for number in range(data.start, data.month):
        if (employee.pk, number) in data.figures:
            last_external = number
            if number >= anchor:
                links.append(CarryMonth(number, CARRY_EXTERNAL, Decimal(0), Decimal(0)))
            continue
        if number < anchor:
            continue  # devirden önceki aylar devrin içindedir
        row = data.rows[number].get(employee.pk)
        if row is None:
            continue  # kişi o ay işte değil
        month_input = _month_input(
            row,
            data.grids[number].days,
            data.wages.get(employee.pk, []),
            items=data.items.get((employee.pk, number), []),
        )
        if not month_input.days:
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
    entry = data.start if last_external is None else last_external + 1
    has_opening = opening is not None and opening.month >= entry
    needed = months_employed_before(employee, data.year, entry) > 0 and not has_opening
    return _Chain(payroll.Carry(tax_base, exemption), tuple(links), entry, needed, incomplete)


def payroll_month(year: int, month: int, *, department: str = "", net: bool = True) -> PayrollMonth:
    """Ayın ön bordrosu (isteğe bağlı birim süzgeciyle): puantajın günleri (açık ayda takvim
    varsayılanları, onaylı ayda kayıtlı günler), ücretler ve ayın ek ödeme ve kesintilerinden kişi
    başına brütten nete hesap ve işverene maliyet. Bordrosu mali müşavirde olan kişide (o ay için
    rakamı girilmiş ya da kartı işaretli) o ayın girilmiş rakamları kullanılır.

    `net=True` ve başlangıç ayından sonraki ayda gelir vergisi kişinin kümülatif zinciriyle (devir
    ve önceki ERP ayları) hesaplanır; sorgu sayısı ay ve kişi sayısından bağımsızdır. Personel
    maliyeti `net=False` ile çağırır (işveren maliyeti kümülatife bağlı değildir)."""
    net = net and net_available(year, month)
    start = chain_start(year) if net else None
    months = list(range(start, month + 1)) if start is not None else [month]
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
    )
    rows = []
    for row in grid.rows:
        employee = row.employee
        own_items = items.get((employee.pk, month), [])
        month_input = _month_input(row, grid.days, wages.get(employee.pk, []), items=own_items)
        if not month_input.days:
            continue  # kişi bu ay işte değil (yalnızca işte olmadığı günlerde kaydı var)
        figure = figures.get((employee.pk, month))
        if employee.payroll_external or figure is not None:
            line = payroll.compute(month_input, settings.params)
            rows.append(
                PayrollRow(
                    employee,
                    line,
                    True,
                    figure,
                    () if figure else (EXTERNAL_MISSING,),
                    items=tuple(own_items),
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
            rows.append(PayrollRow(employee, line, False, None, tuple(warnings), tuple(own_items)))
            continue
        if chain.opening_needed:
            warnings.append(OPENING_MISSING)
        if chain.incomplete:
            warnings.append(CARRY_INCOMPLETE)
        if line.payable < 0:
            warnings.append(NEGATIVE_PAYABLE)
        suggestion = months_employed_before(employee, year, chain.entry_month)
        rows.append(
            PayrollRow(
                employee,
                line,
                False,
                None,
                tuple(warnings),
                tuple(own_items),
                opening=anchor,
                openings=tuple(own_openings),
                entry_month=chain.entry_month,
                opening_needed=chain.opening_needed,
                suggestion_months=suggestion,
                suggestion_base=opening_exemption_base(
                    settings_by_month, chain.entry_month, suggestion
                ),
                carry_months=chain.months,
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
    )
