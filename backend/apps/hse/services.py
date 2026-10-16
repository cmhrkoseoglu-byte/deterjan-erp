"""İSG ve çevre servisleri (Faz 4, Adım 4.5).

Kurallar:
- Tehlike bilgisi: piktogramı olan malzeme tehlikeli madde sayılır; `Material.is_hazardous`
  `masterdata.services.update_record` ile eşitlenir. Piktogram varsa uyarı kelimesi zorunludur.
- GBF: malzeme başına revizyonlar; yeni GBF girilince önceki geçerli GBF arşive geçer
  (`superseded_at`). Daha eski revizyon tarihli GBF geçerli olanın yerine girilemez.
- Depolama limiti: lokasyon × tehlike sınıfı için en çok kg. Stok hareketi kancası, tehlikeli
  malzemenin limitli lokasyona girişinden sonra commit'te doluluğu denetler; aşılan sınıf için
  `hse.storage_limit_exceeded` yayınlanır (işlem durmaz, uyarıdır).
- Atık kaydı (`AT-`): EWC kodu `07 06 01*` biçiminde; yıldızlı kod tehlikeli atıktır. Pasif ya da
  lisansı teslim tarihinde geçmiş firmaya teslim kaydedilemez.
- Olay kaydı (`OL-`): herkes açar, yönetim inceler ve kapatır. Kapatmak için kök neden ve
  düzeltici faaliyet zorunludur.
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import ALL_ROLES, DEPO, LABORATUVAR, YONETIM
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.hse import selectors
from apps.hse.models import (
    HazardClass,
    HazardStatement,
    HseSettings,
    Incident,
    MaterialHazard,
    SafetyDataSheet,
    SignalWord,
    StorageLimit,
    WasteContractor,
    WasteRecord,
)
from apps.hse.state import incident_states, waste_record_states
from apps.inventory import services as inventory
from apps.inventory.models import StockMovement
from apps.masterdata import services as masterdata
from apps.masterdata.models import Location, Material

IncidentStatus = Incident.Status

# İSG kayıtlarını yönetim tutar.
HSE_ROLES = (YONETIM,)
SETTINGS_ROLES = (YONETIM,)
# Tehlike bilgisini (piktogram, ifadeler) yönetim ve laboratuvar girer; herkes okur.
HAZARD_ROLES = (YONETIM, LABORATUVAR)
HAZARD_READ_ROLES = ALL_ROLES
# GBF'leri depo ve laboratuvar da görür ve indirir.
SDS_READ_ROLES = (YONETIM, DEPO, LABORATUVAR)
# Depolama limitlerini ve doluluğu depo da görür.
STORAGE_READ_ROLES = (YONETIM, DEPO)
# Olayı herkes bildirir.
INCIDENT_REPORT_ROLES = ALL_ROLES

SETTINGS_FIELDS = ("sds_max_age_months",)
STATEMENT_FIELDS = ("code", "kind", "text")
HAZARD_FIELDS = ("pictograms", "signal_word", "statements", "note")
SDS_FIELDS = ("material", "supplier", "revision_no", "revision_date", "valid_until", "language")
SDS_FIELDS_ALL = (*SDS_FIELDS, "note")
STORAGE_LIMIT_FIELDS = ("location", "hazard_class", "max_kg", "note")
CONTRACTOR_FIELDS = ("name", "license_no", "license_valid_until", "phone", "note")
WASTE_FIELDS = (
    "waste_code",
    "description",
    "is_hazardous",
    "quantity_kg",
    "contractor",
    "delivered_on",
    "document_no",
    "note",
)
INCIDENT_FIELDS = (
    "incident_type",
    "occurred_at",
    "place",
    "location",
    "equipment",
    "description",
    "injury",
    "injured_person",
    "severity",
)
INVESTIGATION_FIELDS = (
    "severity",
    "root_cause",
    "corrective_action",
    "action_owner",
    "action_due",
)
CLOSE_FIELDS = (*INVESTIGATION_FIELDS, "closed_note")

STATEMENT_DENIED = "Tehlike ifadelerini yalnızca yönetim ve laboratuvar yönetir."
WASTE_CODE_RE = re.compile(r"^\d{2} \d{2} \d{2}\*?$")


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def _require_role(actor: User | None, roles: Sequence[str], message: str) -> None:
    if not user_has_role(actor, tuple(roles)):
        raise PermissionDenied(message)


def _pick(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _require_active(obj: Any, label: str) -> None:
    if obj is not None and not obj.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif {label} seçilemez: {obj}.")


# --- ek izinleri (apps.py) ---------------------------------------------------------------------


def can_attach_sds(user: User, sheet: Any) -> bool:
    """GBF dosyasını yönetim yükler."""
    return user_has_role(user, HSE_ROLES)


def can_attach_waste(user: User, record: Any) -> bool:
    """Atık belgesini yönetim yükler."""
    return user_has_role(user, HSE_ROLES)


def can_attach_incident(user: User, incident: Any) -> bool:
    """Olay fotoğrafını bildiren kişi ya da yönetim ekler."""
    return user_has_role(user, HSE_ROLES) or (
        user.is_authenticated and getattr(incident, "created_by_id", None) == user.pk
    )


# --- ayarlar -----------------------------------------------------------------------------------


@transaction.atomic
def update_settings(actor: User, data: Mapping[str, Any]) -> HseSettings:
    """GBF en çok yaşını (ay) günceller (rol: yonetim)."""
    _require_role(actor, SETTINGS_ROLES, "İSG ayarlarını yalnızca yönetim değiştirir.")
    values = _pick(data, SETTINGS_FIELDS)
    if "sds_max_age_months" in values and int(values["sds_max_age_months"]) <= 0:
        raise BusinessRuleError("invalid_months", "GBF en çok yaşı sıfırdan büyük olmalıdır.")
    instance = HseSettings.objects.select_for_update().get(pk=selectors.get_settings().pk)
    for name, value in values.items():
        setattr(instance, name, value)
    return save_with_audit(instance, actor)


# --- tehlike ifadeleri ve malzeme tehlike bilgisi ------------------------------------------------


@transaction.atomic
def create_statement(actor: User, data: Mapping[str, Any]) -> HazardStatement:
    """Yeni H / P / EUH ifadesi tanımlar (rol: yönetim, laboratuvar). Kod türüyle başlamalıdır."""
    _require_role(actor, HAZARD_ROLES, STATEMENT_DENIED)
    values = _pick(data, STATEMENT_FIELDS)
    code = _text(values.get("code")).upper().replace(" ", "")
    kind = values.get("kind", "")
    text = _text(values.get("text"))
    prefix_ok = code.startswith(kind) and (kind == HazardStatement.Kind.EUH or code[:3] != "EUH")
    if kind not in HazardStatement.Kind.values or not prefix_ok:
        raise BusinessRuleError(
            "invalid_statement_code", "İfade kodu türüyle başlamalıdır (ör. H290, P280, EUH208)."
        )
    if not text:
        raise BusinessRuleError("text_required", "İfade metni girilmelidir.")
    return masterdata.create_record(
        actor, HazardStatement, {"code": code, "kind": kind, "text": text}
    )


@transaction.atomic
def update_statement(
    actor: User, statement: HazardStatement, data: Mapping[str, Any]
) -> HazardStatement:
    """İfade metnini günceller (kod ve tür değişmez)."""
    _require_role(actor, HAZARD_ROLES, STATEMENT_DENIED)
    values = _pick(data, ("text",))
    text = _text(values.get("text"))
    if not text:
        raise BusinessRuleError("text_required", "İfade metni girilmelidir.")
    return masterdata.update_record(actor, statement, {"text": text})


@transaction.atomic
def set_statement_active(actor: User, statement: HazardStatement, active: bool) -> HazardStatement:
    """İfadeyi aktif / pasif yapar (silinmez)."""
    _require_role(actor, HAZARD_ROLES, STATEMENT_DENIED)
    return masterdata.set_active(actor, statement, active)


def _clean_pictograms(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list | tuple):
        raise BusinessRuleError("invalid_pictogram", "Piktogramlar liste olmalıdır.")
    codes = [str(code).strip().upper() for code in value]
    unknown = [code for code in codes if code not in HazardClass.values]
    if unknown:
        raise BusinessRuleError("invalid_pictogram", f"Tanımsız piktogram: {', '.join(unknown)}.")
    return sorted(set(codes))


@transaction.atomic
def set_material_hazard(actor: User, material: Material, data: Mapping[str, Any]) -> MaterialHazard:
    """Malzemenin tehlike bilgisini oluşturur ya da günceller (rol: yönetim, laboratuvar).

    Piktogram varsa uyarı kelimesi zorunludur; piktogram yoksa uyarı kelimesi boşaltılır.
    `Material.is_hazardous` piktogram olup olmamasına göre (değişmişse) güncellenir."""
    _require_role(actor, HAZARD_ROLES, "Tehlike bilgisini yalnızca yönetim ve laboratuvar girer.")
    values = _pick(data, HAZARD_FIELDS)
    hazard = MaterialHazard.objects.select_for_update().filter(material=material).first()
    if hazard is None:
        hazard = MaterialHazard(material=material)
    if "pictograms" in values:
        hazard.pictograms = _clean_pictograms(values["pictograms"])
    if "signal_word" in values:
        hazard.signal_word = values["signal_word"] or ""
    if "note" in values:
        hazard.note = _text(values["note"])
    if hazard.signal_word and hazard.signal_word not in SignalWord.values:
        raise BusinessRuleError(
            "invalid_signal_word", "Uyarı kelimesi Tehlike ya da Dikkat olmalıdır."
        )
    if hazard.pictograms and not hazard.signal_word:
        raise BusinessRuleError(
            "signal_word_required", "Piktogramı olan malzemede uyarı kelimesi seçilmelidir."
        )
    if not hazard.pictograms:
        hazard.signal_word = ""
    save_with_audit(hazard, actor)
    if "statements" in values:
        statements = list(values["statements"] or [])
        for statement in statements:
            _require_active(statement, "ifade")
        before = sorted(hazard.statements.values_list("code", flat=True))
        after = sorted(statement.code for statement in statements)
        if before != after:
            hazard.statements.set(statements)
            log_change(
                _actor(actor), hazard, AuditLog.Action.UPDATE, {"statements": [before, after]}
            )
    hazardous = bool(hazard.pictograms)
    stored = Material.objects.filter(pk=material.pk).values_list("is_hazardous", flat=True)
    if stored.first() != hazardous:
        masterdata.update_record(
            actor, material, {"is_hazardous": hazardous}, note="Tehlike bilgisinden"
        )
        material.is_hazardous = hazardous
    return hazard


# --- GBF ---------------------------------------------------------------------------------------


@transaction.atomic
def create_sds(actor: User, data: Mapping[str, Any]) -> SafetyDataSheet:
    """Yeni GBF revizyonu girer (rol: yonetim). Malzemenin önceki geçerli GBF'si arşive geçer.
    PDF, kayıttan sonra ek olarak yüklenir (dosyasız GBF raporda "Dosya yok" görünür)."""
    _require_role(actor, HSE_ROLES, "GBF kaydını yalnızca yönetim girer.")
    values = _pick(data, SDS_FIELDS_ALL)
    sheet = SafetyDataSheet(**values)
    sheet.revision_no = _text(sheet.revision_no)
    sheet.language = _text(sheet.language).lower() or "tr"
    sheet.note = _text(sheet.note)
    material = sheet.material
    _require_active(material, "malzeme")
    _require_active(sheet.supplier, "tedarikçi")
    if not sheet.revision_no:
        raise BusinessRuleError("revision_no_required", "Revizyon numarası girilmelidir.")
    if sheet.revision_date > timezone.localdate():
        raise BusinessRuleError("future_revision_date", "Revizyon tarihi ileri bir tarih olamaz.")
    if sheet.valid_until is not None and sheet.valid_until < sheet.revision_date:
        raise BusinessRuleError(
            "invalid_valid_until", "Geçerlilik tarihi revizyon tarihinden önce olamaz."
        )
    now = timezone.now()
    for previous in SafetyDataSheet.objects.select_for_update().filter(
        material=material, superseded_at__isnull=True
    ):
        if previous.revision_date > sheet.revision_date:
            raise BusinessRuleError(
                "older_revision",
                f"Geçerli GBF'nin revizyon tarihi ({previous.revision_date:%d.%m.%Y}) daha yeni; "
                "eski revizyon geçerli GBF'nin yerine girilemez.",
            )
        previous.superseded_at = now
        save_with_audit(previous, actor, note="Yeni GBF revizyonu girildi")
    return save_with_audit(sheet, actor)


@transaction.atomic
def update_sds(actor: User, sheet: SafetyDataSheet, data: Mapping[str, Any]) -> SafetyDataSheet:
    """GBF bilgilerini düzeltir (malzeme değişmez; rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "GBF kaydını yalnızca yönetim değiştirir.")
    values = _pick(data, tuple(f for f in SDS_FIELDS_ALL if f != "material"))
    locked = SafetyDataSheet.objects.select_for_update().get(pk=sheet.pk)
    for name, value in values.items():
        setattr(locked, name, value)
    locked.revision_no = _text(locked.revision_no)
    if "supplier" in values:
        _require_active(locked.supplier, "tedarikçi")
    if not locked.revision_no:
        raise BusinessRuleError("revision_no_required", "Revizyon numarası girilmelidir.")
    if locked.valid_until is not None and locked.valid_until < locked.revision_date:
        raise BusinessRuleError(
            "invalid_valid_until", "Geçerlilik tarihi revizyon tarihinden önce olamaz."
        )
    return save_with_audit(locked, actor)


