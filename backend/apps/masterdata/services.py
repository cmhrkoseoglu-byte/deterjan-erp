"""Ana veri servisleri: birim dönüşümü ve denetim günlüklü oluştur / güncelle / pasifleştir.

Ana veriler silinmez (CLAUDE.md §4.6); kullanılmayan kayıt `set_active(..., False)` ile pasife
alınır. Tüm yazma işlemleri `core.services.save_with_audit` ile denetim günlüğüne düşer.
"""

import socket
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, models, transaction

from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.labels import gs1_check_digit, is_valid_gtin
from apps.core.models import AuditLog, MasterDataModel, User
from apps.core.services import save_with_audit
from apps.masterdata.fields import normalize_code
from apps.masterdata.models import (
    Equipment,
    LabelSettings,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    Printer,
    UnitOfMeasure,
    Warehouse,
)

# --- birim dönüşümü --------------------------------------------------------------------------


def _no_conversion(material: Material, from_unit: UnitOfMeasure, to_unit: UnitOfMeasure) -> None:
    raise BusinessRuleError(
        "no_conversion",
        f"{material.code} için {from_unit.code} → {to_unit.code} dönüşümü tanımlı değil.",
    )


def _material_factor(material: Material, unit: UnitOfMeasure) -> Decimal | None:
    """Malzemeye özel dönüşüm katsayısı (1 birim = katsayı × temel birim); yoksa None."""
    conversion = (
        MaterialUnitConversion.objects.filter(material=material, unit=unit, is_active=True)
        .only("factor_to_base")
        .first()
    )
    return conversion.factor_to_base if conversion is not None else None


def _kind_factor_to_base(material: Material, unit: UnitOfMeasure) -> Decimal | None:
    """Genel birim katsayılarıyla (ve gerekirse yoğunlukla) 1 `unit` kaç temel birim eder.

    - Aynı tür (G → KG): tür katsayılarının oranı.
    - Kütle ↔ hacim: yoğunluk g/ml = kg/lt olduğundan 1 LT = yoğunluk KG.
    Hesaplanamıyorsa None.
    """
    base = material.base_unit
    if unit.factor_to_kind_base is None or base.factor_to_kind_base is None:
        return None
    # unit → kendi türünün temel birimi (KG, LT ya da ADET)
    in_kind_base = unit.factor_to_kind_base
    if unit.kind == base.kind:
        return in_kind_base / base.factor_to_kind_base
    kinds = {unit.kind, base.kind}
    if kinds != {UnitOfMeasure.Kind.MASS, UnitOfMeasure.Kind.VOLUME} or not material.density:
        return None
    if unit.kind == UnitOfMeasure.Kind.VOLUME:  # LT → KG
        in_base_kind = in_kind_base * material.density
    else:  # KG → LT
        in_base_kind = in_kind_base / material.density
    return in_base_kind / base.factor_to_kind_base


def unit_factor_to_base(material: Material, unit: UnitOfMeasure) -> Decimal | None:
    """1 `unit`'in malzemenin temel biriminde karşılığı; dönüşüm yoksa None.

    Öncelik: temel birimin kendisi → malzemeye özel dönüşüm → genel katsayı / yoğunluk.
    """
    if unit.pk == material.base_unit_id:
        return Decimal(1)
    factor = _material_factor(material, unit)
    if factor is not None:
        return factor
    return _kind_factor_to_base(material, unit)


def convert_quantity(
    material: Material, qty: Decimal, from_unit: UnitOfMeasure, to_unit: UnitOfMeasure
) -> Decimal:
    """Miktarı malzemeye göre bir birimden diğerine çevirir (CLAUDE.md §4.9: tek dönüşüm yolu).

    Önce malzemeye özel dönüşüm (`MaterialUnitConversion`), sonra aynı tür içi genel katsayı,
    kütle ↔ hacim için malzemenin yoğunluğu kullanılır. Dönüşüm yoksa
    `BusinessRuleError("no_conversion")`. Sonuç yuvarlanmaz; yuvarlamayı çağıran yapar.
    """
    if not isinstance(qty, Decimal):
        raise TypeError("Miktar Decimal olmalıdır.")
    if from_unit.pk == to_unit.pk:
        return qty
    from_factor = unit_factor_to_base(material, from_unit)
    to_factor = unit_factor_to_base(material, to_unit)
    if from_factor is None or to_factor is None:
        _no_conversion(material, from_unit, to_unit)
    assert from_factor is not None and to_factor is not None
    return qty * from_factor / to_factor


