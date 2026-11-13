"""Maliyet okuma sorguları ve raporlar (Faz 4, Adım 4.1).

Raporlama modülü (Adım 4.3) lot maliyeti ve stok değeri için bu fonksiyonları kullanır
(sözleşme: docs/DECISIONS.md "Maliyet okuma API'si"):

- `lot_unit_cost(lot)`: lotun güncel birim maliyeti (TL / temel birim) ve tahmini mi.
- `stock_value(...)`: stok değeri (bakiye × lot birim maliyeti), malzeme bazında ve toplam.
- `cost_trend`, `batch_variance`, `scrap_cost`, `top_materials`: maliyet raporları.
- `personnel_cost_report(year, month)`: aylık personel maliyeti ve işçilik oranı önerisi.

Tutarlar yalnızca yonetim ve admin rolüne gösterilir; bu kontrol API katmanındadır.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Case, Count, F, Q, QuerySet, Sum, Value, When
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.costing.models import (
    CostRate,
    CostStage,
    DepartmentCostCenter,
    LotCost,
    LotCostLine,
)
from apps.costing.services import known_unit_cost, money, to_kg, unit_amount
from apps.filling.models import ConsumptionKind, FillingConsumption, FillingRun
from apps.inventory.models import Lot, StockBalance
from apps.masterdata.models import Material
from apps.personnel import selectors as personnel
from apps.production.models import ProductionBatch
from apps.production.services import batch_line_quantity

ZERO = Decimal(0)
C = LotCostLine.Category
MATERIAL_CATEGORIES = (C.MATERIAL, C.BULK, C.PACKAGING)
OVERHEAD_CATEGORIES = (C.ENERGY, C.LABOR, C.DEPRECIATION)
PURCHASED_TYPES = (Material.Type.RAW, Material.Type.PACKAGING)


@dataclass(frozen=True)
class UnitCost:
    unit_cost: Decimal | None
    is_estimated: bool


def lot_unit_cost(lot: Lot) -> UnitCost:
    """Lotun güncel birim maliyeti (hesaplanmamışsa None, tahmini sayılır)."""
    if lot.unit_cost is None:
        return UnitCost(None, True)
    return UnitCost(lot.unit_cost, lot.cost_is_estimated)


def current_costs() -> QuerySet[LotCost]:
    return LotCost.objects.filter(is_current=True).select_related("lot", "material__base_unit")


def _in_range(
    qs: QuerySet[LotCost], date_from: date | None, date_to: date | None
) -> QuerySet[LotCost]:
    if date_from:
        qs = qs.filter(cost_date__gte=date_from)
    if date_to:
        qs = qs.filter(cost_date__lte=date_to)
    return qs


def _count_true(field: str) -> Sum:
    return Sum(Case(When(**{field: True}, then=Value(1)), default=Value(0)))


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return unit_amount(numerator / denominator) if denominator else None


def cost_trend(
    *, material: Material | None = None, date_from: date | None = None, date_to: date | None = None
) -> list[dict[str, Any]]:
    """Ürün bazında aylık birim maliyet: o ay maliyeti hesaplanan bulk ve mamul lotlarının
    ağırlıklı ortalaması (Σ toplam ÷ Σ miktar)."""
    qs = _in_range(
        current_costs().filter(method__in=(LotCost.Method.PRODUCTION, LotCost.Method.FILLING)),
        date_from,
        date_to,
    )
    if material is not None:
        qs = qs.filter(material=material)
    rows = (
        qs.annotate(month=TruncMonth("cost_date"))
        .values("material_id", "material__code", "material__name", "month")
        .annotate(
            total=Sum("total_cost"),
            quantity=Sum("quantity"),
            lots=Count("id"),
            estimated=_count_true("is_estimated"),
        )
        .order_by("material__code", "month")
    )
    unit_codes = dict(
        Material.objects.filter(pk__in={r["material_id"] for r in rows}).values_list(
            "pk", "base_unit__code"
        )
    )
    return [
        {
            "material_id": r["material_id"],
            "material_code": r["material__code"],
            "material_name": r["material__name"],
            "unit": unit_codes.get(r["material_id"], ""),
            "month": r["month"],
            "lot_count": r["lots"],
            "quantity": r["quantity"],
            "total_cost": r["total"],
            "unit_cost": _ratio(r["total"], r["quantity"]),
            "has_estimated": bool(r["estimated"]),
        }
        for r in rows
    ]


def _line_totals(cost_ids: list[int]) -> dict[int, dict[str, Decimal]]:
    totals: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    rows = (
        LotCostLine.objects.filter(lot_cost_id__in=cost_ids)
        .values("lot_cost_id", "category")
        .annotate(amount=Sum("amount"))
    )
    for row in rows:
        totals[row["lot_cost_id"]][row["category"]] = row["amount"]
    return totals


def batch_variance(
    *, product: Material | None = None, date_from: date | None = None, date_to: date | None = None
) -> list[dict[str, Any]]:
    """Şarj bazında reçete (teorik) ve fiili malzeme maliyeti. Teorik: şarjın reçete ihtiyaçları
    × malzemenin bugün bilinen birim maliyeti (son alış ya da standart); fiili: tüketilen
    lotların maliyeti. Birim maliyetler teorikte şarj miktarına, fiilide gerçek çıktıya
    bölünür; fark yüzdesi birim malzeme maliyeti üzerinden."""
    qs = _in_range(current_costs().filter(method=LotCost.Method.PRODUCTION), date_from, date_to)
    if product is not None:
        qs = qs.filter(material=product)
    costs = list(qs.order_by("-cost_date", "-id"))
    totals = _line_totals([c.pk for c in costs])
    batches = {
        b.output_lot_id: b
        for b in ProductionBatch.objects.filter(output_lot__in=[c.lot_id for c in costs])
        .select_related("order")
        .prefetch_related("order__requirements__material")
    }
    known: dict[int, Decimal | None] = {}
    result = []
    for cost in costs:
        batch = batches.get(cost.lot_id)
        if batch is None:
            continue
        theoretical = ZERO
        theoretical_missing = False
        for requirement in batch.order.requirements.all():
            material = requirement.material
            if material.pk not in known:
                known[material.pk] = known_unit_cost(material)
            price = known[material.pk]
            if price is None:
                theoretical_missing = True
                continue
            theoretical += batch_line_quantity(requirement, batch) * price
        theoretical = money(theoretical)
        lines = totals[cost.pk]
        actual = sum((lines[c] for c in MATERIAL_CATEGORIES), ZERO)
        overhead = sum((lines[c] for c in OVERHEAD_CATEGORIES), ZERO)
        theoretical_unit = _ratio(theoretical, batch.planned_quantity)
        actual_unit = _ratio(actual, cost.quantity)
        variance = None
        if theoretical_unit and actual_unit is not None:
            variance = money((actual_unit - theoretical_unit) / theoretical_unit * 100)
        result.append(
            {
                "lot_cost_id": cost.pk,
                "lot_id": cost.lot_id,
                "lot_no": cost.lot.lot_no,
                "order_number": batch.order.number,
                "product_code": cost.material.code,
                "product_name": cost.material.name,
                "unit": cost.material.base_unit.code,
                "cost_date": cost.cost_date,
                "planned_quantity": batch.planned_quantity,
                "actual_quantity": cost.quantity,
                "theoretical_material_cost": theoretical,
                "actual_material_cost": actual,
                "overhead_cost": overhead,
                "total_cost": cost.total_cost,
                "theoretical_unit_cost": theoretical_unit,
                "actual_material_unit_cost": actual_unit,
                "unit_cost": cost.unit_cost,
                "variance_pct": variance,
                "is_estimated": cost.is_estimated or theoretical_missing,
            }
        )
    return result


def scrap_cost(
    *, product: Material | None = None, date_from: date | None = None, date_to: date | None = None
) -> list[dict[str, Any]]:
    """Dolum partisi bazında fire maliyeti: parti sırasında imha edilen bulk ve ambalaj ile
    mamul firesine (dolup ayrılan adet) giden pay."""
    qs = _in_range(current_costs().filter(method=LotCost.Method.FILLING), date_from, date_to)
    if product is not None:
        qs = qs.filter(material=product)
    costs = list(qs.order_by("-cost_date", "-id"))
    totals = _line_totals([c.pk for c in costs])
    result = []
    for cost in costs:
        material_scrap = totals[cost.pk][C.SCRAP]
        total_scrap = material_scrap + cost.finished_scrap_cost
        result.append(
            {
                "lot_cost_id": cost.pk,
                "lot_id": cost.lot_id,
                "lot_no": cost.lot.lot_no,
                "product_code": cost.material.code,
                "product_name": cost.material.name,
                "cost_date": cost.cost_date,
                "good_units": cost.quantity,
                "material_scrap_cost": material_scrap,
                "finished_scrap_cost": cost.finished_scrap_cost,
                "total_scrap_cost": total_scrap,
                "total_cost": cost.total_cost,
                "scrap_pct": money(total_scrap / cost.total_cost * 100)
                if cost.total_cost
                else None,
            }
        )
    return result


def top_materials(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    material_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Üretim ve dolumda tüketilen hammadde ve ambalajın maliyeti, en pahalıdan (tahmini ve
    fire kalemleri dahil değil: fire `scrap_cost` raporundadır)."""
    costs = _in_range(
        LotCost.objects.filter(
            is_current=True, method__in=(LotCost.Method.PRODUCTION, LotCost.Method.FILLING)
        ),
        date_from,
        date_to,
    )
    qs = LotCostLine.objects.filter(
        lot_cost__in=costs,
        category__in=(C.MATERIAL, C.PACKAGING),
        material__material_type__in=PURCHASED_TYPES,
    )
    if material_type:
        qs = qs.filter(material__material_type=material_type)
    rows = (
        qs.values(
            "material_id",
            "material__code",
            "material__name",
            "material__material_type",
            "material__base_unit__code",
        )
        .annotate(amount=Sum("amount"), quantity=Sum("quantity"), missing=_count_true("is_missing"))
        .order_by("-amount", "material__code")[:limit]
    )
    grand = sum((r["amount"] for r in rows), ZERO)
    return [
        {
            "material_id": r["material_id"],
            "material_code": r["material__code"],
            "material_name": r["material__name"],
            "material_type": r["material__material_type"],
            "unit": r["material__base_unit__code"],
            "quantity": r["quantity"],
            "amount": r["amount"],
            "average_unit_cost": _ratio(r["amount"], r["quantity"] or ZERO),
            "share_pct": money(r["amount"] / grand * 100) if grand else None,
            "has_missing": bool(r["missing"]),
        }
        for r in rows
    ]


