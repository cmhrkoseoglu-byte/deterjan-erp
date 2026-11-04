"""Bordro hesap motoru (2026-11-01, docs/DECISIONS.md "Personel bordrosu"): brütten nete ücret ve
işverene maliyet.

Yalnızca Python standart kitaplığını kullanır (Django ve uygulama modülleri yok); girdiler puantaj
günleri, o gün geçerli brüt ücret, yasal parametreler ve kişinin bu işverendeki yıl içi kümülatif
durumudur, çıktı bordronun bütün kalemleridir. Her kalem kuruşa yarım yukarı yuvarlanır
(`ROUND_HALF_UP`; Decimal'in varsayılanı olan yarımda çifte yuvarlama kullanılmaz).

- Ay 30 gün sayılır; ücretsiz izin, devamsızlık ve rapor günleri brüt / 30 ile düşülür. Ay içinde
  giren ya da ayrılan işte olduğu takvim günü kadar alır (personel maliyeti kuralı).
- Saat ücreti brüt / 225. Fazla mesai iş günü ve hafta tatilinde 1,5 kat. Resmî tatilde çalışana bir
  günlük ilave ücret (brüt / 30), 7,5 saati aşan saatler 1,5 kat; yarım gün tatilde öğleden sonra
  çalışana yarım günlük ilave.
- SGK günü: tam ayda 30; eksik gün varsa ayın takvim günü eksi eksik gün (en çok 30); ay içinde
  giriş ya da çıkışta işte olunan takvim günü eksi eksik gün.
- SGK matrahı günlük alt sınır (asgari ücret / 30) ile üst sınır (alt sınır × çarpan) arasındadır.
  Ücret alt sınırın altında kalırsa işçi payları ücretten hesaplanır; farkın primini işçi payı dahil
  işveren öder (5510 s. Kanun m.82).
- Gelir vergisi yıl içi kümülatif matrahla, iki yuvarlanmamış tarife tutarının farkı olarak
  hesaplanır. Asgari ücret istisnası aynı yöntemle, kişinin bu işverendeki kümülatif asgari ücret
  matrahıyla bulunur ve hesaplanan vergiyi aşmaz. Damga vergisi brütün asgari ücreti aşan kısmından.
- BES kesintisi SGK matrahının yüzdesi olarak netten düşülür.
- Nakit yemek ek ödemesinin fiilen çalışılan gün × günlük sınıra kadarki kısmı SGK matrahına girmez
  (5510 s. Kanun m.80); gelir ve damga vergisine tabi kalır. Günlük sınır parametredir (varsayılan
  0: istisna yok).
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

ENGINE_VERSION = "2026.2"

ZERO = Decimal(0)
CENT = Decimal("0.01")
HUNDRED = Decimal(100)
THOUSAND = Decimal(1000)
PAYROLL_DAYS = 30
MONTHLY_HOURS = Decimal(225)
DAILY_HOURS = Decimal("7.5")
HALF_DAY_HOURS = Decimal("3.75")
OVERTIME_FACTOR = Decimal("1.5")

# Puantaj durumları (`personnel.models.AttendanceStatus` değerleri; eşitliği testler denetler).
WORKED = "WORKED"
WEEKLY_REST = "WEEKLY_REST"
PUBLIC_HOLIDAY = "PUBLIC_HOLIDAY"
UNPAID_LEAVE = "UNPAID_LEAVE"
SICK_LEAVE = "SICK_LEAVE"
ABSENT = "ABSENT"
UNPAID_STATUSES = frozenset({UNPAID_LEAVE, SICK_LEAVE, ABSENT})
REST_STATUSES = frozenset({WEEKLY_REST, PUBLIC_HOLIDAY})

# Ek ödeme kategorisi (`personnel.models.PayrollItem.Category`): SGK istisnası nakit yemekte.
MEAL = "MEAL"


def money(value: Decimal) -> Decimal:
    """Kuruşa yarım yukarı yuvarlama."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percent(base: Decimal, rate: Decimal) -> Decimal:
    """Tutarın yüzdesi, kuruşa yuvarlanmış."""
    return money(base * rate / HUNDRED)


