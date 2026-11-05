"""Ana veri servisleri: birim dönüşümü ve denetim günlüklü oluştur / güncelle / pasifleştir.

Ana veriler silinmez (CLAUDE.md §4.6); kullanılmayan kayıt `set_active(..., False)` ile pasife
alınır. Tüm yazma işlemleri `core.services.save_with_audit` ile denetim günlüğüne düşer.
"""

import re
import socket
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import EllipsisType
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db import IntegrityError, connection, models, transaction
from django.db.models import Exists, OuterRef, Q, QuerySet, Value
from django.db.models.functions import LPad

from apps.core import standards
from apps.core.audit import log_change
from apps.core.coding import registry as coding_registry
from apps.core.coding import selectors as coding_selectors
from apps.core.coding import services as coding
from apps.core.exceptions import BusinessRuleError
from apps.core.labels import gs1_check_digit, gtin14, is_ascii_digits, is_valid_gtin
from apps.core.models import AuditLog, MasterDataModel, User
from apps.core.permissions import user_has_role
from apps.core.roles import ADMIN, YONETIM
from apps.core.services import save_with_audit
from apps.masterdata.fields import CodeField, normalize_code
from apps.masterdata.models import (
    CompanyProfile,
    Customer,
    Equipment,
    LabelSettings,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    Printer,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)
from apps.masterdata.selectors import gtin_owner

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


def normalized_code(model: type[models.Model], value: str, field: str = "code") -> str:
    """Kodu alanın kendi kuralıyla düzeltir: `CodeField` büyük harfe çevirir (`upper=False` ise
    yalnız boşlukları atar, ör. H360Fd); başka alan türünde büyük harf."""
    try:
        model_field = model._meta.get_field(field)
    except FieldDoesNotExist:
        return normalize_code(value)
    if isinstance(model_field, CodeField):
        return model_field.normalize(value)
    return normalize_code(value)


def _validate_unit(unit: UnitOfMeasure) -> None:
    # UN/ECE Rec 20 ortak kodu (ambalajda Rec 21 kodunun başına X): büyük harf, 2-3 karakter.
    unit.unece_code = (unit.unece_code or "").strip().upper()
    unit.symbol = (unit.symbol or "").strip()
    if unit.unece_code and not standards.is_unece_code(unit.unece_code):
        raise BusinessRuleError(
            "invalid_unece_code",
            "UN/ECE birim kodu 2-3 büyük harf ya da rakamdır (ör. KGM, LTR, C62; koli XCT, "
            "palet XPX).",
        )
    if unit._state.adding:
        return
    before = type(unit)._base_manager.get(pk=unit.pk)
    changed = before.kind != unit.kind or before.factor_to_kind_base != unit.factor_to_kind_base
    if changed and is_referenced(unit):
        raise BusinessRuleError(
            "unit_in_use", f"{unit.code} kullanılıyor; türü ve katsayısı değiştirilemez."
        )


# --- GTIN kuralları (GS1) ----------------------------------------------------------------------

# Koli GTIN'i yalnızca bu birimin dönüşümünde tutulur: koli etiketinin (01), palet etiketinin (02)
# alanına basılır.
CASE_UNIT = "KOLI"
# Ürün ve koli GTIN'leri iki tabloda birlikte tektir. Denetimle kayıt arasında başka bir işlem aynı
# GTIN'i yazmasın diye GTIN yazan işlemler bu PostgreSQL işlem kilidiyle sıraya girer.
_GTIN_LOCK_ID = 730_103
# Malzemenin lotları (`inventory.Lot.material` ters ilişkisi); masterdata lot modülünü import etmez.
_LOT_RELATION = "lots"


def _check_gtin_format(gtin: str) -> None:
    if gtin and not is_valid_gtin(gtin):
        raise BusinessRuleError(
            "invalid_gtin",
            f"{gtin} geçerli bir GTIN değil (yalnızca rakam; 8, 12, 13 ya da 14 hane, kontrol "
            "hanesi doğru olmalı).",
        )


def material_has_lots(material: Material) -> bool:
    """Malzemenin lotu var mı? Lotu olan malzemenin dolu GTIN'i ve koli GTIN'i değiştirilemez:
    o GTIN'le basılmış koli ve palet etiketleri okutulamaz olur."""
    if material.pk is None:
        return False
    lots = getattr(material, _LOT_RELATION, None)
    return lots is not None and bool(lots.exists())


def lot_exists(material_field: str) -> Exists | Value:
    """Sorgu eki: dış sorgudaki `material_field` malzemesinin lotu var mı. Liste uç noktaları GTIN
    kilidini satır başına sorgu yapmadan gösterir (`gtin_locked`, `case_gtin_locked`)."""
    try:
        relation = Material._meta.get_field(_LOT_RELATION)
    except FieldDoesNotExist:  # lot modülü kurulu değil
        return Value(False)
    lot_model = getattr(relation, "related_model", None)
    assert isinstance(lot_model, type) and issubclass(lot_model, models.Model)
    return Exists(lot_model._base_manager.filter(material=OuterRef(material_field)))


def _lockable(gtin: str) -> bool:
    """Lot açılınca kilitlenen GTIN: dolu ve geçerli. Geçersiz eski GTIN (ör. yönetim panelinden
    denetimsiz girilmiş) okutulamaz; düzeltilmesi serbesttir."""
    return bool(gtin) and is_valid_gtin(gtin)


