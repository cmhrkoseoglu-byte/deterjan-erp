"""Maliyet servisleri (Faz 4, Adım 4.1).

Fiili maliyet lot bazında hesaplanır ve `LotCost` sürümü olarak saklanır:

- **Mal kabul lotu**: satır tutarı (fiyat × kur) + mal kabulün ek masraflarından satıra düşen pay
  (miktar ya da tutar oranında) ÷ temel birimde miktar. Fiyat yoksa malzemenin son bilinen alış
  maliyeti, o da yoksa standart maliyet kullanılır ve lot "tahmini" işaretlenir.
- **Bulk lot (şarj)**: Σ(tüketilen lot miktarı × lot birim maliyeti) + üretim gider oranları
  (TL/kg × gerçek çıktı kg) ÷ gerçek çıktı.
- **Dolum lotu (mamul)**: bulk + ambalaj tüketimi + fire (parti sırasında imha edilen bulk ve
  ambalaj) + dolum gider oranları (TL/kg × dolan bulk kg) ÷ sağlam adet.

Hesap olayla tetiklenir (bkz. `handlers.py`); üretim ve dolum modülleri maliyeti bilmez. Girdi
lotunun maliyeti henüz yoksa önce o hesaplanır. Lotun güncel birim maliyeti
`inventory.services.set_lot_cost` ile `Lot.unit_cost`'a yazılır.

Personel maliyeti (2026-10-29): ücret, birim eşleştirmesi ve işveren payı burada yazılır; aylık
hesap `selectors.personnel_cost_report`'tadır ve puantajı (personnel) yalnızca okur.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Max, Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.formatting import format_money
from apps.core.models import User
from apps.core.permissions import user_has_role
from apps.core.roles import YONETIM
from apps.core.services import save_with_audit
from apps.costing.models import (
    CostRate,
    CostStage,
    DepartmentCostCenter,
    EmployeeWage,
    LotCost,
    LotCostLine,
    PersonnelCostSettings,
    StandardCost,
)
from apps.filling.models import ConsumptionKind, FillingRun, ScrapRecord
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceiptExtraCost, GoodsReceiptLine, Lot, LotLink
from apps.inventory.models import StockMovement as Movement
from apps.masterdata import services as masterdata
from apps.masterdata.models import Material, UnitOfMeasure
from apps.production.models import ProductionBatch

MONEY_STEP = Decimal("0.01")
UNIT_STEP = Decimal("0.0001")
ZERO = Decimal(0)
Category = LotCostLine.Category
Method = LotCost.Method

# Malzeme türü → tüketim kalemi
CONSUMPTION_CATEGORY: dict[str, str] = {
    Material.Type.RAW: Category.MATERIAL,
    Material.Type.PACKAGING: Category.PACKAGING,
    Material.Type.BULK: Category.BULK,
    Material.Type.FINISHED: Category.BULK,
}
RATE_CATEGORY: dict[str, str] = {
    CostRate.Kind.ENERGY: Category.ENERGY,
    CostRate.Kind.LABOR: Category.LABOR,
    CostRate.Kind.DEPRECIATION: Category.DEPRECIATION,
}
OVERHEAD_CATEGORIES = tuple(RATE_CATEGORY.values())
# Fiyatı bilinmeyen kaynaklar: tahmini maliyetle başlar.
ESTIMATED_INBOUND_TYPES = (Movement.Type.RECEIPT, Movement.Type.OPENING, Movement.Type.RETURN)

RATE_FIELDS = ("stage", "kind", "rate_per_kg", "valid_from", "note")
WAGE_FIELDS = ("employee", "gross_monthly", "valid_from", "note")
# Ücret ve personel maliyeti kişisel veridir: yalnızca yönetim (ve admin) görür ve yazar.
PERSONNEL_COST_ROLES = (YONETIM,)
STANDARD_COST_FIELDS = ("material", "unit_cost", "note", "is_active")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def unit_amount(value: Decimal) -> Decimal:
    return value.quantize(UNIT_STEP, rounding=ROUND_HALF_UP)


def _pick(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key in allowed}


# --- hesap yapıları ------------------------------------------------------------------------


@dataclass
class _Line:
    category: str
    amount: Decimal
    description: str = ""
    material: Material | None = None
    source_lot: Lot | None = None
    quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    is_estimated: bool = False
    is_missing: bool = False


@dataclass
class _Calc:
    method: str
    quantity: Decimal
    cost_date: date
    lines: list[_Line] = field(default_factory=list)
    finished_scrap_cost: Decimal = ZERO
    # Birim maliyet hiç bilinmiyor (tahmin kaynağı yok).
    unit_unknown: bool = False


@dataclass(frozen=True)
class InputCost:
    """Bir lotun kullanılabilir birim maliyeti."""

    unit_cost: Decimal | None
    is_estimated: bool
    is_missing: bool


# --- yardımcılar -----------------------------------------------------------------------------


def allocate(amount: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Tutarı ağırlıklara kuruş hassasiyetinde dağıtır; yuvarlama farkı en büyük ağırlığa
    eklenir, böylece paylar toplamı tutara eşittir. Ağırlıkların toplamı sıfırsa eşit dağıtır."""
    if not weights:
        return []
    total = sum(weights, ZERO)
    if total <= 0:
        weights = [Decimal(1)] * len(weights)
        total = Decimal(len(weights))
    shares = [money(amount * w / total) for w in weights]
    diff = money(amount) - sum(shares, ZERO)
    if diff:
        largest = max(range(len(weights)), key=lambda i: (weights[i], -i))
        shares[largest] += diff
    return shares


