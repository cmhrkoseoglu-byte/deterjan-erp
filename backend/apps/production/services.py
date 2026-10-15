"""Üretim servisleri: emir, ihtiyaç listesi, malzeme hazırlama, şarj, tartım ve emir kapanışı.

Kurallar:
- Stok yalnızca `inventory.services` ile hareket eder (CLAUDE.md §3). Hazırlama `transfer`,
  tartım `ISSUE_PRODUCTION`, şarj bitişi `PRODUCTION_OUTPUT` hareketidir; tartım soy ağacına
  girdi lot → çıktı lot bağı yazar (`link_lots`).
- Yalnızca serbest ve SKT'si geçmemiş lot hazırlanır ve tüketilir.
- Karar D-4: emir tank kapasitesini aşarsa birden çok şarja bölünür; her şarjın kendi tartımları ve
  kendi bulk lotu vardır. Planlanan miktarın tamamı şarjlara dağıtılıp hepsi bitince emir analiz
  bekler; tüm çıktı lotları serbest bırakılınca emir tamamlanır.
- Karar D-1: şebeke suyu stokludur ama depoda hazırlanmaz; tartımda kendi lokasyonundan düşülür.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import DEPO, PLANLAMA, URETIM
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockBalance, StockMovement
from apps.inventory.services import format_quantity, lot_payload, quantize
from apps.masterdata import services as masterdata
from apps.masterdata.models import Equipment, Location, Material
from apps.production.models import (
    BatchConsumption,
    MaterialPick,
    ProductionBatch,
    ProductionOrder,
    ProductionRequirement,
)
from apps.production.state import production_batch_states, production_order_states
from apps.recipes import services as recipes
from apps.recipes.models import RecipeVersion

ORDER_ROLES = (PLANLAMA,)
PREP_ROLES = (DEPO,)
PRODUCTION_ROLES = (URETIM,)

Status = ProductionOrder.Status
BatchStatus = ProductionBatch.Status
MovementType = StockMovement.Type

ORDER_FIELDS = (
    "recipe_version",
    "planned_quantity",
    "unit",
    "planned_date",
    "equipment",
    "production_location",
    "priority",
    "notes",
)
# Hazırlama bu durumlarda yapılır; onaylı emirde ilk hazırlama hazırlığı başlatır. Şarj sırasında
# eksik çıkan malzeme için de hazırlama yapılabilir.
PICKABLE_STATUSES = (
    Status.APPROVED,
    Status.MATERIAL_PREP,
    Status.MATERIAL_READY,
    Status.IN_PRODUCTION,
)
BATCHABLE_STATUSES = (Status.MATERIAL_READY, Status.IN_PRODUCTION)
# Hazırlanan miktar ihtiyacın en çok bu katı olabilir (ambalaj yuvarlaması için pay).
MAX_PICK_FACTOR = Decimal(2)
PCT_STEP = Decimal("0.01")
HUNDRED = Decimal(100)


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def _require_role(actor: User | None, roles: tuple[str, ...], message: str) -> None:
    if not user_has_role(actor, roles):
        raise PermissionDenied(message)


def _pick_fields(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


def _pct(value: Decimal) -> Decimal:
    return value.quantize(PCT_STEP, rounding=ROUND_HALF_UP)


def low_yield_threshold() -> Decimal:
    """Düşük verim eşiği (%), `PRODUCTION_LOW_YIELD_THRESHOLD_PCT` ayarı (varsayılan 97)."""
    return Decimal(str(getattr(settings, "PRODUCTION_LOW_YIELD_THRESHOLD_PCT", "97")))


def order_ref(order: ProductionOrder) -> dict[str, Any]:
    """Olay payload'ındaki emir sözlüğü."""
    return {"model": order._meta.label_lower, "id": order.pk, "number": order.number}


def _lock_order(order: ProductionOrder) -> ProductionOrder:
    return (
        ProductionOrder.objects.select_for_update(of=("self",))
        .select_related(
            "product__base_unit",
            "unit",
            "equipment__location",
            "production_location",
            "recipe_version",
        )
        .get(pk=order.pk)
    )


def _lock_batch(batch: ProductionBatch) -> ProductionBatch:
    return (
        ProductionBatch.objects.select_for_update(of=("self",))
        .select_related("order", "output_lot__material__base_unit", "equipment__location")
        .get(pk=batch.pk)
    )


def _require_status(order: ProductionOrder, allowed: Sequence[str], code: str, what: str) -> None:
    if order.status not in allowed:
        raise BusinessRuleError(
            code,
            f"{order.number} {production_order_states.label(order.status).lower()} durumda; "
            f"{what}.",
        )