@dataclass(frozen=True)
class Parameters:
    """Bir dönemin yasal değerleri. Oranlar yüzde, damga vergisi binde; tarife dört dilim sınırı ve
    beş oran."""

    minimum_wage: Decimal
    ceiling_multiplier: Decimal
    employee_sgk_rate: Decimal
    employee_unemployment_rate: Decimal
    employer_sgk_rate: Decimal
    employer_unemployment_rate: Decimal
    incentive_points: Decimal
    stamp_tax_per_mille: Decimal
    tax_brackets: tuple[Decimal, Decimal, Decimal, Decimal]
    tax_rates: tuple[Decimal, Decimal, Decimal, Decimal, Decimal]
    bes_rate: Decimal
    # Nakit yemek SGK istisnası, fiilen çalışılan gün başına TL (0: istisna yok).
    meal_exemption_daily: Decimal = ZERO

    @property
    def daily_floor(self) -> Decimal:
        """Günlük SGK matrahı alt sınırı (günlük asgari ücret)."""
        return money(self.minimum_wage / PAYROLL_DAYS)

    @property
    def daily_ceiling(self) -> Decimal:
        """Günlük SGK matrahı üst sınırı."""
        return money(self.daily_floor * self.ceiling_multiplier)

    @property
    def employer_rate(self) -> Decimal:
        """Etkin işveren oranı: SGK işveren payı − teşvik + işsizlik işveren payı."""
        return self.employer_sgk_rate - self.incentive_points + self.employer_unemployment_rate

    @property
    def exemption_base(self) -> Decimal:
        """Asgari ücretin gelir vergisi matrahı: brüt eksi SGK ve işsizlik işçi payları."""
        wage = self.minimum_wage
        return (
            wage
            - percent(wage, self.employee_sgk_rate)
            - percent(wage, self.employee_unemployment_rate)
        )

    def tariff(self, base: Decimal) -> Decimal:
        """Ücret gelirleri tarifesi T(base), yuvarlanmadan."""
        total, lower = ZERO, ZERO
        for limit, rate in zip(self.tax_brackets, self.tax_rates, strict=False):
            if base <= limit:
                return total + (base - lower) * rate / HUNDRED
            total += (limit - lower) * rate / HUNDRED
            lower = limit
        return total + (base - lower) * self.tax_rates[-1] / HUNDRED

    def tax_between(self, before: Decimal, added: Decimal) -> Decimal:
        """Kümülatif matrah `before`'dan `before + added`'e çıkınca doğan vergi (kuruşa)."""
        return money(self.tariff(before + added) - self.tariff(before))


@dataclass(frozen=True)
class Day:
    """Kişinin işte olduğu bir gün: puantaj durumu, fazla mesai saati, o gün geçerli brüt aylık
    ücret (yoksa None) ve yarım gün tatilde öğleden sonra çalışıp çalışmadığı."""

    date: date
    status: str
    overtime_hours: Decimal = ZERO
    wage: Decimal | None = None
    half_holiday_worked: bool = False


@dataclass(frozen=True)
class Item:
    """Elle girilen aylık kalem: ek ödeme (brüt) ya da net kesinti. `kind` kalemin kategorisidir
    (ör. "MEAL" nakit yemek, "ADVANCE" avans)."""

    kind: str
    label: str
    amount: Decimal


@dataclass(frozen=True)
class Carry:
    """Kişinin bu işverende bu yıl, hesaplanan aydan önceki kümülatif durumu: gelir vergisi matrahı
    ve asgari ücret istisnası matrahı."""

    tax_base: Decimal = ZERO
    exemption_base: Decimal = ZERO


@dataclass(frozen=True)
class MonthInput:
    """Bir kişinin bir ayı. `days` yalnızca işte olunan (durumu olan) günlerdir."""

    days: tuple[Day, ...]
    days_in_month: int
    extras: tuple[Item, ...] = ()
    deductions: tuple[Item, ...] = ()
    bes: bool = False
    carry: Carry = Carry()