def _kg_unit() -> UnitOfMeasure:
    return UnitOfMeasure.objects.get(code="KG")


def to_kg(material: Material, quantity: Decimal) -> Decimal | None:
    """Temel birimdeki miktarı kg'a çevirir; dönüşüm yoksa (ör. yoğunluğu girilmemiş litre
    ürün) None."""
    try:
        return masterdata.convert_quantity(material, quantity, material.base_unit, _kg_unit())
    except BusinessRuleError:
        return None


def rates_on(stage: str, day: date) -> list[CostRate]:
    """`day` tarihinde geçerli gider oranları (her tür için en son başlayan; sıfır oran yok
    sayılır)."""
    result = []
    for kind in CostRate.Kind.values:
        rate = (
            CostRate.objects.filter(stage=stage, kind=kind, valid_from__lte=day)
            .order_by("-valid_from", "-id")
            .first()
        )
        if rate is not None and rate.rate_per_kg > 0:
            result.append(rate)
    return result


def known_unit_cost(material: Material, *, exclude_lot: Lot | None = None) -> Decimal | None:
    """Malzemenin bilinen birim maliyeti (tahmin için): son fiyatlı mal kabul lotunun maliyeti,
    yoksa aktif standart maliyet; ikisi de yoksa None."""
    last = (
        LotCost.objects.filter(
            material=material,
            is_current=True,
            method=Method.PURCHASE,
            is_estimated=False,
            unit_cost__isnull=False,
        )
        .exclude(lot=exclude_lot)
        .order_by("-cost_date", "-id")
        .values_list("unit_cost", flat=True)
        .first()
    )
    if last is not None:
        return last
    return (
        StandardCost.objects.filter(material=material, is_active=True)
        .values_list("unit_cost", flat=True)
        .first()
    )


def current_cost(lot: Lot) -> LotCost | None:
    return LotCost.objects.filter(lot=lot, is_current=True).first()


def input_cost(actor: User | None, lot: Lot) -> InputCost:
    """Girdi lotunun birim maliyeti. Lotun maliyeti henüz hesaplanmamışsa önce hesaplanır
    (ör. olay handler'ı çalışmamış bir lot)."""
    cost = current_cost(lot)
    if cost is None and is_costable(lot):
        cost = calculate_lot_cost(actor, lot, note="Girdi lotu olarak otomatik hesaplandı")
    if cost is None or cost.unit_cost is None:
        return InputCost(None, True, True)
    return InputCost(cost.unit_cost, cost.is_estimated, cost.has_missing)


def _consumption_line(
    actor: User | None, lot: Lot, quantity: Decimal, category: str | None = None, desc: str = ""
) -> _Line:
    cost = input_cost(actor, lot)
    amount = money(quantity * cost.unit_cost) if cost.unit_cost is not None else ZERO
    return _Line(
        category=category or CONSUMPTION_CATEGORY[lot.material.material_type],
        amount=amount,
        description=desc or lot.material.name,
        material=lot.material,
        source_lot=lot,
        quantity=quantity,
        unit_cost=cost.unit_cost,
        is_estimated=cost.is_estimated,
        is_missing=cost.is_missing,
    )