def to_base_quantity(material: Material, qty: Decimal, unit: UnitOfMeasure) -> Decimal:
    """Miktarı malzemenin temel birimine çevirir (`convert_quantity` kısayolu)."""
    return convert_quantity(material, qty, unit, material.base_unit)


# --- kurallar --------------------------------------------------------------------------------


def _require_active(obj: MasterDataModel | None, label: str) -> None:
    if obj is not None and not obj.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif {label} seçilemez: {obj}.")


def is_referenced(instance: models.Model, *, ignore: tuple[str, ...] = ()) -> bool:
    """Kayda başka bir tablodan (herhangi bir modülden) başvuru var mı?

    `ignore`: bakılmayacak ters ilişki adları (ör. malzemenin kendi dönüşümleri).
    Modül bağımlılığı doğurmadan "kullanılmış veri" kontrolü yapar.
    """
    for relation in instance._meta.get_fields(include_hidden=True):
        if not (relation.auto_created and not relation.concrete):
            continue
        if not (relation.one_to_many or relation.one_to_one):
            continue
        if relation.get_accessor_name() in ignore:  # type: ignore[union-attr,operator]
            continue
        model = relation.related_model
        assert isinstance(model, type)
        field_name = relation.field.name  # type: ignore[union-attr]
        if model._base_manager.filter(**{field_name: instance}).exists():
            return True
    return False


def _db_value(instance: models.Model, field: str) -> Any:
    return type(instance)._base_manager.filter(pk=instance.pk).values_list(field, flat=True).first()


def _validate_unit(unit: UnitOfMeasure) -> None:
    if unit._state.adding:
        return
    before = type(unit)._base_manager.get(pk=unit.pk)
    changed = before.kind != unit.kind or before.factor_to_kind_base != unit.factor_to_kind_base
    if changed and is_referenced(unit):
        raise BusinessRuleError(
            "unit_in_use", f"{unit.code} kullanılıyor; türü ve katsayısı değiştirilemez."
        )


def _validate_material(material: Material) -> None:
    _require_active(material.base_unit, "birim")
    _require_active(material.category, "kategori")
    material.gtin = (material.gtin or "").strip()
    if material.gtin and not is_valid_gtin(material.gtin):
        raise BusinessRuleError(
            "invalid_gtin",
            f"{material.gtin} geçerli bir GTIN değil (8, 12, 13 ya da 14 hane, kontrol hanesi "
            "doğru olmalı).",
        )
    if material._state.adding:
        return
    old_base = _db_value(material, "base_unit_id")
    if old_base != material.base_unit_id and is_referenced(material, ignore=("conversions",)):
        raise BusinessRuleError(
            "base_unit_locked",
            f"{material.code} kullanılıyor; temel birimi değiştirilemez.",
        )


def _validate_conversion(conversion: MaterialUnitConversion) -> None:
    material = conversion.material
    unit = conversion.unit
    _require_active(material, "malzeme")
    _require_active(unit, "birim")
    if unit.pk == material.base_unit_id:
        raise BusinessRuleError(
            "conversion_to_itself", "Temel birim için dönüşüm tanımlanmaz (katsayı her zaman 1)."
        )
    if unit.kind == material.base_unit.kind and _kind_factor_to_base(material, unit) is not None:
        raise BusinessRuleError(
            "conversion_redundant",
            f"{unit.code} temel birime ({material.base_unit.code}) zaten genel katsayıyla "
            "çevrilir; malzemeye özel dönüşüm tanımlanmaz.",
        )
    if not conversion._state.adding:
        old = type(conversion)._base_manager.get(pk=conversion.pk)
        if (old.material_id, old.unit_id) != (conversion.material_id, conversion.unit_id):
            raise BusinessRuleError(
                "conversion_key_locked",
                "Dönüşümün malzemesi ve birimi değiştirilemez; yeni dönüşüm tanımlayın.",
            )