def stock_value(
    *,
    material_type: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    material: Material | None = None,
) -> dict[str, Any]:
    """Stok değeri: bakiye × lotun güncel birim maliyeti, malzeme bazında. Maliyeti olmayan
    lotların miktarı ayrıca gösterilir (değere katılmaz)."""
    qs = StockBalance.objects.filter(quantity__gt=0)
    if material_type:
        qs = qs.filter(material__material_type=material_type)
    if warehouse_id:
        qs = qs.filter(location__warehouse_id=warehouse_id)
    if location_id:
        qs = qs.filter(location_id=location_id)
    if material is not None:
        qs = qs.filter(material=material)
    rows = (
        qs.values(
            "material_id",
            "material__code",
            "material__name",
            "material__material_type",
            "material__base_unit__code",
        )
        .annotate(
            total_quantity=Sum("quantity"),
            value=Sum(F("quantity") * F("lot__unit_cost"), filter=Q(lot__unit_cost__isnull=False)),
            uncosted=Sum("quantity", filter=Q(lot__unit_cost__isnull=True)),
            estimated=Sum("quantity", filter=Q(lot__cost_is_estimated=True)),
        )
        .order_by("material__material_type", "material__code")
    )
    result = []
    by_type: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in rows:
        value = money(r["value"] or ZERO)
        by_type[r["material__material_type"]] += value
        result.append(
            {
                "material_id": r["material_id"],
                "material_code": r["material__code"],
                "material_name": r["material__name"],
                "material_type": r["material__material_type"],
                "unit": r["material__base_unit__code"],
                "quantity": r["total_quantity"],
                "value": value,
                "average_unit_cost": _ratio(value, r["total_quantity"] - (r["uncosted"] or ZERO)),
                "uncosted_quantity": r["uncosted"] or ZERO,
                "estimated_quantity": r["estimated"] or ZERO,
            }
        )
    return {
        "total_value": sum(by_type.values(), ZERO),
        "by_type": [{"material_type": k, "value": v} for k, v in sorted(by_type.items())],
        "rows": result,
    }


