"""Dolum servisleri: ambalaj reçetesi, dolum emri, ambalaj hazırlama, dolum partisi, tüketim,
fire ve emir kapanışı (Faz 2, Adım 2.2).

Kurallar:
- Stok yalnızca `inventory.services` ile hareket eder (CLAUDE.md §3). Ambalaj hazırlama `transfer`
  (ortak hazırlama servisi `inventory.picking`), bulk ve ambalaj tüketimi `ISSUE_PRODUCTION`, mamul
  girişi `PRODUCTION_OUTPUT`, fire `SCRAP` hareketidir. Her tüketim soy ağacına girdi lot → dolum
  lotu bağı yazar (`link_lots`).
- Yalnızca serbest ve SKT'si geçmemiş bulk ve ambalaj lotu tüketilir (kural 4). Bulk depoda
  hazırlanmaz; tank lotu bulunduğu (karantina dışı) lokasyondan tüketilir.
- Dolum lotu `D-YYMMDD-NNN` (D-2) karantinada açılır; parti bitince son kontrol (`FINAL`) numunesi
  açılır ve lot yalnızca kalite kararıyla serbest kalır.
- Ambalaj tüketimi bitişte hesaplanır: (sağlam + mamul firesi) × adet başına miktar; adet birimli
  malzemede yukarı yuvarlanır. Önce partiye okutulan lotlardan (okutma sırasıyla), sonra hat
  başındaki diğer serbest lotlardan (SKT sırasıyla) düşülür.
- Teorik bulk = sağlam adet × dolum miktarı (bulkun temel birimine çevrilir); gerçek = partiye
  tüketilen bulk + bulk firesi. Fark `FILL_VARIANCE_THRESHOLD_PCT` eşiğini aşarsa
  `filling.bulk_variance` yayınlanır.
"""

from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F, Max, Q, Sum
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.audit import log_change, snapshot
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import DEPO, DOLUM, PLANLAMA
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.filling.models import (
    ConsumptionKind,
    FillingConsumption,
    FillingOrder,
    FillingRequirement,
    FillingRun,
    PackagingPick,
    PackagingSpec,
    PackagingSpecLine,
    RunLot,
    ScrapRecord,
)
from apps.filling.state import filling_order_states, filling_run_states, packaging_spec_states
from apps.inventory import picking
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockBalance, StockMovement
from apps.inventory.services import format_quantity, lot_payload, quantize
from apps.masterdata import services as masterdata
from apps.masterdata.models import Equipment, Location, Material, UnitOfMeasure
from apps.quality import services as quality
from apps.quality.models import Sample, SampleStage

SPEC_ROLES = (PLANLAMA,)
ORDER_ROLES = (PLANLAMA,)
PREP_ROLES = (DEPO,)
FILLING_ROLES = (DOLUM,)

Status = FillingOrder.Status
RunStatus = FillingRun.Status
SpecStatus = PackagingSpec.Status
ScrapKind = ScrapRecord.Kind
MovementType = StockMovement.Type

SPEC_FIELDS = (
    "finished_product",
    "bulk_product",
    "fill_quantity",
    "fill_unit",
    "fill_tolerance_pct",
    "units_per_case",
    "cases_per_pallet",
    "change_note",
)
LINE_FIELDS = ("sequence", "material", "quantity_per_unit", "scrap_allowance_pct")
ORDER_FIELDS = (
    "finished_product",
    "planned_units",
    "filling_line",
    "output_location",
    "planned_date",
    "notes",
)
PICKABLE_STATUSES = (
    Status.APPROVED,
    Status.MATERIAL_PREP,
    Status.MATERIAL_READY,
    Status.IN_PROGRESS,
)
RUNNABLE_STATUSES = (Status.MATERIAL_READY, Status.IN_PROGRESS)
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


def variance_threshold() -> Decimal:
    """Bulk dolum farkı eşiği (%), `FILL_VARIANCE_THRESHOLD_PCT` ayarı (varsayılan 1,5)."""
    return Decimal(str(getattr(settings, "FILL_VARIANCE_THRESHOLD_PCT", "1.5")))


def is_count_unit(material: Material) -> bool:
    """Malzemenin temel birimi adet türünde mi (şişe, kapak, koli)? Bu malzemelerde miktar tam
    sayıya yukarı yuvarlanır."""
    return material.base_unit.kind == UnitOfMeasure.Kind.COUNT


def round_for(material: Material, quantity: Decimal) -> Decimal:
    """Miktarı 4 ondalığa, adet birimli malzemede tam sayıya yukarı yuvarlar."""
    quantity = quantize(quantity)
    if is_count_unit(material):
        return quantity.to_integral_value(rounding=ROUND_CEILING)
    return quantity


def order_ref(order: FillingOrder) -> dict[str, Any]:
    """Olay payload'ındaki emir sözlüğü."""
    return {"model": order._meta.label_lower, "id": order.pk, "number": order.number}


# --- ambalaj reçetesi ------------------------------------------------------------------------


def _lock_spec(spec: PackagingSpec) -> PackagingSpec:
    return (
        PackagingSpec.objects.select_for_update(of=("self",))
        .select_related("finished_product__base_unit", "bulk_product__base_unit", "fill_unit")
        .get(pk=spec.pk)
    )


def _require_spec_draft(spec: PackagingSpec) -> None:
    if spec.status != SpecStatus.DRAFT:
        raise BusinessRuleError(
            "packaging_spec_locked",
            f"{spec} {packaging_spec_states.label(spec.status).lower()}; değiştirilemez. "
            "Değişiklik için sürümü kopyalayın.",
        )