# --- emir ------------------------------------------------------------------------------------


def default_production_location(equipment: Equipment) -> Location | None:
    """Tankın deposundaki ilk aktif üretim (`PRODUCTION`) lokasyonu."""
    if equipment.location is None:
        return None
    return (
        Location.objects.filter(
            warehouse_id=equipment.location.warehouse_id,
            location_type=Location.Type.PRODUCTION,
            is_active=True,
        )
        .order_by("code")
        .first()
    )


def _validate_equipment(equipment: Equipment) -> None:
    if not equipment.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif tank seçilemez: {equipment}.")
    if equipment.equipment_type != Equipment.Type.MIXING_TANK or equipment.location is None:
        raise BusinessRuleError(
            "invalid_equipment", f"{equipment.code} lokasyonu tanımlı bir karıştırma tankı değil."
        )


def _validate_version(version: RecipeVersion) -> None:
    if version.status != RecipeVersion.Status.APPROVED:
        raise BusinessRuleError(
            "recipe_version_not_approved",
            f"{version} onaylı değil; üretim emri yalnızca onaylı reçete sürümüyle açılır.",
        )
    if not version.recipe.is_active:
        raise BusinessRuleError("inactive_reference", "Pasif reçeteyle üretim emri açılamaz.")
    product = version.recipe.product
    if product.material_type != Material.Type.BULK or not product.is_active:
        raise BusinessRuleError(
            "invalid_product", f"{product.code} aktif bir dökme (bulk) ürün değil."
        )


def _prepare_order(order: ProductionOrder) -> None:
    """Emir alanlarını doğrular; ürünü, temel birim miktarını ve üretim lokasyonunu doldurur."""
    version = RecipeVersion.objects.select_related("recipe__product__base_unit").get(
        pk=order.recipe_version_id
    )
    _validate_version(version)
    order.product = version.recipe.product
    _validate_equipment(order.equipment)
    if order.production_location_id is None:
        location = default_production_location(order.equipment)
        if location is None:
            raise BusinessRuleError(
                "production_location_required",
                "Tankın deposunda üretim lokasyonu yok; üretim lokasyonu seçilmelidir.",
            )
        order.production_location = location
    location = order.production_location
    if location.location_type != Location.Type.PRODUCTION or not location.is_active:
        raise BusinessRuleError(
            "invalid_production_location", "Üretim lokasyonu aktif ve “Üretim” türünde olmalıdır."
        )
    if order.planned_quantity is None or order.planned_quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Planlanan miktar sıfırdan büyük olmalıdır.")
    if order.priority not in ProductionOrder.Priority.values:
        raise BusinessRuleError("invalid_priority", "Öncelik 1 ile 4 arasında olmalıdır.")
    base = quantize(masterdata.to_base_quantity(order.product, order.planned_quantity, order.unit))
    if base <= 0:
        raise BusinessRuleError(
            "quantity_too_small", "Planlanan miktar temel birimde sıfıra iniyor."
        )
    order.planned_base_quantity = base


@transaction.atomic
def create_order(actor: User | None, data: Mapping[str, Any]) -> ProductionOrder:
    """Taslak üretim emri açar (`UE-`, rol: planlama). Reçete sürümü onaylı olmalıdır ve emre
    sabitlenir; ürün sürümün ürünüdür. Üretim lokasyonu verilmezse tankın deposundaki üretim
    lokasyonu seçilir."""
    _require_role(actor, ORDER_ROLES, "Üretim emrini yalnızca planlama açar.")
    order = ProductionOrder(**_pick_fields(data, ORDER_FIELDS))
    _prepare_order(order)
    return create_document(order, actor, prefix="UE", machine=production_order_states)


@transaction.atomic
def update_order(
    actor: User | None, order: ProductionOrder, data: Mapping[str, Any]
) -> ProductionOrder:
    """Taslak emri günceller (rol: planlama). Onaylanan emir değiştirilmez."""
    _require_role(actor, ORDER_ROLES, "Üretim emrini yalnızca planlama değiştirir.")
    values = _pick_fields(data, ORDER_FIELDS)
    order = _lock_order(order)
    _require_status(order, (Status.DRAFT,), "document_locked", "değiştirilemez")
    if "equipment" in values and "production_location" not in values:
        # Tank değişince üretim lokasyonu yeniden seçilir.
        order.production_location = None  # type: ignore[assignment]
    for name, value in values.items():
        setattr(order, name, value)
    _prepare_order(order)
    return save_with_audit(order, actor)


