"""Üretim: üretim emri, ihtiyaç listesi, malzeme hazırlama, şarj ve tartım kayıtları.

Bu dosyada iş mantığı yoktur. Emir ve şarj durumu yalnızca `services` içinden, `state.py`'deki
izin tablosuna göre değişir. Stok `inventory.services` ile hareket eder (CLAUDE.md §3).
"""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, User
from apps.inventory.models import Lot, LotLink, StockMovement
from apps.masterdata.models import Equipment, Location, Material, UnitOfMeasure
from apps.recipes.models import RecipeLine, RecipeVersion


class ProductionOrder(DocumentModel):
    """Üretim emri (`UE-`). Karar D-4: emir tank kapasitesini aşarsa birden çok şarja bölünür.

    Yeniden işleme emri (Faz 2): `rework_lot` kalite kararıyla bloke edilen bulk lottur ve emrin
    ilk girdisidir. Reçete isteğe bağlıdır: seçilirse lot reçeteli yeni şarjla harmanlanır,
    seçilmezse planlamanın girdiği düzeltme satırları (`ReworkAddition`) kullanılır."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        APPROVED = "APPROVED", "Onaylandı"
        MATERIAL_PREP = "MATERIAL_PREP", "Malzeme hazırlanıyor"
        MATERIAL_READY = "MATERIAL_READY", "Malzeme hazır"
        IN_PRODUCTION = "IN_PRODUCTION", "Üretimde"
        QC_PENDING = "QC_PENDING", "Analiz bekliyor"
        COMPLETED = "COMPLETED", "Tamamlandı"
        CANCELLED = "CANCELLED", "İptal"

    class Priority(models.IntegerChoices):
        LOW = 1, "Düşük"
        NORMAL = 2, "Normal"
        HIGH = 3, "Yüksek"
        URGENT = 4, "Acil"

    product = models.ForeignKey(
        Material, verbose_name="ürün (dökme)", on_delete=models.PROTECT, related_name="+"
    )
    recipe_version = models.ForeignKey(
        RecipeVersion,
        verbose_name="reçete sürümü",
        on_delete=models.PROTECT,
        related_name="production_orders",
        null=True,
        blank=True,
        help_text="Yalnızca yeniden işleme emrinde boş olabilir (düzeltme listesi).",
    )
    rework_lot = models.ForeignKey(
        Lot,
        verbose_name="yeniden işlenen lot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rework_orders",
    )
    planned_quantity = models.DecimalField("planlanan miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    # Ürünün temel biriminde; oluştururken/güncellerken hesaplanır.
    planned_base_quantity = models.DecimalField(
        "planlanan miktar (temel birim)", editable=False, max_digits=18, decimal_places=4
    )
    planned_date = models.DateField("planlanan tarih")
    equipment = models.ForeignKey(
        Equipment, verbose_name="karıştırma tankı", on_delete=models.PROTECT, related_name="+"
    )
    production_location = models.ForeignKey(
        Location,
        verbose_name="üretim lokasyonu",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Hazırlanan malzemenin taşındığı tank başı lokasyonu",
    )
    priority = models.PositiveSmallIntegerField(
        "öncelik", choices=Priority.choices, default=Priority.NORMAL
    )
    notes = models.TextField("notlar", blank=True)
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
    completed_at = models.DateTimeField("tamamlanma zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "üretim emri"
        verbose_name_plural = "üretim emirleri"
        ordering = ["-planned_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(planned_quantity__gt=0),
                name="production_order_quantity_positive",
                violation_error_message="Planlanan miktar sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(recipe_version__isnull=False) | Q(rework_lot__isnull=False),
                name="production_order_recipe_or_rework",
                violation_error_message="Reçetesiz emir yalnızca yeniden işleme emri olabilir.",
            ),
        ]


class ProductionRequirement(BaseModel):
    """Emir onaylanınca reçeteden ölçeklenen ihtiyaç satırı (malzemenin temel biriminde)."""

    order = models.ForeignKey(
        ProductionOrder,
        verbose_name="üretim emri",
        on_delete=models.PROTECT,
        related_name="requirements",
    )
    recipe_line = models.ForeignKey(
        RecipeLine,
        verbose_name="reçete satırı",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    # Yeniden işleme: satır yalnızca bu lottan tüketilir (hazırlanmaz, bulunduğu yerden düşülür).
    lot = models.ForeignKey(
        Lot,
        verbose_name="sabit lot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    required_quantity = models.DecimalField(
        "ihtiyaç (temel birim)", max_digits=18, decimal_places=4
    )
    tolerance_pct = models.DecimalField("tolerans (%)", max_digits=6, decimal_places=2)
    sequence = models.PositiveIntegerField("sıra")
    is_water = models.BooleanField("şebeke suyu", default=False)
    instruction = models.TextField("talimat", blank=True)

    class Meta:
        verbose_name = "üretim ihtiyacı"
        verbose_name_plural = "üretim ihtiyaçları"
        ordering = ["order", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "sequence"], name="production_requirement_seq_uniq"
            ),
            models.CheckConstraint(
                condition=Q(required_quantity__gt=0),
                name="production_requirement_quantity_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}/{self.sequence} {self.material_id}"

    @property
    def is_picked(self) -> bool:
        """Depo hazırlar mı? Su (D-1) ve yeniden işlenen lot hazırlanmaz."""
        return not self.is_water and self.lot_id is None


class ReworkAddition(BaseModel):
    """Yeniden işleme emrinin düzeltme satırı (taslakta planlama girer; onayda ihtiyaç olur)."""

    order = models.ForeignKey(
        ProductionOrder,
        verbose_name="üretim emri",
        on_delete=models.PROTECT,
        related_name="rework_additions",
    )
    sequence = models.PositiveIntegerField("sıra")
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    tolerance_pct = models.DecimalField(
        "tartım toleransı (%)", max_digits=5, decimal_places=2, default=2
    )
    is_water = models.BooleanField("şebeke suyu", default=False)
    instruction = models.TextField("talimat", blank=True)

    class Meta:
        verbose_name = "düzeltme satırı"
        verbose_name_plural = "düzeltme satırları"
        ordering = ["order", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "sequence"], name="production_rework_addition_seq_uniq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="production_rework_addition_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id} #{self.sequence} {self.material_id}"


class MaterialPick(BaseModel):
    """Depo hazırlığı: ihtiyaç için okutulan lot, depodan üretim lokasyonuna transfer edilir."""

    order = models.ForeignKey(
        ProductionOrder, verbose_name="üretim emri", on_delete=models.PROTECT, related_name="picks"
    )
    requirement = models.ForeignKey(
        ProductionRequirement,
        verbose_name="ihtiyaç",
        on_delete=models.PROTECT,
        related_name="picks",
    )
    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField("miktar (temel birim)", max_digits=18, decimal_places=4)
    from_location = models.ForeignKey(
        Location, verbose_name="kaynak lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    to_location = models.ForeignKey(
        Location, verbose_name="hedef lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    picked_by = models.ForeignKey(
        User, verbose_name="hazırlayan", on_delete=models.PROTECT, null=True, related_name="+"
    )
    picked_at = models.DateTimeField("hazırlama zamanı")
    transfer_group = models.UUIDField("transfer grubu", editable=False)
    # Emir hazırlıkta iptal edilince malzeme kaynağa geri transfer edilir.
    returned_at = models.DateTimeField("iade zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "malzeme hazırlama"
        verbose_name_plural = "malzeme hazırlamaları"
        ordering = ["order", "picked_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="production_pick_quantity_positive"
            )
        ]

    def __str__(self) -> str:
        return f"{self.order_id} {self.lot_id} {self.quantity}"


class ProductionBatch(BaseModel):
    """Şarj. `batch_no` çıktı lotunun numarasıdır (`B-YYMMDD-NNN`, Karar D-2)."""

    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "Devam ediyor"
        COMPLETED = "COMPLETED", "Tamamlandı"
        CANCELLED = "CANCELLED", "İptal"

    order = models.ForeignKey(
        ProductionOrder,
        verbose_name="üretim emri",
        on_delete=models.PROTECT,
        related_name="batches",
    )
    sequence = models.PositiveIntegerField("şarj sırası")
    batch_no = models.CharField("şarj no", max_length=64, unique=True)
    equipment = models.ForeignKey(
        Equipment, verbose_name="tank", on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
        db_index=True,
        editable=False,
    )
    # Ürünün temel biriminde.
    planned_quantity = models.DecimalField(
        "şarj miktarı (temel birim)", max_digits=18, decimal_places=4
    )
    output_lot = models.OneToOneField(
        Lot,
        verbose_name="çıktı lotu",
        on_delete=models.PROTECT,
        related_name="production_batch",
        editable=False,
    )
    started_at = models.DateTimeField("başlama zamanı")
    started_by = models.ForeignKey(
        User, verbose_name="başlatan", on_delete=models.PROTECT, null=True, related_name="+"
    )
    finished_at = models.DateTimeField("bitiş zamanı", null=True, blank=True)
    finished_by = models.ForeignKey(
        User,
        verbose_name="bitiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    actual_output_quantity = models.DecimalField(
        "gerçek çıktı (temel birim)", null=True, blank=True, max_digits=18, decimal_places=4
    )
    yield_pct = models.DecimalField(
        "verim (%)", null=True, blank=True, max_digits=8, decimal_places=2
    )
    output_movement = models.OneToOneField(
        StockMovement,
        verbose_name="üretim girişi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    finish_note = models.TextField("bitiş notu", blank=True)
    cancel_reason = models.TextField("iptal nedeni", blank=True)

    class Meta:
        verbose_name = "şarj"
        verbose_name_plural = "şarjlar"
        ordering = ["order", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["order", "sequence"], name="production_batch_seq_uniq"),
            models.CheckConstraint(
                condition=Q(planned_quantity__gt=0), name="production_batch_quantity_positive"
            ),
            # Bir tankta aynı anda tek açık şarj olur.
            models.UniqueConstraint(
                fields=["equipment"],
                condition=Q(status="IN_PROGRESS"),
                name="production_batch_one_open_per_equipment",
                violation_error_message="Bu tankta devam eden bir şarj var.",
            ),
        ]

    def __str__(self) -> str:
        return self.batch_no


class BatchConsumption(BaseModel):
    """Tartım kaydı: şarja girdi lottan tüketim (`ISSUE_PRODUCTION` + soy ağacı bağı).

    `planned_quantity` satırın bu şarj için planlanan miktarıdır; `deviation_pct` bu kayıtla
    birlikte satırda tartılan toplamın plana göre sapmasıdır.
    """

    batch = models.ForeignKey(
        ProductionBatch, verbose_name="şarj", on_delete=models.PROTECT, related_name="consumptions"
    )
    requirement = models.ForeignKey(
        ProductionRequirement,
        verbose_name="ihtiyaç",
        on_delete=models.PROTECT,
        related_name="consumptions",
    )
    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    planned_quantity = models.DecimalField(
        "planlanan (temel birim)", max_digits=18, decimal_places=4
    )
    actual_quantity = models.DecimalField("tartılan (temel birim)", max_digits=18, decimal_places=4)
    weighed_by = models.ForeignKey(
        User, verbose_name="tartan", on_delete=models.PROTECT, null=True, related_name="+"
    )
    weighed_at = models.DateTimeField("tartım zamanı")
    deviation_pct = models.DecimalField("sapma (%)", max_digits=8, decimal_places=2)
    deviation_note = models.TextField("sapma notu", blank=True)
    movement = models.OneToOneField(
        StockMovement,
        verbose_name="stok hareketi",
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
    )
    lot_link = models.OneToOneField(
        LotLink, verbose_name="soy ağacı bağı", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "tartım kaydı"
        verbose_name_plural = "tartım kayıtları"
        ordering = ["batch", "weighed_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(actual_quantity__gt=0), name="production_consumption_positive"
            )
        ]

    def __str__(self) -> str:
        return f"{self.batch_id} {self.lot_id} {self.actual_quantity}"