def _validate_spec(spec: PackagingSpec) -> None:
    finished, bulk = spec.finished_product, spec.bulk_product
    if finished.material_type != Material.Type.FINISHED:
        raise BusinessRuleError("invalid_product", f"{finished.code} bir mamul değil.")
    if bulk.material_type != Material.Type.BULK:
        raise BusinessRuleError("invalid_bulk", f"{bulk.code} bir dökme (bulk) ürün değil.")
    for material in (finished, bulk):
        if not material.is_active:
            raise BusinessRuleError("inactive_reference", f"Pasif malzeme seçilemez: {material}.")
    if not is_count_unit(finished):
        raise BusinessRuleError(
            "finished_unit_not_count",
            f"{finished.code} mamulünün temel birimi adet türünde olmalıdır (ör. ADET).",
        )
    if spec.fill_quantity is None or spec.fill_quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Dolum miktarı sıfırdan büyük olmalıdır.")
    if spec.fill_tolerance_pct is not None and spec.fill_tolerance_pct < 0:
        raise BusinessRuleError("invalid_tolerance", "Dolum toleransı negatif olamaz.")
    if not spec.units_per_case or spec.units_per_case <= 0:
        raise BusinessRuleError("invalid_quantity", "Koli içi adet sıfırdan büyük olmalıdır.")
    # Dolum birimi bulkun temel birimine çevrilebilmeli (ör. ML → KG için yoğunluk).
    masterdata.to_base_quantity(bulk, spec.fill_quantity, spec.fill_unit)


def _validate_spec_line(line: PackagingSpecLine) -> None:
    material = line.material
    if material.material_type != Material.Type.PACKAGING:
        raise BusinessRuleError(
            "invalid_packaging_material", f"{material.code} bir ambalaj malzemesi değil."
        )
    if not material.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif malzeme seçilemez: {material}.")
    if line.quantity_per_unit is None or line.quantity_per_unit <= 0:
        raise BusinessRuleError("invalid_quantity", "Adet başına miktar sıfırdan büyük olmalıdır.")
    if line.scrap_allowance_pct is not None and line.scrap_allowance_pct < 0:
        raise BusinessRuleError("invalid_tolerance", "Fire payı negatif olamaz.")


def _clean_save[M: PackagingSpec | PackagingSpecLine](instance: M, actor: User | None) -> M:
    instance.full_clean(exclude=["created_by", "updated_by", "version_no", "spec"])
    return save_with_audit(instance, actor)


@transaction.atomic
def create_spec(actor: User | None, data: Mapping[str, Any]) -> PackagingSpec:
    """Mamul için yeni taslak ambalaj reçetesi sürümü açar (rol: planlama). `lines` verilirse
    satırlar da eklenir. Sürüm no mamulde bir sonrakidir."""
    _require_role(actor, SPEC_ROLES, "Ambalaj reçetesini yalnızca planlama yazar.")
    values = _pick_fields(data, (*SPEC_FIELDS, "lines", "copied_from"))
    lines = values.pop("lines", None) or []
    finished: Material = values["finished_product"]
    # Aynı mamulde eşzamanlı iki sürüm açılışını sıraya sokar.
    Material.objects.select_for_update().get(pk=finished.pk)
    last = PackagingSpec.objects.filter(finished_product=finished).aggregate(m=Max("version_no"))
    if values.get("change_note") is None:
        values["change_note"] = ""
    spec = PackagingSpec(version_no=(last["m"] or 0) + 1, **values)
    _validate_spec(spec)
    spec = _clean_save(spec, actor)
    for line in lines:
        add_spec_line(actor, spec, line)
    return spec


@transaction.atomic
def update_spec(actor: User | None, spec: PackagingSpec, data: Mapping[str, Any]) -> PackagingSpec:
    """Taslak sürümü günceller (rol: planlama). Mamul değiştirilemez."""
    _require_role(actor, SPEC_ROLES, "Ambalaj reçetesini yalnızca planlama yazar.")
    values = _pick_fields(data, SPEC_FIELDS)
    spec = _lock_spec(spec)
    _require_spec_draft(spec)
    finished = values.pop("finished_product", None)
    if finished is not None and finished.pk != spec.finished_product_id:
        raise BusinessRuleError(
            "finished_product_locked", "Sürümün mamulü değiştirilemez; yeni reçete açın."
        )
    for name, value in values.items():
        setattr(spec, name, "" if name == "change_note" and value is None else value)
    _validate_spec(spec)
    return _clean_save(spec, actor)


def _next_line_number(spec: PackagingSpec) -> int:
    current = PackagingSpecLine.objects.filter(spec=spec).aggregate(m=Max("sequence"))
    return (current["m"] or 0) + 1


@transaction.atomic
def add_spec_line(
    actor: User | None, spec: PackagingSpec, data: Mapping[str, Any]
) -> PackagingSpecLine:
    """Taslak sürüme ambalaj satırı ekler (rol: planlama). Sıra verilmezse sona eklenir."""
    _require_role(actor, SPEC_ROLES, "Ambalaj reçetesini yalnızca planlama yazar.")
    spec = _lock_spec(spec)
    _require_spec_draft(spec)
    values = _pick_fields(data, LINE_FIELDS)
    if values.get("sequence") is None:
        values["sequence"] = _next_line_number(spec)
    if values.get("scrap_allowance_pct") is None:
        values["scrap_allowance_pct"] = Decimal(0)
    line = PackagingSpecLine(spec=spec, **values)
    _validate_spec_line(line)
    return _clean_save(line, actor)


@transaction.atomic
def update_spec_line(
    actor: User | None, line: PackagingSpecLine, data: Mapping[str, Any]
) -> PackagingSpecLine:
    """Taslak sürümdeki ambalaj satırını günceller (rol: planlama)."""
    _require_role(actor, SPEC_ROLES, "Ambalaj reçetesini yalnızca planlama yazar.")
    values = _pick_fields(data, LINE_FIELDS)
    spec = _lock_spec(line.spec)
    _require_spec_draft(spec)
    line = PackagingSpecLine.objects.select_for_update().get(pk=line.pk)
    for name, value in values.items():
        if name == "scrap_allowance_pct" and value is None:
            value = Decimal(0)
        setattr(line, name, value)
    _validate_spec_line(line)
    return _clean_save(line, actor)


@transaction.atomic
def remove_spec_line(actor: User | None, line: PackagingSpecLine) -> None:
    """Taslak sürümden satırı kaldırır; silinen satır sürümün denetim kaydına yazılır (reçete
    taslağındaki gibi). Onaylı ya da eski sürümün satırı kaldırılamaz."""
    _require_role(actor, SPEC_ROLES, "Ambalaj reçetesini yalnızca planlama yazar.")
    spec = _lock_spec(line.spec)
    _require_spec_draft(spec)
    line = PackagingSpecLine.objects.select_for_update().get(pk=line.pk)
    log_change(
        _actor(actor),
        spec,
        AuditLog.Action.UPDATE,
        {"line": [snapshot(line), None]},
        "ambalaj reçetesi satırı silindi (taslak)",
    )
    line.delete()