@transaction.atomic
def approve_order(actor: User | None, order: ProductionOrder, note: str = "") -> ProductionOrder:
    """Emri onaylar (rol: planlama): reçete sürümü planlanan miktara ölçeklenir ve ihtiyaç listesi
    oluşur. Olay `production_order.approved` depoya "Malzeme hazırla" görevi açar."""
    _require_role(actor, ORDER_ROLES, "Üretim emrini yalnızca planlama onaylar.")
    actor = _actor(actor)
    order = _lock_order(order)
    production_order_states.assert_can_transition(order.status, Status.APPROVED)
    _prepare_order(order)
    scaled = recipes.scale_requirements(order.recipe_version, order.planned_quantity, order.unit)
    for item in scaled:
        if item.quantity <= 0:
            raise BusinessRuleError(
                "quantity_too_small",
                f"{item.material.code} ihtiyacı bu miktarda sıfıra iniyor; planlanan miktarı "
                "artırın.",
            )
        save_with_audit(
            ProductionRequirement(
                order=order,
                recipe_line=item.line,
                material=item.material,
                required_quantity=item.quantity,
                tolerance_pct=item.tolerance_pct,
                sequence=item.sequence,
                is_water=item.is_water,
                instruction=item.line.instruction,
            ),
            actor,
        )
    order.approved_by = actor
    order.approved_at = timezone.now()
    order.save(update_fields=["approved_by", "approved_at", "planned_base_quantity", "product"])
    return transition_status(
        order,
        Status.APPROVED,
        actor,
        machine=production_order_states,
        note=note,
        event_payload={"priority": order.priority},
    )


@transaction.atomic
def start_material_prep(actor: User | None, order: ProductionOrder) -> ProductionOrder:
    """Depo hazırlığa başlar (rol: depo). İlk hazırlama da hazırlığı kendiliğinden başlatır."""
    _require_role(actor, PREP_ROLES, "Malzeme hazırlığını yalnızca depo başlatır.")
    order = _lock_order(order)
    return transition_status(order, Status.MATERIAL_PREP, actor, machine=production_order_states)


def picked_quantity(requirement: ProductionRequirement) -> Decimal:
    """İhtiyaç için hazırlanmış (iade edilmemiş) toplam miktar."""
    total = requirement.picks.filter(returned_at__isnull=True).aggregate(t=Sum("quantity"))["t"]
    return total or Decimal(0)


def _pick_source(
    lot: Lot, quantity: Decimal, exclude: Location, from_location: Location | None
) -> Location:
    if from_location is not None:
        if from_location.pk == exclude.pk:
            raise BusinessRuleError(
                "same_location", "Malzeme zaten üretim lokasyonunda; başka lokasyondan hazırlanır."
            )
        return from_location
    balances = list(
        StockBalance.objects.filter(lot=lot, quantity__gt=0)
        .exclude(location=exclude)
        .exclude(location__location_type=Location.Type.QUARANTINE)
        .select_related("location")
        .order_by("-quantity", "location__code")
    )
    if not balances:
        raise BusinessRuleError(
            "lot_not_in_stock", f"Lot {lot.lot_no} için hazırlanacak stok bulunamadı."
        )
    enough = [b for b in balances if b.quantity >= quantity]
    # Yeterli stok tek lokasyondaysa orası; değilse en çok stoklu lokasyon (yetersizse
    # post_movement negatif stok hatası verir).
    return (enough or balances)[0].location