def _validate_location(location: Location) -> None:
    _require_active(location.warehouse, "depo")
    if location._state.adding:
        return
    old_type = _db_value(location, "location_type")
    if old_type != location.location_type and location.equipment.filter(is_active=True).exists():
        raise BusinessRuleError(
            "location_has_equipment",
            "Bu lokasyona bağlı aktif ekipman var; lokasyon türü değiştirilemez.",
        )


def _validate_equipment(equipment: Equipment) -> None:
    _require_active(equipment.location, "lokasyon")
    _require_active(equipment.capacity_unit, "birim")
    if equipment.is_tank:
        if equipment.location is None:
            raise BusinessRuleError("tank_location_required", "Tanklar için lokasyon zorunludur.")
        if equipment.location.location_type != Location.Type.TANK:
            raise BusinessRuleError(
                "tank_location_type",
                "Tankın lokasyonu “Tank” türünde olmalıdır (üretilen ürün tankta durur).",
            )
    if (equipment.capacity is None) != (equipment.capacity_unit is None):
        raise BusinessRuleError(
            "capacity_incomplete", "Kapasite ve kapasite birimi birlikte girilmelidir."
        )


def _validate_printer(printer: Printer) -> None:
    _require_active(printer.location, "lokasyon")
    printer.host = printer.host.strip()
    if not printer.host or any(char.isspace() for char in printer.host):
        raise BusinessRuleError(
            "invalid_host", "Yazıcının IP adresi / ana bilgisayar adı geçersiz."
        )


_VALIDATORS: Mapping[type[models.Model], Callable[[Any], None]] = {
    UnitOfMeasure: _validate_unit,
    Material: _validate_material,
    MaterialUnitConversion: _validate_conversion,
    Location: _validate_location,
    Equipment: _validate_equipment,
    Printer: _validate_printer,
}


def _validate_deactivation(instance: MasterDataModel) -> None:
    if isinstance(instance, UnitOfMeasure):
        if Material.objects.filter(base_unit=instance, is_active=True).exists():
            raise BusinessRuleError(
                "unit_in_use", f"{instance.code} aktif malzemelerin temel birimi; pasife alınamaz."
            )
    elif isinstance(instance, Warehouse):
        if instance.locations.filter(is_active=True).exists():
            raise BusinessRuleError(
                "warehouse_has_locations",
                "Depoda aktif lokasyonlar var; önce lokasyonları pasife alın.",
            )
    elif isinstance(instance, Location):
        if instance.equipment.filter(is_active=True).exists():
            raise BusinessRuleError(
                "location_has_equipment",
                "Lokasyona bağlı aktif ekipman var; önce ekipmanı pasife alın.",
            )
    elif isinstance(instance, MaterialCategory):
        return


def _validate_activation(instance: MasterDataModel) -> None:
    if isinstance(instance, Material):
        _require_active(instance.base_unit, "birim")
    elif isinstance(instance, Location):
        _require_active(instance.warehouse, "depo")
    elif isinstance(instance, MaterialUnitConversion):
        _require_active(instance.material, "malzeme")
    elif isinstance(instance, Equipment | Printer):
        _require_active(instance.location, "lokasyon")


def validate_record(instance: MasterDataModel) -> None:
    """Kaydı yazmadan doğrular: iş kuralları (`BusinessRuleError`), ardından alan, seçenek,
    benzersizlik ve CHECK kısıtları (Türkçe mesajlı Django `ValidationError`).

    Kod alanı yerinde büyük harfe çevrilir. İçe aktarma önizlemesi de bunu kullanır.
    """
    if hasattr(instance, "code") and isinstance(instance.code, str):
        instance.code = normalize_code(instance.code)
    validator = _VALIDATORS.get(type(instance))
    if validator is not None:
        validator(instance)
    instance.full_clean(exclude=["created_by", "updated_by"])