def stock_value_lots(**filters: Any) -> list[dict[str, Any]]:
    """Stok değeri, lot ve lokasyon bazında (Excel dökümü için)."""
    qs = StockBalance.objects.filter(quantity__gt=0).select_related(
        "material__base_unit", "lot", "location__warehouse"
    )
    if filters.get("material_type"):
        qs = qs.filter(material__material_type=filters["material_type"])
    if filters.get("warehouse_id"):
        qs = qs.filter(location__warehouse_id=filters["warehouse_id"])
    if filters.get("location_id"):
        qs = qs.filter(location_id=filters["location_id"])
    if filters.get("material") is not None:
        qs = qs.filter(material=filters["material"])
    return [
        {
            "material_code": b.material.code,
            "material_name": b.material.name,
            "lot_no": b.lot.lot_no,
            "warehouse": b.location.warehouse.code,
            "location": b.location.code,
            "quantity": b.quantity,
            "unit": b.material.base_unit.code,
            "unit_cost": b.lot.unit_cost,
            "value": money(b.quantity * b.lot.unit_cost) if b.lot.unit_cost is not None else None,
            "is_estimated": b.lot.cost_is_estimated,
        }
        for b in qs.order_by("material__code", "lot__lot_no", "location__code")
    ]


# --- personel maliyeti (docs/DECISIONS.md "Personel maliyeti", "Personel bordrosu") -------------
# Kişi maliyeti personel modülünün ön bordro hesabından gelir (`personnel.selectors.payroll_month`):
# 30 gün usulü brüt, fazla mesai ve resmi tatil çalışması, SGK matrahının alt ve üst sınırı, SGK ve
# işsizlik işveren payları (teşvik sonrası) ve alt sınır farkı.