@dataclass(frozen=True)
class Result:
    """Bordro satırının bütün kalemleri (TL, kuruşa yuvarlanmış)."""

    # Günler
    employed_days: int
    worked_days: int
    paid_days: int
    unpaid_days: int
    sick_days: int
    unpaid_leave_days: int
    absent_days: int
    sgk_days: int
    monthly_wage: Decimal | None
    missing_wage: bool
    # Kazançlar
    salary: Decimal
    overtime_worked_hours: Decimal
    overtime_worked_pay: Decimal
    overtime_rest_hours: Decimal
    overtime_rest_pay: Decimal
    holiday_days: int
    holiday_half_days: int
    holiday_hours: Decimal
    holiday_extra_hours: Decimal
    holiday_pay: Decimal
    extras: tuple[Item, ...]
    extras_total: Decimal
    gross_total: Decimal
    # SGK ve işsizlik (işçi)
    meal_exemption: Decimal
    sgk_gross: Decimal
    sgk_base: Decimal
    floor_applied: bool
    ceiling_applied: bool
    employee_sgk: Decimal
    employee_unemployment: Decimal
    # Gelir ve damga vergisi
    tax_base: Decimal
    cumulative_tax_base_before: Decimal
    cumulative_tax_base_after: Decimal
    income_tax_computed: Decimal
    income_tax_exemption: Decimal
    income_tax: Decimal
    exemption_base_before: Decimal
    exemption_base_added: Decimal
    stamp_tax_computed: Decimal
    stamp_tax_exemption: Decimal
    stamp_tax: Decimal
    net_pay: Decimal
    # Netten kesintiler ve ödenecek
    bes_deduction: Decimal
    deductions: tuple[Item, ...]
    deductions_total: Decimal
    payable: Decimal
    # İşveren
    employer_sgk_gross: Decimal
    incentive: Decimal
    employer_sgk: Decimal
    employer_unemployment: Decimal
    floor_gap: Decimal
    employer_cost: Decimal

    @property
    def employee_deductions(self) -> Decimal:
        """Yasal kesintiler: SGK, işsizlik, gelir ve damga vergisi."""
        return self.employee_sgk + self.employee_unemployment + self.income_tax + self.stamp_tax

    @property
    def overtime_pay(self) -> Decimal:
        """Fazla mesai ve tatil çalışması toplamı."""
        return self.overtime_worked_pay + self.overtime_rest_pay + self.holiday_pay

    @property
    def employer_share(self) -> Decimal:
        """İşverenin brüt üstündeki payı: SGK (teşvik sonrası), işsizlik, alt sınır farkı."""
        return self.employer_sgk + self.employer_unemployment + self.floor_gap


def _salary(days: tuple[Day, ...], days_in_month: int) -> tuple[Decimal, int]:
    """Normal ücret (30 gün usulü) ve ücretli gün. Her gün o gün geçerli ücretle; tek bölme."""
    unpaid = [day for day in days if day.status in UNPAID_STATUSES]
    count = len(days)
    paid_count = count - len(unpaid)
    known = sum((day.wage for day in days if day.wage is not None), ZERO)
    unpaid_known = sum((day.wage for day in unpaid if day.wage is not None), ZERO)
    if count == days_in_month and paid_count and len(unpaid) < PAYROLL_DAYS:
        # Tam ay: takvim günleri 30'a ölçeklenir (31 ve 28 çeken aylarda da ücret aylık brüttür).
        raw = (PAYROLL_DAYS * known - count * unpaid_known) / (PAYROLL_DAYS * count)
        return money(max(ZERO, raw)), PAYROLL_DAYS - len(unpaid)
    return money(max(ZERO, (known - unpaid_known) / PAYROLL_DAYS)), paid_count


def _sgk_days(days: tuple[Day, ...], days_in_month: int) -> int:
    count = len(days)
    unpaid = sum(1 for day in days if day.status in UNPAID_STATUSES)
    if count == days_in_month and not unpaid:
        return PAYROLL_DAYS if count else 0
    return max(0, min(PAYROLL_DAYS, count - unpaid))