def _overhead_lines(stage: str, day: date, kg: Decimal | None, basis: str) -> list[_Line]:
    rates = rates_on(stage, day)
    if not rates:
        return []
    if kg is None:
        return [
            _Line(
                category=RATE_CATEGORY[rate.kind],
                amount=ZERO,
                description=f"{rate.get_kind_display()}: kg'a çevrilemedi (yoğunluk yok)",
                is_missing=True,
            )
            for rate in rates
        ]
    return [
        _Line(
            category=RATE_CATEGORY[rate.kind],
            amount=money(kg * rate.rate_per_kg),
            description=f"{rate.get_kind_display()} ({basis})",
            quantity=kg,
            unit_cost=rate.rate_per_kg,
        )
        for rate in rates
    ]


def _local_date(value: Any) -> date:
    return timezone.localdate(value) if value is not None else timezone.localdate()


# --- lot türüne göre hesap -------------------------------------------------------------------


def _receipt_line(lot: Lot) -> GoodsReceiptLine | None:
    return (
        GoodsReceiptLine.objects.select_related("receipt", "material__base_unit")
        .filter(created_lot=lot)
        .first()
    )


def _line_amount_tl(line: GoodsReceiptLine) -> Decimal | None:
    if line.unit_price is None:
        return None
    return money(line.quantity * line.unit_price * (line.exchange_rate or Decimal(1)))


def _extra_lines(line: GoodsReceiptLine) -> list[_Line]:
    """Mal kabulün ek masraflarından bu satıra düşen paylar."""
    receipt = line.receipt
    extras = list(receipt.extra_costs.order_by("id"))
    if not extras:
        return []
    lines = list(receipt.lines.filter(base_quantity__isnull=False).order_by("line_no"))
    index = next(i for i, other in enumerate(lines) if other.pk == line.pk)
    result = []
    for extra in extras:
        if extra.allocation == GoodsReceiptExtraCost.Allocation.VALUE:
            values = [_line_amount_tl(other) or ZERO for other in lines]
            # Hiçbir satırda fiyat yoksa miktar oranına düşülür.
            weights = values if sum(values, ZERO) > 0 else [o.base_quantity or ZERO for o in lines]
        else:
            weights = [other.base_quantity or ZERO for other in lines]
        share = allocate(extra.amount, weights)[index]
        label = extra.get_kind_display()
        if extra.description:
            label = f"{label}: {extra.description}"
        result.append(
            _Line(
                category=Category.EXTRA,
                amount=share,
                description=f"{label} ({extra.get_allocation_display().lower()})",
            )
        )
    return result


def _inbound_quantity(lot: Lot) -> Decimal:
    total = Movement.objects.filter(
        lot=lot, movement_type__in=ESTIMATED_INBOUND_TYPES, quantity__gt=0
    ).aggregate(s=Sum("quantity"))["s"]
    return total or ZERO


def _estimate_line(lot: Lot, quantity: Decimal, reason: str) -> tuple[_Line, bool]:
    known = known_unit_cost(lot.material, exclude_lot=lot)
    if known is None:
        return (
            _Line(
                category=Category.ESTIMATE,
                amount=ZERO,
                description=f"{reason}; son alış ya da standart maliyet yok",
                material=lot.material,
                quantity=quantity,
                is_estimated=True,
                is_missing=True,
            ),
            True,
        )
    return (
        _Line(
            category=Category.ESTIMATE,
            amount=money(quantity * known),
            description=f"{reason}; son bilinen / standart maliyet",
            material=lot.material,
            quantity=quantity,
            unit_cost=known,
            is_estimated=True,
        ),
        False,
    )


def _purchase_calc(lot: Lot) -> _Calc:
    line = _receipt_line(lot)
    if line is None or line.base_quantity is None:
        return _estimate_calc(lot)
    calc = _Calc(Method.PURCHASE, line.base_quantity, line.receipt.receipt_date)
    amount = _line_amount_tl(line)
    if amount is None:
        estimate, unknown = _estimate_line(lot, line.base_quantity, "Mal kabulde fiyat yok")
        calc.lines.append(estimate)
        calc.unit_unknown = unknown
    else:
        currency = ""
        if line.exchange_rate is not None:
            currency = f" ({line.unit_price} {line.currency} × {line.exchange_rate})"
        calc.lines.append(
            _Line(
                category=Category.PURCHASE,
                amount=amount,
                description=f"{line.receipt.number} satır {line.line_no}{currency}",
                material=lot.material,
                quantity=line.base_quantity,
                unit_cost=unit_amount(amount / line.base_quantity),
            )
        )
    calc.lines.extend(_extra_lines(line))
    return calc