@transaction.atomic
def copy_spec(actor: User | None, spec: PackagingSpec, change_note: str = "") -> PackagingSpec:
    """Sürümü satırlarıyla yeni taslak sürüme kopyalar (onaylı sürümü değiştirmenin tek yolu)."""
    source = PackagingSpec.objects.get(pk=spec.pk)
    return create_spec(
        actor,
        {
            **{f: getattr(source, f) for f in SPEC_FIELDS if f != "change_note"},
            "change_note": change_note,
            "copied_from": source,
            "lines": [
                {f: getattr(line, f) for f in LINE_FIELDS}
                for line in source.lines.select_related("material")
            ],
        },
    )


def _set_spec_status(
    spec: PackagingSpec, to_status: str, actor: User | None, note: str, **extra: Any
) -> None:
    from_status = spec.status
    packaging_spec_states.assert_can_transition(from_status, to_status)
    spec.status = to_status
    spec.updated_by = actor
    for name, value in extra.items():
        setattr(spec, name, value)
    spec.save(update_fields=["status", "updated_by", "updated_at", *extra])
    log_change(
        actor, spec, AuditLog.Action.STATUS_CHANGE, {"status": [from_status, to_status]}, note
    )
    events.publish(
        packaging_spec_states.event_name(to_status),
        {
            "model": spec._meta.label_lower,
            "id": spec.pk,
            "repr": str(spec),
            "material_code": spec.finished_product.code,
            "version_no": spec.version_no,
            "from_status": from_status,
            "to_status": to_status,
        },
        actor,
    )


@transaction.atomic
def approve_spec(actor: User | None, spec: PackagingSpec, note: str = "") -> PackagingSpec:
    """Taslak sürümü onaylar (rol: planlama). Mamulün önceki onaylı sürümü eski sürüm olur. En az
    bir satır olmalıdır. Açık dolum emirleri açıldıkları sürümle kalır."""
    _require_role(actor, SPEC_ROLES, "Ambalaj reçetesini yalnızca planlama onaylar.")
    actor = _actor(actor)
    Material.objects.select_for_update().get(pk=spec.finished_product_id)
    spec = _lock_spec(spec)
    _require_spec_draft(spec)
    _validate_spec(spec)
    lines = list(spec.lines.select_related("material"))
    if not lines:
        raise BusinessRuleError(
            "packaging_spec_has_no_lines", "Satırı olmayan ambalaj reçetesi onaylanamaz."
        )
    for line in lines:
        _validate_spec_line(line)
    previous = PackagingSpec.objects.select_for_update().filter(
        finished_product=spec.finished_product, status=SpecStatus.APPROVED
    )
    now = timezone.now()
    for old in previous.select_related("finished_product"):
        _set_spec_status(
            old, SpecStatus.OBSOLETE, actor, f"v{spec.version_no} onaylandı", obsoleted_at=now
        )
    _set_spec_status(spec, SpecStatus.APPROVED, actor, note, approved_by=actor, approved_at=now)
    return spec


def approved_spec(finished: Material) -> PackagingSpec | None:
    """Mamulün onaylı ambalaj reçetesi (yoksa None)."""
    return (
        PackagingSpec.objects.filter(finished_product=finished, status=SpecStatus.APPROVED)
        .select_related("bulk_product__base_unit", "fill_unit")
        .first()
    )


# --- dolum emri ------------------------------------------------------------------------------


def _lock_order(order: FillingOrder) -> FillingOrder:
    return (
        FillingOrder.objects.select_for_update(of=("self",))
        .select_related(
            "finished_product__base_unit",
            "packaging_spec__bulk_product__base_unit",
            "packaging_spec__fill_unit",
            "filling_line__location",
            "output_location",
        )
        .get(pk=order.pk)
    )


def _require_status(order: FillingOrder, allowed: Sequence[str], code: str, what: str) -> None:
    if order.status not in allowed:
        raise BusinessRuleError(
            code,
            f"{order.number} {filling_order_states.label(order.status).lower()} durumda; {what}.",
        )


def line_location(order: FillingOrder) -> Location:
    """Dolum hattının lokasyonu: ambalaj buraya hazırlanır ve buradan tüketilir."""
    location = order.filling_line.location
    assert location is not None
    return location


def _validate_filling_line(equipment: Equipment) -> None:
    if not equipment.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif dolum hattı seçilemez: {equipment}.")
    location = equipment.location
    if (
        equipment.equipment_type != Equipment.Type.FILLING_LINE
        or location is None
        or location.location_type != Location.Type.PRODUCTION
        or not location.is_active
    ):
        raise BusinessRuleError(
            "invalid_filling_line",
            f"{equipment.code} lokasyonu (üretim türünde) tanımlı bir dolum hattı değil.",
        )


def _prepare_order(order: FillingOrder) -> None:
    """Emir alanlarını doğrular; mamulün onaylı ambalaj reçetesini emre sabitler."""
    finished = order.finished_product
    if finished.material_type != Material.Type.FINISHED or not finished.is_active:
        raise BusinessRuleError("invalid_product", f"{finished.code} aktif bir mamul değil.")
    spec = approved_spec(finished)
    if spec is None:
        raise BusinessRuleError(
            "no_approved_packaging_spec",
            f"{finished.code} için onaylı ambalaj reçetesi yok; önce reçeteyi onaylayın.",
        )
    order.packaging_spec = spec
    _validate_filling_line(order.filling_line)
    location = order.output_location
    if location.location_type != Location.Type.STORAGE or not location.is_active:
        raise BusinessRuleError(
            "invalid_output_location", "Mamul deposu lokasyonu aktif ve “Depolama” türünde olmalı."
        )
    if order.planned_units is None or order.planned_units <= 0:
        raise BusinessRuleError("invalid_quantity", "Planlanan adet sıfırdan büyük olmalıdır.")


