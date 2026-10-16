"""Maliyet okuma sorguları ve raporlar (Faz 4, Adım 4.1).

Raporlama modülü (Adım 4.3) lot maliyeti ve stok değeri için bu fonksiyonları kullanır
(sözleşme: docs/DECISIONS.md "Maliyet okuma API'si"):

- `lot_unit_cost(lot)`: lotun güncel birim maliyeti (TL / temel birim) ve tahmini mi.
- `stock_value(...)`: stok değeri (bakiye × lot birim maliyeti), malzeme bazında ve toplam.
- `cost_trend`, `batch_variance`, `scrap_cost`, `top_materials`: maliyet raporları.

Tutarlar yalnızca yonetim ve admin rolüne gösterilir; bu kontrol API katmanındadır.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Case, Count, F, Q, QuerySet, Sum, Value, When
from django.db.models.functions import TruncMonth

from apps.costing.models import LotCost, LotCostLine
from apps.costing.services import known_unit_cost, money, unit_amount
from apps.inventory.models import Lot, StockBalance
from apps.masterdata.models import Material
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