# --- depolama limitleri ------------------------------------------------------------------------


def _validate_limit(values: Mapping[str, Any]) -> None:
    if "hazard_class" in values and values["hazard_class"] not in HazardClass.values:
        raise BusinessRuleError("invalid_pictogram", "Tanımsız tehlike sınıfı.")
    if "max_kg" in values and Decimal(values["max_kg"]) <= 0:
        raise BusinessRuleError("invalid_limit", "Limit sıfırdan büyük olmalıdır.")
    if "location" in values:
        _require_active(values["location"], "lokasyon")


@transaction.atomic
def create_storage_limit(actor: User, data: Mapping[str, Any]) -> StorageLimit:
    """Lokasyon × tehlike sınıfı için kg limiti tanımlar (rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "Depolama limitini yalnızca yönetim tanımlar.")
    values = _pick(data, STORAGE_LIMIT_FIELDS)
    _validate_limit(values)
    return masterdata.create_record(actor, StorageLimit, values)


@transaction.atomic
def update_storage_limit(actor: User, limit: StorageLimit, data: Mapping[str, Any]) -> StorageLimit:
    """Limiti günceller (rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "Depolama limitini yalnızca yönetim değiştirir.")
    values = _pick(data, STORAGE_LIMIT_FIELDS)
    _validate_limit(values)
    return masterdata.update_record(actor, limit, values)