GENERAL = ""  # genel gider: üretim ya da dolum aşamasına bağlanmamış birimler


@dataclass(frozen=True)
class PersonnelCostRow:
    """Kişinin ay maliyeti. `gross_monthly` ayın son çalışılan günündeki brüt ücret (yoksa None);
    `missing_wage`: işte olduğu bir gün için geçerli ücret yok (o günler sıfır sayıldı) ya da
    bordrosu mali müşavirde olan kişinin (`payroll_external`) o ayın rakamları girilmedi.
    `gross_salary` normal ücret (30 gün usulü), yarım gün kesintisi düşülmüş; fazla mesai ve resmî
    tatil ile ek ödemeler (prim, ikramiye, nakit yol ve yemek) ayrıdır. Mali müşavirdeki kişide brüt
    toplamın tamamıdır.
    `employee` kişinin bordrodaki bilgisidir (onaylı bordroda onay anındaki ad ve birim)."""

    employee: personnel.PersonView
    stage: str
    gross_monthly: Decimal | None
    employed_days: int
    unpaid_days: int
    paid_days: int
    overtime_hours: Decimal
    gross_salary: Decimal
    overtime_pay: Decimal
    employer_share: Decimal
    total_cost: Decimal
    missing_wage: bool
    payroll_external: bool = False
    extras_total: Decimal = ZERO

    @property
    def gross_total(self) -> Decimal:
        return self.gross_salary + self.overtime_pay + self.extras_total


@dataclass(frozen=True)
class ProducedKg:
    """Ayda üretilen kg; `unconverted` kg'a çevrilemeyen (yoğunluğu girilmemiş) malzeme sayısı."""

    kg: Decimal
    unconverted: int


@dataclass(frozen=True)
class StageCost:
    """Aşamanın (üretim, dolum, genel gider) ay maliyeti, üretilen kg ve işçilik oranı önerisi."""

    stage: str
    cost: Decimal
    employee_count: int
    kg: Decimal | None
    unconverted: int
    current_rate: Decimal | None
    missing_wage_count: int

    @property
    def suggested_rate(self) -> Decimal | None:
        """Gerçekleşen işçilik (TL/kg); genel giderde, kg ya da maliyet yokken None."""
        if not self.stage or not self.kg or self.cost <= 0:
            return None
        return unit_amount(self.cost / self.kg)


