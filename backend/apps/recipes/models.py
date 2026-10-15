"""Sürümlü reçeteler (formülasyon).

Bu dosyada iş mantığı yoktur; yazma işlemleri `services.py` üzerinden yapılır. Sürüm durumu
yalnızca `services` içinden, `state.py`'deki izin tablosuna göre değişir.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, MasterDataModel, User
from apps.masterdata.fields import CodeField
from apps.masterdata.models import Material, UnitOfMeasure


class Recipe(MasterDataModel):
    code = CodeField("kod", unique=True)
    name = models.CharField("ad", max_length=200)
    product = models.ForeignKey(
        Material,
        verbose_name="ürün (dökme)",
        on_delete=models.PROTECT,
        related_name="recipes",
    )
    notes = models.TextField("notlar", blank=True)

    class Meta:
        verbose_name = "reçete"
        verbose_name_plural = "reçeteler"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class RecipeVersion(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        APPROVED = "APPROVED", "Onaylı"
        OBSOLETE = "OBSOLETE", "Geçersiz"

    recipe = models.ForeignKey(
        Recipe, verbose_name="reçete", on_delete=models.PROTECT, related_name="versions"
    )
    version_no = models.PositiveIntegerField("sürüm no", editable=False)
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        editable=False,
    )
    batch_size = models.DecimalField("şarj miktarı", max_digits=18, decimal_places=4)
    batch_unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="şarj birimi", on_delete=models.PROTECT, related_name="+"
    )
    change_note = models.TextField("değişiklik notu", blank=True)
    copied_from = models.ForeignKey(
        "self",
        verbose_name="kopyalandığı sürüm",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    approved_by = models.ForeignKey(
        User,
        verbose_name="onaylayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    approved_at = models.DateTimeField("onay zamanı", null=True, blank=True, editable=False)
    obsoleted_at = models.DateTimeField(
        "geçersiz olma zamanı", null=True, blank=True, editable=False
    )

    class Meta:
        verbose_name = "reçete sürümü"
        verbose_name_plural = "reçete sürümleri"
        ordering = ["recipe__code", "-version_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "version_no"],
                name="recipes_version_no_uniq",
                violation_error_message="Bu sürüm numarası zaten var.",
            ),
            # Bir reçetenin aynı anda tek onaylı sürümü olur.
            models.UniqueConstraint(
                fields=["recipe"],
                condition=Q(status="APPROVED"),
                name="recipes_single_approved_version",
                violation_error_message="Reçetenin zaten onaylı bir sürümü var.",
            ),
            models.CheckConstraint(
                condition=Q(batch_size__gt=0),
                name="recipes_batch_size_positive",
                violation_error_message="Şarj miktarı sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.recipe.code} v{self.version_no}"

    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT


class RecipeLine(BaseModel):
    version = models.ForeignKey(
        RecipeVersion, verbose_name="sürüm", on_delete=models.PROTECT, related_name="lines"
    )
    sequence = models.PositiveIntegerField("sıra")
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="recipe_lines"
    )
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    tolerance_pct = models.DecimalField(
        "tartım toleransı (%)", max_digits=5, decimal_places=2, default=Decimal("2.00")
    )
    instruction = models.TextField("talimat", blank=True)
    # Yalnızca işaret: su da stoklu malzemedir ve her şarjda stoktan düşer (Karar D-1).
    is_water = models.BooleanField("şebeke suyu", default=False)

    class Meta:
        verbose_name = "reçete satırı"
        verbose_name_plural = "reçete satırları"
        ordering = ["version", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "sequence"],
                name="recipes_line_sequence_uniq",
                violation_error_message="Bu sıra numarası sürümde zaten kullanılıyor.",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="recipes_line_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(tolerance_pct__gte=0) & Q(tolerance_pct__lte=100),
                name="recipes_line_tolerance_range",
                violation_error_message="Tolerans 0 ile 100 arasında olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.version} #{self.sequence} {self.material.code}"


class RecipeStep(BaseModel):
    version = models.ForeignKey(
        RecipeVersion, verbose_name="sürüm", on_delete=models.PROTECT, related_name="steps"
    )
    sequence = models.PositiveIntegerField("sıra")
    description = models.TextField("açıklama")
    duration_min = models.PositiveIntegerField("süre (dk)", null=True, blank=True)
    temperature_c = models.DecimalField(
        "sıcaklık (°C)", max_digits=6, decimal_places=2, null=True, blank=True
    )
    mixer_rpm = models.PositiveIntegerField("karıştırıcı devri (rpm)", null=True, blank=True)

    class Meta:
        verbose_name = "proses adımı"
        verbose_name_plural = "proses adımları"
        ordering = ["version", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "sequence"],
                name="recipes_step_sequence_uniq",
                violation_error_message="Bu sıra numarası sürümde zaten kullanılıyor.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.version} adım {self.sequence}"