@transaction.atomic
def set_storage_limit_active(actor: User, limit: StorageLimit, active: bool) -> StorageLimit:
    """Limiti aktif / pasif yapar."""
    _require_role(actor, HSE_ROLES, "Depolama limitini yalnızca yönetim değiştirir.")
    return masterdata.set_active(actor, limit, active)


class _StorageCheck:
    """Commit sonrası bir lokasyonun depolama limitlerini denetleyen iş. Aynı transaction'da aynı
    lokasyon için tek iş kuyruğa girer; sonraki hareketler yalnızca sınıf ekler."""

    def __init__(self, actor: User | None, location_id: int) -> None:
        self.actor = actor
        self.location_id = location_id
        self.classes: set[str] = set()
        self.done = False

    def __call__(self) -> None:
        self.done = True
        location = Location.objects.get(pk=self.location_id)
        for row in selectors.storage_utilisation(location):
            if row.exceeded and row.hazard_class in self.classes:
                events.publish(
                    ev.STORAGE_LIMIT_EXCEEDED,
                    {
                        "model": "masterdata.location",
                        "id": location.pk,
                        "repr": location.code,
                        "location_code": location.code,
                        "hazard_class": row.hazard_class,
                        "hazard_class_display": row.hazard_class_display,
                        "quantity_kg": inventory.format_quantity(row.quantity_kg),
                        "limit_kg": inventory.format_quantity(row.limit_kg),
                    },
                    self.actor,
                )