def _save[M: MasterDataModel](instance: M, actor: User | None, note: str) -> M:
    validate_record(instance)
    try:
        with transaction.atomic():
            return save_with_audit(instance, actor, note=note)
    except IntegrityError as exc:  # eşzamanlı aynı kod
        raise BusinessRuleError("duplicate", "Bu kayıt zaten var (kod tekrarı).") from exc


# --- yazma servisleri --------------------------------------------------------------------------


@transaction.atomic
def create_record[M: MasterDataModel](
    actor: User | None, model: type[M], data: Mapping[str, Any], *, note: str = ""
) -> M:
    """Yeni ana veri kaydı oluşturur (kurallar + alan doğrulaması + denetim günlüğü).

    `data` alan adı → değer (FK'lar model nesnesi). Kod büyük harfe çevrilir; kod tekrarında
    doğrulama hatası döner.
    """
    instance = model(**data)
    return _save(instance, actor, note)


@transaction.atomic
def update_record[M: MasterDataModel](
    actor: User | None, instance: M, data: Mapping[str, Any], *, note: str = ""
) -> M:
    """Ana veri kaydını günceller; değişen alanlar eski → yeni değerleriyle günlüğe yazılır.

    `is_active` bu servisle değiştirilemez (`set_active` kullanılır).
    """
    if "is_active" in data:
        raise ValueError("Aktiflik set_active ile değiştirilir.")
    locked = type(instance)._base_manager.select_for_update().get(pk=instance.pk)
    for name, value in data.items():
        setattr(locked, name, value)
    return _save(locked, actor, note)


@transaction.atomic
def set_active[M: MasterDataModel](
    actor: User | None, instance: M, active: bool, *, note: str = ""
) -> M:
    """Kaydı aktif ya da pasif yapar (ana veriler silinmez). Kullanımdaki kayıt (ör. aktif
    malzemelerin temel birimi) pasife alınamaz."""
    locked = type(instance)._base_manager.select_for_update().get(pk=instance.pk)
    if locked.is_active == active:
        return locked
    if active:
        _validate_activation(locked)
    else:
        _validate_deactivation(locked)
    locked.is_active = active
    return save_with_audit(locked, actor, note=note)


# --- etiket ayarları ve yazıcı -----------------------------------------------------------------


def get_label_settings() -> LabelSettings:
    """Etiket ayarları kaydını döner; yoksa boş ayarla oluşturur (tek kayıt)."""
    instance = LabelSettings.objects.order_by("pk").first()
    if instance is None:
        instance, _ = LabelSettings.objects.get_or_create(pk=1)
    return instance


def sscc_enabled() -> bool:
    """GS1 firma öneki girildiyse SSCC palet etiketi açıktır (Karar D-6)."""
    return bool(get_label_settings().gs1_company_prefix)


@transaction.atomic
def update_label_settings(actor: User, data: Mapping[str, Any]) -> LabelSettings:
    """Etiket ayarlarını günceller (denetimli). Firma öneki 6-12 hanelik sayı olmalıdır."""
    get_label_settings()
    instance = LabelSettings.objects.select_for_update().order_by("pk").first()
    assert instance is not None
    for name, value in data.items():
        setattr(instance, name, value)
    instance.company_name = instance.company_name.strip()
    instance.gs1_company_prefix = instance.gs1_company_prefix.strip()
    prefix = instance.gs1_company_prefix
    if prefix and not (prefix.isdigit() and 6 <= len(prefix) <= 12):
        raise BusinessRuleError(
            "invalid_gs1_prefix", "GS1 firma öneki 6-12 haneli bir sayı olmalıdır."
        )
    if instance.sscc_extension_digit > 9:
        raise BusinessRuleError(
            "invalid_extension_digit", "SSCC uzantı hanesi 0-9 arasında olmalıdır."
        )
    _require_active(instance.default_printer, "yazıcı")
    return save_with_audit(instance, actor)