def _gtin_change_locked(old: str, new: str) -> bool:
    """Eski GTIN kilitlenebilir ve başka bir GTIN'e değişiyor ya da siliniyor mu? Boştan ilk kez
    girmek ve aynı GTIN'i başka uzunlukta yazmak (8690000000012 → 08690000000012) değişiklik
    sayılmaz."""
    return _lockable(old) and (not new or gtin14(new) != gtin14(old))


def gtin_locked(material: Material) -> bool:
    """Malzemenin GTIN'i kilitli mi: GTIN dolu (ve geçerli) ve malzemenin lotu var. Sorgudaki
    `has_lots` eki (`lot_exists`) varsa ek sorgu yapılmaz."""
    if not _lockable(material.gtin):
        return False
    flag = getattr(material, "has_lots", None)
    return bool(flag) if flag is not None else material_has_lots(material)


def case_gtin_locked(conversion: MaterialUnitConversion) -> bool:
    """Koli GTIN'i kilitli mi: koli GTIN'i dolu (ve geçerli) ve malzemenin lotu var. Dönüşümde
    `material_has_lots`, malzemede `has_lots` eki varsa ek sorgu yapılmaz."""
    if not _lockable(conversion.gtin):
        return False
    flag = getattr(conversion, "material_has_lots", None)
    if flag is None:
        flag = getattr(conversion.material, "has_lots", None)
    return bool(flag) if flag is not None else material_has_lots(conversion.material)


def _lock_gtins() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_GTIN_LOCK_ID])


def _lock_gtins_first(model: type[models.Model], data: Mapping[str, Any], *, update: bool) -> None:
    """GTIN yazan işlem GTIN kilidini satır kilitlerinden (kaydın `select_for_update`'i, kod
    sayacı) önce alır; kilit sırası her yolda aynı olur, iki işlem birbirini beklemez (deadlock).
    Yeni kayıtta GTIN doluysa, güncellemede `gtin` verildiyse alınır; `_ensure_gtin_free` aynı
    kilidi yeniden alır (aynı işlemde birikir)."""
    if not issubclass(model, Material | MaterialUnitConversion) or "gtin" not in data:
        return
    if update or str(data["gtin"] or "").strip():
        _lock_gtins()


def _ensure_gtin_free(
    gtin: str,
    *,
    material: Material | None = None,
    conversion: MaterialUnitConversion | None = None,
) -> None:
    """GTIN 14 haneli normal biçimde başka bir malzemenin ürün GTIN'i ya da herhangi bir koli
    dönüşümünün GTIN'i olmamalı (pasif kayıtlar dahil; `gtin_taken`). Malzemenin kendi koli GTIN'i
    de ürün GTIN'i olamaz: koli ayrı bir ticari üründür. Kilit işlem sonuna kadar tutulur."""
    _lock_gtins()
    owner, owner_conversion = gtin_owner(gtin)
    if owner is None:
        return
    if owner_conversion is None:
        if material is not None and owner.pk == material.pk:
            return
        if conversion is not None and owner.pk == conversion.material_id:
            raise BusinessRuleError(
                "gtin_taken",
                "Koli GTIN'i malzemenin kendi ürün GTIN'i olamaz; koli için ayrı bir GTIN girin.",
            )
    elif conversion is not None and owner_conversion.pk == conversion.pk:
        return
    elif material is not None and material.pk is not None and owner.pk == material.pk:
        raise BusinessRuleError(
            "gtin_taken",
            "Ürün GTIN'i bu malzemenin koli GTIN'iyle aynı olamaz; koli ayrı bir ticari üründür.",
        )
    where = owner.code if owner_conversion is None else f"{owner.code} koli dönüşümü"
    raise BusinessRuleError(
        "gtin_taken", f"Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: {where}."
    )


def _gtin_locked_error(material: Material, what: str) -> BusinessRuleError:
    return BusinessRuleError(
        "gtin_locked",
        f"{material.code}: lotu olan malzemenin {what} değiştirilemez ya da silinemez (basılmış "
        "koli ve palet etiketleri bu GTIN'i taşır).",
    )


def _validate_material(material: Material) -> None:
    _require_active(material.base_unit, "birim")
    _require_active(material.category, "kategori")
    material.gtin = (material.gtin or "").strip()
    old_gtin = "" if material._state.adding else str(_db_value(material, "gtin") or "")
    # Kurallar GTIN değişince uygulanır: eski veride kalmış GTIN öteki alanların kaydını
    # engellemez.
    if material.gtin != old_gtin:
        _check_gtin_format(material.gtin)
        # Boştan ilk kez girmek serbest; dolu GTIN lot açıldıktan sonra değişmez.
        if _gtin_change_locked(old_gtin, material.gtin) and material_has_lots(material):
            raise _gtin_locked_error(material, "GTIN'i")
        if material.gtin:
            _ensure_gtin_free(material.gtin, material=material)
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
    old_gtin = ""
    if not conversion._state.adding:
        old = type(conversion)._base_manager.get(pk=conversion.pk)
        if (old.material_id, old.unit_id) != (conversion.material_id, conversion.unit_id):
            raise BusinessRuleError(
                "conversion_key_locked",
                "Dönüşümün malzemesi ve birimi değiştirilemez; yeni dönüşüm tanımlayın.",
            )
        old_gtin = old.gtin
    conversion.gtin = (conversion.gtin or "").strip()
    if conversion.gtin != old_gtin:
        if conversion.gtin and unit.code != CASE_UNIT:
            raise BusinessRuleError(
                "case_gtin_not_allowed",
                f"GTIN yalnızca koli ({CASE_UNIT}) dönüşümünde girilir; {unit.code} dönüşümünde "
                "boş bırakın.",
            )
        _check_gtin_format(conversion.gtin)
        if _gtin_change_locked(old_gtin, conversion.gtin) and material_has_lots(material):
            raise _gtin_locked_error(material, "koli GTIN'i")
        if conversion.gtin:
            _ensure_gtin_free(conversion.gtin, conversion=conversion)