@transaction.atomic
def pick_material(
    actor: User | None,
    order: ProductionOrder,
    requirement: ProductionRequirement,
    lot: Lot,
    quantity: Decimal,
    from_location: Location | None = None,
    note: str = "",
) -> MaterialPick:
    """Depo ihtiyaç için lot hazırlar (rol: depo): stok kaynak lokasyondan emrin üretim
    lokasyonuna transfer edilir.

    Yalnızca serbest ve SKT'si geçmemiş lot seçilir; lot ihtiyacın malzemesinden olmalıdır.
    Kaynak verilmezse lotun karantina dışı, yeterli stoklu lokasyonu seçilir. Hazırlanan toplam
    ihtiyacın iki katını geçemez. Şebeke suyu hazırlanmaz (tartımda kendi lokasyonundan düşülür).
    """
    _require_role(actor, PREP_ROLES, "Malzemeyi yalnızca depo hazırlar.")
    actor = _actor(actor)
    order = _lock_order(order)
    _require_status(order, PICKABLE_STATUSES, "order_not_pickable", "malzeme hazırlanamaz")
    requirement = ProductionRequirement.objects.select_for_update(of=("self",)).get(
        pk=requirement.pk
    )
    if requirement.order_id != order.pk:
        raise BusinessRuleError("requirement_not_in_order", "İhtiyaç satırı bu emre ait değil.")
    if requirement.is_water:
        raise BusinessRuleError(
            "water_not_picked", "Şebeke suyu hazırlanmaz; tartımda doğrudan düşülür."
        )
    lot = Lot.objects.select_related("material__base_unit").get(pk=lot.pk)
    if lot.material_id != requirement.material_id:
        raise BusinessRuleError(
            "lot_material_mismatch",
            f"Lot {lot.lot_no} {lot.material.code} malzemesine ait; bu satır "
            f"{requirement.material.code} istiyor.",
        )
    inventory.assert_lot_usable(lot)
    quantity = quantize(quantity)
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    limit = requirement.required_quantity * MAX_PICK_FACTOR
    if picked_quantity(requirement) + quantity > limit:
        unit = requirement.material.base_unit.code
        raise BusinessRuleError(
            "pick_exceeds_requirement",
            f"{requirement.material.code} için en çok {format_quantity(limit)} {unit} "
            "hazırlanabilir (ihtiyacın iki katı).",
        )
    source = _pick_source(lot, quantity, order.production_location, from_location)
    if order.status == Status.APPROVED:
        order = transition_status(
            order, Status.MATERIAL_PREP, actor, machine=production_order_states
        )
    out, _into = inventory.transfer(
        actor,
        lot,
        source,
        order.production_location,
        quantity,
        source=order,
        note=note or f"Hazırlama {order.number}",
    )
    assert out.transfer_group is not None
    return save_with_audit(
        MaterialPick(
            order=order,
            requirement=requirement,
            lot=lot,
            quantity=quantity,
            from_location=source,
            to_location=order.production_location,
            picked_by=actor,
            picked_at=timezone.now(),
            transfer_group=out.transfer_group,
        ),
        actor,
    )


def missing_materials(order: ProductionOrder) -> list[ProductionRequirement]:
    """Hazırlanan miktarı toleransın alt sınırına ulaşmayan (su dışı) ihtiyaçlar."""
    missing = []
    for requirement in order.requirements.select_related("material").order_by("sequence"):
        if requirement.is_water:
            continue
        lower = requirement.required_quantity * (1 - requirement.tolerance_pct / HUNDRED)
        if picked_quantity(requirement) < lower:
            missing.append(requirement)
    return missing


@transaction.atomic
def mark_material_ready(actor: User | None, order: ProductionOrder) -> ProductionOrder:
    """Malzeme hazır (rol: depo). Su dışındaki her ihtiyaç en az toleransın alt sınırı kadar
    hazırlanmış olmalıdır. Olay `production_order.material_ready` üretime "Şarjı başlat" görevi
    açar ve depo görevini kapatır."""
    _require_role(actor, PREP_ROLES, "Malzeme hazır bilgisini yalnızca depo verir.")
    order = _lock_order(order)
    if order.status == Status.APPROVED:
        # Yalnızca su gibi hazırlanmayan satırlar varsa hazırlık doğrudan tamamlanır.
        order = transition_status(
            order, Status.MATERIAL_PREP, actor, machine=production_order_states
        )
    production_order_states.assert_can_transition(order.status, Status.MATERIAL_READY)
    missing = missing_materials(order)
    if missing:
        codes = ", ".join(r.material.code for r in missing)
        raise BusinessRuleError("material_not_ready", f"Hazırlanmamış malzeme var: {codes}.")
    return transition_status(order, Status.MATERIAL_READY, actor, machine=production_order_states)


@transaction.atomic
def cancel_order(actor: User | None, order: ProductionOrder, reason: str) -> ProductionOrder:
    """Emri iptal eder (rol: planlama; taslak, onaylı ya da hazırlıktaki emir). Hazırlanan
    malzeme geldiği lokasyonlara geri transfer edilir. Olay `production_order.cancelled` emre bağlı
    açık görevleri iptal eder."""
    _require_role(actor, ORDER_ROLES, "Üretim emrini yalnızca planlama iptal eder.")
    actor = _actor(actor)
    order = _lock_order(order)
    production_order_states.assert_can_transition(order.status, Status.CANCELLED)
    if not reason.strip():
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    now = timezone.now()
    for pick in order.picks.filter(returned_at__isnull=True).select_related(
        "lot", "from_location", "to_location"
    ):
        inventory.transfer(
            actor,
            pick.lot,
            pick.to_location,
            pick.from_location,
            pick.quantity,
            source=order,
            note=f"İptal iadesi {order.number}",
        )
        pick.returned_at = now
        save_with_audit(pick, actor, note="Emir iptali: malzeme geri transfer edildi")
    return cancel_document(order, actor, reason=reason, machine=production_order_states)