@transaction.atomic
def create_order(actor: User | None, data: Mapping[str, Any]) -> FillingOrder:
    """Taslak dolum emri açar (`DO-`, rol: planlama). Mamulün onaylı ambalaj reçetesi emre
    sabitlenir."""
    _require_role(actor, ORDER_ROLES, "Dolum emrini yalnızca planlama açar.")
    values = _pick_fields(data, ORDER_FIELDS)
    if values.get("notes") is None:
        values["notes"] = ""
    order = FillingOrder(**values)
    _prepare_order(order)
    return create_document(order, actor, prefix="DO", machine=filling_order_states)


@transaction.atomic
def update_order(actor: User | None, order: FillingOrder, data: Mapping[str, Any]) -> FillingOrder:
    """Taslak emri günceller (rol: planlama); ambalaj reçetesi o anki onaylı sürüme yenilenir.
    Onaylanan emir değiştirilmez."""
    _require_role(actor, ORDER_ROLES, "Dolum emrini yalnızca planlama değiştirir.")
    values = _pick_fields(data, ORDER_FIELDS)
    order = _lock_order(order)
    _require_status(order, (Status.DRAFT,), "document_locked", "değiştirilemez")
    for name, value in values.items():
        setattr(order, name, "" if name == "notes" and value is None else value)
    _prepare_order(order)
    return save_with_audit(order, actor)


def build_requirements(order: FillingOrder) -> list[FillingRequirement]:
    """Onayda yazılacak ambalaj ihtiyacı: planlanan adet × adet başına miktar × (1 + fire payı),
    adet birimli malzemede yukarı yuvarlanır."""
    result = []
    lines = order.packaging_spec.lines.select_related("material__base_unit").order_by("sequence")
    for sequence, line in enumerate(lines, start=1):
        factor = 1 + line.scrap_allowance_pct / HUNDRED
        quantity = round_for(line.material, order.planned_units * line.quantity_per_unit * factor)
        if quantity <= 0:
            raise BusinessRuleError(
                "quantity_too_small", f"{line.material.code} ihtiyacı bu adette sıfıra iniyor."
            )
        result.append(
            FillingRequirement(
                order=order,
                spec_line=line,
                material=line.material,
                required_quantity=quantity,
                sequence=sequence,
            )
        )
    return result


@transaction.atomic
def approve_order(actor: User | None, order: FillingOrder, note: str = "") -> FillingOrder:
    """Emri onaylar (rol: planlama): ambalaj ihtiyacı hesaplanır. Olay `filling_order.approved`
    depoya "Ambalaj malzemesi hazırla" görevi açar. Sabitlenen ambalaj reçetesi hâlâ onaylı
    olmalıdır (değiştiyse taslak emir güncellenir)."""
    _require_role(actor, ORDER_ROLES, "Dolum emrini yalnızca planlama onaylar.")
    actor = _actor(actor)
    order = _lock_order(order)
    filling_order_states.assert_can_transition(order.status, Status.APPROVED)
    if order.packaging_spec.status != SpecStatus.APPROVED:
        raise BusinessRuleError(
            "packaging_spec_not_approved",
            f"Emirdeki ambalaj reçetesi ({order.packaging_spec}) artık onaylı değil; emri "
            "güncelleyip yeni sürümü sabitleyin.",
        )
    _validate_filling_line(order.filling_line)
    for requirement in build_requirements(order):
        save_with_audit(requirement, actor)
    order.approved_by = actor
    order.approved_at = timezone.now()
    order.save(update_fields=["approved_by", "approved_at"])
    return transition_status(
        order,
        Status.APPROVED,
        actor,
        machine=filling_order_states,
        note=note,
        event_payload={"product_code": order.finished_product.code},
    )


@transaction.atomic
def start_material_prep(actor: User | None, order: FillingOrder) -> FillingOrder:
    """Depo ambalaj hazırlığına başlar (rol: depo). İlk hazırlama da hazırlığı başlatır."""
    _require_role(actor, PREP_ROLES, "Ambalaj hazırlığını yalnızca depo başlatır.")
    order = _lock_order(order)
    return transition_status(order, Status.MATERIAL_PREP, actor, machine=filling_order_states)


def picked_quantity(requirement: FillingRequirement) -> Decimal:
    """İhtiyaç için hazırlanmış (iade edilmemiş) toplam miktar."""
    return picking.picked_total(requirement.picks.all())


def net_requirement(requirement: FillingRequirement) -> Decimal:
    """Fire payı hariç ihtiyaç: planlanan adet × adet başına miktar (yuvarlanmış). "Ambalaj hazır"
    için en az bu kadar hazırlanmalıdır; fire payı isteğe bağlıdır."""
    line = requirement.spec_line
    return round_for(requirement.material, requirement.order.planned_units * line.quantity_per_unit)


@transaction.atomic
def pick_packaging(
    actor: User | None,
    order: FillingOrder,
    requirement: FillingRequirement,
    lot: Lot,
    quantity: Decimal,
    from_location: Location | None = None,
    note: str = "",
) -> PackagingPick:
    """Depo ambalaj lotu hazırlar (rol: depo): lot depodan dolum hattının lokasyonuna transfer
    edilir (ortak hazırlama servisi). Yalnızca serbest, SKT'si geçmemiş ve satırın malzemesinden
    lot; hazırlanan toplam ihtiyacın iki katını geçemez."""
    _require_role(actor, PREP_ROLES, "Ambalajı yalnızca depo hazırlar.")
    actor = _actor(actor)
    order = _lock_order(order)
    _require_status(order, PICKABLE_STATUSES, "order_not_pickable", "ambalaj hazırlanamaz")
    requirement = (
        FillingRequirement.objects.select_for_update(of=("self",))
        .select_related("material__base_unit")
        .get(pk=requirement.pk)
    )
    if requirement.order_id != order.pk:
        raise BusinessRuleError("requirement_not_in_order", "İhtiyaç satırı bu emre ait değil.")
    if order.status == Status.APPROVED:
        order = transition_status(order, Status.MATERIAL_PREP, actor, machine=filling_order_states)
    result = picking.pick_lot(
        actor,
        lot=lot,
        material=requirement.material,
        quantity=quantity,
        required_quantity=requirement.required_quantity,
        already_picked=picked_quantity(requirement),
        to_location=line_location(order),
        document=order,
        from_location=from_location,
        note=note or f"Ambalaj hazırlama {order.number}",
    )
    return save_with_audit(
        PackagingPick(
            order=order,
            requirement=requirement,
            lot=lot,
            quantity=result.quantity,
            from_location=result.from_location,
            to_location=result.to_location,
            picked_by=actor,
            picked_at=timezone.now(),
            transfer_group=result.transfer_group,
        ),
        actor,
    )