def _estimate_calc(lot: Lot) -> _Calc:
    quantity = _inbound_quantity(lot)
    calc = _Calc(Method.ESTIMATE, quantity, _local_date(lot.created_at))
    estimate, unknown = _estimate_line(lot, quantity, lot.get_source_display())
    calc.lines.append(estimate)
    calc.unit_unknown = unknown
    return calc


def _grouped(rows: Iterable[tuple[Lot, Decimal]]) -> list[tuple[Lot, Decimal]]:
    totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    lots: dict[int, Lot] = {}
    for lot, quantity in rows:
        totals[lot.pk] += quantity
        lots[lot.pk] = lot
    return [(lots[pk], totals[pk]) for pk in totals]


def _production_calc(actor: User | None, lot: Lot) -> _Calc:
    batch = (
        ProductionBatch.objects.select_related("order__product__base_unit")
        .filter(output_lot=lot)
        .first()
    )
    if batch is None or batch.status != ProductionBatch.Status.COMPLETED:
        raise BusinessRuleError("cost_not_ready", f"{lot.lot_no}: şarj tamamlanmadı.")
    assert batch.actual_output_quantity is not None
    day = _local_date(batch.finished_at)
    calc = _Calc(Method.PRODUCTION, batch.actual_output_quantity, day)
    consumptions = batch.consumptions.select_related("lot__material").order_by("id")
    for source, quantity in _grouped((c.lot, c.actual_quantity) for c in consumptions):
        calc.lines.append(_consumption_line(actor, source, quantity))
    product = batch.order.product
    kg = to_kg(product, batch.actual_output_quantity)
    calc.lines.extend(_overhead_lines(CostStage.PRODUCTION, day, kg, "kg çıktı"))
    return calc


def _filling_calc(actor: User | None, lot: Lot) -> _Calc:
    run = FillingRun.objects.select_related("order").filter(output_lot=lot).first()
    if run is None or run.status != FillingRun.Status.COMPLETED:
        raise BusinessRuleError("cost_not_ready", f"{lot.lot_no}: dolum partisi tamamlanmadı.")
    assert run.good_units is not None
    day = _local_date(run.finished_at)
    calc = _Calc(Method.FILLING, Decimal(run.good_units), day)
    consumptions = list(run.consumptions.select_related("lot__material__base_unit").order_by("id"))
    bulk_kg: Decimal | None = ZERO
    for kind in (ConsumptionKind.BULK, ConsumptionKind.PACKAGING):
        rows = [(c.lot, c.quantity) for c in consumptions if c.kind == kind]
        category = Category.BULK if kind == ConsumptionKind.BULK else Category.PACKAGING
        for source, quantity in _grouped(rows):
            calc.lines.append(_consumption_line(actor, source, quantity, category))
            if kind == ConsumptionKind.BULK and bulk_kg is not None:
                kg = to_kg(source.material, quantity)
                bulk_kg = None if kg is None else bulk_kg + kg
    calc.lines.extend(_overhead_lines(CostStage.FILLING, day, bulk_kg, "kg dolan bulk"))
    # Mamul firesine (dolup ayrılan adet) giden tüketim payı: bilgi amaçlı.
    scrapped = sum((s.quantity for s in run.scraps.filter(kind=ScrapRecord.Kind.FINISHED)), ZERO)
    consumed = sum((line.amount for line in calc.lines), ZERO)
    total_units = Decimal(run.good_units) + scrapped
    if scrapped and total_units:
        calc.finished_scrap_cost = money(consumed * scrapped / total_units)
    scraps = run.scraps.exclude(kind=ScrapRecord.Kind.FINISHED).select_related("lot__material")
    for scrap in scraps.order_by("recorded_at", "id"):
        calc.lines.append(
            _consumption_line(
                actor,
                scrap.lot,
                scrap.quantity,
                Category.SCRAP,
                f"Fire ({scrap.get_kind_display().lower()}): {scrap.lot.material.name}, "
                f"{scrap.get_reason_code_display().lower()}",
            )
        )
    return calc