@transaction.atomic
def next_sscc(actor: User | None) -> str:
    """Sıradaki SSCC'yi (18 hane: uzantı + firma öneki + seri + kontrol) üretir ve sayacı
    artırır. Çakışmasızdır (`select_for_update`). Önek yoksa `sscc_disabled` hatası."""
    get_label_settings()
    instance = LabelSettings.objects.select_for_update().order_by("pk").first()
    assert instance is not None
    prefix = instance.gs1_company_prefix
    if not prefix:
        raise BusinessRuleError(
            "sscc_disabled",
            "GS1 firma öneki tanımlı değil; palet (SSCC) etiketi kullanılamaz.",
        )
    serial_digits = 16 - len(prefix)
    serial = instance.next_sscc_serial
    if serial >= 10**serial_digits:
        raise BusinessRuleError("sscc_exhausted", "SSCC seri numaraları tükendi.")
    body = f"{instance.sscc_extension_digit}{prefix}{serial:0{serial_digits}d}"
    instance.next_sscc_serial = serial + 1
    instance.updated_by = actor if actor is not None and actor.is_authenticated else None
    instance.save(update_fields=["next_sscc_serial", "updated_by", "updated_at"])
    return body + gs1_check_digit(body)


def send_to_printer(
    actor: User,
    printer: Printer,
    zpl: str,
    *,
    target: models.Model | None = None,
    description: str = "",
) -> None:
    """Ham ZPL'i yazıcıya TCP ile gönderir ve baskıyı denetim günlüğüne yazar.

    Pasif yazıcıya gönderilmez. Bağlantı kurulamazsa `printer_unreachable` hatası.
    """
    if not printer.is_active:
        raise BusinessRuleError("inactive", f"{printer.code} yazıcısı pasif.")
    if printer.printer_type != Printer.Type.ZPL:
        raise BusinessRuleError("printer_type", "Bu yazıcı türüne gönderim desteklenmiyor.")
    timeout = float(getattr(settings, "PRINTER_TIMEOUT_SECONDS", 5))
    try:
        with socket.create_connection((printer.host, printer.port), timeout=timeout) as conn:
            conn.sendall(zpl.encode("utf-8"))
    except OSError as exc:
        raise BusinessRuleError(
            "printer_unreachable",
            f"{printer.name} yazıcısına ulaşılamadı ({printer.host}:{printer.port}). "
            "Yazıcının açık ve ağa bağlı olduğunu kontrol edin.",
        ) from exc
    note = f"Etiket yazdırıldı: {printer.code}"
    if description:
        note += f" — {description}"
    log_change(actor, target or printer, AuditLog.Action.CUSTOM, {}, note)


# --- ekipman kullanım kancaları (Faz 4, bakım) -------------------------------------------------

# Ekipman kullanım amaçları. Üretim ve dolum ekipmanı kullanmadan önce `check_equipment` çağırır;
# bakım modülü kurallarını (`register_equipment_guard`) buraya kaydeder, alt modüller onu import
# etmez (satın almanın mal kabul kancasıyla aynı yöntem).
EQUIPMENT_ASSIGN = "assign"  # emre atama / emir onayı
EQUIPMENT_START = "start"  # şarj ya da dolum partisi başlatma (`product` verilir)
EQUIPMENT_WEIGH = "weigh"  # terazide tartım

EquipmentGuard = Callable[[Equipment, str, Mapping[str, Any]], list[str]]
_equipment_guards: list[EquipmentGuard] = []


def register_equipment_guard(guard: EquipmentGuard) -> EquipmentGuard:
    """Kancayı kaydeder (dekoratör olarak da kullanılır). `guard(equipment, use, context)` engel
    için `BusinessRuleError` fırlatır, uyarı metinlerini liste olarak döner."""
    if guard not in _equipment_guards:
        _equipment_guards.append(guard)
    return guard


def check_equipment(equipment: Equipment, use: str, **context: Any) -> list[str]:
    """Ekipmanın bu amaçla kullanılabildiğini kayıtlı kancalarla denetler; uyarıları döner.

    Engelde kancanın `BusinessRuleError`'ı (ör. `equipment_down`, `cleaning_required`,
    `calibration_overdue`) çağırana geçer."""
    warnings: list[str] = []
    for guard in _equipment_guards:
        warnings.extend(guard(equipment, use, context))
    return warnings