@dataclass(frozen=True)
class PersonnelCostReport:
    year: int
    month: int
    label: str
    attendance_status: str
    attendance_number: str
    # Etkin işveren oranı (SGK işveren − teşvik + işsizlik işveren) ve parametrelerin kaynağı.
    employer_rate: Decimal
    parameters_origin: str
    parameters_year: int
    rows: list[PersonnelCostRow]
    stages: list[StageCost]
    # Bordro (Ekim 2026'dan): "APPROVED" onaylı (saklı satırlar), "OPEN" tahmin; başlangıçtan önce
    # boş (bordro mali müşavirde, maliyet puantajdan hesaplanır).
    payroll_status: str = ""
    payroll_number: str = ""

    @property
    def attendance_approved(self) -> bool:
        return self.attendance_status == "APPROVED"

    @property
    def payroll_required(self) -> bool:
        """İşçilik oranı için onaylı bordro gerekir mi (başlangıç ayı ve sonrası)?"""
        return personnel.net_available(self.year, self.month)

    @property
    def payroll_approved(self) -> bool:
        return self.payroll_status == "APPROVED"

    @property
    def missing_wage_count(self) -> int:
        return sum(1 for row in self.rows if row.missing_wage)

    @property
    def gross_salary(self) -> Decimal:
        return sum((row.gross_salary for row in self.rows), ZERO)

    @property
    def overtime_pay(self) -> Decimal:
        return sum((row.overtime_pay for row in self.rows), ZERO)

    @property
    def extras_total(self) -> Decimal:
        return sum((row.extras_total for row in self.rows), ZERO)

    @property
    def employer_share(self) -> Decimal:
        return sum((row.employer_share for row in self.rows), ZERO)

    @property
    def total_cost(self) -> Decimal:
        return sum((row.total_cost for row in self.rows), ZERO)

    def stage_cost(self, stage: str) -> StageCost:
        return next(item for item in self.stages if item.stage == stage)


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    """Ayın başı ve bir sonraki ayın başı (Türkiye saatiyle)."""
    first, last = personnel.month_bounds(year, month)
    start = timezone.make_aware(datetime.combine(first, time.min))
    end = timezone.make_aware(datetime.combine(last + timedelta(days=1), time.min))
    return start, end


def _sum_kg(rows: Iterable[tuple[Material, Decimal]]) -> ProducedKg:
    kg, unconverted = ZERO, 0
    for material, quantity in rows:
        converted = to_kg(material, quantity)
        if converted is None:
            unconverted += 1
        else:
            kg += converted
    return ProducedKg(kg=kg, unconverted=unconverted)


def monthly_produced_kg(year: int, month: int) -> dict[str, ProducedKg]:
    """Ayda üretilen kg; lot maliyetinde işçilik oranının uygulandığı tabanla aynı: üretimde
    tamamlanan şarjların gerçek çıktısı, dolumda tamamlanan partilerde dolan bulk (fire hariç).
    Ay, şarjın / partinin bitiş zamanına göre (Türkiye saati) belirlenir."""
    start, end = _month_range(year, month)
    outputs = (
        ProductionBatch.objects.filter(
            status=ProductionBatch.Status.COMPLETED, finished_at__gte=start, finished_at__lt=end
        )
        .values("order__product")
        .annotate(total=Sum("actual_output_quantity"))
    )
    filled = (
        FillingConsumption.objects.filter(
            kind=ConsumptionKind.BULK,
            run__status=FillingRun.Status.COMPLETED,
            run__finished_at__gte=start,
            run__finished_at__lt=end,
        )
        .values("lot__material")
        .annotate(total=Sum("quantity"))
    )
    materials = Material.objects.select_related("base_unit").in_bulk(
        [row["order__product"] for row in outputs] + [row["lot__material"] for row in filled]
    )
    return {
        CostStage.PRODUCTION: _sum_kg(
            (materials[row["order__product"]], row["total"]) for row in outputs if row["total"]
        ),
        CostStage.FILLING: _sum_kg(
            (materials[row["lot__material"]], row["total"]) for row in filled if row["total"]
        ),
    }


