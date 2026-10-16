"""Kalite servisleri: test tanımı, spesifikasyon, numune, test sonucu ve kalite kararı.

Kurallar (Faz 2, Adım 2.1):
- Lot serbest bırakma ve ret **yalnızca** `decide` ile olur (`inventory.release_lot` /
  `reject_lot` kalite kararıyla çağrılır). Elle serbest bırakma yalnızca admin, gerekçeli (D-5).
- Zorunlu testlerin hepsi girilmeden karar verilemez; spesifikasyon dışı sonuç varken "Serbest"
  verilemez. Şartlı kabul yönetim onayı ister.
- Sonuç düzeltmesi yeni kayıttır; eski sonuç `superseded_by` ile bağlanır, silinmez.
- Spesifikasyon sürümlüdür: aynı malzeme ve aşamada tek onaylı sürüm; onaylı sürüm değiştirilmez.
- `open_sample` diğer modüllerden çağrılabilir (mal kabul, şarj bitişi, dolum); yetkiyi çağıran
  denetler. Laboratuvarın elle açtığı numune `create_sample` ile.
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core import events
from apps.core.audit import log_change, snapshot
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import LABORATUVAR, YONETIM
from apps.core.services import (
    cancel_document,
    create_document,
    save_with_audit,
    transition_status,
)
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceiptLine, Lot, StockMovement
from apps.inventory.services import lot_payload
from apps.inventory.state import lot_states
from apps.masterdata import services as masterdata
from apps.masterdata.models import Location, Material
from apps.quality.models import (
    QualityDecision,
    Sample,
    SampleStage,
    Specification,
    SpecificationLine,
    TestDefinition,
    TestResult,
)
from apps.quality.state import sample_states, specification_states

LAB_ROLES = (LABORATUVAR,)
APPROVAL_ROLES = (YONETIM,)
# Spesifikasyon tanımlanabilen malzemeler. Ambalaj da giriş kontrolüne girebildiği için dahil.
SPEC_MATERIAL_TYPES = (
    Material.Type.RAW,
    Material.Type.PACKAGING,
    Material.Type.BULK,
    Material.Type.FINISHED,
)
# Numune yalnızca kararı verilmemiş lota açılır (serbest lot önce bloke edilir).
SAMPLEABLE_LOT_STATUSES = (Lot.Status.QUARANTINE, Lot.Status.BLOCKED)
OPEN_SAMPLE_STATUSES = (
    Sample.Status.PENDING,
    Sample.Status.IN_TEST,
    Sample.Status.AWAITING_APPROVAL,
)
# Ara kontrol (şarj sırasında) numunesinin kararı lotu değiştirmez; yalnızca uygun / uygun değil.
IN_PROCESS_DECISIONS = (QualityDecision.Decision.RELEASE, QualityDecision.Decision.REJECT)

LINE_FIELDS = (
    "sequence",
    "test",
    "min_value",
    "max_value",
    "target_value",
    "text_expected",
    "is_mandatory",
)
TEST_FIELDS = ("code", "name", "result_type", "unit", "method", "decimal_places")

Decision = QualityDecision.Decision
Approval = QualityDecision.Approval
ResultType = TestDefinition.ResultType


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def _require_role(actor: User | None, roles: tuple[str, ...], message: str) -> None:
    if not user_has_role(actor, roles):
        raise PermissionDenied(message)


def _pick(data: Mapping[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


# --- test tanımı -----------------------------------------------------------------------------


@transaction.atomic
def create_test_definition(actor: User | None, data: Mapping[str, Any]) -> TestDefinition:
    """Yeni test tanımı (rol: laboratuvar)."""
    _require_role(actor, LAB_ROLES, "Test tanımını yalnızca laboratuvar yazar.")
    return masterdata.create_record(actor, TestDefinition, _pick(data, TEST_FIELDS))


@transaction.atomic
def update_test_definition(
    actor: User | None, test: TestDefinition, data: Mapping[str, Any]
) -> TestDefinition:
    """Test tanımını günceller (rol: laboratuvar). Spesifikasyonda kullanılan testin sonuç türü
    değiştirilemez (girilmiş sonuçların anlamı değişir)."""
    _require_role(actor, LAB_ROLES, "Test tanımını yalnızca laboratuvar yazar.")
    values = _pick(data, TEST_FIELDS)
    new_type = values.get("result_type")
    if (
        new_type is not None
        and new_type != test.result_type
        and SpecificationLine.objects.filter(test=test).exists()
    ):
        raise BusinessRuleError(
            "test_in_use", "Spesifikasyonda kullanılan testin sonuç türü değiştirilemez."
        )
    return masterdata.update_record(actor, test, values)


@transaction.atomic
def set_test_active(actor: User | None, test: TestDefinition, active: bool) -> TestDefinition:
    """Testi aktif ya da pasif yapar (rol: laboratuvar). Pasif test yeni satırda seçilemez."""
    _require_role(actor, LAB_ROLES, "Test tanımını yalnızca laboratuvar yazar.")
    return masterdata.set_active(actor, test, active)


# --- spesifikasyon ---------------------------------------------------------------------------


def _lock_spec(spec: Specification) -> Specification:
    return (
        Specification.objects.select_for_update(of=("self",))
        .select_related("material")
        .get(pk=spec.pk)
    )


def _require_draft(spec: Specification) -> None:
    if spec.status != Specification.Status.DRAFT:
        raise BusinessRuleError(
            "specification_locked",
            f"{spec} {specification_states.label(spec.status).lower()}; değiştirilemez. "
            "Değişiklik için sürümü kopyalayın.",
        )


def _validate_spec_material(material: Material) -> None:
    if material.material_type not in SPEC_MATERIAL_TYPES:
        raise BusinessRuleError(
            "invalid_spec_material", "Bu malzeme türü için spesifikasyon tanımlanamaz."
        )
    if not material.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif malzeme seçilemez: {material}.")


def _validate_line(line: SpecificationLine) -> None:
    test = line.test
    if not test.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif test seçilemez: {test}.")
    if test.result_type == ResultType.NUMERIC:
        if line.min_value is None and line.max_value is None:
            raise BusinessRuleError(
                "spec_limits_required",
                f"{test.code} sayısal bir test; alt ya da üst sınırdan en az biri girilmelidir.",
            )
        if line.text_expected:
            raise BusinessRuleError(
                "spec_text_not_allowed", f"{test.code} sayısal bir test; beklenen metin girilmez."
            )
    elif line.min_value is not None or line.max_value is not None or line.target_value is not None:
        raise BusinessRuleError(
            "spec_limits_not_allowed", f"{test.code} sayısal değil; sınır değeri girilmez."
        )


def _clean_save[M: Specification | SpecificationLine](instance: M, actor: User | None) -> M:
    instance.full_clean(exclude=["created_by", "updated_by"])
    return save_with_audit(instance, actor)


def _next_line_number(spec: Specification) -> int:
    current = SpecificationLine.objects.filter(specification=spec).aggregate(m=Max("sequence"))
    return (current["m"] or 0) + 1


@transaction.atomic
def create_specification(
    actor: User | None,
    *,
    material: Material,
    sample_stage: str,
    change_note: str = "",
    lines: Iterable[Mapping[str, Any]] = (),
    copied_from: Specification | None = None,
) -> Specification:
    """Malzeme + aşama için yeni taslak sürüm açar (rol: laboratuvar); sürüm no bir sonrakidir."""
    _require_role(actor, LAB_ROLES, "Spesifikasyonu yalnızca laboratuvar yazar.")
    _validate_spec_material(material)
    if sample_stage not in SampleStage.values:
        raise BusinessRuleError("invalid_stage", "Geçersiz numune aşaması.")
    # Aynı malzeme+aşamada eşzamanlı iki sürüm açılışını sıraya sokar.
    Material.objects.select_for_update().get(pk=material.pk)
    last = (
        Specification.objects.filter(material=material, sample_stage=sample_stage).aggregate(
            m=Max("version_no")
        )["m"]
        or 0
    )
    spec = _clean_save(
        Specification(
            material=material,
            sample_stage=sample_stage,
            version_no=last + 1,
            change_note=change_note,
            copied_from=copied_from,
        ),
        actor,
    )
    for line in lines:
        add_spec_line(actor, spec, line)
    return spec


@transaction.atomic
def update_specification(
    actor: User | None, spec: Specification, data: Mapping[str, Any]
) -> Specification:
    """Taslak sürümün değişiklik notunu günceller (rol: laboratuvar)."""
    _require_role(actor, LAB_ROLES, "Spesifikasyonu yalnızca laboratuvar yazar.")
    values = _pick(data, ("change_note",))
    spec = _lock_spec(spec)
    _require_draft(spec)
    for name, value in values.items():
        setattr(spec, name, value)
    return _clean_save(spec, actor)


@transaction.atomic
def copy_specification(
    actor: User | None, spec: Specification, change_note: str = ""
) -> Specification:
    """Sürümü satırlarıyla yeni taslak sürüme kopyalar (onaylı sürümü değiştirmenin tek yolu)."""
    source = Specification.objects.select_related("material").get(pk=spec.pk)
    return create_specification(
        actor,
        material=source.material,
        sample_stage=source.sample_stage,
        change_note=change_note,
        lines=[{f: getattr(line, f) for f in LINE_FIELDS} for line in source.lines.all()],
        copied_from=source,
    )


def _set_spec_status(
    spec: Specification, to_status: str, actor: User | None, note: str, **extra: Any
) -> None:
    from_status = spec.status
    specification_states.assert_can_transition(from_status, to_status)
    spec.status = to_status
    spec.updated_by = actor
    for name, value in extra.items():
        setattr(spec, name, value)
    spec.save(update_fields=["status", "updated_by", "updated_at", *extra])
    log_change(
        actor, spec, AuditLog.Action.STATUS_CHANGE, {"status": [from_status, to_status]}, note
    )
    events.publish(
        specification_states.event_name(to_status),
        {
            "model": spec._meta.label_lower,
            "id": spec.pk,
            "repr": str(spec),
            "material_code": spec.material.code,
            "sample_stage": spec.sample_stage,
            "version_no": spec.version_no,
            "from_status": from_status,
            "to_status": to_status,
        },
        actor,
    )


@transaction.atomic
def approve_specification(actor: User | None, spec: Specification, note: str = "") -> Specification:
    """Taslak sürümü onaylar (rol: laboratuvar). Aynı malzeme ve aşamanın önceki onaylı sürümü
    geçersiz olur. En az bir satır olmalı, testler ve malzeme aktif olmalıdır. Açık numuneler
    açıldıkları sürümle kalır."""
    _require_role(actor, LAB_ROLES, "Spesifikasyonu yalnızca laboratuvar onaylar.")
    actor = _actor(actor)
    Material.objects.select_for_update().get(pk=spec.material_id)
    spec = _lock_spec(spec)
    _require_draft(spec)
    _validate_spec_material(spec.material)
    lines = list(spec.lines.select_related("test"))
    if not lines:
        raise BusinessRuleError("specification_has_no_lines", "Satırı olmayan sürüm onaylanamaz.")
    for line in lines:
        _validate_line(line)
    previous = Specification.objects.select_for_update().filter(
        material=spec.material,
        sample_stage=spec.sample_stage,
        status=Specification.Status.APPROVED,
    )
    now = timezone.now()
    for old in previous.select_related("material"):
        _set_spec_status(
            old,
            Specification.Status.OBSOLETE,
            actor,
            f"v{spec.version_no} onaylandı",
            obsoleted_at=now,
        )
    _set_spec_status(
        spec, Specification.Status.APPROVED, actor, note, approved_by=actor, approved_at=now
    )
    return spec


@transaction.atomic
def add_spec_line(
    actor: User | None, spec: Specification, data: Mapping[str, Any]
) -> SpecificationLine:
    """Taslak sürüme satır ekler (rol: laboratuvar). Sıra verilmezse sona eklenir."""
    _require_role(actor, LAB_ROLES, "Spesifikasyonu yalnızca laboratuvar yazar.")
    spec = _lock_spec(spec)
    _require_draft(spec)
    values = _pick(data, LINE_FIELDS)
    if values.get("sequence") is None:
        values["sequence"] = _next_line_number(spec)
    if values.get("text_expected") is None:
        values["text_expected"] = ""
    line = SpecificationLine(specification=spec, **values)
    _validate_line(line)
    return _clean_save(line, actor)


@transaction.atomic
def update_spec_line(
    actor: User | None, line: SpecificationLine, data: Mapping[str, Any]
) -> SpecificationLine:
    """Taslak sürümdeki satırı günceller (rol: laboratuvar)."""
    _require_role(actor, LAB_ROLES, "Spesifikasyonu yalnızca laboratuvar yazar.")
    values = _pick(data, LINE_FIELDS)
    spec = _lock_spec(line.specification)
    _require_draft(spec)
    line = SpecificationLine.objects.select_for_update().get(pk=line.pk)
    for name, value in values.items():
        setattr(line, name, "" if name == "text_expected" and value is None else value)
    _validate_line(line)
    return _clean_save(line, actor)


@transaction.atomic
def remove_spec_line(actor: User | None, line: SpecificationLine) -> None:
    """Taslak sürümden satırı kaldırır; silinen satır sürümün denetim kaydına yazılır (reçete
    taslağındaki gibi). Onaylı ya da geçersiz sürümün satırı kaldırılamaz."""
    _require_role(actor, LAB_ROLES, "Spesifikasyonu yalnızca laboratuvar yazar.")
    spec = _lock_spec(line.specification)
    _require_draft(spec)
    line = SpecificationLine.objects.select_for_update().get(pk=line.pk)
    log_change(
        _actor(actor),
        spec,
        AuditLog.Action.UPDATE,
        {"line": [snapshot(line), None]},
        "spesifikasyon satırı silindi (taslak)",
    )
    line.delete()


def approved_specification(material: Material, stage: str) -> Specification | None:
    """Malzeme ve aşamanın onaylı spesifikasyon sürümü (yoksa None). İade numunesinde iade
    spesifikasyonu yoksa son kontrol spesifikasyonu kullanılır (Faz 3, Adım 3.3)."""
    spec = Specification.objects.filter(
        material=material, sample_stage=stage, status=Specification.Status.APPROVED
    ).first()
    if spec is None and stage == SampleStage.RETURN:
        return approved_specification(material, SampleStage.FINAL)
    return spec


# --- numune ----------------------------------------------------------------------------------


def sample_payload(sample: Sample, **extra: Any) -> dict[str, Any]:
    """Numune olaylarının ek alanları: aşama ve lot sözlüğü (olay sözleşmesi)."""
    lot = sample.lot
    return {
        "stage": sample.stage,
        "lot_no": lot.lot_no,
        "material_code": lot.material.code,
        "material_name": lot.material.name,
        "material_type": lot.material.material_type,
        "lot": lot_payload(lot),
        **extra,
    }


def _lock_sample(sample: Sample) -> Sample:
    return (
        Sample.objects.select_for_update(of=("self",))
        .select_related("lot__material", "specification")
        .get(pk=sample.pk)
    )


def open_sample(
    actor: User | None,
    lot: Lot,
    stage: str,
    *,
    origin: str = Sample.Origin.MANUAL,
    taken_by: User | None = None,
    taken_at: Any = None,
    retain_location: Location | None = None,
    note: str = "",
) -> Sample:
    """Lota numune açar (`NM-`). **Diğer modüllerden çağrılabilir** (mal kabul, şarj bitişi,
    dolum); yetkiyi çağıran denetler. Spesifikasyon o anki onaylı sürüme sabitlenir (yoksa boş
    kalır). Lot karantinada ya da bloke olmalı; aynı lot ve aşamada açık numune varsa reddedilir.
    Olay `sample.created` laboratuvara "Numune analizi" görevi açar."""
    with transaction.atomic():
        lot = Lot.objects.select_for_update().select_related("material").get(pk=lot.pk)
        if stage not in SampleStage.values:
            raise BusinessRuleError("invalid_stage", "Geçersiz numune aşaması.")
        if lot.status not in SAMPLEABLE_LOT_STATUSES:
            raise BusinessRuleError(
                "lot_not_sampleable",
                f"Lot {lot.lot_no} {lot_states.label(lot.status).lower()}; numune "
                "yalnızca karantinadaki ya da bloke lota açılır (serbest lotu önce bloke edin).",
            )
        if Sample.objects.filter(lot=lot, stage=stage, status__in=OPEN_SAMPLE_STATUSES).exists():
            raise BusinessRuleError(
                "sample_already_open", f"Lot {lot.lot_no} için bu aşamada açık numune var."
            )
        if retain_location is not None and not retain_location.is_active:
            raise BusinessRuleError(
                "inactive_reference", f"Pasif lokasyon seçilemez: {retain_location}."
            )
        sample = Sample(
            lot=lot,
            stage=stage,
            origin=origin,
            specification=approved_specification(lot.material, stage),
            taken_by=taken_by,
            taken_at=taken_at,
            retain_location=retain_location,
            note=note.strip(),
        )
        return create_document(
            sample,
            actor,
            prefix="NM",
            machine=sample_states,
            event_payload=sample_payload(sample, origin=origin),
        )


@transaction.atomic
def create_sample(actor: User | None, lot: Lot, stage: str, **kwargs: Any) -> Sample:
    """Laboratuvarın elle açtığı numune (rol: laboratuvar); kurallar `open_sample` ile aynı."""
    _require_role(actor, LAB_ROLES, "Numuneyi yalnızca laboratuvar açar.")
    kwargs.setdefault("taken_by", _actor(actor))
    if kwargs.get("taken_by") is not None and kwargs.get("taken_at") is None:
        kwargs["taken_at"] = timezone.now()
    return open_sample(actor, lot, stage, origin=Sample.Origin.MANUAL, **kwargs)


def _require_open(sample: Sample, what: str) -> None:
    if not sample.is_open:
        raise BusinessRuleError(
            "sample_not_open",
            f"{sample.number} {sample_states.label(sample.status).lower()}; {what}.",
        )


@transaction.atomic
def update_sample(actor: User | None, sample: Sample, data: Mapping[str, Any]) -> Sample:
    """Numune alma bilgilerini günceller (rol: laboratuvar): alan, zaman, şahit numune yeri, not.
    Karar verilmiş numune değiştirilemez."""
    _require_role(actor, LAB_ROLES, "Numuneyi yalnızca laboratuvar günceller.")
    values = _pick(data, ("taken_by", "taken_at", "retain_location", "note"))
    sample = _lock_sample(sample)
    _require_open(sample, "değiştirilemez")
    for name, value in values.items():
        setattr(sample, name, value)
    if sample.retain_location is not None and not sample.retain_location.is_active:
        raise BusinessRuleError(
            "inactive_reference", f"Pasif lokasyon seçilemez: {sample.retain_location}."
        )
    return save_with_audit(sample, actor)


@transaction.atomic
def assign_specification(actor: User | None, sample: Sample, spec: Specification) -> Sample:
    """Numuneye spesifikasyon atar (rol: laboratuvar): onaylı, numunenin malzemesi ve aşamasına
    ait olmalı. Sonuç girilmiş numunenin spesifikasyonu değiştirilemez."""
    _require_role(actor, LAB_ROLES, "Spesifikasyonu yalnızca laboratuvar atar.")
    sample = _lock_sample(sample)
    _require_open(sample, "spesifikasyon atanamaz")
    spec = Specification.objects.get(pk=spec.pk)
    if spec.status != Specification.Status.APPROVED:
        raise BusinessRuleError(
            "specification_not_approved", "Numuneye yalnızca onaylı spesifikasyon atanır."
        )
    if spec.material_id != sample.lot.material_id or spec.sample_stage != sample.stage:
        raise BusinessRuleError(
            "specification_mismatch",
            "Spesifikasyon numunenin malzemesine ve aşamasına ait olmalıdır.",
        )
    if sample.results.exists():
        raise BusinessRuleError(
            "sample_has_results", "Sonuç girilmiş numunenin spesifikasyonu değiştirilemez."
        )
    sample.specification = spec
    return save_with_audit(sample, actor)


@transaction.atomic
def cancel_sample(actor: User | None, sample: Sample, reason: str) -> Sample:
    """Yanlış açılan numuneyi iptal eder (rol: laboratuvar; karar verilmemiş numune). Olay
    `sample.cancelled` numune görevini kapatır."""
    _require_role(actor, LAB_ROLES, "Numuneyi yalnızca laboratuvar iptal eder.")
    sample = _lock_sample(sample)
    if sample.status == Sample.Status.AWAITING_APPROVAL:
        raise BusinessRuleError(
            "sample_awaiting_approval", "Şartlı kabul onayı bekleyen numune iptal edilemez."
        )
    return cancel_document(sample, actor, reason=reason, machine=sample_states)


# --- test sonucu -----------------------------------------------------------------------------


def evaluate(
    line: SpecificationLine,
    *,
    numeric_value: Decimal | None,
    text_value: str,
    passed: bool | None,
) -> tuple[Decimal | None, str, bool | None, bool]:
    """Sonucu test türüne göre doğrular ve spesifikasyona uygunluğunu hesaplar.

    - Sayısal: değer zorunlu; alt ≤ değer ≤ üst (boş sınır açık).
    - Uygun / uygun değil: `passed` zorunlu; uygunluk = `passed`.
    - Metin: metin zorunlu; `passed` verilirse laboratuvarın kararıdır, verilmezse beklenen
      metinle (büyük/küçük harf ve baştaki/sondaki boşluklar önemsiz) karşılaştırılır.
    Dönüş: (sayısal, metin, uygun, spesifikasyona uygun).
    """
    test = line.test
    text_value = (text_value or "").strip()
    if test.result_type == ResultType.NUMERIC:
        if numeric_value is None:
            raise BusinessRuleError("result_value_required", f"{test.code} için değer girilmeli.")
        within = (line.min_value is None or numeric_value >= line.min_value) and (
            line.max_value is None or numeric_value <= line.max_value
        )
        return numeric_value, text_value, None, within
    if test.result_type == ResultType.PASS_FAIL:
        if passed is None:
            raise BusinessRuleError(
                "result_value_required", f"{test.code} için uygun / uygun değil seçilmeli."
            )
        return None, text_value, passed, passed
    if not text_value:
        raise BusinessRuleError("result_value_required", f"{test.code} için sonuç yazılmalı.")
    if passed is None:
        expected = line.text_expected.strip().casefold()
        passed = not expected or text_value.casefold() == expected
    return None, text_value, passed, passed


def current_results(sample: Sample) -> list[TestResult]:
    """Numunenin geçerli (düzeltilmemiş) sonuçları."""
    return list(sample.results.filter(superseded_by__isnull=True).select_related("spec_line__test"))


@transaction.atomic
def record_result(
    actor: User | None,
    sample: Sample,
    spec_line: SpecificationLine,
    *,
    numeric_value: Decimal | None = None,
    text_value: str = "",
    passed: bool | None = None,
    instrument: str = "",
    measured_at: Any = None,
    note: str = "",
) -> TestResult:
    """Test sonucu girer (rol: laboratuvar). Uygunluk spesifikasyona göre hesaplanır.

    Satırın geçerli sonucu varsa bu bir **düzeltmedir**: not (düzeltme nedeni) zorunludur, yeni
    kayıt yazılır ve eski kayıt `superseded_by` ile ona bağlanır (silinmez). İlk sonuç numuneyi
    "Testte" durumuna geçirir; numune alma bilgisi boşsa sonucu giren ve ölçüm zamanıyla doldurulur.
    """
    _require_role(actor, LAB_ROLES, "Test sonucunu yalnızca laboratuvar girer.")
    actor = _actor(actor)
    sample = _lock_sample(sample)
    _require_open(sample, "sonuç girilemez")
    if sample.specification_id is None:
        raise BusinessRuleError(
            "sample_has_no_specification", "Numuneye önce spesifikasyon atanmalıdır."
        )
    line = SpecificationLine.objects.select_related("test").get(pk=spec_line.pk)
    if line.specification_id != sample.specification_id:
        raise BusinessRuleError(
            "spec_line_not_in_sample", "Test satırı numunenin spesifikasyonuna ait değil."
        )
    numeric, text, ok, within = evaluate(
        line, numeric_value=numeric_value, text_value=text_value, passed=passed
    )
    note = note.strip()
    previous = (
        TestResult.objects.select_for_update()
        .filter(sample=sample, spec_line=line, superseded_by__isnull=True)
        .first()
    )
    if previous is not None and not note:
        raise BusinessRuleError(
            "correction_reason_required",
            f"{line.test.code} için sonuç zaten var; düzeltme nedeni girilmelidir.",
        )
    result = TestResult(
        sample=sample,
        spec_line=line,
        numeric_value=numeric,
        text_value=text,
        passed=ok,
        is_within_spec=within,
        measured_by=actor,
        measured_at=measured_at or timezone.now(),
        instrument=instrument.strip(),
        note=note,
    )
    if previous is not None:
        _supersede(actor, previous, result)
    else:
        save_with_audit(result, actor)
    if sample.taken_at is None:
        # Otomatik açılan numune: ilk sonucu giren numuneyi almış sayılır.
        Sample.objects.filter(pk=sample.pk).update(
            taken_by=sample.taken_by or actor, taken_at=result.measured_at
        )
    if sample.status == Sample.Status.PENDING:
        transition_status(
            sample,
            Sample.Status.IN_TEST,
            actor,
            machine=sample_states,
            event_payload=sample_payload(sample),
        )
    return result


def _supersede(actor: User | None, previous: TestResult, result: TestResult) -> None:
    """Eski sonucu yenisiyle değiştirir. "Tek geçerli sonuç" kısıtı yalnızca `superseded_by` boş
    kayıtları sayar: eski kayıt önce geçici olarak kendisine bağlanır, yeni kayıt yazılır, sonra
    eski kayıt yeni kayda bağlanır (hepsi aynı transaction'da)."""
    TestResult.objects.filter(pk=previous.pk).update(superseded_by=previous.pk)
    save_with_audit(result, actor)
    TestResult.objects.filter(pk=previous.pk).update(superseded_by=result.pk)
    log_change(
        actor,
        previous,
        AuditLog.Action.UPDATE,
        {"superseded_by": [None, result.pk]},
        f"Sonuç düzeltildi: {result.note}",
    )


# --- karar -----------------------------------------------------------------------------------


def missing_mandatory_tests(sample: Sample) -> list[SpecificationLine]:
    """Geçerli sonucu girilmemiş zorunlu spesifikasyon satırları."""
    if sample.specification_id is None:
        return []
    done = {r.spec_line_id for r in current_results(sample)}
    return [
        line
        for line in SpecificationLine.objects.filter(
            specification_id=sample.specification_id, is_mandatory=True
        )
        .select_related("test")
        .order_by("sequence")
        if line.pk not in done
    ]


def out_of_spec_results(sample: Sample) -> list[TestResult]:
    """Spesifikasyon dışı geçerli sonuçlar."""
    return [r for r in current_results(sample) if not r.is_within_spec]


def default_release_location(lot: Lot) -> Location | None:
    """Serbest bırakılan lotun karantinadan taşınacağı varsayılan lokasyon: lotu oluşturan mal
    kabulün depo lokasyonu; yoksa (ör. iade edilen mamul) lotun en son girdiği karantina dışı
    aktif lokasyon."""
    line = (
        GoodsReceiptLine.objects.filter(created_lot=lot)
        .select_related("receipt__storage_location")
        .first()
    )
    if line is not None and line.receipt.storage_location is not None:
        return line.receipt.storage_location
    movement = (
        StockMovement.objects.filter(lot=lot, quantity__gt=0, location__is_active=True)
        .exclude(location__location_type=Location.Type.QUARANTINE)
        .select_related("location")
        .order_by("-created_at", "-id")
        .first()
    )
    return movement.location if movement is not None else None


def _apply_to_lot(actor: User | None, sample: Sample, decision: QualityDecision, note: str) -> None:
    """Yürürlüğe giren kararı lota uygular (ara kontrol numunesinde lot değişmez)."""
    if sample.stage == SampleStage.IN_PROCESS:
        return
    lot = sample.lot
    if decision.decision in (Decision.RELEASE, Decision.CONDITIONAL_RELEASE):
        target = decision.release_location or default_release_location(lot)
        inventory.release_lot(actor, lot, note, to_location=target, quality_decision=True)
    elif decision.decision == Decision.REJECT:
        inventory.reject_lot(actor, lot, note, quality_decision=True)
    elif decision.decision == Decision.REWORK:
        if lot.status != Lot.Status.BLOCKED:
            inventory.block_lot(actor, lot, note, quality_decision=True)


def _validate_decision(sample: Sample, decision: str, reason: str) -> None:
    if decision not in Decision.values:
        raise BusinessRuleError("invalid_decision", "Geçersiz kalite kararı.")
    if sample.specification_id is None:
        raise BusinessRuleError(
            "sample_has_no_specification",
            "Numuneye spesifikasyon atanmadan karar verilemez.",
        )
    missing = missing_mandatory_tests(sample)
    if missing:
        codes = ", ".join(line.test.code for line in missing)
        raise BusinessRuleError(
            "mandatory_tests_missing", f"Zorunlu testlerin sonucu girilmedi: {codes}."
        )
    if sample.stage == SampleStage.IN_PROCESS:
        if decision not in IN_PROCESS_DECISIONS:
            raise BusinessRuleError(
                "invalid_in_process_decision",
                "Şarj sırası numunesinde karar yalnızca uygun (serbest) ya da uygun değil (ret) "
                "olur; lot durumu değişmez.",
            )
    else:
        lot = sample.lot
        if lot.status not in SAMPLEABLE_LOT_STATUSES:
            raise BusinessRuleError(
                "lot_already_decided",
                f"Lot {lot.lot_no} {lot_states.label(lot.status).lower()}; karar verilemez.",
            )
        if (
            decision == Decision.REWORK
            and lot.material.material_type != Material.Type.BULK
            and sample.stage != SampleStage.RETURN
        ):
            raise BusinessRuleError(
                "rework_not_allowed",
                "Yeniden işleme kararı yalnızca dökme (bulk) lota ya da iade numunesine verilir.",
            )
    out = out_of_spec_results(sample)
    if decision == Decision.RELEASE and out:
        codes = ", ".join(r.spec_line.test.code for r in out)
        raise BusinessRuleError(
            "out_of_spec_release",
            f"Spesifikasyon dışı sonuç varken serbest bırakılamaz ({codes}); şartlı kabul, ret "
            "ya da yeniden işleme kararı verin.",
        )
    if decision != Decision.RELEASE and not reason:
        raise BusinessRuleError("decision_reason_required", "Karar gerekçesi girilmelidir.")


@transaction.atomic
def decide(
    actor: User | None,
    sample: Sample,
    decision: str,
    reason: str = "",
    *,
    release_location: Location | None = None,
) -> QualityDecision:
    """Kalite kararı verir (rol: laboratuvar). **Lot serbest bırakma ve reddin tek yolu.**

    - Zorunlu testlerin hepsi girilmiş olmalı; spesifikasyon dışı sonuç varken `RELEASE` olmaz.
    - `RELEASE`: lot serbest; karantinadaki stoku `release_location`'a (verilmezse mal kabulün
      depo lokasyonuna) taşınır. `REJECT`: lot reddedilir.
    - `REWORK` (bulk lot ya da iade numunesi): lot bloke olur; planlamaya görev düşer.
    - `CONDITIONAL_RELEASE`: numune yönetim onayına gider; lot onay gelince serbest olur.
    - Şarj sırası numunesinde lot değişmez; karar yalnızca uygun / uygun değildir.
    `RELEASE` dışındaki kararlarda gerekçe zorunludur. Olay: `sample.decided` (şartlı kabulde
    `sample.awaiting_approval`).
    """
    _require_role(actor, LAB_ROLES, "Kalite kararını yalnızca laboratuvar verir.")
    actor = _actor(actor)
    sample = _lock_sample(sample)
    _require_open(sample, "karar verilemez")
    reason = reason.strip()
    _validate_decision(sample, decision, reason)
    if release_location is not None and (
        not release_location.is_active or release_location.location_type == Location.Type.QUARANTINE
    ):
        raise BusinessRuleError(
            "invalid_release_location", "Serbest bırakılan lot aktif bir depo lokasyonuna taşınır."
        )
    conditional = (
        decision == Decision.CONDITIONAL_RELEASE and sample.stage != SampleStage.IN_PROCESS
    )
    record = save_with_audit(
        QualityDecision(
            sample=sample,
            decision=decision,
            reason=reason,
            decided_by=actor,
            decided_at=timezone.now(),
            release_location=release_location,
            approval_status=Approval.PENDING if conditional else Approval.NOT_REQUIRED,
        ),
        actor,
    )
    if conditional:
        transition_status(
            sample,
            Sample.Status.AWAITING_APPROVAL,
            actor,
            machine=sample_states,
            note=reason,
            event_payload=sample_payload(sample, decision=decision, reason=reason),
        )
        return record
    _apply_to_lot(actor, sample, record, _lot_note(record))
    _close_sample(actor, sample, record)
    return record


def _lot_note(decision: QualityDecision) -> str:
    label = decision.get_decision_display()
    text = f"{decision.sample.number}: {label}"
    return f"{text}. {decision.reason}" if decision.reason else text


def _close_sample(actor: User | None, sample: Sample, decision: QualityDecision) -> None:
    sample.decided_at = timezone.now()
    save_with_audit(sample, actor)
    transition_status(
        sample,
        Sample.Status.DECIDED,
        actor,
        machine=sample_states,
        note=decision.reason,
        event_payload=sample_payload(sample, decision=decision.decision, reason=decision.reason),
    )


@transaction.atomic
def review_conditional_release(
    actor: User | None, decision: QualityDecision, *, approve: bool, note: str = ""
) -> QualityDecision:
    """Şartlı kabulü onaylar ya da reddeder (rol: yönetim).

    Onay: lot serbest bırakılır, numune "Karar verildi" olur. Ret: not zorunlu; numune "Testte"
    durumuna döner ve laboratuvar yeniden karar verir. Her iki durumda da onay görevi kapanır.
    """
    _require_role(actor, APPROVAL_ROLES, "Şartlı kabulü yalnızca yönetim onaylar.")
    actor = _actor(actor)
    decision = QualityDecision.objects.select_for_update().get(pk=decision.pk)
    if decision.approval_status != Approval.PENDING:
        raise BusinessRuleError("decision_not_pending", "Bu karar onay beklemiyor.")
    sample = _lock_sample(decision.sample)
    decision.sample = sample
    note = note.strip()
    if not approve and not note:
        raise BusinessRuleError("note_required", "Ret nedeni girilmelidir.")
    decision.approval_status = Approval.APPROVED if approve else Approval.REFUSED
    decision.approved_by = actor
    decision.approved_at = timezone.now()
    decision.approval_note = note
    save_with_audit(decision, actor)
    if not approve:
        transition_status(
            sample,
            Sample.Status.IN_TEST,
            actor,
            machine=sample_states,
            note=f"Şartlı kabul reddedildi: {note}",
            event_payload=sample_payload(sample, decision=decision.decision, refused=True),
        )
        return decision
    lot_note = _lot_note(decision)
    if note:
        lot_note = f"{lot_note} Yönetim: {note}"
    _apply_to_lot(actor, sample, decision, lot_note)
    _close_sample(actor, sample, decision)
    return decision


def effective_decision(sample: Sample) -> QualityDecision | None:
    """Numunenin yürürlükteki kararı (karar verilmemişse None)."""
    if sample.status != Sample.Status.DECIDED:
        return None
    return (
        sample.decisions.filter(approval_status__in=(Approval.NOT_REQUIRED, Approval.APPROVED))
        .select_related("decided_by", "approved_by")
        .order_by("-decided_at", "-id")
        .first()
    )
