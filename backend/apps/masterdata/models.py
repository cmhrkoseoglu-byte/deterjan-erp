"""Ana veriler: birim, malzeme, dönüşüm, depo/lokasyon, ekipman, tedarikçi, müşteri.

Bu dosyada iş mantığı yoktur; yazma işlemleri `services.py` üzerinden yapılır.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import MasterDataModel
from apps.masterdata.fields import CodeField


class UnitOfMeasure(MasterDataModel):
    class Kind(models.TextChoices):
        MASS = "MASS", "Kütle"
        VOLUME = "VOLUME", "Hacim"
        COUNT = "COUNT", "Adet"

    code = CodeField("kod", max_length=16, unique=True)
    name = models.CharField("ad", max_length=64)
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    # Aynı tür içinde temel birime katsayı: KG = 1, G = 0.001; LT = 1, ML = 0.001.
    # Boş: genel katsayısı olmayan ambalaj birimleri (KOLI, PALET); yalnızca malzemeye özel
    # dönüşümle (`MaterialUnitConversion`) çevrilir.
    factor_to_kind_base = models.DecimalField(
        "tür temel birimine katsayı", null=True, blank=True, max_digits=18, decimal_places=6
    )

    class Meta:
        verbose_name = "birim"
        verbose_name_plural = "birimler"
        ordering = ["kind", "code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(factor_to_kind_base__isnull=True) | Q(factor_to_kind_base__gt=0),
                name="masterdata_uom_factor_positive",
                violation_error_message="Katsayı sıfırdan büyük olmalıdır.",
            )
        ]

    def __str__(self) -> str:
        return self.code


class MaterialCategory(MasterDataModel):
    code = CodeField("kod", unique=True)
    name = models.CharField("ad", max_length=128)

    class Meta:
        verbose_name = "malzeme kategorisi"
        verbose_name_plural = "malzeme kategorileri"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Material(MasterDataModel):
    class Type(models.TextChoices):
        RAW = "RAW", "Hammadde"
        PACKAGING = "PACKAGING", "Ambalaj"
        BULK = "BULK", "Yarı mamul (dökme)"
        FINISHED = "FINISHED", "Mamul"

    code = CodeField("kod", unique=True)
    name = models.CharField("ad", max_length=200)
    material_type = models.CharField("malzeme türü", max_length=16, choices=Type.choices)
    category = models.ForeignKey(
        MaterialCategory,
        verbose_name="kategori",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="materials",
    )
    base_unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="temel birim", on_delete=models.PROTECT, related_name="+"
    )
    density = models.DecimalField(
        "yoğunluk (g/ml)",
        null=True,
        blank=True,
        help_text="kg ↔ lt dönüşümü için",
        max_digits=18,
        decimal_places=4,
    )
    shelf_life_days = models.PositiveIntegerField("raf ömrü (gün)", null=True, blank=True)
    min_stock = models.DecimalField(
        "minimum stok",
        null=True,
        blank=True,
        help_text="Temel birimde",
        max_digits=18,
        decimal_places=4,
    )
    requires_incoming_qc = models.BooleanField("giriş kontrolü gerekli", default=True)
    is_hazardous = models.BooleanField("tehlikeli madde", default=False)
    storage_notes = models.TextField("depolama notu", blank=True)

    class Meta:
        verbose_name = "malzeme"
        verbose_name_plural = "malzemeler"
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(density__isnull=True) | Q(density__gt=0),
                name="masterdata_material_density_positive",
                violation_error_message="Yoğunluk sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(min_stock__isnull=True) | Q(min_stock__gte=0),
                name="masterdata_material_min_stock_non_negative",
                violation_error_message="Minimum stok negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class MaterialUnitConversion(MasterDataModel):
    """Malzemeye özel dönüşüm: 1 `unit` = `factor_to_base` temel birim (1 KOLI = 12 ADET)."""

    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="conversions"
    )
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    factor_to_base = models.DecimalField("temel birim karşılığı", max_digits=18, decimal_places=6)

    class Meta:
        verbose_name = "malzeme birim dönüşümü"
        verbose_name_plural = "malzeme birim dönüşümleri"
        ordering = ["material__code", "unit__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["material", "unit"],
                name="masterdata_conversion_material_unit_uniq",
                violation_error_message="Bu malzeme için bu birimin dönüşümü zaten tanımlı.",
            ),
            models.CheckConstraint(
                condition=Q(factor_to_base__gt=0),
                name="masterdata_conversion_factor_positive",
                violation_error_message="Dönüşüm katsayısı sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.material.code}: 1 {self.unit.code} = {self.factor_to_base}"


class Warehouse(MasterDataModel):
    code = CodeField("kod", unique=True)
    name = models.CharField("ad", max_length=128)

    class Meta:
        verbose_name = "depo"
        verbose_name_plural = "depolar"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Location(MasterDataModel):
    class Type(models.TextChoices):
        STORAGE = "STORAGE", "Depolama"
        QUARANTINE = "QUARANTINE", "Karantina"
        PRODUCTION = "PRODUCTION", "Üretim"
        SHIPPING = "SHIPPING", "Sevkiyat"
        TANK = "TANK", "Tank"

    warehouse = models.ForeignKey(
        Warehouse, verbose_name="depo", on_delete=models.PROTECT, related_name="locations"
    )
    # Barkodla okutulacağı için tüm depolarda benzersizdir.
    code = CodeField("kod", unique=True)
    name = models.CharField("ad", max_length=128)
    location_type = models.CharField("lokasyon türü", max_length=16, choices=Type.choices)

    class Meta:
        verbose_name = "lokasyon"
        verbose_name_plural = "lokasyonlar"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Equipment(MasterDataModel):
    class Type(models.TextChoices):
        MIXING_TANK = "MIXING_TANK", "Karıştırma tankı"
        STORAGE_TANK = "STORAGE_TANK", "Stok tankı"
        FILLING_LINE = "FILLING_LINE", "Dolum hattı"
        SCALE = "SCALE", "Terazi"
        OTHER = "OTHER", "Diğer"

    TANK_TYPES = (Type.MIXING_TANK, Type.STORAGE_TANK)

    code = CodeField("kod", unique=True)
    name = models.CharField("ad", max_length=128)
    equipment_type = models.CharField("ekipman türü", max_length=16, choices=Type.choices)
    capacity = models.DecimalField(
        "kapasite", null=True, blank=True, max_digits=18, decimal_places=4
    )
    capacity_unit = models.ForeignKey(
        UnitOfMeasure,
        verbose_name="kapasite birimi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    location = models.ForeignKey(
        Location,
        verbose_name="lokasyon",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="equipment",
        help_text="Tanklar için zorunlu",
    )

    class Meta:
        verbose_name = "ekipman"
        verbose_name_plural = "ekipmanlar"
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(equipment_type__in=["MIXING_TANK", "STORAGE_TANK"])
                | Q(location__isnull=False),
                name="masterdata_equipment_tank_has_location",
                violation_error_message="Tanklar için lokasyon zorunludur.",
            ),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True)
                | (Q(capacity__gt=0) & Q(capacity_unit__isnull=False)),
                name="masterdata_equipment_capacity_valid",
                violation_error_message="Kapasite sıfırdan büyük olmalı ve birimi girilmelidir.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    @property
    def is_tank(self) -> bool:
        return self.equipment_type in self.TANK_TYPES


class BusinessPartner(MasterDataModel):
    """Tedarikçi ve müşterinin ortak alanları."""

    code = CodeField("kod", unique=True)
    name = models.CharField("ünvan", max_length=200)
    tax_office = models.CharField("vergi dairesi", max_length=100, blank=True)
    tax_number = models.CharField("vergi no / TCKN", max_length=11, blank=True)
    address = models.TextField("adres", blank=True)
    phone = models.CharField("telefon", max_length=32, blank=True)
    email = models.EmailField("e-posta", blank=True)
    contact_person = models.CharField("yetkili kişi", max_length=128, blank=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Supplier(BusinessPartner):
    class Meta(BusinessPartner.Meta):
        verbose_name = "tedarikçi"
        verbose_name_plural = "tedarikçiler"


class Customer(BusinessPartner):
    class Meta(BusinessPartner.Meta):
        verbose_name = "müşteri"
        verbose_name_plural = "müşteriler"