def compute(month: MonthInput, params: Parameters) -> Result:
    """Kişinin ay bordrosu: günler, kazançlar, SGK, vergiler, net ve işverene maliyet."""
    days = month.days
    salary, paid_days = _salary(days, month.days_in_month)
    worked_hours = rest_hours = holiday_hours = holiday_extra = ZERO
    worked_raw = rest_raw = holiday_raw = ZERO
    holiday_days = holiday_half_days = 0
    for day in days:
        hours = Decimal(day.overtime_hours or 0)
        wage = day.wage
        if day.status == WORKED:
            worked_hours += hours
            if wage is not None:
                worked_raw += hours * wage * OVERTIME_FACTOR
                if day.half_holiday_worked:
                    holiday_raw += HALF_DAY_HOURS * wage
            if day.half_holiday_worked:
                holiday_half_days += 1
        elif day.status == WEEKLY_REST:
            rest_hours += hours
            if wage is not None:
                rest_raw += hours * wage * OVERTIME_FACTOR
        elif day.status == PUBLIC_HOLIDAY and hours > 0:
            # Tatilde çalışılan gün: bir günlük ilave ücret; 7,5 saati aşan saat fazla mesaidir.
            holiday_days += 1
            holiday_hours += hours
            extra = max(ZERO, hours - DAILY_HOURS)
            holiday_extra += extra
            if wage is not None:
                holiday_raw += DAILY_HOURS * wage + extra * wage * OVERTIME_FACTOR
    overtime_worked = money(worked_raw / MONTHLY_HOURS)
    overtime_rest = money(rest_raw / MONTHLY_HOURS)
    holiday_pay = money(holiday_raw / MONTHLY_HOURS)
    extras_total = sum((item.amount for item in month.extras), ZERO)
    gross = salary + overtime_worked + overtime_rest + holiday_pay + extras_total

    # Nakit yemek: fiilen çalışılan gün × günlük sınıra kadarki kısmı SGK matrahına girmez (gelir
    # ve damga vergisine tabi kalır). Fiilen çalışılan gün: Ç, fazla mesaili hafta tatili ve
    # resmî tatil.
    worked_days = sum(
        1
        for day in days
        if day.status == WORKED or (day.status in REST_STATUSES and day.overtime_hours > 0)
    )
    meal_total = sum((item.amount for item in month.extras if item.kind == MEAL), ZERO)
    meal_exemption = money(min(meal_total, params.meal_exemption_daily * worked_days))
    sgk_gross = gross - meal_exemption

    # SGK matrahı (alt ve üst sınır), işçi payları ve alt sınır farkı. Ücreti girilmemiş gün varsa
    # brüt eksiktir: alt sınır uygulanmaz (yoksa ücretsiz görünen kişiye prim yazılırdı); satır
    # "ücret eksik" uyarısı taşır.
    wages = [day.wage for day in days]
    missing_wage = any(wage is None for wage in wages)
    sgk_days = _sgk_days(days, month.days_in_month)
    if sgk_days:
        floor = ZERO if missing_wage else params.daily_floor * sgk_days
        ceiling = params.daily_ceiling * sgk_days
        sgk_base = min(max(sgk_gross, floor), ceiling)
    else:
        floor = ceiling = sgk_base = ZERO
    floor_applied = bool(sgk_days) and sgk_gross < floor
    ceiling_applied = bool(sgk_days) and sgk_gross > ceiling
    employee_base = min(sgk_gross, sgk_base)
    employee_sgk = percent(employee_base, params.employee_sgk_rate)
    employee_unemployment = percent(employee_base, params.employee_unemployment_rate)
    floor_gap = ZERO
    if floor_applied:
        floor_gap = (
            percent(sgk_base, params.employee_sgk_rate)
            - employee_sgk
            + percent(sgk_base, params.employee_unemployment_rate)
            - employee_unemployment
        )

    # Gelir vergisi ve asgari ücret istisnası
    carry = month.carry
    tax_base = max(ZERO, gross - employee_sgk - employee_unemployment)
    computed = params.tax_between(carry.tax_base, tax_base)
    exemption = added = ZERO
    if gross > 0:
        added = params.exemption_base
        exemption = min(computed, params.tax_between(carry.exemption_base, added))
    income_tax = computed - exemption

    # Damga vergisi (asgari ücreti aşan kısım)
    per_mille = params.stamp_tax_per_mille
    stamp_computed = money(gross * per_mille / THOUSAND)
    stamp_tax = money(max(ZERO, gross - params.minimum_wage) * per_mille / THOUSAND)

    net_pay = gross - employee_sgk - employee_unemployment - income_tax - stamp_tax
    bes = percent(sgk_base, params.bes_rate) if month.bes else ZERO
    deductions_total = sum((item.amount for item in month.deductions), ZERO)

    # İşveren payları
    employer_sgk_gross = percent(sgk_base, params.employer_sgk_rate)
    incentive = percent(sgk_base, params.incentive_points)
    employer_sgk = employer_sgk_gross - incentive
    employer_unemployment = percent(sgk_base, params.employer_unemployment_rate)
    employer_cost = gross + employer_sgk + employer_unemployment + floor_gap

    return Result(
        employed_days=len(days),
        worked_days=worked_days,
        paid_days=paid_days,
        unpaid_days=sum(1 for day in days if day.status in UNPAID_STATUSES),
        sick_days=sum(1 for day in days if day.status == SICK_LEAVE),
        unpaid_leave_days=sum(1 for day in days if day.status == UNPAID_LEAVE),
        absent_days=sum(1 for day in days if day.status == ABSENT),
        sgk_days=sgk_days,
        monthly_wage=wages[-1] if wages else None,
        missing_wage=missing_wage,
        salary=salary,
        overtime_worked_hours=worked_hours,
        overtime_worked_pay=overtime_worked,
        overtime_rest_hours=rest_hours,
        overtime_rest_pay=overtime_rest,
        holiday_days=holiday_days,
        holiday_half_days=holiday_half_days,
        holiday_hours=holiday_hours,
        holiday_extra_hours=holiday_extra,
        holiday_pay=holiday_pay,
        extras=month.extras,
        extras_total=extras_total,
        gross_total=gross,
        meal_exemption=meal_exemption,
        sgk_gross=sgk_gross,
        sgk_base=sgk_base,
        floor_applied=floor_applied,
        ceiling_applied=ceiling_applied,
        employee_sgk=employee_sgk,
        employee_unemployment=employee_unemployment,
        tax_base=tax_base,
        cumulative_tax_base_before=carry.tax_base,
        cumulative_tax_base_after=carry.tax_base + tax_base,
        income_tax_computed=computed,
        income_tax_exemption=exemption,
        income_tax=income_tax,
        exemption_base_before=carry.exemption_base,
        exemption_base_added=added,
        stamp_tax_computed=stamp_computed,
        stamp_tax_exemption=stamp_computed - stamp_tax,
        stamp_tax=stamp_tax,
        net_pay=net_pay,
        bes_deduction=bes,
        deductions=month.deductions,
        deductions_total=deductions_total,
        payable=net_pay - bes - deductions_total,
        employer_sgk_gross=employer_sgk_gross,
        incentive=incentive,
        employer_sgk=employer_sgk,
        employer_unemployment=employer_unemployment,
        floor_gap=floor_gap,
        employer_cost=employer_cost,
    )