def is_costable(lot: Lot) -> bool:
    """Lotun maliyeti şu an hesaplanabilir mi (üretim ve dolum lotunda iş bitmiş olmalı)."""
    if lot.source == Lot.Source.PRODUCTION:
        return ProductionBatch.objects.filter(
            output_lot=lot, status=ProductionBatch.Status.COMPLETED
        ).exists()
    if lot.source == Lot.Source.FILLING:
        return FillingRun.objects.filter(
            output_lot=lot, status=FillingRun.Status.COMPLETED
        ).exists()
    return True


def _compute(actor: User | None, lot: Lot) -> _Calc:
    if lot.source == Lot.Source.PURCHASE:
        return _purchase_calc(lot)
    if lot.source == Lot.Source.PRODUCTION:
        return _production_calc(actor, lot)
    if lot.source == Lot.Source.FILLING:
        return _filling_calc(actor, lot)
    return _estimate_calc(lot)


# --- kayıt ----------------------------------------------------------------------------------


@transaction.atomic
def calculate_lot_cost(actor: User | None, lot: Lot, *, note: str = "") -> LotCost:
    """Lotun maliyetini hesaplayıp yeni sürüm olarak saklar; önceki sürüm güncel olmaktan çıkar.
    `Lot.unit_cost` güncellenir. Üretim / dolum lotunda şarj / parti tamamlanmamışsa
    `cost_not_ready`."""
    lot = (
        Lot.objects.select_for_update(of=("self",))
        .select_related("material__base_unit")
        .get(pk=lot.pk)
    )
    calc = _compute(actor, lot)
    total = sum((line.amount for line in calc.lines), ZERO)
    has_missing = any(line.is_missing for line in calc.lines)
    is_estimated = has_missing or any(line.is_estimated for line in calc.lines)
    unit_cost: Decimal | None = None
    if not calc.unit_unknown:
        if calc.quantity > 0:
            unit_cost = unit_amount(total / calc.quantity)
        else:
            estimate = next((ln for ln in calc.lines if ln.unit_cost is not None), None)
            unit_cost = estimate.unit_cost if estimate is not None else None
    previous = LotCost.objects.filter(lot=lot).aggregate(v=Max("version"))["v"] or 0
    LotCost.objects.filter(lot=lot, is_current=True).update(is_current=False)
    cost = save_with_audit(
        LotCost(
            lot=lot,
            material=lot.material,
            version=previous + 1,
            is_current=True,
            method=calc.method,
            quantity=calc.quantity,
            total_cost=money(total),
            unit_cost=unit_cost,
            finished_scrap_cost=calc.finished_scrap_cost,
            is_estimated=is_estimated,
            has_missing=has_missing,
            cost_date=calc.cost_date,
            calculated_at=timezone.now(),
            calculated_by=actor if actor is not None and actor.is_authenticated else None,
            note=note,
        ),
        actor,
        note=note,
    )
    LotCostLine.objects.bulk_create(
        LotCostLine(
            lot_cost=cost,
            line_no=number,
            category=line.category,
            description=line.description[:200],
            material=line.material,
            source_lot=line.source_lot,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
            amount=line.amount,
            is_estimated=line.is_estimated,
            is_missing=line.is_missing,
            created_by=cost.created_by,
            updated_by=cost.created_by,
        )
        for number, line in enumerate(calc.lines, start=1)
    )
    inventory.set_lot_cost(
        actor,
        lot,
        unit_cost,
        estimated=is_estimated,
        note=f"Maliyet sürüm {cost.version}" + (f": {note}" if note else ""),
    )
    return cost


def ensure_lot_cost(actor: User | None, lot: Lot, *, note: str = "") -> LotCost | None:
    """Lotun güncel maliyeti yoksa hesaplar (olay handler'ları için; aynı olay iki kez gelirse
    ikinci sürüm açılmaz). Hesaplanamıyorsa None."""
    cost = current_cost(lot)
    if cost is not None:
        return cost
    if not is_costable(lot):
        return None
    return calculate_lot_cost(actor, lot, note=note)