# --- şarj ------------------------------------------------------------------------------------


def batched_quantity(order: ProductionOrder) -> Decimal:
    """İptal edilmemiş şarjlara dağıtılmış toplam miktar (ürünün temel biriminde)."""
    total = order.batches.exclude(status=BatchStatus.CANCELLED).aggregate(
        t=Sum("planned_quantity")
    )["t"] or Decimal(0)
    return Decimal(total)


def remaining_quantity(order: ProductionOrder) -> Decimal:
    """Henüz şarja dağıtılmamış miktar."""
    return max(order.planned_base_quantity - batched_quantity(order), Decimal(0))


def equipment_capacity(equipment: Equipment, product: Material) -> Decimal | None:
    """Tank kapasitesi ürünün temel biriminde (kapasite tanımsızsa None)."""
    if equipment.capacity is None or equipment.capacity_unit is None:
        return None
    return quantize(
        masterdata.convert_quantity(
            product, equipment.capacity, equipment.capacity_unit, product.base_unit
        )
    )


def suggested_batch_quantity(order: ProductionOrder, equipment: Equipment | None = None) -> Decimal:
    """Sıradaki şarj için önerilen miktar: kalan miktar ile tank kapasitesinden küçüğü."""
    remaining = remaining_quantity(order)
    capacity = equipment_capacity(equipment or order.equipment, order.product)
    return min(remaining, capacity) if capacity is not None else remaining


def batch_line_quantity(requirement: ProductionRequirement, batch: ProductionBatch) -> Decimal:
    """İhtiyacın bu şarja düşen payı: ihtiyaç × şarj miktarı / emir miktarı."""
    order = batch.order
    return quantize(
        requirement.required_quantity * batch.planned_quantity / order.planned_base_quantity
    )


def batch_payload(batch: ProductionBatch, **extra: Any) -> dict[str, Any]:
    return {
        "model": batch._meta.label_lower,
        "id": batch.pk,
        "batch_no": batch.batch_no,
        "order": order_ref(batch.order),
        **extra,
    }


def _set_batch_status(
    actor: User | None, batch: ProductionBatch, to_status: str, note: str = ""
) -> None:
    production_batch_states.assert_can_transition(batch.status, to_status)
    from_status = batch.status
    batch.status = to_status
    batch.updated_by = actor
    batch.save()
    log_change(
        actor, batch, AuditLog.Action.STATUS_CHANGE, {"status": [from_status, to_status]}, note
    )


@transaction.atomic
def start_batch(
    actor: User | None,
    order: ProductionOrder,
    equipment: Equipment | None = None,
    planned_quantity: Decimal | None = None,
) -> ProductionBatch:
    """Şarjı başlatır (rol: uretim). Çıktı lotu `B-YYMMDD-NNN` numarasıyla karantinada açılır.

    Şarj miktarı verilmezse kalan miktar ile tank kapasitesinden küçüğüdür; kalanı ya da tank
    kapasitesini aşan şarj reddedilir (Karar D-4). Tankta devam eden şarj varsa yeni şarj
    başlatılamaz. İlk şarjla emir "Üretimde" olur. Olay `production_batch.started`.
    """
    _require_role(actor, PRODUCTION_ROLES, "Şarjı yalnızca üretim başlatır.")
    actor = _actor(actor)
    order = _lock_order(order)
    _require_status(order, BATCHABLE_STATUSES, "order_not_ready", "şarj başlatılamaz")
    equipment = equipment or order.equipment
    equipment = Equipment.objects.select_related("location", "capacity_unit").get(pk=equipment.pk)
    _validate_equipment(equipment)
    if ProductionBatch.objects.filter(equipment=equipment, status=BatchStatus.IN_PROGRESS).exists():
        raise BusinessRuleError(
            "equipment_busy", f"{equipment.code} tankında devam eden bir şarj var."
        )
    remaining = remaining_quantity(order)
    if remaining <= 0:
        raise BusinessRuleError(
            "order_fully_batched", "Emrin tüm miktarı şarjlara dağıtıldı; yeni şarj açılamaz."
        )
    capacity = equipment_capacity(equipment, order.product)
    unit = order.product.base_unit.code
    if planned_quantity is None:
        planned_quantity = min(remaining, capacity) if capacity is not None else remaining
    planned_quantity = quantize(planned_quantity)
    if planned_quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Şarj miktarı sıfırdan büyük olmalıdır.")
    if planned_quantity > remaining:
        raise BusinessRuleError(
            "batch_exceeds_order",
            f"Şarj miktarı emirde kalan miktarı ({format_quantity(remaining)} {unit}) aşıyor.",
        )
    if capacity is not None and planned_quantity > capacity:
        raise BusinessRuleError(
            "batch_exceeds_capacity",
            f"Şarj miktarı {equipment.code} kapasitesini ({format_quantity(capacity)} {unit}) "
            "aşıyor; emri birden çok şarja bölün.",
        )
    today = timezone.localdate()
    output_lot = inventory.create_lot(
        actor,
        material=order.product,
        source=Lot.Source.PRODUCTION,
        status=Lot.Status.QUARANTINE,
        manufactured_at=today,
        day=today,
        note=f"Üretim emri {order.number}",
    )
    batch = save_with_audit(
        ProductionBatch(
            order=order,
            sequence=order.batches.count() + 1,
            batch_no=output_lot.lot_no,
            equipment=equipment,
            planned_quantity=planned_quantity,
            output_lot=output_lot,
            started_at=timezone.now(),
            started_by=actor,
        ),
        actor,
    )
    if order.status == Status.MATERIAL_READY:
        transition_status(order, Status.IN_PRODUCTION, actor, machine=production_order_states)
    events.publish(ev.PRODUCTION_BATCH_STARTED, batch_payload(batch), actor)
    return batch