def missing_packaging(order: FillingOrder) -> list[FillingRequirement]:
    """Hazırlanan miktarı fire payı hariç ihtiyaca ulaşmayan ambalaj satırları."""
    requirements = order.requirements.select_related("material__base_unit", "spec_line", "order")
    return [r for r in requirements.order_by("sequence") if picked_quantity(r) < net_requirement(r)]


@transaction.atomic
def mark_material_ready(actor: User | None, order: FillingOrder) -> FillingOrder:
    """Ambalaj hazır (rol: depo): her satır en az fire payı hariç ihtiyaç kadar hazırlanmış
    olmalıdır. Olay `filling_order.material_ready` dolum ekibine "Dolumu başlat" görevi açar ve
    depo görevini kapatır."""
    _require_role(actor, PREP_ROLES, "Ambalaj hazır bilgisini yalnızca depo verir.")
    order = _lock_order(order)
    if order.status == Status.APPROVED:
        order = transition_status(order, Status.MATERIAL_PREP, actor, machine=filling_order_states)
    filling_order_states.assert_can_transition(order.status, Status.MATERIAL_READY)
    missing = missing_packaging(order)
    if missing:
        codes = ", ".join(r.material.code for r in missing)
        raise BusinessRuleError("material_not_ready", f"Hazırlanmamış ambalaj var: {codes}.")
    return transition_status(order, Status.MATERIAL_READY, actor, machine=filling_order_states)


@transaction.atomic
def cancel_order(actor: User | None, order: FillingOrder, reason: str) -> FillingOrder:
    """Emri iptal eder (rol: planlama; taslak, onaylı ya da hazırlıktaki emir). Hazırlanan ambalaj
    geldiği lokasyonlara geri transfer edilir. Olay `filling_order.cancelled` emre bağlı açık
    görevleri iptal eder."""
    _require_role(actor, ORDER_ROLES, "Dolum emrini yalnızca planlama iptal eder.")
    actor = _actor(actor)
    order = _lock_order(order)
    filling_order_states.assert_can_transition(order.status, Status.CANCELLED)
    if not reason.strip():
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    picking.return_picks(
        actor,
        order.picks.filter(returned_at__isnull=True).select_related(
            "lot__material", "from_location", "to_location"
        ),
        document=order,
        note=f"İptal iadesi {order.number}",
        audit_note="Emir iptali: ambalaj geri transfer edildi",
    )
    return cancel_document(order, actor, reason=reason, machine=filling_order_states)


# --- dolum partisi ---------------------------------------------------------------------------


def _lock_run(run: FillingRun) -> FillingRun:
    return (
        FillingRun.objects.select_for_update(of=("self",))
        .select_related("output_lot__material__base_unit")
        .get(pk=run.pk)
    )


def _require_in_progress(run: FillingRun) -> None:
    if run.status != RunStatus.IN_PROGRESS:
        raise BusinessRuleError(
            "run_not_in_progress", f"Dolum partisi {run.output_lot.lot_no} devam etmiyor."
        )


def run_payload(run: FillingRun, **extra: Any) -> dict[str, Any]:
    lot = run.output_lot
    return {
        "model": run._meta.label_lower,
        "id": run.pk,
        "lot_no": lot.lot_no,
        "order": order_ref(run.order),
        "order_number": run.order.number,
        **extra,
    }


@transaction.atomic
def start_run(actor: User | None, order: FillingOrder) -> FillingRun:
    """Dolum partisini başlatır (rol: dolum). Dolum lotu `D-YYMMDD-NNN` numarasıyla karantinada
    açılır; SKT = dolum tarihi + mamulün raf ömrü. Emirde açık parti varsa yenisi açılmaz. İlk
    partiyle emir "Dolumda" olur. Olay `filling_run.started` "Dolumu başlat" görevini kapatır."""
    _require_role(actor, FILLING_ROLES, "Dolum partisini yalnızca dolum başlatır.")
    actor = _actor(actor)
    order = _lock_order(order)
    _require_status(order, RUNNABLE_STATUSES, "order_not_ready", "dolum başlatılamaz")
    if order.runs.filter(status=RunStatus.IN_PROGRESS).exists():
        raise BusinessRuleError(
            "run_in_progress", f"{order.number} emrinde devam eden bir dolum partisi var."
        )
    today = timezone.localdate()
    lot = inventory.create_lot(
        actor,
        material=order.finished_product,
        source=Lot.Source.FILLING,
        status=Lot.Status.QUARANTINE,
        manufactured_at=today,
        day=today,
        note=f"Dolum emri {order.number}",
    )
    run = save_with_audit(
        FillingRun(
            order=order,
            sequence=order.runs.count() + 1,
            output_lot=lot,
            operator=actor,
            started_at=timezone.now(),
        ),
        actor,
    )
    if order.status == Status.MATERIAL_READY:
        transition_status(order, Status.IN_PROGRESS, actor, machine=filling_order_states)
    events.publish(ev.FILLING_RUN_STARTED, run_payload(run), actor)
    return run


def _stock_location(lot: Lot, quantity: Decimal, from_location: Location | None) -> Location:
    """Bulk lotunun tüketileceği lokasyon: verilen ya da lotun karantina dışı, yeterli stoklu
    (yoksa en çok stoklu) lokasyonu (genellikle tank)."""
    if from_location is not None:
        return from_location
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


def _bulk_lot(order: FillingOrder, lot: Lot) -> Lot:
    lot = Lot.objects.select_related("material__base_unit").get(pk=lot.pk)
    bulk = order.packaging_spec.bulk_product
    if lot.material_id != bulk.pk:
        raise BusinessRuleError(
            "lot_material_mismatch",
            f"Lot {lot.lot_no} {lot.material.code} malzemesine ait; bu dolum {bulk.code} "
            "bulkundan yapılır.",
        )
    return lot


