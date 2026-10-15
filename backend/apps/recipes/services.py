"""Reçete servisleri: reçete, sürüm, satır ve adım yazma işlemleri, onay ve ölçekleme.

Kurallar:
- Bir reçetenin aynı anda tek onaylı (APPROVED) sürümü olur; yeni sürüm onaylanınca önceki
  onaylı sürüm OBSOLETE olur.
- Onaylı ya da geçersiz sürüm ve satırları değiştirilemez; değişiklik için sürüm kopyalanır
  (`copy_version`) ve yeni taslak düzenlenir (CLAUDE.md §4.6).
- Su da stoklu bir malzemedir; `is_water` yalnızca bir işarettir (Karar D-1).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core import events
from apps.core.audit import log_change, snapshot
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.roles import LABORATUVAR, PLANLAMA
from apps.core.services import save_with_audit
from apps.masterdata import services as masterdata
from apps.masterdata.models import Material, UnitOfMeasure
from apps.recipes.models import Recipe, RecipeLine, RecipeStep, RecipeVersion
from apps.recipes.state import recipe_version_states

APPROVER_ROLES = (PLANLAMA, LABORATUVAR)
INGREDIENT_TYPES = (Material.Type.RAW, Material.Type.BULK)
QUANTITY_STEP = Decimal("0.0001")

LINE_FIELDS = (
    "sequence",
    "material",
    "quantity",
    "unit",
    "tolerance_pct",
    "instruction",
    "is_water",
)
STEP_FIELDS = ("sequence", "description", "duration_min", "temperature_c", "mixer_rpm")


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


# --- reçete ----------------------------------------------------------------------------------


def _validate_product(product: Material) -> None:
    if product.material_type != Material.Type.BULK:
        raise BusinessRuleError(
            "recipe_product_not_bulk", "Reçetenin ürünü yarı mamul (dökme) bir malzeme olmalıdır."
        )
    if not product.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif malzeme seçilemez: {product}.")


@transaction.atomic
def create_recipe(actor: User | None, data: Mapping[str, Any]) -> Recipe:
    """Yeni reçete açar (sürümsüz). Ürün dökme (BULK) ve aktif bir malzeme olmalıdır."""
    _validate_product(data["product"])
    return masterdata.create_record(actor, Recipe, data)


@transaction.atomic
def update_recipe(actor: User | None, recipe: Recipe, data: Mapping[str, Any]) -> Recipe:
    """Reçetenin kod, ad, not ve ürününü günceller. Sürümü olan reçetenin ürünü değiştirilemez."""
    product = data.get("product")
    if product is not None and product.pk != recipe.product_id:
        _validate_product(product)
        if recipe.versions.exists():
            raise BusinessRuleError(
                "recipe_product_locked",
                "Sürümü olan reçetenin ürünü değiştirilemez; yeni reçete açın.",
            )
    return masterdata.update_record(actor, recipe, data)


@transaction.atomic
def set_recipe_active(actor: User | None, recipe: Recipe, active: bool) -> Recipe:
    """Reçeteyi aktif ya da pasif yapar (reçeteler silinmez). Pasif reçetenin sürümü onaylanamaz."""
    return masterdata.set_active(actor, recipe, active)


# --- sürüm -----------------------------------------------------------------------------------


def _lock_version(version: RecipeVersion) -> RecipeVersion:
    return RecipeVersion.objects.select_for_update().get(pk=version.pk)


def _require_draft(version: RecipeVersion) -> None:
    if version.status != RecipeVersion.Status.DRAFT:
        raise BusinessRuleError(
            "version_locked",
            f"{version} {recipe_version_states.label(version.status).lower()}; değiştirilemez. "
            "Değişiklik için sürümü kopyalayın.",
        )


def _validate_batch_unit(recipe: Recipe, unit: UnitOfMeasure) -> None:
    masterdata.convert_quantity(recipe.product, Decimal(1), unit, recipe.product.base_unit)


def _next_number(model: type[RecipeLine] | type[RecipeStep], version: RecipeVersion) -> int:
    current = model.objects.filter(version=version).aggregate(m=Max("sequence"))["m"]
    return (current or 0) + 1


def _clean_save[M: RecipeLine | RecipeStep | RecipeVersion](instance: M, actor: User | None) -> M:
    instance.full_clean(exclude=["created_by", "updated_by"])
    return save_with_audit(instance, actor)


@transaction.atomic
def create_version(
    actor: User | None,
    recipe: Recipe,
    *,
    batch_size: Decimal,
    batch_unit: UnitOfMeasure,
    change_note: str = "",
    lines: Iterable[Mapping[str, Any]] = (),
    steps: Iterable[Mapping[str, Any]] = (),
    copied_from: RecipeVersion | None = None,
) -> RecipeVersion:
    """Reçeteye yeni taslak (DRAFT) sürüm açar; sürüm no bir sonraki numaradır.

    `lines` / `steps`: `add_line` / `add_step` ile aynı alanlar. Şarj birimi ürünün temel
    birimine çevrilebilir olmalıdır.
    """
    recipe = (
        Recipe.objects.select_for_update(of=("self",))
        .select_related("product__base_unit")
        .get(pk=recipe.pk)
    )
    if not recipe.is_active:
        raise BusinessRuleError("inactive_reference", "Pasif reçeteye sürüm açılamaz.")
    _validate_batch_unit(recipe, batch_unit)
    last = recipe.versions.aggregate(m=Max("version_no"))["m"] or 0
    version = RecipeVersion(
        recipe=recipe,
        version_no=last + 1,
        batch_size=batch_size,
        batch_unit=batch_unit,
        change_note=change_note,
        copied_from=copied_from,
    )
    _clean_save(version, actor)
    for line in lines:
        add_line(actor, version, line)
    for step in steps:
        add_step(actor, version, step)
    return version


@transaction.atomic
def update_version(
    actor: User | None, version: RecipeVersion, data: Mapping[str, Any]
) -> RecipeVersion:
    """Taslak sürümün şarj miktarını, birimini ve değişiklik notunu günceller."""
    allowed = {"batch_size", "batch_unit", "change_note"}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Değiştirilemeyen alan: {', '.join(sorted(unknown))}")
    version = _lock_version(version)
    _require_draft(version)
    for name, value in data.items():
        setattr(version, name, value)
    _validate_batch_unit(version.recipe, version.batch_unit)
    return _clean_save(version, actor)


@transaction.atomic
def copy_version(
    actor: User | None, version: RecipeVersion, change_note: str = ""
) -> RecipeVersion:
    """Sürümü satır ve adımlarıyla birlikte yeni taslak sürüme kopyalar.

    Onaylı sürümü değiştirmenin tek yolu budur. Kaynak sürüm değişmez.
    """
    source = RecipeVersion.objects.select_related("recipe").get(pk=version.pk)
    copy = create_version(
        actor,
        source.recipe,
        batch_size=source.batch_size,
        batch_unit=source.batch_unit,
        change_note=change_note,
        lines=[{f: getattr(line, f) for f in LINE_FIELDS} for line in source.lines.all()],
        steps=[{f: getattr(step, f) for f in STEP_FIELDS} for step in source.steps.all()],
        copied_from=source,
    )
    return copy


def can_approve(actor: User | None) -> bool:
    """Reçete sürümü onaylama yetkisi: planlama, laboratuvar (ve admin)."""
    actor = _actor(actor)
    return (
        actor is not None
        and actor.is_active
        and (actor.is_admin or actor.has_role(*APPROVER_ROLES))
    )


def _set_status(
    version: RecipeVersion, to_status: str, actor: User | None, note: str, **extra: Any
) -> None:
    from_status = version.status
    recipe_version_states.assert_can_transition(from_status, to_status)
    version.status = to_status
    version.updated_by = actor
    for name, value in extra.items():
        setattr(version, name, value)
    version.save(update_fields=["status", "updated_by", "updated_at", *extra])
    log_change(
        actor, version, AuditLog.Action.STATUS_CHANGE, {"status": [from_status, to_status]}, note
    )
    events.publish(
        recipe_version_states.event_name(to_status),
        {
            "model": version._meta.label_lower,
            "id": version.pk,
            "recipe_id": version.recipe_id,
            "recipe_code": version.recipe.code,
            "version_no": version.version_no,
            "from_status": from_status,
            "to_status": to_status,
        },
        actor,
    )


@transaction.atomic
def approve_version(actor: User | None, version: RecipeVersion, note: str = "") -> RecipeVersion:
    """Taslak sürümü onaylar (rol: planlama veya laboratuvar). Reçetenin önceki onaylı sürümü
    OBSOLETE olur.

    Kontroller: sürüm taslak, en az bir satır var, reçete ve ürün aktif, tüm satır
    malzemeleri aktif ve birimleri temel birime çevrilebilir. Olaylar:
    `recipe_version.obsolete` (önceki), `recipe_version.approved`.
    """
    actor = _actor(actor)
    if not can_approve(actor):
        raise PermissionDenied("Reçete sürümünü yalnızca planlama ya da laboratuvar onaylar.")
    # Aynı reçetede eşzamanlı iki onayı sıraya sokmak için önce reçete kilitlenir.
    recipe = (
        Recipe.objects.select_for_update(of=("self",))
        .select_related("product")
        .get(pk=version.recipe_id)
    )
    version = _lock_version(version)
    _require_draft(version)
    if not recipe.is_active:
        raise BusinessRuleError("inactive_reference", "Pasif reçetenin sürümü onaylanamaz.")
    _validate_product(recipe.product)
    lines = list(version.lines.select_related("material__base_unit", "unit"))
    if not lines:
        raise BusinessRuleError("version_has_no_lines", "Satırı olmayan sürüm onaylanamaz.")
    for line in lines:
        _validate_line_material(line.material, recipe)
        masterdata.to_base_quantity(line.material, line.quantity, line.unit)

    previous = RecipeVersion.objects.select_for_update().filter(
        recipe=recipe, status=RecipeVersion.Status.APPROVED
    )
    now = timezone.now()
    for old in previous:
        _set_status(
            old,
            RecipeVersion.Status.OBSOLETE,
            actor,
            f"v{version.version_no} onaylandı",
            obsoleted_at=now,
        )
    _set_status(
        version, RecipeVersion.Status.APPROVED, actor, note, approved_by=actor, approved_at=now
    )
    return version


# --- satırlar ve adımlar ---------------------------------------------------------------------


def _validate_line_material(material: Material, recipe: Recipe) -> None:
    if material.material_type not in INGREDIENT_TYPES:
        raise BusinessRuleError(
            "invalid_ingredient", "Reçete satırında yalnızca hammadde ya da dökme ürün kullanılır."
        )
    if not material.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif malzeme seçilemez: {material}.")
    if material.pk == recipe.product_id:
        raise BusinessRuleError(
            "recipe_self_reference", "Reçetenin ürünü kendi satırında kullanılamaz."
        )


def _validate_line(line: RecipeLine) -> None:
    _validate_line_material(line.material, line.version.recipe)
    if not line.unit.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif birim seçilemez: {line.unit}.")
    # Birim temel birime çevrilebilmeli (yoksa no_conversion).
    masterdata.to_base_quantity(line.material, line.quantity, line.unit)


def _pick(data: Mapping[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


@transaction.atomic
def add_line(actor: User | None, version: RecipeVersion, data: Mapping[str, Any]) -> RecipeLine:
    """Taslak sürüme satır ekler. Sıra verilmezse sona eklenir."""
    version = _lock_version(version)
    _require_draft(version)
    values = _pick(data, LINE_FIELDS)
    if values.get("sequence") is None:
        values["sequence"] = _next_number(RecipeLine, version)
    line = RecipeLine(version=version, **values)
    _validate_line(line)
    return _clean_save(line, actor)


@transaction.atomic
def update_line(actor: User | None, line: RecipeLine, data: Mapping[str, Any]) -> RecipeLine:
    """Taslak sürümdeki satırı günceller."""
    values = _pick(data, LINE_FIELDS)
    version = _lock_version(line.version)
    _require_draft(version)
    line = RecipeLine.objects.select_for_update().get(pk=line.pk)
    for name, value in values.items():
        setattr(line, name, value)
    _validate_line(line)
    return _clean_save(line, actor)


def _remove(actor: User | None, item: RecipeLine | RecipeStep, label: str) -> None:
    version = _lock_version(item.version)
    _require_draft(version)
    item = type(item).objects.select_for_update().get(pk=item.pk)  # bayat nesne değil, güncel hali
    values = snapshot(item)
    log_change(
        _actor(actor),
        version,
        AuditLog.Action.UPDATE,
        {label: [values, None]},
        f"{item._meta.verbose_name} silindi (taslak)",
    )
    item.delete()


@transaction.atomic
def remove_line(actor: User | None, line: RecipeLine) -> None:
    """Taslak sürümden satırı kaldırır; silinen satır sürümün denetim kaydına yazılır.

    Onaylı ya da geçersiz sürümün satırı kaldırılamaz.
    """
    _remove(actor, line, "line")


@transaction.atomic
def add_step(actor: User | None, version: RecipeVersion, data: Mapping[str, Any]) -> RecipeStep:
    """Taslak sürüme proses adımı ekler. Sıra verilmezse sona eklenir."""
    version = _lock_version(version)
    _require_draft(version)
    values = _pick(data, STEP_FIELDS)
    if values.get("sequence") is None:
        values["sequence"] = _next_number(RecipeStep, version)
    return _clean_save(RecipeStep(version=version, **values), actor)


@transaction.atomic
def update_step(actor: User | None, step: RecipeStep, data: Mapping[str, Any]) -> RecipeStep:
    """Taslak sürümdeki proses adımını günceller."""
    values = _pick(data, STEP_FIELDS)
    version = _lock_version(step.version)
    _require_draft(version)
    step = RecipeStep.objects.select_for_update().get(pk=step.pk)
    for name, value in values.items():
        setattr(step, name, value)
    return _clean_save(step, actor)


@transaction.atomic
def remove_step(actor: User | None, step: RecipeStep) -> None:
    """Taslak sürümden proses adımını kaldırır (denetim kaydıyla)."""
    _remove(actor, step, "step")


# --- ölçekleme -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaledRequirement:
    """Ölçeklenmiş ihtiyaç: malzeme, temel birimde miktar ve tartım toleransı."""

    line: RecipeLine
    material: Material
    quantity: Decimal  # temel birimde, 4 basamağa yuvarlı
    unit: UnitOfMeasure  # malzemenin temel birimi
    tolerance_pct: Decimal
    sequence: int
    is_water: bool


def scale_requirements(
    version: RecipeVersion, target_qty: Decimal, target_unit: UnitOfMeasure
) -> list[ScaledRequirement]:
    """Sürümü hedef üretim miktarına ölçekler; her satırın ihtiyacını temel birimde döner.

    Oran = hedef miktar (şarj birimine çevrilmiş) / şarj miktarı. Hedef birim ürünün birimlerine
    çevrilebilir olmalıdır (ör. reçete KG, hedef LT ise ürünün yoğunluğu gerekir).
    """
    if target_qty <= 0:
        raise BusinessRuleError("invalid_quantity", "Hedef miktar sıfırdan büyük olmalıdır.")
    version = RecipeVersion.objects.select_related("recipe__product__base_unit", "batch_unit").get(
        pk=version.pk
    )
    product = version.recipe.product
    target_in_batch_unit = masterdata.convert_quantity(
        product, target_qty, target_unit, version.batch_unit
    )
    ratio = target_in_batch_unit / version.batch_size
    result = []
    for line in version.lines.select_related("material__base_unit", "unit").order_by("sequence"):
        in_base = masterdata.to_base_quantity(line.material, line.quantity, line.unit)
        result.append(
            ScaledRequirement(
                line=line,
                material=line.material,
                quantity=(in_base * ratio).quantize(QUANTITY_STEP, ROUND_HALF_UP),
                unit=line.material.base_unit,
                tolerance_pct=line.tolerance_pct,
                sequence=line.sequence,
                is_water=line.is_water,
            )
        )
    return result