def consumed_quantity(batch: ProductionBatch, requirement: ProductionRequirement) -> Decimal:
    """Şarjda ihtiyaç satırı için tartılan toplam."""
    total = batch.consumptions.filter(requirement=requirement).aggregate(t=Sum("actual_quantity"))[
        "t"
    ]
    return total or Decimal(0)


def deviation_pct(planned: Decimal, actual: Decimal) -> Decimal:
    """Plana göre sapma yüzdesi (işaretli, 2 ondalık)."""
    if planned == 0:
        return Decimal(0)
    return _pct((actual - planned) / planned * HUNDRED)


def _consumption_location(
    order: ProductionOrder, requirement: ProductionRequirement, lot: Lot, quantity: Decimal
) -> Location:
    if not requirement.is_water:
        return order.production_location
    # Su (D-1): hazırlanmaz, stoklu olduğu lokasyondan düşülür.
    balances = list(
        StockBalance.objects.filter(lot=lot, quantity__gt=0)
        .exclude(location__location_type=Location.Type.QUARANTINE)
        .select_related("location")
        .order_by("-quantity", "location__code")
    )
    if not balances:
        raise BusinessRuleError("lot_not_in_stock", f"Lot {lot.lot_no} stokta yok.")
    enough = [b for b in balances if b.quantity >= quantity]
    return (enough or balances)[0].location


@dataclass(frozen=True)
class _Deviation:
    requirement: ProductionRequirement
    planned: Decimal
    actual: Decimal
    pct: Decimal
    lot_no: str


def _publish_deviation(
    actor: User | None, batch: ProductionBatch, deviation: _Deviation, note: str
) -> None:
    unit = deviation.requirement.material.base_unit.code
    events.publish(
        ev.PRODUCTION_DEVIATION,
        {
            "model": batch._meta.label_lower,
            "id": batch.pk,
            "batch_no": batch.batch_no,
            "order_number": batch.order.number,
            "order": order_ref(batch.order),
            "material_code": deviation.requirement.material.code,
            "lot_no": deviation.lot_no,
            "planned_quantity": f"{format_quantity(deviation.planned)} {unit}",
            "actual_quantity": f"{format_quantity(deviation.actual)} {unit}",
            "deviation_pct": format_quantity(deviation.pct),
            "note": note,
        },
        actor,
    )