def _spec_line_for(order: FillingOrder, lot: Lot) -> PackagingSpecLine:
    line = order.packaging_spec.lines.filter(material_id=lot.material_id).first()
    if line is None:
        raise BusinessRuleError(
            "lot_material_mismatch",
            f"Lot {lot.lot_no} ({lot.material.code}) bu dolumun ambalaj malzemesi değil.",
        )
    return line


def _consume(
    actor: User | None,
    run: FillingRun,
    *,
    kind: str,
    lot: Lot,
    location: Location,
    quantity: Decimal,
    spec_line: PackagingSpecLine | None = None,
) -> FillingConsumption:
    movement = inventory.post_movement(
        actor,
        lot.material,
        lot,
        location,
        -quantity,
        MovementType.ISSUE_PRODUCTION,
        run.order,
        f"Dolum {run.output_lot.lot_no}",
    )
    link = inventory.link_lots(actor, lot, run.output_lot, quantity, source=run)
    return save_with_audit(
        FillingConsumption(
            run=run,
            kind=kind,
            spec_line=spec_line,
            material=lot.material,
            lot=lot,
            location=location,
            quantity=quantity,
            consumed_by=actor,
            consumed_at=timezone.now(),
            movement=movement,
            lot_link=link,
        ),
        actor,
    )


@transaction.atomic
def consume_bulk(
    actor: User | None,
    run: FillingRun,
    lot: Lot,
    quantity: Decimal,
    from_location: Location | None = None,
) -> FillingConsumption:
    """Bulk tüketimi (rol: dolum): okutulan tank lotundan `ISSUE_PRODUCTION` ve bulk lot → dolum
    lotu soy ağacı bağı. Bir partiye birden çok bulk lotu girebilir. Lot ambalaj reçetesinin
    bulkundan, serbest ve SKT'si geçmemiş olmalıdır; bulunduğu (karantina dışı) lokasyondan düşülür.
    """
    _require_role(actor, FILLING_ROLES, "Bulk tüketimini yalnızca dolum kaydeder.")
    actor = _actor(actor)
    run = _lock_run(run)
    _require_in_progress(run)
    order = _lock_order(run.order)
    run.order = order
    lot = _bulk_lot(order, lot)
    quantity = quantize(quantity)
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    inventory.assert_lot_usable(lot)
    location = _stock_location(lot, quantity, from_location)
    return _consume(
        actor, run, kind=ConsumptionKind.BULK, lot=lot, location=location, quantity=quantity
    )


@transaction.atomic
def scan_packaging_lot(actor: User | None, run: FillingRun, lot: Lot) -> RunLot:
    """Partiye ambalaj lotu okutur (rol: dolum). Lot reçetedeki bir ambalaj malzemesinden olmalı
    (yanlış malzemenin lotu reddedilir), serbest ve SKT'si geçmemiş olmalı ve hat başında stokta
    bulunmalıdır. Aynı lot ikinci kez okutulursa var olan kayıt döner."""
    _require_role(actor, FILLING_ROLES, "Ambalaj lotunu yalnızca dolum okutur.")
    actor = _actor(actor)
    run = _lock_run(run)
    _require_in_progress(run)
    order = _lock_order(run.order)
    lot = Lot.objects.select_related("material").get(pk=lot.pk)
    _spec_line_for(order, lot)
    inventory.assert_lot_usable(lot)
    if inventory.current_balance(lot, line_location(order)) <= 0:
        raise BusinessRuleError(
            "lot_not_at_line",
            f"Lot {lot.lot_no} dolum hattında ({line_location(order).code}) stokta yok; önce "
            "ambalaj hazırlanmalıdır.",
        )
    existing = run.run_lots.filter(lot=lot).first()
    if existing is not None:
        return existing
    return save_with_audit(
        RunLot(
            run=run, lot=lot, material=lot.material, scanned_by=actor, scanned_at=timezone.now()
        ),
        actor,
    )


@transaction.atomic
def record_scrap(
    actor: User | None,
    run: FillingRun,
    *,
    kind: str,
    quantity: Decimal,
    reason_code: str,
    lot: Lot | None = None,
    note: str = "",
) -> ScrapRecord:
    """Fire kaydı (rol: dolum). Bulk firesi lotun bulunduğu lokasyondan, ambalaj firesi hat
    başından hemen `SCRAP` hareketi yazar. Mamul firesi (dolup ayrılan adet) dolum lotuna yazılır;
    stok hareketi parti bitişinde, mamul girişinin ardından düşülür. `OTHER` nedeninde not
    zorunludur."""
    _require_role(actor, FILLING_ROLES, "Fireyi yalnızca dolum kaydeder.")
    actor = _actor(actor)
    run = _lock_run(run)
    _require_in_progress(run)
    order = _lock_order(run.order)
    run.order = order
    if kind not in ScrapKind.values:
        raise BusinessRuleError("invalid_scrap_kind", "Geçersiz fire türü.")
    if reason_code not in ScrapRecord.Reason.values:
        raise BusinessRuleError("invalid_reason", "Geçersiz fire nedeni.")
    note = note.strip()
    if reason_code == ScrapRecord.Reason.OTHER and not note:
        raise BusinessRuleError("scrap_note_required", "“Diğer” nedeninde not girilmelidir.")
    quantity = quantize(quantity)
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Fire miktarı sıfırdan büyük olmalıdır.")
    movement: StockMovement | None = None
    if kind == ScrapKind.FINISHED:
        if quantity != quantity.to_integral_value():
            raise BusinessRuleError("invalid_quantity", "Mamul firesi tam adet olmalıdır.")
        lot = run.output_lot
        location = order.output_location
    else:
        if lot is None:
            raise BusinessRuleError("lot_required", "Fire için lot okutulmalıdır.")
        if kind == ScrapKind.BULK:
            lot = _bulk_lot(order, lot)
            location = _stock_location(lot, quantity, None)
        else:
            lot = Lot.objects.select_related("material__base_unit").get(pk=lot.pk)
            _spec_line_for(order, lot)
            location = line_location(order)
        movement = inventory.post_movement(
            actor,
            lot.material,
            lot,
            location,
            -quantity,
            MovementType.SCRAP,
            order,
            f"Dolum firesi {run.output_lot.lot_no}: {ScrapRecord.Reason(reason_code).label}",
        )
    return save_with_audit(
        ScrapRecord(
            run=run,
            kind=kind,
            material=lot.material,
            lot=lot,
            location=location,
            quantity=quantity,
            reason_code=reason_code,
            note=note,
            recorded_by=actor,
            recorded_at=timezone.now(),
            movement=movement,
        ),
        actor,
    )