def carry_after(result: Result) -> Carry:
    """Bir sonraki ayın kümülatif durumu."""
    return Carry(
        tax_base=result.cumulative_tax_base_after,
        exemption_base=result.exemption_base_before + result.exemption_base_added,
    )


# Onaylı ayın saklanan satırı: `Result` JSON biçiminde (tutarlar metin; motor sürümüyle saklanır).
_INT_FIELDS = frozenset(
    {
        "employed_days",
        "worked_days",
        "paid_days",
        "unpaid_days",
        "sick_days",
        "unpaid_leave_days",
        "absent_days",
        "sgk_days",
        "holiday_days",
        "holiday_half_days",
    }
)
_BOOL_FIELDS = frozenset({"missing_wage", "floor_applied", "ceiling_applied"})
_ITEM_FIELDS = frozenset({"extras", "deductions"})


def result_to_dict(result: Result) -> dict[str, Any]:
    """Satırın saklanacak biçimi: tutarlar metin (Decimal kesinliği korunur), kalemler liste."""
    data: dict[str, Any] = {}
    for field in fields(Result):
        value = getattr(result, field.name)
        if field.name in _ITEM_FIELDS:
            data[field.name] = [
                {"kind": item.kind, "label": item.label, "amount": str(item.amount)}
                for item in value
            ]
        elif isinstance(value, Decimal):
            data[field.name] = str(value)
        else:
            data[field.name] = value  # gün sayıları, işaretler, boş ücret
    return data