def descendants(lot: Lot) -> list[Lot]:
    """Soy ağacında lottan ileri giden lotlar; her lot tüm girdilerinden sonra gelecek sırada
    (en uzun yol derinliğine göre)."""
    depth: dict[int, int] = {}
    frontier = {lot.pk: 0}
    while frontier:
        children: dict[int, int] = {}
        for pk, level in frontier.items():
            for child in LotLink.objects.filter(parent_lot_id=pk).values_list(
                "child_lot_id", flat=True
            ):
                if child == lot.pk:
                    continue
                if depth.get(child, -1) < level + 1:
                    depth[child] = level + 1
                    children[child] = level + 1
        frontier = children
    lots = Lot.objects.in_bulk(list(depth))
    return [lots[pk] for pk in sorted(depth, key=lambda pk: (depth[pk], pk))]


@transaction.atomic
def recalculate_lot_cost(
    actor: User | None, lot: Lot, note: str, *, cascade: bool = False
) -> list[LotCost]:
    """Lotun maliyetini yeniden hesaplar (yeni sürüm, not zorunlu). `cascade` ile soy ağacında
    ileri giden lotlar da (hammadde → bulk → mamul) girdileri yeni maliyetle sırayla yeniden
    hesaplanır; henüz tamamlanmamış şarj / partinin lotu atlanır."""
    note = note.strip()
    if not note:
        raise BusinessRuleError("note_required", "Yeniden hesaplama için not girilmelidir.")
    if not is_costable(lot):
        raise BusinessRuleError(
            "cost_not_ready", f"{lot.lot_no}: şarj / dolum partisi tamamlanmadı."
        )
    results = [calculate_lot_cost(actor, lot, note=note)]
    if cascade:
        for child in descendants(lot):
            if is_costable(child):
                results.append(
                    calculate_lot_cost(actor, child, note=f"{note} (girdi lot {lot.lot_no})")
                )
    return results


# --- gider oranları ve standart maliyet ----------------------------------------------------


def _validate_rate(rate: CostRate) -> None:
    if rate.stage not in CostStage.values:
        raise BusinessRuleError("invalid_stage", "Geçersiz aşama.")
    if rate.kind not in CostRate.Kind.values:
        raise BusinessRuleError("invalid_rate_kind", "Geçersiz gider türü.")
    if rate.rate_per_kg is None or rate.rate_per_kg < 0:
        raise BusinessRuleError("invalid_rate", "Oran negatif olamaz.")
    duplicate = CostRate.objects.filter(
        stage=rate.stage, kind=rate.kind, valid_from=rate.valid_from
    ).exclude(pk=rate.pk)
    if duplicate.exists():
        raise BusinessRuleError(
            "duplicate_rate", "Bu aşama ve türde bu tarihte başlayan bir oran zaten var."
        )


@transaction.atomic
def create_rate(actor: User | None, data: Mapping[str, Any]) -> CostRate:
    """Gider oranı ekler (Karar D-15, rol: yonetim). Oran değişince eskisi silinmez; yeni tarihle
    yeni oran girilir. Hesaplanmış lot maliyetleri değişmez."""
    rate = CostRate(**_pick(data, RATE_FIELDS))
    _validate_rate(rate)
    return save_with_audit(rate, actor)


@transaction.atomic
def update_rate(actor: User | None, rate: CostRate, data: Mapping[str, Any]) -> CostRate:
    """Gider oranını düzeltir (denetim günlüğüne eski → yeni yazılır). Hesaplanmış maliyetler
    ancak yeniden hesaplamayla değişir."""
    rate = CostRate.objects.select_for_update().get(pk=rate.pk)
    for name, value in _pick(data, RATE_FIELDS).items():
        setattr(rate, name, value)
    _validate_rate(rate)
    return save_with_audit(rate, actor)


def _validate_standard_cost(cost: StandardCost) -> None:
    if cost.unit_cost is None or cost.unit_cost < 0:
        raise BusinessRuleError("invalid_cost", "Maliyet negatif olamaz.")
    duplicate = StandardCost.objects.filter(material=cost.material).exclude(pk=cost.pk)
    if duplicate.exists():
        raise BusinessRuleError(
            "duplicate_standard_cost", "Bu malzemenin standart maliyeti zaten var."
        )