def _packaging_lots(run: FillingRun, line: PackagingSpecLine, location: Location) -> list[Lot]:
    """Ambalaj tüketiminin düşüleceği lotlar: önce partiye okutulanlar (okutma sırasıyla), sonra
    hat başındaki diğer serbest, SKT'si geçmemiş lotlar (SKT, sonra eskiden yeniye)."""
    scanned = [
        r.lot for r in run.run_lots.filter(material=line.material).select_related("lot__material")
    ]
    today = timezone.localdate()
    others = (
        StockBalance.objects.filter(
            material=line.material,
            location=location,
            quantity__gt=0,
            lot__status=Lot.Status.RELEASED,
        )
        .filter(Q(lot__expiry_date__isnull=True) | Q(lot__expiry_date__gte=today))
        .exclude(lot__in=[lot.pk for lot in scanned])
        .select_related("lot__material")
        .order_by(F("lot__expiry_date").asc(nulls_last=True), "lot__created_at", "lot__id")
    )
    return scanned + [balance.lot for balance in others]


def _consume_packaging(
    actor: User | None, run: FillingRun, line: PackagingSpecLine, total_units: int
) -> Decimal:
    """Bir ambalaj satırının tüketimini hat başındaki lotlardan düşer; düşülen toplamı döner."""
    order = run.order
    location = line_location(order)
    needed = round_for(line.material, total_units * line.quantity_per_unit)
    remaining = needed
    for lot in _packaging_lots(run, line, location):
        if remaining <= 0:
            break
        available = inventory.current_balance(lot, location)
        if available <= 0:
            continue
        take = min(available, remaining)
        _consume(
            actor,
            run,
            kind=ConsumptionKind.PACKAGING,
            lot=lot,
            location=location,
            quantity=take,
            spec_line=line,
        )
        remaining -= take
    if remaining > 0:
        unit = line.material.base_unit.code
        raise BusinessRuleError(
            "packaging_short",
            f"Dolum hattında yeterli {line.material.code} yok: {format_quantity(needed)} {unit} "
            f"gerekli, {format_quantity(needed - remaining)} {unit} var. Ambalaj hazırlatın.",
        )
    return needed


def theoretical_bulk(order: FillingOrder, good_units: int) -> Decimal:
    """Teorik bulk tüketimi: sağlam adet × dolum miktarı, bulkun temel biriminde."""
    spec = order.packaging_spec
    return quantize(
        masterdata.to_base_quantity(
            spec.bulk_product, good_units * spec.fill_quantity, spec.fill_unit
        )
    )


def actual_bulk(run: FillingRun) -> Decimal:
    """Gerçek bulk: partiye tüketilen bulk + bulk firesi (bulkun temel biriminde)."""
    consumed = run.consumptions.filter(kind=ConsumptionKind.BULK).aggregate(t=Sum("quantity"))["t"]
    scrapped = run.scraps.filter(kind=ScrapKind.BULK).aggregate(t=Sum("quantity"))["t"]
    return (consumed or Decimal(0)) + (scrapped or Decimal(0))


def finished_scrap_units(run: FillingRun) -> int:
    """Partide mamul firesi olarak ayrılan adet."""
    total = run.scraps.filter(kind=ScrapKind.FINISHED).aggregate(t=Sum("quantity"))["t"]
    return int(total or 0)


def variance_pct(theoretical: Decimal, actual: Decimal) -> Decimal:
    """Teorik değere göre fark yüzdesi (işaretli, 2 ondalık)."""
    if theoretical == 0:
        return Decimal(0)
    return _pct((actual - theoretical) / theoretical * HUNDRED)


@transaction.atomic
def finish_run(actor: User | None, run: FillingRun, good_units: int, note: str = "") -> FillingRun:
    """Partiyi bitirir (rol: dolum).

    - Ambalaj tüketimi (sağlam + mamul firesi) × adet başına miktar olarak hat başındaki lotlardan
      düşülür; her tüketim ambalaj lotu → dolum lotu bağı yazar.
    - Mamul `PRODUCTION_OUTPUT` ile mamul deposuna (ADET) girer; mamul firesi `SCRAP` ile düşülür.
      Lot karantinada kalır; son kontrol (`FINAL`) numunesi açılır.
    - Teorik ve gerçek bulk karşılaştırılır; fark eşiği aşarsa `filling.bulk_variance`.
    Olay `filling_run.completed` laboratuvara "Mamul kontrolü" görevi açar.
    """
    _require_role(actor, FILLING_ROLES, "Dolum partisini yalnızca dolum bitirir.")
    actor = _actor(actor)
    run = _lock_run(run)
    filling_run_states.assert_can_transition(run.status, RunStatus.COMPLETED)
    order = _lock_order(run.order)
    run.order = order
    if not isinstance(good_units, int) or good_units <= 0:
        raise BusinessRuleError("invalid_quantity", "Sağlam adet sıfırdan büyük olmalıdır.")
    if not run.consumptions.filter(kind=ConsumptionKind.BULK).exists():
        raise BusinessRuleError(
            "run_has_no_bulk", "Bulk tüketimi kaydedilmemiş dolum partisi bitirilemez."
        )
    scrapped_units = finished_scrap_units(run)
    total_units = good_units + scrapped_units
    lines = order.packaging_spec.lines.select_related("material__base_unit").order_by("sequence")
    for line in lines:
        _consume_packaging(actor, run, line, total_units)
    lot = run.output_lot
    movement = inventory.post_movement(
        actor,
        order.finished_product,
        lot,
        order.output_location,
        Decimal(total_units),
        MovementType.PRODUCTION_OUTPUT,
        order,
        f"Dolum {lot.lot_no}",
    )
    for scrap in run.scraps.filter(kind=ScrapKind.FINISHED, movement__isnull=True):
        scrap.movement = inventory.post_movement(
            actor,
            order.finished_product,
            lot,
            order.output_location,
            -scrap.quantity,
            MovementType.SCRAP,
            order,
            f"Dolum firesi {lot.lot_no}: {scrap.get_reason_code_display()}",
        )
        save_with_audit(scrap, actor)
    theoretical = theoretical_bulk(order, good_units)
    actual = actual_bulk(run)
    pct = variance_pct(theoretical, actual)
    run.good_units = good_units
    run.theoretical_bulk = theoretical
    run.actual_bulk = actual
    run.bulk_variance_pct = pct
    run.output_movement = movement
    run.finished_at = timezone.now()
    run.finished_by = actor
    run.finish_note = note.strip()
    _set_run_status(actor, run, RunStatus.COMPLETED, run.finish_note)
    sample = quality.open_sample(actor, lot, SampleStage.FINAL, origin=Sample.Origin.FILLING)
    unit = order.packaging_spec.bulk_product.base_unit.code
    events.publish(
        ev.FILLING_RUN_COMPLETED,
        run_payload(
            run,
            output_lot=lot_payload(lot, material_type=lot.material.material_type),
            good_units=good_units,
            scrapped_units=scrapped_units,
            sample_number=sample.number,
        ),
        actor,
    )
    threshold = variance_threshold()
    if abs(pct) > threshold:
        events.publish(
            ev.FILLING_BULK_VARIANCE,
            {
                **order_ref(order),
                "lot_no": lot.lot_no,
                "run": {"model": run._meta.label_lower, "id": run.pk, "lot_no": lot.lot_no},
                "product_code": order.finished_product.code,
                "good_units": good_units,
                "theoretical_quantity": f"{format_quantity(theoretical)} {unit}",
                "actual_quantity": f"{format_quantity(actual)} {unit}",
                "variance_pct": format_quantity(pct),
                "threshold_pct": format_quantity(threshold),
            },
            actor,
        )
    return run