def _pending_check(location_id: int) -> _StorageCheck | None:
    """Bu transaction'da (geri alınmamış) bekleyen denetim işi."""
    connection = transaction.get_connection()
    for _sids, func, *_rest in connection.run_on_commit:
        if isinstance(func, _StorageCheck) and func.location_id == location_id and not func.done:
            return func
    return None


def storage_limit_hook(actor: User | None, movement: StockMovement) -> None:
    """Stok hareketi kancası: tehlikeli malzemenin aktif limiti olan lokasyona girişinde commit
    sonrası limit denetimi kuyruğa alınır. Hareket engellenmez."""
    if movement.quantity <= 0:
        return
    pictograms = selectors.material_pictograms(movement.material)
    if not pictograms:
        return
    classes = set(
        StorageLimit.objects.filter(
            location_id=movement.location_id, is_active=True, hazard_class__in=pictograms
        ).values_list("hazard_class", flat=True)
    )
    if not classes:
        return
    check = _pending_check(movement.location_id)
    if check is None:
        check = _StorageCheck(_actor(actor), movement.location_id)
        transaction.on_commit(check)
    check.classes.update(classes)


inventory.register_movement_hook(storage_limit_hook)


# --- atık firmaları ve atık kayıtları -----------------------------------------------------------


def _validate_contractor(values: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = dict(values)
    for name in ("name", "license_no", "phone", "note"):
        if name in cleaned:
            cleaned[name] = _text(cleaned[name])
    if "name" in cleaned and not cleaned["name"]:
        raise BusinessRuleError("name_required", "Firma adı girilmelidir.")
    if "license_no" in cleaned and not cleaned["license_no"]:
        raise BusinessRuleError("license_no_required", "Lisans numarası girilmelidir.")
    return cleaned


@transaction.atomic
def create_contractor(actor: User, data: Mapping[str, Any]) -> WasteContractor:
    """Lisanslı atık firması tanımlar (rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "Atık firmasını yalnızca yönetim tanımlar.")
    values = _validate_contractor(_pick(data, CONTRACTOR_FIELDS))
    return masterdata.create_record(actor, WasteContractor, values)


@transaction.atomic
def update_contractor(
    actor: User, contractor: WasteContractor, data: Mapping[str, Any]
) -> WasteContractor:
    """Firmayı günceller (ör. lisans yenileme; rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "Atık firmasını yalnızca yönetim değiştirir.")
    values = _validate_contractor(_pick(data, CONTRACTOR_FIELDS))
    return masterdata.update_record(actor, contractor, values)


@transaction.atomic
def set_contractor_active(
    actor: User, contractor: WasteContractor, active: bool
) -> WasteContractor:
    """Firmayı aktif / pasif yapar."""
    _require_role(actor, HSE_ROLES, "Atık firmasını yalnızca yönetim değiştirir.")
    return masterdata.set_active(actor, contractor, active)


def normalize_waste_code(value: str) -> str:
    """EWC atık kodunu `07 06 01*` biçimine getirir (`070601*`, `07-06-01 *` kabul edilir).
    Geçersiz kodda `BusinessRuleError("invalid_waste_code")`."""
    raw = re.sub(r"[\s.\-]", "", value or "")
    star = raw.endswith("*")
    digits = raw.rstrip("*")
    if len(digits) == 6 and digits.isdigit() and raw.count("*") <= 1:
        code = f"{digits[0:2]} {digits[2:4]} {digits[4:6]}{'*' if star else ''}"
        if WASTE_CODE_RE.match(code):
            return code
    raise BusinessRuleError(
        "invalid_waste_code", "Atık kodu 6 haneli EWC kodu olmalıdır (ör. 07 06 01*)."
    )


@transaction.atomic
def record_waste(actor: User, data: Mapping[str, Any]) -> WasteRecord:
    """Atık teslimini kaydeder (`AT-`, rol: yonetim). Yıldızlı kod tehlikeli atıktır. Pasif ya da
    lisansı teslim tarihinde geçmiş firmaya teslim kaydedilemez."""
    _require_role(actor, HSE_ROLES, "Atık kaydını yalnızca yönetim girer.")
    values = _pick(data, WASTE_FIELDS)
    code = normalize_waste_code(values.get("waste_code", ""))
    contractor: WasteContractor = values["contractor"]
    delivered_on: date = values["delivered_on"]
    quantity = Decimal(values["quantity_kg"])
    description = _text(values.get("description"))
    if not description:
        raise BusinessRuleError("description_required", "Atık tanımı girilmelidir.")
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    if delivered_on > timezone.localdate():
        raise BusinessRuleError("future_date", "Teslim tarihi ileri bir tarih olamaz.")
    _require_active(contractor, "atık firması")
    if contractor.license_valid_until < delivered_on:
        raise BusinessRuleError(
            "contractor_license_expired",
            f"{contractor.name} lisansı {contractor.license_valid_until:%d.%m.%Y} tarihinde "
            "dolmuş; teslim kaydedilemez.",
        )
    record = WasteRecord(
        waste_code=code,
        description=description,
        is_hazardous=code.endswith("*") or bool(values.get("is_hazardous")),
        quantity_kg=inventory.quantize(quantity),
        contractor=contractor,
        delivered_on=delivered_on,
        document_no=_text(values.get("document_no")),
        note=_text(values.get("note")),
    )
    return create_document(
        record,
        _actor(actor),
        prefix="AT",
        machine=waste_record_states,
        event_payload={
            "waste_code": record.waste_code,
            "is_hazardous": record.is_hazardous,
            "quantity_kg": inventory.format_quantity(record.quantity_kg),
            "contractor_name": contractor.name,
        },
    )


@transaction.atomic
def cancel_waste_record(actor: User, record: WasteRecord, reason: str) -> WasteRecord:
    """Atık kaydını iptal eder (neden zorunlu; rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "Atık kaydını yalnızca yönetim iptal eder.")
    return cancel_document(record, _actor(actor), reason=reason, machine=waste_record_states)


# --- olay / kaza kayıtları ---------------------------------------------------------------------


def _incident_payload(incident: Incident) -> dict[str, Any]:
    return {
        "incident_type": incident.incident_type,
        "incident_type_display": incident.get_incident_type_display(),
        "occurred_at": f"{timezone.localtime(incident.occurred_at):%d.%m.%Y %H:%M}",
        "place": incident.place,
        "injury": incident.injury,
        "severity": incident.severity,
    }


def _lock(incident: Incident) -> Incident:
    return Incident.objects.select_for_update().get(pk=incident.pk)


@transaction.atomic
def report_incident(actor: User, data: Mapping[str, Any]) -> Incident:
    """Olay / kaza bildirir (her rol). Kayıt açılınca yönetime inceleme görevi düşer; yaralanma
    varsa ayrıca uyarı bildirimi gider."""
    _require_role(actor, INCIDENT_REPORT_ROLES, "Olay bildirmek için bir rolünüz olmalı.")
    values = _pick(data, INCIDENT_FIELDS)
    incident = Incident(**values)
    incident.place = _text(incident.place)
    incident.description = _text(incident.description)
    incident.injured_person = _text(incident.injured_person)
    if incident.incident_type not in Incident.Type.values:
        raise BusinessRuleError("invalid_incident_type", "Geçersiz olay türü.")
    if incident.severity not in Incident.Severity.values:
        raise BusinessRuleError("invalid_severity", "Geçersiz ağırlık.")
    if incident.occurred_at is None or incident.occurred_at > timezone.now():
        raise BusinessRuleError("future_occurred_at", "Olay zamanı ileri bir zaman olamaz.")
    if not incident.place and incident.location is None and incident.equipment is None:
        raise BusinessRuleError("place_required", "Olayın yeri girilmelidir.")
    if not incident.place:
        incident.place = str(incident.equipment or incident.location)
    if not incident.description:
        raise BusinessRuleError("description_required", "Olayın anlatımı girilmelidir.")
    if not incident.injury:
        incident.injured_person = ""
    return create_document(
        incident,
        _actor(actor),
        prefix="OL",
        machine=incident_states,
        event_payload=_incident_payload(incident),
    )


def _apply_fields(incident: Incident, data: Mapping[str, Any], allowed: Sequence[str]) -> None:
    values = _pick(data, allowed)
    for name, value in values.items():
        if name in ("action_due", "severity"):
            setattr(incident, name, value)
        else:
            setattr(incident, name, _text(value))
    if incident.severity not in Incident.Severity.values:
        raise BusinessRuleError("invalid_severity", "Geçersiz ağırlık.")


@transaction.atomic
def start_investigation(
    actor: User, incident: Incident, data: Mapping[str, Any] | None = None
) -> Incident:
    """Olayı incelemeye alır (rol: yonetim); kök neden, ağırlık ve faaliyet bilgileri
    isteğe bağlı girilir."""
    _require_role(actor, HSE_ROLES, "Olayı yalnızca yönetim inceler.")
    incident = _lock(incident)
    incident_states.assert_can_transition(incident.status, IncidentStatus.INVESTIGATING)
    _apply_fields(incident, data or {}, INVESTIGATION_FIELDS)
    save_with_audit(incident, actor)
    return transition_status(
        incident,
        IncidentStatus.INVESTIGATING,
        _actor(actor),
        machine=incident_states,
        event_payload=_incident_payload(incident),
    )


@transaction.atomic
def update_investigation(actor: User, incident: Incident, data: Mapping[str, Any]) -> Incident:
    """İncelemedeki olayın kök neden / faaliyet bilgilerini günceller (rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "Olayı yalnızca yönetim inceler.")
    incident = _lock(incident)
    if incident.status not in selectors.OPEN_INCIDENT_STATUSES:
        raise BusinessRuleError("incident_not_open", "Kapanmış ya da iptal olay değiştirilemez.")
    _apply_fields(incident, data, INVESTIGATION_FIELDS)
    return save_with_audit(incident, actor)


@transaction.atomic
def close_incident(actor: User, incident: Incident, data: Mapping[str, Any]) -> Incident:
    """İncelenen olayı kapatır (rol: yonetim). Kök neden ve düzeltici faaliyet zorunludur."""
    _require_role(actor, HSE_ROLES, "Olayı yalnızca yönetim kapatır.")
    incident = _lock(incident)
    incident_states.assert_can_transition(incident.status, IncidentStatus.CLOSED)
    _apply_fields(incident, data, CLOSE_FIELDS)
    if not incident.root_cause:
        raise BusinessRuleError("root_cause_required", "Kapatmak için kök neden girilmelidir.")
    if not incident.corrective_action:
        raise BusinessRuleError(
            "corrective_action_required", "Kapatmak için düzeltici faaliyet girilmelidir."
        )
    save_with_audit(incident, actor)
    return transition_status(
        incident,
        IncidentStatus.CLOSED,
        _actor(actor),
        machine=incident_states,
        event_payload=_incident_payload(incident),
    )


@transaction.atomic
def cancel_incident(actor: User, incident: Incident, reason: str) -> Incident:
    """Olay kaydını iptal eder (ör. mükerrer kayıt; neden zorunlu, rol: yonetim)."""
    _require_role(actor, HSE_ROLES, "Olay kaydını yalnızca yönetim iptal eder.")
    return cancel_document(_lock(incident), _actor(actor), reason=reason, machine=incident_states)
