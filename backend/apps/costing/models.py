"""Maliyet (Faz 4, Adım 4.1): fiili maliyet, lot bazında.

Lotun maliyeti oluştuğunda / şarj ya da dolum partisi bittiğinde bir kez hesaplanıp `LotCost`
(kalem kalem `LotCostLine`) olarak saklanır; sonradan yeniden hesaplama yeni sürüm açar, eski
sürümler kalır. Lotun güncel birim maliyeti `inventory.Lot.unit_cost`'a da yazılır. Tutarlar
yalnızca yonetim ve admin rolüne gösterilir (Karar D-15). Bu dosyada iş mantığı yoktur.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, MasterDataModel, User
from apps.inventory.models import Lot
from apps.masterdata.models import Material


class CostStage(models.TextChoices):
    PRODUCTION = "PRODUCTION", "Üretim"
    FILLING = "FILLING", "Dolum"


class CostRate(BaseModel):
    """Genel gider oranı (Karar D-15): aşama × tür için TL / kg, bir tarihten itibaren geçerli.
    Hesapta şarjın / partinin bitiş tarihinde geçerli oran kullanılır; eski oranlar kalır."""

    class Kind(models.TextChoices):
        ENERGY = "ENERGY", "Enerji"
        LABOR = "LABOR", "İşçilik"
        DEPRECIATION = "DEPRECIATION", "Amortisman"

    stage = models.CharField("aşama", max_length=16, choices=CostStage.choices)
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    rate_per_kg = models.DecimalField("oran (TL/kg)", max_digits=18, decimal_places=4)
    valid_from = models.DateField("geçerlilik başlangıcı")
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        verbose_name = "gider oranı"
        verbose_name_plural = "gider oranları"
        ordering = ["stage", "kind", "-valid_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["stage", "kind", "valid_from"],
                name="costing_rate_stage_kind_date_uniq",
                violation_error_message="Bu aşama ve türde bu tarihte başlayan bir oran zaten var.",
            ),
            models.CheckConstraint(
                condition=Q(rate_per_kg__gte=0),
                name="costing_rate_non_negative",
                violation_error_message="Oran negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.stage} {self.kind} {self.rate_per_kg} ({self.valid_from})"


class StandardCost(MasterDataModel):
    """Malzemenin standart birim maliyeti (TL / temel birim). Fiyatı olmayan ve son alış maliyeti
    bilinmeyen lot için tahmini maliyet olarak kullanılır."""

    material = models.OneToOneField(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="standard_cost"
    )
    unit_cost = models.DecimalField("birim maliyet (TL)", max_digits=18, decimal_places=4)
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        verbose_name = "standart maliyet"
        verbose_name_plural = "standart maliyetler"
        ordering = ["material__code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(unit_cost__gte=0),
                name="costing_standard_cost_non_negative",
                violation_error_message="Maliyet negatif olamaz.",
            )
        ]

    def __str__(self) -> str:
        return f"{self.material_id} {self.unit_cost}"


class LotCost(BaseModel):
    """Lotun bir maliyet hesabı (sürüm). Lot başına tek güncel sürüm vardır."""

    class Method(models.TextChoices):
        PURCHASE = "PURCHASE", "Mal kabul"
        PRODUCTION = "PRODUCTION", "Üretim şarjı"
        FILLING = "FILLING", "Dolum partisi"
        ESTIMATE = "ESTIMATE", "Tahmin"

    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="costs")
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    version = models.PositiveIntegerField("sürüm")
    is_current = models.BooleanField("güncel", default=True, db_index=True)
    method = models.CharField("yöntem", max_length=16, choices=Method.choices)
    # Maliyetin bölündüğü miktar (temel birim): mal kabul miktarı, gerçek çıktı, sağlam adet.
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    total_cost = models.DecimalField("toplam maliyet (TL)", max_digits=18, decimal_places=2)
    unit_cost = models.DecimalField(
        "birim maliyet (TL)", null=True, blank=True, max_digits=18, decimal_places=4
    )
    # Bilgi amaçlı: mamul firesine (dolup ayrılan adet) giden pay; toplamın içindedir.
    finished_scrap_cost = models.DecimalField(
        "mamul firesi payı (TL)", max_digits=18, decimal_places=2, default=0
    )
    is_estimated = models.BooleanField("tahmini", default=False)
    # Bir girdinin maliyeti hiç bilinmiyor (sıfır sayıldı).
    has_missing = models.BooleanField("eksik maliyet", default=False)
    cost_date = models.DateField("maliyet tarihi", db_index=True)
    calculated_at = models.DateTimeField("hesaplanma zamanı")
    calculated_by = models.ForeignKey(
        User, verbose_name="hesaplayan", on_delete=models.PROTECT, null=True, related_name="+"
    )
    note = models.TextField("sürüm notu", blank=True)

    class Meta:
        verbose_name = "lot maliyeti"
        verbose_name_plural = "lot maliyetleri"
        ordering = ["-cost_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["lot", "version"], name="costing_lot_cost_version_uniq"
            ),
            models.UniqueConstraint(
                fields=["lot"], condition=Q(is_current=True), name="costing_lot_cost_one_current"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.lot_id} v{self.version}"


class LotCostLine(BaseModel):
    """Maliyet dökümünün bir kalemi."""

    class Category(models.TextChoices):
        PURCHASE = "PURCHASE", "Alış"
        EXTRA = "EXTRA", "Ek masraf"
        MATERIAL = "MATERIAL", "Hammadde"
        BULK = "BULK", "Bulk"
        PACKAGING = "PACKAGING", "Ambalaj"
        SCRAP = "SCRAP", "Fire"
        ENERGY = "ENERGY", "Enerji"
        LABOR = "LABOR", "İşçilik"
        DEPRECIATION = "DEPRECIATION", "Amortisman"
        ESTIMATE = "ESTIMATE", "Tahmini maliyet"

    lot_cost = models.ForeignKey(
        LotCost, verbose_name="lot maliyeti", on_delete=models.PROTECT, related_name="lines"
    )
    line_no = models.PositiveIntegerField("sıra")
    category = models.CharField("kalem", max_length=16, choices=Category.choices)
    description = models.CharField("açıklama", max_length=200, blank=True)
    material = models.ForeignKey(
        Material,
        verbose_name="malzeme",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    source_lot = models.ForeignKey(
        Lot,
        verbose_name="girdi lotu",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    quantity = models.DecimalField("miktar", null=True, blank=True, max_digits=18, decimal_places=4)
    unit_cost = models.DecimalField(
        "birim maliyet (TL)", null=True, blank=True, max_digits=18, decimal_places=4
    )
    amount = models.DecimalField("tutar (TL)", max_digits=18, decimal_places=2)
    is_estimated = models.BooleanField("tahmini", default=False)
    is_missing = models.BooleanField("maliyet yok", default=False)

    class Meta:
        verbose_name = "lot maliyeti kalemi"
        verbose_name_plural = "lot maliyeti kalemleri"
        ordering = ["lot_cost", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["lot_cost", "line_no"], name="costing_line_no_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.lot_cost_id}/{self.line_no} {self.category} {self.amount}"