def result_from_dict(data: Mapping[str, Any]) -> Result:
    """Saklanan satırdan `Result` (`result_to_dict`in tersi). Eski motor sürümüyle saklanmış satır
    da okunur: bilinmeyen anahtarlar atlanır, eksik alan boş değerini alır (gün 0, işaret hayır,
    kalem yok, tutar 0; aylık ücret boş)."""
    values: dict[str, Any] = {}
    for field in fields(Result):
        raw = data.get(field.name)
        if field.name in _ITEM_FIELDS:
            values[field.name] = tuple(
                Item(str(entry["kind"]), str(entry["label"]), Decimal(entry["amount"]))
                for entry in raw or ()
            )
        elif field.name in _INT_FIELDS:
            values[field.name] = int(raw or 0)
        elif field.name in _BOOL_FIELDS:
            values[field.name] = bool(raw)
        elif raw is None:
            values[field.name] = None if field.name == "monthly_wage" else ZERO
        else:
            values[field.name] = Decimal(raw)
    return Result(**values)


_TUPLE_PARAMETERS = frozenset({"tax_brackets", "tax_rates"})


def parameters_to_dict(params: Parameters) -> dict[str, Any]:
    """Parametrelerin saklanacak biçimi (onayda): değerler metin, tarife listeleri."""
    data: dict[str, Any] = {}
    for field in fields(Parameters):
        value = getattr(params, field.name)
        data[field.name] = [str(item) for item in value] if isinstance(value, tuple) else str(value)
    return data


def parameters_from_dict(data: Mapping[str, Any]) -> Parameters:
    """Saklanan parametrelerden `Parameters` (`parameters_to_dict`in tersi; eksik değer 0)."""
    values: dict[str, Any] = {}
    for field in fields(Parameters):
        raw = data.get(field.name)
        if field.name in _TUPLE_PARAMETERS:
            values[field.name] = tuple(Decimal(item) for item in raw or ())
        else:
            values[field.name] = ZERO if raw is None else Decimal(raw)
    return Parameters(**values)


# Yasal değerler ve kaynakları. Parametre ekranı bunlarla doldurulur; o yıl için kayıtlı set yoksa
# taslak hesap bunları kullanır ve ekran "Parametreler kaydedilmedi" uyarısı gösterir. Her yıl
# yeni değerlerle güncellenir (mali müşavirle teyit edilerek).
LEGAL_DEFAULTS: dict[int, Parameters] = {
    2026: Parameters(
        minimum_wage=Decimal("33030.00"),
        ceiling_multiplier=Decimal("9.00"),
        employee_sgk_rate=Decimal("14.00"),
        employee_unemployment_rate=Decimal("1.00"),
        employer_sgk_rate=Decimal("21.75"),
        employer_unemployment_rate=Decimal("2.00"),
        incentive_points=Decimal("5.00"),
        stamp_tax_per_mille=Decimal("7.590"),
        tax_brackets=(
            Decimal("190000.00"),
            Decimal("400000.00"),
            Decimal("1500000.00"),
            Decimal("5300000.00"),
        ),
        tax_rates=(
            Decimal("15.00"),
            Decimal("20.00"),
            Decimal("27.00"),
            Decimal("35.00"),
            Decimal("40.00"),
        ),
        bes_rate=Decimal("3.00"),
    ),
}
LEGAL_SOURCES: dict[int, str] = {
    2026: (
        "Asgari ücret: Asgari Ücret Tespit Komisyonu 2025/1 (RG 26.12.2025/33119). SGK alt ve üst "
        "sınır, prim oranları ve teşvik: 5510 s. Kanun m.81–82 (7566 s. Kanun), SGK Genelge 2026/1 "
        "ve 2026/2. Gelir vergisi tarifesi: GVK m.103, GVGT Seri No 332 (RG 31.12.2025/33124). "
        "Damga vergisi: DVK (1) IV-1-b. BES: 4632 s. Kanun ek m.2."
    ),
}


def legal_parameters(year: int) -> Parameters | None:
    """Yılın yasal değerleri (bilinmiyorsa None)."""
    return LEGAL_DEFAULTS.get(year)


def nearest_legal_year(year: int) -> int:
    """Yasal değerleri bilinen en yakın yıl (önce geçmiş yıllar)."""
    return min(LEGAL_DEFAULTS, key=lambda known: (abs(known - year), known > year))