def _cost_row(row: personnel.PayrollRow, stage: str) -> PersonnelCostRow:
    """Ön bordro satırından kişi maliyeti. Bordrosu mali müşavirde olan kişide brüt ve işverene
    maliyet o ayın girilmiş rakamlarıdır (girilmemişse sıfır ve eksik)."""
    line = row.line
    if row.external:
        figure = row.figure
        gross = figure.gross_total if figure else ZERO
        cost = figure.employer_cost if figure else ZERO
        return PersonnelCostRow(
            employee=row.person,
            stage=stage,
            gross_monthly=None,
            employed_days=line.employed_days,
            unpaid_days=line.unpaid_days,
            paid_days=line.paid_days,
            overtime_hours=ZERO,
            gross_salary=gross,
            overtime_pay=ZERO,
            employer_share=cost - gross,
            total_cost=cost,
            missing_wage=figure is None,
            payroll_external=True,
        )
    return PersonnelCostRow(
        employee=row.person,
        stage=stage,
        gross_monthly=line.monthly_wage,
        employed_days=line.employed_days,
        unpaid_days=line.unpaid_days,
        paid_days=line.paid_days,
        overtime_hours=line.overtime_worked_hours + line.overtime_rest_hours + line.holiday_hours,
        gross_salary=line.salary - line.short_day_deduction,
        overtime_pay=line.overtime_pay,
        employer_share=line.employer_share,
        total_cost=line.employer_cost,
        missing_wage=line.missing_wage,
        extras_total=line.extras_total,
    )


def _labor_rate_on(stage: str, day: date) -> Decimal | None:
    rate = (
        CostRate.objects.filter(stage=stage, kind=CostRate.Kind.LABOR, valid_from__lte=day)
        .order_by("-valid_from", "-id")
        .first()
    )
    return rate.rate_per_kg if rate else None


def personnel_cost_report(year: int, month: int) -> PersonnelCostReport:
    """Ayın personel maliyeti: ön bordro hesabından (puantaj, ücretler ve bordro parametreleri)
    kişi başına maliyet; birim eşleştirmesine göre üretim, dolum ve genel gider toplamları; üretim
    ve dolumda o ay üretilen kg ile gerçekleşen işçilik (TL/kg). Bordrosu onaylı ayda (Ekim
    2026'dan) kişi satırları ve birimleri onayda saklananlardır; diğer aylar her açılışta bugünkü
    ücret kayıtları, kişinin bugünkü birimi ile işe giriş ve çıkış tarihi ve o yılın bordro
    parametreleriyle hesaplanır (tahmin). Aşama eşleştirmesi bugünkü haliyledir."""
    # İşveren maliyeti gelir vergisi kümülatifine bağlı değil: zincir hesaplanmaz.
    payroll = personnel.payroll_month(year, month, net=False)
    centers = _center_stages()
    rows = [
        _cost_row(row, centers.get(personnel.fold(row.person.department), GENERAL))
        for row in payroll.rows
    ]
    last = payroll.grid.days[-1].date
    produced = monthly_produced_kg(year, month)
    stages = []
    for stage in (CostStage.PRODUCTION, CostStage.FILLING, GENERAL):
        members = [row for row in rows if row.stage == stage]
        made = produced.get(stage)
        stages.append(
            StageCost(
                stage=stage,
                cost=sum((row.total_cost for row in members), ZERO),
                employee_count=len(members),
                kg=made.kg if made else None,
                unconverted=made.unconverted if made else 0,
                current_rate=_labor_rate_on(stage, last) if stage else None,
                missing_wage_count=sum(1 for row in members if row.missing_wage),
            )
        )
    settings = payroll.settings
    return PersonnelCostReport(
        year=year,
        month=month,
        label=payroll.label,
        attendance_status=payroll.grid.status,
        attendance_number=payroll.attendance_number,
        employer_rate=settings.params.employer_rate,
        parameters_origin=settings.source,
        parameters_year=settings.year,
        rows=rows,
        stages=stages,
        payroll_status=(
            ("APPROVED" if payroll.approved else "OPEN") if payroll.net_available else ""
        ),
        payroll_number=payroll.number if payroll.approved else "",
    )


def _center_stages() -> dict[str, str]:
    """Katlanmış birim adı → maliyet aşaması."""
    return {center.key: center.stage for center in DepartmentCostCenter.objects.all()}


def cost_centers() -> list[dict[str, str]]:
    """Personel birimleri ve maliyet aşamaları; eşleştirilmemiş birim genel giderdir (boş)."""
    mapping = _center_stages()
    return [
        {"department": name, "stage": mapping.get(personnel.fold(name), GENERAL)}
        for name in personnel.departments()
    ]