def _validate_partner(partner: Supplier | Customer) -> None:
    """Ülke kodu ISO 3166-1 alpha-2 (TR, DE, IQ …); küçük harf büyütülür."""
    partner.country_code = standards.normalize_country(partner.country_code or "")
    if not standards.is_country_code(partner.country_code):
        raise BusinessRuleError(
            "invalid_country_code",
            "Ülke kodu ISO 3166-1 alpha-2 olmalıdır (ör. TR, DE, IQ).",
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
    Supplier: _validate_partner,
    Customer: _validate_partner,
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


def code_type_of(
    instance: models.Model | type[models.Model],
) -> coding_registry.CodeType | None:
    """Kaydın (ya da modelin) kodlama sistematiğindeki ana veri kod türü; standart kodlarda ve
    kodsuz kayıtta None."""
    item = coding_registry.master_type_for_model(instance._meta.label_lower)
    return item if item is not None and item.kind == coding_registry.MASTER else None


def _previous_code(instance: models.Model, item: coding_registry.CodeType) -> str | None:
    """Veritabanındaki kod (yeni kayıtta None)."""
    if instance._state.adding:
        return None
    value = _db_value(instance, item.field)
    return None if value is None else str(value)


def validate_record(instance: MasterDataModel) -> None:
    """Kaydı yazmadan doğrular: iş kuralları (`BusinessRuleError`), ardından alan, seçenek,
    benzersizlik ve CHECK kısıtları (Türkçe mesajlı Django `ValidationError`).

    Kod alanı yerinde alanın kuralıyla düzeltilir (`normalized_code`: büyük harf; büyük/küçük
    harfi korunan kodda yalnız boşluklar atılır). Kodlama sistematiğinin kuralları (eski kod,
    biçim) yeni kayıtta ve kod değişince uygulanır (`core.coding`). İçe aktarma önizlemesi de bunu
    kullanır.
    """
    if hasattr(instance, "code") and isinstance(instance.code, str):
        instance.code = normalized_code(type(instance), instance.code)
    validator = _VALIDATORS.get(type(instance))
    if validator is not None:
        validator(instance)
    item = code_type_of(instance)
    if item is not None:
        coding.check_master_code(item, instance, previous_code=_previous_code(instance, item))
    instance.full_clean(exclude=["created_by", "updated_by"])


def _previous_gtin(instance: models.Model) -> str | None:
    """GTIN taşıyan kayıtta (malzeme, koli dönüşümü) veritabanındaki GTIN (yeni kayıtta "");
    öteki türlerde None."""
    if not isinstance(instance, Material | MaterialUnitConversion):
        return None
    if instance._state.adding:
        return ""
    return str(_db_value(instance, "gtin") or "")


def _save[M: MasterDataModel](instance: M, actor: User | None, note: str) -> M:
    item = code_type_of(instance)
    previous = _previous_code(instance, item) if item is not None else None
    previous_gtin = _previous_gtin(instance)
    if item is not None and previous is None:
        coding.assign_master_code(item, instance)  # kod boşsa etkin biçimde sıradaki kod
    validate_record(instance)
    try:
        with transaction.atomic():
            if item is not None:
                coding.claim_master_code(item, instance, previous_code=previous)
            saved = save_with_audit(instance, actor, note=note)
            if item is not None and previous is not None:
                current = str(getattr(saved, item.field))
                if current != previous:
                    coding.record_code_change(actor, item, saved, previous, note=note)
            if previous_gtin is not None:
                gtin = str(getattr(saved, "gtin", "") or "")
                if gtin and gtin != previous_gtin:
                    _advance_item_reference(actor, gtin)
            return saved
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
    _lock_gtins_first(model, data, update=False)  # kod sayacı kilidinden önce
    instance = model(**data)
    return _save(instance, actor, note)


@transaction.atomic
def update_record[M: MasterDataModel](
    actor: User | None, instance: M, data: Mapping[str, Any], *, note: str = ""
) -> M:
    """Ana veri kaydını günceller; değişen alanlar eski → yeni değerleriyle günlüğe yazılır.

    `is_active` bu servisle değiştirilemez (`set_active` kullanılır). Kodlama sistematiğine kayıtlı
    türde kodu yalnızca admin değiştirir (`PermissionDenied`); eski kod saklanır.
    """
    if "is_active" in data:
        raise ValueError("Aktiflik set_active ile değiştirilir.")
    _lock_gtins_first(type(instance), data, update=True)  # kaydın satır kilidinden önce
    locked = type(instance)._base_manager.select_for_update().get(pk=instance.pk)
    item = code_type_of(locked)
    if item is not None and item.field in data:
        new_code = normalized_code(type(locked), str(data[item.field] or ""), item.field)
        if new_code != str(getattr(locked, item.field)):
            # Kayıt açıldıktan sonra kodu yalnız admin değiştirir (CUMHUR, 2026-11-04).
            coding.ensure_can_change_code(actor)
    for name, value in data.items():
        setattr(locked, name, value)
    return _save(locked, actor, note)


@transaction.atomic
def recode_record(
    actor: User | None,
    instance: MasterDataModel,
    new_code: str,
    note: str,
    run_id: int | None = None,
    reason: str = "migration",
) -> MasterDataModel:
    """Kod göçü (`core.coding.migration`): yalnızca kodu değiştirir.

    Kaydın öteki alanları yeniden doğrulanmaz (göç, ilgisiz bir kural yüzünden yarıda kalmasın);
    kod kuralları denetlenir: kod başka kaydın güncel kodu ya da eski koduysa `recode_conflict`.
    Değişiklik denetim günlüğüne (`code: [eski, yeni]`) ve eski kod geçmişine yazılır.
    """
    item = code_type_of(instance)
    if item is None:
        raise ValueError("Kod göçü yalnızca kodlama sistematiğine kayıtlı türlerde yapılır.")
    locked = type(instance)._base_manager.select_for_update().get(pk=instance.pk)
    old = str(getattr(locked, item.field))
    new_code = normalized_code(type(locked), new_code, item.field)
    if old == new_code:
        return locked
    if coding_selectors.code_in_use(item, new_code, exclude_pk=locked.pk) or (
        coding_selectors.code_reserved(item, new_code, exclude_pk=locked.pk)
    ):
        raise BusinessRuleError(
            "recode_conflict", f"{new_code} başka bir kayıtta kullanılıyor ya da kullanıldı."
        )
    setattr(locked, item.field, new_code)
    locked.updated_by = actor if actor is not None and actor.is_authenticated else None
    locked.save(update_fields=[item.field, "updated_by", "updated_at"])
    log_change(actor, locked, AuditLog.Action.UPDATE, {item.field: [old, new_code]}, note)
    coding.record_code_change(actor, item, locked, old, reason=reason, note=note, run_id=run_id)
    return locked


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


# --- firma bilgileri ---------------------------------------------------------------------------

# Firma bilgilerini değiştiren roller (admin her yere erişir); okuma giriş yapmış herkese.
COMPANY_WRITE_ROLES = (YONETIM,)
COMPANY_FIELDS = (
    "legal_name",
    "address",
    "tax_office",
    "tax_number",
    "trade_registry_no",
    "mersis_no",
)


def get_company_profile() -> CompanyProfile:
    """Firma bilgilerini döner; yoksa ayar dosyasındaki `COMPANY_*` değerleriyle oluşturur (tek
    kayıt). Sonraki değişiklikler yalnızca ekrandan (`update_company_profile`)."""
    instance = CompanyProfile.objects.order_by("pk").first()
    if instance is None:
        instance, _ = CompanyProfile.objects.get_or_create(
            pk=1,
            defaults={
                "legal_name": (settings.COMPANY_NAME or "").strip(),
                "address": (settings.COMPANY_ADDRESS or "").strip(),
                "tax_office": (settings.COMPANY_TAX_OFFICE or "").strip(),
                "tax_number": (settings.COMPANY_TAX_NO or "").strip(),
            },
        )
    return instance


def company_registry_line(profile: CompanyProfile) -> str:
    """Belgelerde unvanın altındaki sicil satırı ("Ticaret sicil no: … MERSİS no: …"); boşsa ""."""
    parts = []
    if profile.trade_registry_no:
        parts.append(f"Ticaret sicil no: {profile.trade_registry_no}")
    if profile.mersis_no:
        parts.append(f"MERSİS no: {profile.mersis_no}")
    return "  ".join(parts)


def valid_vkn(value: str) -> bool:
    """10 haneli vergi kimlik numarası ve kontrol hanesi (GİB algoritması)."""
    if len(value) != 10 or not value.isdigit():
        return False
    total = 0
    for i, char in enumerate(value[:9]):
        tmp = (int(char) + 9 - i) % 10
        part = (tmp * 2 ** (9 - i)) % 9
        total += 9 if tmp and not part else part
    return (10 - total % 10) % 10 == int(value[9])


def valid_tckn(value: str) -> bool:
    """11 haneli T.C. kimlik numarası ve iki kontrol hanesi."""
    if len(value) != 11 or not value.isdigit() or value[0] == "0":
        return False
    d = [int(char) for char in value]
    tenth = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return d[9] == tenth and d[10] == sum(d[:10]) % 10


def _company_text(name: str, value: Any) -> str:
    text = str(value or "")
    if name == "address":
        # Adres satırları korunur; her satırın başı ve sonu kırpılır, boş satırlar atılır.
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
    text = re.sub(r"\s+", " ", text).strip()
    if name in ("tax_number", "mersis_no"):
        text = text.replace(" ", "")
    return text


@transaction.atomic
def update_company_profile(actor: User, data: Mapping[str, Any]) -> CompanyProfile:
    """Firma bilgilerini günceller (yönetim ve admin); değişen alanlar eski → yeni değerleriyle
    denetim günlüğüne yazılır. Ticari unvan boş olamaz; vergi no 10 haneli VKN ya da şahıs
    firmasında 11 haneli TCKN, MERSİS no 16 hane olmalıdır (doluysa)."""
    if not user_has_role(actor, COMPANY_WRITE_ROLES):
        raise PermissionDenied(
            "Firma bilgilerini yalnızca yönetim ve sistem yöneticisi değiştirir."
        )
    unknown = set(data) - set(COMPANY_FIELDS)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    get_company_profile()
    instance = CompanyProfile.objects.select_for_update().order_by("pk").first()
    assert instance is not None
    for name, value in data.items():
        setattr(instance, name, _company_text(name, value))
    if not instance.legal_name:
        raise BusinessRuleError("legal_name_required", "Ticari unvan girilmelidir.")
    number = instance.tax_number
    if number and not (valid_vkn(number) or valid_tckn(number)):
        raise BusinessRuleError(
            "invalid_tax_number",
            "Vergi no 10 haneli VKN ya da 11 haneli TCKN olmalı; kontrol hanesi tutmuyor.",
        )
    if instance.mersis_no and not (len(instance.mersis_no) == 16 and instance.mersis_no.isdigit()):
        raise BusinessRuleError("invalid_mersis_no", "MERSİS no 16 haneli bir sayı olmalıdır.")
    instance.full_clean(exclude=["created_by", "updated_by"])
    return save_with_audit(instance, actor)


# GS1 alanları yalnızca `update_gs1_settings` (Sistem > Kodlama sistematiği > GS1) ve sayaçları
# ilerleten servisler (`next_sscc`, GTIN kaydı) yazar; etiket ayarları ekranı değiştiremez.
GS1_FIELDS = (
    "gs1_company_prefix",
    "sscc_extension_digit",
    "next_item_reference",
    "next_sscc_serial",
)


@transaction.atomic
def update_label_settings(actor: User, data: Mapping[str, Any]) -> LabelSettings:
    """Etiket ayarlarını günceller (denetimli): etikette firma adı ve varsayılan yazıcı. GS1
    alanları burada değişmez (`update_gs1_settings`); verilirse `ValueError`."""
    gs1 = sorted(set(data) & set(GS1_FIELDS))
    if gs1:
        raise ValueError(f"GS1 alanları update_gs1_settings ile değiştirilir: {', '.join(gs1)}")
    get_label_settings()
    instance = LabelSettings.objects.select_for_update().order_by("pk").first()
    assert instance is not None
    for name, value in data.items():
        setattr(instance, name, value)
    instance.company_name = instance.company_name.strip()
    _require_active(instance.default_printer, "yazıcı")
    return save_with_audit(instance, actor)


# --- GS1 ayarları (Sistem > Kodlama sistematiği > GS1) -------------------------------------------

GS1_ADMIN_MESSAGE = "GS1 ayarlarını yalnızca sistem yöneticisi değiştirir."
# GTIN-13 = firma öneki + ürün referansı + kontrol hanesi: önek ve ürün referansı birlikte 12 hane.
GTIN13_BODY = 12
# SSCC (18 hane) = uzantı hanesi + firma öneki + seri no + kontrol hanesi: önek ve seri no 16 hane.
SSCC_BODY = 16
# Son GS1 değişikliği bu alanlardan birini değiştiren denetim kaydıdır (sayaç ilerlemesi sayılmaz).
_GS1_SETTING_KEYS = ("gs1_company_prefix", "sscc_extension_digit", "next_item_reference")


@dataclass(frozen=True)
class Gs1Settings:
    """GS1 bölümünün durumu."""

    company_prefix: str
    extension_digit: int
    next_sscc_serial: int
    next_item_reference: int | None
    sscc_enabled: bool
    gtin_suggestion_enabled: bool
    item_reference_digits: int | None
    updated_at: datetime | None
    updated_by_name: str


def item_reference_digits(prefix: str) -> int | None:
    """GTIN-13'te ürün referansının hane sayısı (12 - önek uzunluğu); önek yoksa None."""
    return GTIN13_BODY - len(prefix) if prefix else None


def _last_gs1_change(instance: LabelSettings) -> AuditLog | None:
    changed = Q()
    for key in _GS1_SETTING_KEYS:
        changed |= Q(changes__has_key=key)
    return (
        AuditLog.objects.filter(
            content_type=ContentType.objects.get_for_model(LabelSettings), object_id=instance.pk
        )
        .filter(changed)
        .select_related("actor")
        .order_by("-timestamp", "-id")
        .first()
    )


def get_gs1_settings() -> Gs1Settings:
    """GS1 ayarları. Son değişiklik (zaman, kullanıcı) denetim günlüğünden okunur: ayar kaydının
    `updated_at` alanı SSCC ve ürün referansı sayaçlarıyla da değişir."""
    instance = get_label_settings()
    prefix = instance.gs1_company_prefix
    change = _last_gs1_change(instance)
    actor = change.actor if change is not None else None
    return Gs1Settings(
        company_prefix=prefix,
        extension_digit=instance.sscc_extension_digit,
        next_sscc_serial=instance.next_sscc_serial,
        next_item_reference=instance.next_item_reference,
        sscc_enabled=bool(prefix),
        gtin_suggestion_enabled=bool(prefix) and instance.next_item_reference is not None,
        item_reference_digits=item_reference_digits(prefix),
        updated_at=change.timestamp if change is not None else None,
        updated_by_name=(actor.full_name or actor.username) if actor is not None else "",
    )


def _check_prefix_and_extension(instance: LabelSettings) -> None:
    prefix = instance.gs1_company_prefix
    if prefix and not (is_ascii_digits(prefix) and 6 <= len(prefix) <= 12):
        raise BusinessRuleError(
            "invalid_gs1_prefix", "GS1 firma öneki 6-12 haneli bir sayı olmalıdır."
        )
    extension = instance.sscc_extension_digit
    if isinstance(extension, bool) or not isinstance(extension, int) or not 0 <= extension <= 9:
        raise BusinessRuleError(
            "invalid_extension_digit", "SSCC uzantı hanesi 0-9 arasında olmalıdır."
        )


def _check_item_reference(prefix: str, reference: int | None) -> None:
    """Girilen ürün referansı: 0 ≤ ref < 10^(12 - önek uzunluğu); önek yoksa girilemez. (Sayaç
    kaydedilen GTIN'lerle aralığın sonuna kadar ilerleyebilir: öneri "tükendi" der.)"""
    if reference is None:
        return
    if not prefix:
        raise BusinessRuleError(
            "invalid_item_reference",
            "Ürün referansı GS1 firma önekiyle birlikte girilir; önce firma önekini girin.",
        )
    digits = GTIN13_BODY - len(prefix)
    if isinstance(reference, bool) or not isinstance(reference, int):
        reference = -1
    if not 0 <= reference < 10**digits:
        raise BusinessRuleError(
            "invalid_item_reference",
            f"Ürün referansı 0 ile {10**digits - 1} arasında olmalıdır ({len(prefix)} haneli "
            "firma önekinde GTIN-13 = önek + ürün referansı + kontrol hanesi).",
        )


@transaction.atomic
def update_gs1_settings(
    actor: User,
    *,
    note: str,
    company_prefix: str | EllipsisType = ...,
    extension_digit: int | EllipsisType = ...,
    next_item_reference: int | None | EllipsisType = ...,
) -> LabelSettings:
    """GS1 ayarlarını değiştirir: firma öneki, SSCC uzantı hanesi, sıradaki ürün referansı
    (verilmeyen değişmez; ürün referansı `None` ile silinir).

    - Yalnız admin (`PermissionDenied`); değişiklik notu zorunlu (`note_required`), notla
      denetim günlüğüne yazılır.
    - Önek 6-12 rakam ya da boş (`invalid_gs1_prefix`), uzantı 0-9 (`invalid_extension_digit`),
      ürün referansı 0 ≤ ref < 10^(12 - önek uzunluğu), önek yoksa girilemez
      (`invalid_item_reference`).
    - Önek değişince sıradaki ürün referansı silinir (aynı istekte verilmediyse): referans önekin
      numaralamasıdır, yeni önekte GS1 üyeliğindeki ilk boş referans girilir.
    - Önek ya da uzantı değişince SSCC seri no o (uzantı + önek) ile basılmış en büyük seri no + 1
      olur (yoksa 1): eski öneke dönülünce SSCC çakışmaz.
    """
    if not user_has_role(actor, (ADMIN,)):
        raise PermissionDenied(GS1_ADMIN_MESSAGE)
    note = (note or "").strip()
    if not note:
        raise BusinessRuleError("note_required", "Değişiklik notu yazın (geçmişte görünür).")
    get_label_settings()
    instance = LabelSettings.objects.select_for_update().order_by("pk").first()
    assert instance is not None
    old_prefix, old_extension = instance.gs1_company_prefix, instance.sscc_extension_digit
    if not isinstance(company_prefix, EllipsisType):
        instance.gs1_company_prefix = str(company_prefix or "").strip()
    if not isinstance(extension_digit, EllipsisType):
        instance.sscc_extension_digit = extension_digit
    _check_prefix_and_extension(instance)
    if not isinstance(next_item_reference, EllipsisType):
        _check_item_reference(instance.gs1_company_prefix, next_item_reference)
        instance.next_item_reference = next_item_reference
    elif instance.gs1_company_prefix != old_prefix:
        instance.next_item_reference = None
    if (instance.gs1_company_prefix, instance.sscc_extension_digit) != (old_prefix, old_extension):
        instance.next_sscc_serial = _first_free_sscc_serial(
            instance.sscc_extension_digit, instance.gs1_company_prefix
        )
    return save_with_audit(instance, actor, note=note)


# --- SSCC --------------------------------------------------------------------------------------

# Basılmış SSCC'leri saklayan modül (inventory: palet etiketi) kaynağını buraya kaydeder; masterdata
# onu import etmez (ekipman kancalarıyla aynı yöntem). kaynak(başlangıç) → bu başlangıçla (uzantı
# hanesi + firma öneki) basılmış en büyük SSCC ya da None.
SsccSource = Callable[[str], str | None]
_sscc_sources: list[SsccSource] = []


def register_sscc_source(source: SsccSource) -> SsccSource:
    """SSCC kaynağını kaydeder (dekoratör olarak da kullanılır)."""
    if source not in _sscc_sources:
        _sscc_sources.append(source)
    return source


def max_used_sscc_serial(start: str) -> int:
    """`start` (uzantı hanesi + firma öneki) ile basılmış SSCC'lerin en büyük seri numarası; yoksa
    0. Başka önekle basılmış ama aynı rakamlarla başlayan SSCC de sayılır: aynı 18 hane yeniden
    verilmez."""
    best = 0
    for source in _sscc_sources:
        top = source(start)
        if top and len(top) == 18 and top.startswith(start) and is_ascii_digits(top):
            best = max(best, int(top[len(start) : 17]))
    return best


def _first_free_sscc_serial(extension: int, prefix: str) -> int:
    """Önek ya da uzantı değişince sıradaki SSCC seri no: o (uzantı + önek) ile basılmış en büyük
    seri no + 1, yoksa 1 (önek boşsa 1)."""
    if not prefix:
        return 1
    return max_used_sscc_serial(f"{extension}{prefix}") + 1


@transaction.atomic
def next_sscc(actor: User | None) -> str:
    """Sıradaki SSCC'yi (18 hane: uzantı + firma öneki + seri + kontrol) üretir ve sayacı
    artırır. Çakışmasızdır (`select_for_update`); basılmış bir SSCC'yi yeniden vermez (sayaç geride
    kalmışsa basılmış en büyük seri no + 1'den devam eder). Önek yoksa `sscc_disabled`, seri
    numaraları bittiyse `sscc_exhausted` hatası."""
    get_label_settings()
    instance = LabelSettings.objects.select_for_update().order_by("pk").first()
    assert instance is not None
    prefix = instance.gs1_company_prefix
    if not prefix:
        raise BusinessRuleError(
            "sscc_disabled",
            "GS1 firma öneki tanımlı değil; palet (SSCC) etiketi kullanılamaz.",
        )
    serial_digits = SSCC_BODY - len(prefix)
    start = f"{instance.sscc_extension_digit}{prefix}"
    serial = max(instance.next_sscc_serial, max_used_sscc_serial(start) + 1)
    if serial >= 10**serial_digits:
        raise BusinessRuleError("sscc_exhausted", "SSCC seri numaraları tükendi.")
    body = f"{start}{serial:0{serial_digits}d}"
    instance.next_sscc_serial = serial + 1
    instance.updated_by = actor if actor is not None and actor.is_authenticated else None
    instance.save(update_fields=["next_sscc_serial", "updated_by", "updated_at"])
    return body + gs1_check_digit(body)


# --- GTIN önerisi ------------------------------------------------------------------------------

GTIN_SUGGESTION_OFF = (
    "GS1 firma öneki ve sıradaki ürün referansı Sistem > Kodlama sistematiği > GS1'de girilmemiş."
)
# Koli GTIN'inin (GTIN-14) gösterge hanesi: 1-8 (9 değişken ölçülü ürünlere ayrılmıştır).
CASE_INDICATORS = tuple(str(digit) for digit in range(1, 9))


@dataclass(frozen=True)
class GtinSuggestion:
    """Ürün GTIN'i önerisi (yalnızca mamul)."""

    active: bool
    gtin: str | None
    reason: str


@dataclass(frozen=True)
class CaseGtinSuggestion:
    """Koli GTIN'i önerisi."""

    gtin: str | None
    reason: str


def gtin13(prefix: str, reference: int) -> str:
    """Firma öneki + ürün referansı (12 - önek uzunluğu hane) + kontrol hanesi."""
    digits = GTIN13_BODY - len(prefix)
    body = prefix + (f"{reference:0{digits}d}" if digits else "")
    return body + gs1_check_digit(body)


def item_reference(gtin: str, prefix: str) -> int | None:
    """GTIN firma önekiyle başlayan bir GTIN-13 ise (14 haneli normal biçimde "0" + önek) ürün
    referansı; değilse None."""
    if not prefix or not is_ascii_digits(gtin) or len(gtin) > 14:
        return None
    start = "0" + prefix
    normal = gtin14(gtin)
    if not normal.startswith(start):
        return None
    digits = normal[len(start) : 13]
    return int(digits) if digits else 0


def _gtin14_values(queryset: QuerySet[Any], start: str, among: Collection[str]) -> set[str]:
    rows = queryset.exclude(gtin="").annotate(gtin_14=LPad("gtin", 14, Value("0")))
    if start:
        rows = rows.filter(gtin_14__startswith=start)
    if among:
        rows = rows.filter(gtin_14__in=list(among))
    return {str(value) for value in rows.values_list("gtin_14", flat=True)}


def used_gtin14s(*, start: str = "", among: Collection[str] = ()) -> set[str]:
    """Kullanılmış ürün ve koli GTIN'lerinin 14 haneli normal biçimleri (pasif kayıtlar dahil):
    `start` ile başlayanlar ve/veya `among` içindekiler."""
    return _gtin14_values(Material._base_manager.all(), start, among) | _gtin14_values(
        MaterialUnitConversion._base_manager.all(), start, among
    )


def _first_free_item_reference(prefix: str, start: int, used: Collection[str]) -> int | None:
    """`start`'tan itibaren GTIN-13'ü (14 haneli normal biçimde) `used` içinde olmayan ilk ürün
    referansı; referanslar bittiyse None."""
    reference = start
    while reference < 10 ** (GTIN13_BODY - len(prefix)):
        if gtin14(gtin13(prefix, reference)) not in used:
            return reference
        reference += 1
    return None


def gtin_suggestion(material_type: str | None = None) -> GtinSuggestion:
    """Mamul için sıradaki boş GTIN-13: firma öneki + ürün referansı + kontrol hanesi. Öneri firma
    öneki ve sıradaki ürün referansı girildiyse açıktır; kullanılmış ürün ve koli GTIN'leri (14
    haneli normal biçimde) atlanır. `material_type` verilir ve mamul değilse öneri kapalıdır."""
    if material_type is not None and material_type != Material.Type.FINISHED:
        return GtinSuggestion(False, None, "GTIN önerisi yalnızca mamulde kullanılır.")
    row = get_label_settings()
    prefix, reference = row.gs1_company_prefix, row.next_item_reference
    if not prefix:
        return GtinSuggestion(False, None, GTIN_SUGGESTION_OFF)
    if reference is None:
        return GtinSuggestion(
            False,
            None,
            "Sıradaki ürün referansı Sistem > Kodlama sistematiği > GS1'de girilmemiş.",
        )
    free = _first_free_item_reference(prefix, reference, used_gtin14s(start="0" + prefix))
    if free is not None:
        gtin = gtin13(prefix, free)
        return GtinSuggestion(
            True,
            gtin,
            f"Sıradaki boş GTIN-13: firma öneki {prefix}, ürün referansı "
            f"{gtin[len(prefix) : 12] or '-'}, kontrol hanesi {gtin[-1]}.",
        )
    return GtinSuggestion(
        True,
        None,
        f"{prefix} firma önekinin bütün ürün referansları kullanılmış; GTIN'i elle girin.",
    )


def case_gtin_suggestion(material: Material) -> CaseGtinSuggestion:
    """Koli GTIN'i önerisi: malzemenin GTIN-13'ünden (ya da GTIN-12/14'ünden) gösterge hanesi 1-8
    ile türetilen ilk boş GTIN-14 (gösterge + 12 hane + kontrol hanesi)."""
    gtin = (material.gtin or "").strip()
    if not gtin:
        return CaseGtinSuggestion(
            None, "Önce malzemenin GTIN'ini girin; koli GTIN'i ürün GTIN'inden türetilir."
        )
    if len(gtin) == 8 or not is_valid_gtin(gtin):
        return CaseGtinSuggestion(
            None,
            "Koli GTIN'i GTIN-13'ten (ya da GTIN-12/14'ten) türetilir; bu GTIN'den türetilemez, "
            "koli GTIN'ini elle girin.",
        )
    base = gtin14(gtin)[1:13]
    candidates = [code + base + gs1_check_digit(code + base) for code in CASE_INDICATORS]
    used = used_gtin14s(among=candidates)
    for candidate in candidates:
        if candidate not in used:
            return CaseGtinSuggestion(
                candidate,
                f"Ürün GTIN'i {gtin} gösterge hanesi {candidate[0]} ile koli GTIN'ine çevrildi.",
            )
    return CaseGtinSuggestion(
        None,
        "Gösterge hanesi 1-8 ile türetilen koli GTIN'lerinin hepsi kullanılıyor; koli GTIN'ini "
        "elle girin.",
    )


def _advance_item_reference(actor: User | None, gtin: str) -> None:
    """Önerilen GTIN kaydedilince sıradaki ürün referansı ilerler: GTIN firma önekiyle başlıyor ve
    ürün referansı sıradaki referansla önerinin `COUNTER_WINDOW` ilerisi arasındaysa sayaç
    referans + 1 olur (`core.coding` sayacı gibi). Öneri, sıradaki referanstan itibaren ilk boş
    referanstır (`gtin_suggestion`; kaydedilen GTIN dolu sayılmaz): eski ya da elle girilmiş
    GTIN'ler sayacın önünü doldurmuşsa pencere oradan ölçülür. Daha ilerideki elle girilmiş GTIN
    sayacı ilerletmez (öneri onu yine atlar)."""

    def advances(row: LabelSettings | None) -> int | None:
        if row is None or row.next_item_reference is None:
            return None
        prefix, low = row.gs1_company_prefix, row.next_item_reference
        reference = item_reference(gtin, prefix)
        if reference is None or reference < low:
            return None
        # Öneri en az sıradaki referanstır: pencerenin içindeyse öneri aranmaz.
        if reference <= low + coding.COUNTER_WINDOW:
            return reference
        used = used_gtin14s(start="0" + prefix) - {gtin14(gtin)}
        suggested = _first_free_item_reference(prefix, low, used)
        if suggested is None or reference > suggested + coding.COUNTER_WINDOW:
            return None
        return reference

    if advances(LabelSettings.objects.order_by("pk").first()) is None:
        return
    row = LabelSettings.objects.select_for_update().order_by("pk").first()
    reference = advances(row)
    if row is None or reference is None:
        return
    row.next_item_reference = reference + 1
    row.updated_by = actor if actor is not None and actor.is_authenticated else None
    row.save(update_fields=["next_item_reference", "updated_by", "updated_at"])


def case_gtin(material: Material) -> str:
    """Malzemenin koli GTIN'i: koli (KOLI) dönüşümündeki GTIN; yoksa "". Koli etiketinin (01),
    palet etiketinin (02) alanına basılır. Okutma (`selectors.gtin_owner`) gibi pasif dönüşümün
    GTIN'i de sayılır: basılmış etiket aynı GTIN'le okunur."""
    value = (
        MaterialUnitConversion.objects.filter(material=material, unit__code=CASE_UNIT)
        .exclude(gtin="")
        .values_list("gtin", flat=True)
        .first()
    )
    return str(value or "")


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