def _set_run_status(actor: User | None, run: FillingRun, to_status: str, note: str = "") -> None:
    filling_run_states.assert_can_transition(run.status, to_status)
    from_status = run.status
    run.status = to_status
    run.updated_by = actor
    run.save()
    log_change(
        actor, run, AuditLog.Action.STATUS_CHANGE, {"status": [from_status, to_status]}, note
    )


@transaction.atomic
def cancel_run(actor: User | None, run: FillingRun, reason: str) -> FillingRun:
    """Yanlış başlatılan partiyi iptal eder (rol: dolum; tüketim ve fire kaydı yoksa). Dolum lotu
    stoksuz olarak karantinada kalır."""
    _require_role(actor, FILLING_ROLES, "Dolum partisini yalnızca dolum iptal eder.")
    actor = _actor(actor)
    reason = reason.strip()
    if not reason:
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    run = _lock_run(run)
    filling_run_states.assert_can_transition(run.status, RunStatus.CANCELLED)
    if run.consumptions.exists() or run.scraps.exists():
        raise BusinessRuleError(
            "run_has_records",
            "Tüketim ya da fire kaydı olan parti iptal edilemez; partiyi bitirin.",
        )
    run.cancel_reason = reason
    _set_run_status(actor, run, RunStatus.CANCELLED, reason)
    return run


# --- emir kapanışı ---------------------------------------------------------------------------


@transaction.atomic
def finish_filling(actor: User | None, order: FillingOrder, note: str = "") -> FillingOrder:
    """Dolumu bitirir (rol: dolum): açık parti kalmamalı, en az bir parti tamamlanmış olmalıdır.
    Emir "Analiz bekliyor" olur; tüm dolum lotları serbest bırakılınca kendiliğinden tamamlanır."""
    _require_role(actor, FILLING_ROLES, "Dolumu yalnızca dolum bitirir.")
    order = _lock_order(order)
    filling_order_states.assert_can_transition(order.status, Status.QC_PENDING)
    if order.runs.filter(status=RunStatus.IN_PROGRESS).exists():
        raise BusinessRuleError(
            "run_in_progress", "Devam eden dolum partisi var; önce partiyi bitirin."
        )
    if not order.runs.filter(status=RunStatus.COMPLETED).exists():
        raise BusinessRuleError("order_has_no_runs", "Tamamlanmış dolum partisi yok.")
    order = transition_status(
        order, Status.QC_PENDING, actor, machine=filling_order_states, note=note
    )
    # Lotların hepsi zaten serbestse emir hemen kapanır.
    if not unreleased_lots(order):
        order = complete_order(actor, order)
    return order


def unreleased_lots(order: FillingOrder) -> list[Lot]:
    """Tamamlanan partilerin serbest bırakılmamış dolum lotları."""
    return [
        run.output_lot
        for run in order.runs.filter(status=RunStatus.COMPLETED).select_related("output_lot")
        if run.output_lot.status != Lot.Status.RELEASED
    ]


@transaction.atomic
def complete_order(actor: User | None, order: FillingOrder) -> FillingOrder:
    """Emri tamamlar: tüm dolum lotları serbest bırakılmış olmalıdır. Laboratuvar son lotu serbest
    bırakınca kendiliğinden çağrılır (`handlers.py`)."""
    actor = _actor(actor)
    order = _lock_order(order)
    filling_order_states.assert_can_transition(order.status, Status.COMPLETED)
    waiting = unreleased_lots(order)
    if waiting:
        lots = ", ".join(lot.lot_no for lot in waiting)
        raise BusinessRuleError(
            "output_lots_not_released", f"Serbest bırakılmamış dolum lotları var: {lots}."
        )
    order.completed_at = timezone.now()
    order.save(update_fields=["completed_at"])
    return transition_status(order, Status.COMPLETED, actor, machine=filling_order_states)


def lots_for_scrap(run: FillingRun) -> Iterable[Lot]:
    """Fire girişinde seçilebilecek lotlar: partinin bulk lotları ve okutulan ambalaj lotları."""
    bulk = [c.lot for c in run.consumptions.filter(kind=ConsumptionKind.BULK).select_related("lot")]
    scanned = [r.lot for r in run.run_lots.select_related("lot")]
    seen: dict[int, Lot] = {}
    for lot in [*bulk, *scanned]:
        seen.setdefault(lot.pk, lot)
    return list(seen.values())