@transaction.atomic
def record_consumption(
    actor: User | None,
    batch: ProductionBatch,
    requirement: ProductionRequirement,
    lot: Lot,
    actual_quantity: Decimal,
    note: str = "",
) -> BatchConsumption:
    """Tartım kaydı (rol: uretim): girdi lottan `ISSUE_PRODUCTION` hareketi ve girdi lot → çıktı
    lot soy ağacı bağı yazar.

    Lot ihtiyacın malzemesinden, serbest ve SKT'si geçmemiş olmalıdır; su dışındaki malzeme emrin
    üretim lokasyonundan tüketilir. Negatif stoka düşürecek tartım reddedilir. Bir satır birden
    çok lottan tartılabilir; satırın toplamı toleransın üstüne çıkarsa sapma notu zorunludur ve
    `production.deviation` olayı yayınlanır.
    """
    _require_role(actor, PRODUCTION_ROLES, "Tartımı yalnızca üretim kaydeder.")
    actor = _actor(actor)
    batch = _lock_batch(batch)
    if batch.status != BatchStatus.IN_PROGRESS:
        raise BusinessRuleError("batch_not_in_progress", f"Şarj {batch.batch_no} devam etmiyor.")
    order = _lock_order(batch.order)
    batch.order = order
    requirement = ProductionRequirement.objects.select_related("material__base_unit").get(
        pk=requirement.pk
    )
    if requirement.order_id != order.pk:
        raise BusinessRuleError("requirement_not_in_order", "İhtiyaç satırı bu emre ait değil.")
    lot = Lot.objects.select_related("material").get(pk=lot.pk)
    if lot.material_id != requirement.material_id:
        raise BusinessRuleError(
            "lot_material_mismatch",
            f"Lot {lot.lot_no} {lot.material.code} malzemesine ait; bu satır "
            f"{requirement.material.code} istiyor.",
        )
    actual_quantity = quantize(actual_quantity)
    if actual_quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Tartılan miktar sıfırdan büyük olmalıdır.")
    note = note.strip()
    planned = batch_line_quantity(requirement, batch)
    cumulative = consumed_quantity(batch, requirement) + actual_quantity
    pct = deviation_pct(planned, cumulative)
    over = pct > requirement.tolerance_pct
    if over and not note:
        raise BusinessRuleError(
            "deviation_note_required",
            f"{requirement.material.code} tolerans dışında (%{format_quantity(pct)}); sapma "
            "notu girilmelidir.",
        )
    location = _consumption_location(order, requirement, lot, actual_quantity)
    movement = inventory.post_movement(
        actor,
        requirement.material,
        lot,
        location,
        -actual_quantity,
        MovementType.ISSUE_PRODUCTION,
        order,
        f"Şarj {batch.batch_no}",
    )
    link = inventory.link_lots(actor, lot, batch.output_lot, actual_quantity, source=batch)
    consumption = save_with_audit(
        BatchConsumption(
            batch=batch,
            requirement=requirement,
            lot=lot,
            location=location,
            planned_quantity=planned,
            actual_quantity=actual_quantity,
            weighed_by=actor,
            weighed_at=timezone.now(),
            deviation_pct=pct,
            deviation_note=note,
            movement=movement,
            lot_link=link,
        ),
        actor,
    )
    if over:
        _publish_deviation(
            actor, batch, _Deviation(requirement, planned, cumulative, pct, lot.lot_no), note
        )
    return consumption


def under_tolerance_lines(batch: ProductionBatch) -> list[_Deviation]:
    """Şarjda toleransın altında kalan (hiç tartılmamış dahil) ihtiyaç satırları."""
    result = []
    for requirement in batch.order.requirements.select_related("material__base_unit").order_by(
        "sequence"
    ):
        planned = batch_line_quantity(requirement, batch)
        actual = consumed_quantity(batch, requirement)
        pct = deviation_pct(planned, actual)
        if pct < -requirement.tolerance_pct:
            lots = batch.consumptions.filter(requirement=requirement).values_list(
                "lot__lot_no", flat=True
            )
            result.append(_Deviation(requirement, planned, actual, pct, ", ".join(lots)))
    return result


def _maybe_await_qc(actor: User | None, order: ProductionOrder) -> None:
    """Tüm miktar şarjlara dağıtıldıysa ve açık şarj kalmadıysa emir analiz bekler."""
    if order.status != Status.IN_PRODUCTION:
        return
    if remaining_quantity(order) > 0:
        return
    if order.batches.filter(status=BatchStatus.IN_PROGRESS).exists():
        return
    if not order.batches.filter(status=BatchStatus.COMPLETED).exists():
        return
    transition_status(order, Status.QC_PENDING, actor, machine=production_order_states)