@transaction.atomic
def create_standard_cost(actor: User | None, data: Mapping[str, Any]) -> StandardCost:
    """Malzemeye standart birim maliyet (TL / temel birim) girer (rol: yonetim)."""
    cost = StandardCost(**_pick(data, STANDARD_COST_FIELDS))
    _validate_standard_cost(cost)
    return save_with_audit(cost, actor)


@transaction.atomic
def update_standard_cost(
    actor: User | None, cost: StandardCost, data: Mapping[str, Any]
) -> StandardCost:
    """Standart maliyeti günceller ya da pasife alır (malzeme değişmez)."""
    cost = StandardCost.objects.select_for_update().get(pk=cost.pk)
    values = _pick(data, STANDARD_COST_FIELDS)
    values.pop("material", None)
    for name, value in values.items():
        setattr(cost, name, value)
    _validate_standard_cost(cost)
    return save_with_audit(cost, actor)


# --- personel maliyeti (docs/DECISIONS.md "Personel maliyeti") ----------------------------------


def _require_personnel_cost_role(actor: User | None) -> None:
    if not user_has_role(actor, PERSONNEL_COST_ROLES):
        raise PermissionDenied(
            "Ücret ve personel maliyetini yalnızca yönetim ve sistem yöneticisi görür."
        )


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


# Akla yatkınlık sınırları: hatalı yazılan tarih (ör. 0026 yılı) ya da tutar raporu bozmasın.
WAGE_DATE_MIN, WAGE_DATE_MAX = date(2000, 1, 1), date(2100, 12, 31)
MAX_MONTHLY_WAGE = Decimal("100000000")


@transaction.atomic
def add_wage(actor: User, data: Mapping[str, Any]) -> EmployeeWage:
    """Kişiye brüt aylık ücret girer, `valid_from` tarihinden itibaren geçerli. Zam yeni tarihle
    eklenir; aynı kişide aynı tarihte iki geçerli ücret olamaz. Ücret sıfırdan büyük olmalı."""
    _require_personnel_cost_role(actor)
    wage = EmployeeWage(**_pick(data, WAGE_FIELDS))
    if wage.employee_id is None:
        raise BusinessRuleError("employee_required", "Personel seçilmelidir.")
    if wage.valid_from is None:
        raise BusinessRuleError("valid_from_required", "Geçerlilik başlangıcı girilmelidir.")
    if not WAGE_DATE_MIN <= wage.valid_from <= WAGE_DATE_MAX:
        raise BusinessRuleError(
            "invalid_valid_from", "Geçerlilik başlangıcı 2000 ile 2100 yılları arasında olmalı."
        )
    if wage.gross_monthly is None or not ZERO < wage.gross_monthly <= MAX_MONTHLY_WAGE:
        raise BusinessRuleError(
            "invalid_wage",
            f"Brüt ücret sıfırdan büyük ve en çok {format_money(MAX_MONTHLY_WAGE)} TL olmalı.",
        )
    duplicate = EmployeeWage.objects.filter(
        employee_id=wage.employee_id, valid_from=wage.valid_from, is_active=True
    )
    if duplicate.exists():
        raise BusinessRuleError(
            "duplicate_wage",
            f"Bu kişinin {wage.valid_from:%d.%m.%Y} tarihinden geçerli bir ücreti zaten var; "
            "yanlışsa önce o kaydı kaldırın.",
        )
    wage.note = _clean_text(wage.note)[:200]
    try:
        with transaction.atomic():
            return save_with_audit(wage, actor)
    except IntegrityError:
        # Aynı kişi ve tarihe aynı anda iki ücret girildi (tekil kısıt).
        raise BusinessRuleError(
            "duplicate_wage",
            f"Bu kişinin {wage.valid_from:%d.%m.%Y} tarihinden geçerli bir ücreti zaten var; "
            "yanlışsa önce o kaydı kaldırın.",
        ) from None


@transaction.atomic
def remove_wage(actor: User, wage: EmployeeWage, reason: str) -> EmployeeWage:
    """Yanlış ücret kaydını kaldırır (silinmez, pasife alınır; neden zorunlu)."""
    _require_personnel_cost_role(actor)
    reason = _clean_text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    locked = EmployeeWage.objects.select_for_update().get(pk=wage.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Ücret kaydı zaten kaldırılmış.")
    locked.is_active = False
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.removal_reason = reason
    return save_with_audit(locked, actor, note="Ücret kaydı kaldırıldı")


def get_personnel_cost_settings() -> PersonnelCostSettings:
    """Personel maliyeti ayarları (tek kayıt). Kayıt yoksa kaydedilmemiş varsayılan döner (işveren
    payı %17,75); kayıt ilk değişiklikte denetim kaydıyla açılır."""
    return PersonnelCostSettings.objects.order_by("pk").first() or PersonnelCostSettings()


@transaction.atomic
def update_personnel_cost_settings(actor: User, employer_rate: Decimal) -> PersonnelCostSettings:
    """İşveren payını (yüzde, 0–100) değiştirir. Rapor saklanmaz, her açılışta hesaplanır; bu
    yüzden bütün aylar yeni oranla görünür."""
    _require_personnel_cost_role(actor)
    if employer_rate is None or not ZERO <= employer_rate <= 100:
        raise BusinessRuleError(
            "invalid_employer_rate", "İşveren payı %0 ile %100 arasında olmalı."
        )
    instance = PersonnelCostSettings.objects.select_for_update().order_by("pk").first()
    if instance is None:
        try:
            with transaction.atomic():
                return save_with_audit(
                    PersonnelCostSettings(pk=1, employer_rate=employer_rate), actor
                )
        except IntegrityError:
            # Aynı anda ilk kaydı başka biri açtı: onu güncelle.
            instance = PersonnelCostSettings.objects.select_for_update().get(pk=1)
    instance.employer_rate = employer_rate
    return save_with_audit(instance, actor)


@transaction.atomic
def set_department_cost_center(actor: User, department: str, stage: str) -> DepartmentCostCenter:
    """Personel biriminin maliyet aşamasını yazar: PRODUCTION (bulk), FILLING (mamul) ya da boş
    (genel gider). Birim adı büyük/küçük harf farkı gözetmeden eşleşir."""
    from apps.personnel.selectors import fold

    _require_personnel_cost_role(actor)
    name = _clean_text(department)[:64]
    if not name:
        raise BusinessRuleError("department_required", "Birim girilmelidir.")
    if stage and stage not in CostStage.values:
        raise BusinessRuleError("invalid_stage", "Geçersiz aşama.")
    key = fold(name)
    center = DepartmentCostCenter.objects.select_for_update().filter(key=key).first()
    if center is None:
        try:
            with transaction.atomic():
                return save_with_audit(
                    DepartmentCostCenter(department=name, key=key, stage=stage or ""), actor
                )
        except IntegrityError:
            # Aynı birimi aynı anda başka biri eşleştirdi: onu güncelle.
            center = DepartmentCostCenter.objects.select_for_update().get(key=key)
    center.stage = stage or ""
    return save_with_audit(center, actor)


@transaction.atomic
def add_labor_rate_from_personnel_cost(
    actor: User, year: int, month: int, stage: str, valid_from: date
) -> CostRate:
    """Ayın gerçekleşen personel maliyetinden (aşamaya bağlı birimlerin toplam maliyeti ÷ o ay
    üretilen kg) yeni işçilik oranı açar. Yalnızca puantajı onaylı ayda; oran sunucuda yeniden
    hesaplanır. Eski oranlar ve hesaplanmış lot maliyetleri değişmez; aynı tarihte oran varsa
    reddedilir (`duplicate_rate`)."""
    from apps.costing.selectors import personnel_cost_report

    _require_personnel_cost_role(actor)
    if stage not in CostStage.values:
        raise BusinessRuleError("invalid_stage", "Geçersiz aşama.")
    report = personnel_cost_report(year, month)
    if not report.attendance_approved:
        raise BusinessRuleError(
            "attendance_not_approved",
            f"{report.label} puantajı onaylanmadan işçilik oranı eklenemez.",
        )
    summary = report.stage_cost(stage)
    if summary.suggested_rate is None:
        raise BusinessRuleError(
            "no_labor_rate",
            f"{report.label} için bu aşamada personel maliyeti ya da üretilen kg yok; oran "
            "hesaplanamaz.",
        )
    note = (
        f"Personel maliyeti {report.label}: {format_money(summary.cost)} TL / "
        f"{format_money(summary.kg)} kg"
    )
    return create_rate(
        actor,
        {
            "stage": stage,
            "kind": CostRate.Kind.LABOR,
            "rate_per_kg": summary.suggested_rate,
            "valid_from": valid_from,
            "note": note[:200],
        },
    )