@transaction.atomic
def finish_batch(
    actor: User | None, batch: ProductionBatch, output_quantity: Decimal, note: str = ""
) -> ProductionBatch:
    """Şarjı bitirir (rol: uretim): çıktı miktarı `PRODUCTION_OUTPUT` ile tank lokasyonuna girer
    (lot karantinada kalır, kararı laboratuvar verir). Olay `production_batch.completed`
    laboratuvara "Numune analizi" görevi açar.

    Toleransın altında kalan satır varsa not zorunludur ve her satır için `production.deviation`
    yayınlanır. Verim = çıktı / şarj miktarı; eşiğin altındaysa `production.low_yield`. Emrin tüm
    miktarı şarjlara dağıtılıp açık şarj kalmadıysa emir "Analiz bekliyor" olur.
    """
    _require_role(actor, PRODUCTION_ROLES, "Şarjı yalnızca üretim bitirir.")
    actor = _actor(actor)
    batch = _lock_batch(batch)
    production_batch_states.assert_can_transition(batch.status, BatchStatus.COMPLETED)
    order = _lock_order(batch.order)
    batch.order = order
    if not batch.consumptions.exists():
        raise BusinessRuleError("batch_has_no_consumption", "Tartım yapılmamış şarj bitirilemez.")
    output_quantity = quantize(output_quantity)
    if output_quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Çıktı miktarı sıfırdan büyük olmalıdır.")
    note = note.strip()
    short = under_tolerance_lines(batch)
    if short and not note:
        codes = ", ".join(d.requirement.material.code for d in short)
        raise BusinessRuleError(
            "deviation_note_required",
            f"Toleransın altında tartılan satırlar var ({codes}); bitiş notu girilmelidir.",
        )
    assert batch.equipment.location is not None
    movement = inventory.post_movement(
        actor,
        order.product,
        batch.output_lot,
        batch.equipment.location,
        output_quantity,
        MovementType.PRODUCTION_OUTPUT,
        order,
        f"Şarj {batch.batch_no}",
    )
    yield_pct = _pct(output_quantity / batch.planned_quantity * HUNDRED)
    batch.actual_output_quantity = output_quantity
    batch.yield_pct = yield_pct
    batch.output_movement = movement
    batch.finished_at = timezone.now()
    batch.finished_by = actor
    batch.finish_note = note
    _set_batch_status(actor, batch, BatchStatus.COMPLETED, note)
    for deviation in short:
        _publish_deviation(actor, batch, deviation, note)
    lot = batch.output_lot
    events.publish(
        ev.PRODUCTION_BATCH_COMPLETED,
        batch_payload(
            batch,
            output_lot=lot_payload(lot),
            output_quantity=format_quantity(output_quantity),
            yield_pct=format_quantity(yield_pct),
        ),
        actor,
    )
    threshold = low_yield_threshold()
    if yield_pct < threshold:
        events.publish(
            ev.PRODUCTION_LOW_YIELD,
            {
                "model": batch._meta.label_lower,
                "id": batch.pk,
                "batch_no": batch.batch_no,
                "order_number": order.number,
                "order": order_ref(order),
                "yield_pct": format_quantity(yield_pct),
                "threshold_pct": format_quantity(threshold),
            },
            actor,
        )
    _maybe_await_qc(actor, order)
    return batch


@transaction.atomic
def cancel_batch(actor: User | None, batch: ProductionBatch, reason: str) -> ProductionBatch:
    """Yanlış başlatılan şarjı iptal eder (rol: uretim; yalnızca tartım yapılmamışsa). Çıktı
    lotu stoksuz olarak karantinada kalır; şarjın miktarı emre geri döner."""
    _require_role(actor, PRODUCTION_ROLES, "Şarjı yalnızca üretim iptal eder.")
    actor = _actor(actor)
    reason = reason.strip()
    if not reason:
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    batch = _lock_batch(batch)
    production_batch_states.assert_can_transition(batch.status, BatchStatus.CANCELLED)
    if batch.consumptions.exists():
        raise BusinessRuleError(
            "batch_has_consumption", "Tartım yapılmış şarj iptal edilemez; şarjı bitirin."
        )
    batch.cancel_reason = reason
    _set_batch_status(actor, batch, BatchStatus.CANCELLED, reason)
    return batch


# --- emir kapanışı ---------------------------------------------------------------------------


def unreleased_output_lots(order: ProductionOrder) -> list[Lot]:
    """Tamamlanan şarjların serbest bırakılmamış çıktı lotları."""
    return [
        batch.output_lot
        for batch in order.batches.filter(status=BatchStatus.COMPLETED).select_related("output_lot")
        if batch.output_lot.status != Lot.Status.RELEASED
    ]


@transaction.atomic
def complete_order(actor: User | None, order: ProductionOrder) -> ProductionOrder:
    """Emri tamamlar: tüm şarjların çıktı lotları serbest bırakılmış olmalıdır. Laboratuvar son
    lotu serbest bırakınca kendiliğinden çağrılır (`handlers.py`)."""
    actor = _actor(actor)
    order = _lock_order(order)
    production_order_states.assert_can_transition(order.status, Status.COMPLETED)
    waiting = unreleased_output_lots(order)
    if waiting:
        lots = ", ".join(lot.lot_no for lot in waiting)
        raise BusinessRuleError(
            "output_lots_not_released", f"Serbest bırakılmamış çıktı lotları var: {lots}."
        )
    order.completed_at = timezone.now()
    order.save(update_fields=["completed_at"])
    return transition_status(order, Status.COMPLETED, actor, machine=production_order_states)
