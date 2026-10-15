"""Dolum ve ambalaj: ambalaj reçetesi (sürümlü), dolum emri, ambalaj ihtiyacı ve hazırlaması, dolum
partisi, tüketim ve fire kayıtları.

Bu dosyada iş mantığı yoktur. Belge ve parti durumu yalnızca `services` içinden, `state.py`'deki
izin tablosuna göre değişir. Stok `inventory.services` ile hareket eder (CLAUDE.md §3).
"""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, User
from apps.inventory.models import Lot, LotLink, PickRecord, StockMovement
from apps.masterdata.models import Equipment, Location, Material, UnitOfMeasure


class PackagingSpec(BaseModel):
    """Mamulün ambalaj reçetesi (sürümlü, reçete gibi): hangi bulk üründen, kaç ml/lt dolum, hangi
    ambalaj malzemeleri. Taslak → onaylı → eski sürüm; mamul başına tek onaylı sürüm olur."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        APPROVED = "APPROVED", "Onaylı"
        OBSOLETE = "OBSOLETE", "Eski sürüm"

    finished_product = models.ForeignKey(
        Material,
        verbose_name="mamul",
        on_delete=models.PROTECT,
        related_name="packaging_specs",
    )
    bulk_product = models.ForeignKey(
        Material, verbose_name="dökme ürün (bulk)", on_delete=models.PROTECT, related_name="+"
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
    fill_quantity = models.DecimalField("dolum miktarı", max_digits=18, decimal_places=4)
    fill_unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="dolum birimi", on_delete=models.PROTECT, related_name="+"
    )
    fill_tolerance_pct = models.DecimalField(
        "dolum toleransı (%)", max_digits=6, decimal_places=2, default=1
    )
    units_per_case = models.PositiveIntegerField("koli içi adet")
    cases_per_pallet = models.PositiveIntegerField("palet başı koli", null=True, blank=True)
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
        "eski sürüm olma zamanı", null=True, blank=True, editable=False
    )

    class Meta:
        verbose_name = "ambalaj reçetesi"
        verbose_name_plural = "ambalaj reçeteleri"
        ordering = ["finished_product__code", "-version_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["finished_product", "version_no"],
                name="filling_spec_version_no_uniq",
                violation_error_message="Bu sürüm numarası zaten var.",
            ),
            models.UniqueConstraint(
                fields=["finished_product"],
                condition=Q(status="APPROVED"),
                name="filling_spec_single_approved",
                violation_error_message="Bu mamulde zaten onaylı bir ambalaj reçetesi var.",
            ),
            models.CheckConstraint(
                condition=Q(fill_quantity__gt=0),
                name="filling_spec_fill_quantity_positive",
                violation_error_message="Dolum miktarı sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(fill_tolerance_pct__gte=0),
                name="filling_spec_tolerance_non_negative",
                violation_error_message="Dolum toleransı negatif olamaz.",
            ),
            models.CheckConstraint(
                condition=Q(units_per_case__gt=0),
                name="filling_spec_units_per_case_positive",
                violation_error_message="Koli içi adet sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.finished_product.code} v{self.version_no}"


class PackagingSpecLine(BaseModel):
    """Ambalaj reçetesi satırı: mamulün bir adedi için ambalaj malzemesi (şişe 1, koli 1/12)."""

    spec = models.ForeignKey(
        PackagingSpec,
        verbose_name="ambalaj reçetesi",
        on_delete=models.PROTECT,
        related_name="lines",
    )
    sequence = models.PositiveIntegerField("sıra")
    material = models.ForeignKey(
        Material, verbose_name="ambalaj malzemesi", on_delete=models.PROTECT, related_name="+"
    )
    # Oran olduğu için 6 ondalık (koli 1/12 = 0,083333; malzemenin temel biriminde).
    quantity_per_unit = models.DecimalField("adet başına miktar", max_digits=18, decimal_places=6)
    scrap_allowance_pct = models.DecimalField(
        "fire payı (%)", max_digits=6, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = "ambalaj reçetesi satırı"
        verbose_name_plural = "ambalaj reçetesi satırları"
        ordering = ["spec", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["spec", "sequence"],
                name="filling_spec_line_sequence_uniq",
                violation_error_message="Bu sıra numarası sürümde zaten kullanılıyor.",
            ),
            models.UniqueConstraint(
                fields=["spec", "material"],
                name="filling_spec_line_material_uniq",
                violation_error_message="Bu malzeme sürümde zaten var.",
            ),
            models.CheckConstraint(
                condition=Q(quantity_per_unit__gt=0),
                name="filling_spec_line_quantity_positive",
                violation_error_message="Adet başına miktar sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(scrap_allowance_pct__gte=0),
                name="filling_spec_line_allowance_non_negative",
                violation_error_message="Fire payı negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.spec} #{self.sequence} {self.material.code}"


class FillingOrder(DocumentModel):
    """Dolum emri (`DO-`). Onaylı ambalaj reçetesi oluştururken sabitlenir."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        APPROVED = "APPROVED", "Onaylandı"
        MATERIAL_PREP = "MATERIAL_PREP", "Ambalaj hazırlanıyor"
        MATERIAL_READY = "MATERIAL_READY", "Ambalaj hazır"
        IN_PROGRESS = "IN_PROGRESS", "Dolumda"
        QC_PENDING = "QC_PENDING", "Analiz bekliyor"
        COMPLETED = "COMPLETED", "Tamamlandı"
        CANCELLED = "CANCELLED", "İptal"

    finished_product = models.ForeignKey(
        Material, verbose_name="mamul", on_delete=models.PROTECT, related_name="+"
    )
    packaging_spec = models.ForeignKey(
        PackagingSpec,
        verbose_name="ambalaj reçetesi",
        on_delete=models.PROTECT,
        related_name="filling_orders",
    )
    planned_units = models.PositiveIntegerField("planlanan adet")
    filling_line = models.ForeignKey(
        Equipment, verbose_name="dolum hattı", on_delete=models.PROTECT, related_name="+"
    )
    output_location = models.ForeignKey(
        Location,
        verbose_name="mamul deposu lokasyonu",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Dolan mamulün girdiği lokasyon",
    )
    planned_date = models.DateField("planlanan tarih")
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
        verbose_name = "dolum emri"
        verbose_name_plural = "dolum emirleri"
        ordering = ["-planned_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(planned_units__gt=0),
                name="filling_order_units_positive",
                violation_error_message="Planlanan adet sıfırdan büyük olmalıdır.",
            )
        ]


class FillingRequirement(BaseModel):
    """Onayda ambalaj reçetesinden hesaplanan ambalaj ihtiyacı (malzemenin temel biriminde):
    planlanan adet × adet başına miktar × (1 + fire payı)."""

    order = models.ForeignKey(
        FillingOrder,
        verbose_name="dolum emri",
        on_delete=models.PROTECT,
        related_name="requirements",
    )
    spec_line = models.ForeignKey(
        PackagingSpecLine,
        verbose_name="ambalaj reçetesi satırı",
        on_delete=models.PROTECT,
        related_name="+",
    )
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    required_quantity = models.DecimalField(
        "ihtiyaç (temel birim)", max_digits=18, decimal_places=4
    )
    sequence = models.PositiveIntegerField("sıra")

    class Meta:
        verbose_name = "ambalaj ihtiyacı"
        verbose_name_plural = "ambalaj ihtiyaçları"
        ordering = ["order", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "sequence"], name="filling_requirement_seq_uniq"
            ),
            models.CheckConstraint(
                condition=Q(required_quantity__gt=0), name="filling_requirement_quantity_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}/{self.sequence} {self.material_id}"


class PackagingPick(PickRecord):
    """Ambalaj hazırlama: depodan dolum hattına transfer edilen ambalaj lotu (ortak hazırlama
    deseni, `inventory.picking`)."""

    order = models.ForeignKey(
        FillingOrder, verbose_name="dolum emri", on_delete=models.PROTECT, related_name="picks"
    )
    requirement = models.ForeignKey(
        FillingRequirement,
        verbose_name="ihtiyaç",
        on_delete=models.PROTECT,
        related_name="picks",
    )

    class Meta:
        verbose_name = "ambalaj hazırlama"
        verbose_name_plural = "ambalaj hazırlamaları"
        ordering = ["order", "picked_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="filling_pick_quantity_positive"
            )
        ]

    def __str__(self) -> str:
        return f"{self.order_id} {self.lot_id} {self.quantity}"


class FillingRun(BaseModel):
    """Dolum partisi (vardiya/parti). `output_lot` dolum lotudur (`D-YYMMDD-NNN`, Karar D-2); bir ya
    da birden çok bulk (tank) lotundan beslenir."""

    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "Devam ediyor"
        COMPLETED = "COMPLETED", "Tamamlandı"
        CANCELLED = "CANCELLED", "İptal"

    order = models.ForeignKey(
        FillingOrder, verbose_name="dolum emri", on_delete=models.PROTECT, related_name="runs"
    )
    sequence = models.PositiveIntegerField("parti sırası")
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
        db_index=True,
        editable=False,
    )
    output_lot = models.OneToOneField(
        Lot,
        verbose_name="dolum lotu",
        on_delete=models.PROTECT,
        related_name="filling_run",
        editable=False,
    )
    operator = models.ForeignKey(
        User, verbose_name="operatör", on_delete=models.PROTECT, null=True, related_name="+"
    )
    started_at = models.DateTimeField("başlama zamanı")
    finished_at = models.DateTimeField("bitiş zamanı", null=True, blank=True)
    finished_by = models.ForeignKey(
        User,
        verbose_name="bitiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    good_units = models.PositiveIntegerField("sağlam adet", null=True, blank=True)
    # Bitişte hesaplanır (bulkun temel biriminde).
    theoretical_bulk = models.DecimalField(
        "teorik bulk", null=True, blank=True, max_digits=18, decimal_places=4
    )
    actual_bulk = models.DecimalField(
        "gerçek bulk", null=True, blank=True, max_digits=18, decimal_places=4
    )
    bulk_variance_pct = models.DecimalField(
        "bulk farkı (%)", null=True, blank=True, max_digits=8, decimal_places=2
    )
    output_movement = models.OneToOneField(
        StockMovement,
        verbose_name="mamul girişi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    finish_note = models.TextField("bitiş notu", blank=True)
    cancel_reason = models.TextField("iptal nedeni", blank=True)

    class Meta:
        verbose_name = "dolum partisi"
        verbose_name_plural = "dolum partileri"
        ordering = ["order", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["order", "sequence"], name="filling_run_seq_uniq"),
            # Bir dolum hattında aynı anda tek açık parti olur (emir başına tek hat).
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(status="IN_PROGRESS"),
                name="filling_run_one_open_per_order",
                violation_error_message="Bu emirde devam eden bir dolum partisi var.",
            ),
        ]

    def __str__(self) -> str:
        return self.output_lot.lot_no if self.output_lot_id else f"{self.order_id}/{self.sequence}"


class RunLot(BaseModel):
    """Partiye okutulan ambalaj lotu. Bitişte ambalaj tüketimi önce okutulan lotlardan, okutma
    sırasıyla düşülür (yanlış malzemenin lotu okutulamaz)."""

    run = models.ForeignKey(
        FillingRun, verbose_name="dolum partisi", on_delete=models.PROTECT, related_name="run_lots"
    )
    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="+")
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    scanned_by = models.ForeignKey(
        User, verbose_name="okutan", on_delete=models.PROTECT, null=True, related_name="+"
    )
    scanned_at = models.DateTimeField("okutma zamanı")

    class Meta:
        verbose_name = "partiye okutulan lot"
        verbose_name_plural = "partiye okutulan lotlar"
        ordering = ["run", "scanned_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["run", "lot"], name="filling_run_lot_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.run_id} {self.lot_id}"


class ConsumptionKind(models.TextChoices):
    BULK = "BULK", "Bulk"
    PACKAGING = "PACKAGING", "Ambalaj"


class FillingConsumption(BaseModel):
    """Dolum tüketimi: bulk lotu (litre/kg) ya da ambalaj lotu. Her kayıt `ISSUE_PRODUCTION`
    hareketi ve `LotLink(girdi lot → dolum lotu)` yazar."""

    run = models.ForeignKey(
        FillingRun,
        verbose_name="dolum partisi",
        on_delete=models.PROTECT,
        related_name="consumptions",
    )
    kind = models.CharField("tür", max_length=16, choices=ConsumptionKind.choices)
    spec_line = models.ForeignKey(
        PackagingSpecLine,
        verbose_name="ambalaj reçetesi satırı",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar (temel birim)", max_digits=18, decimal_places=4)
    consumed_by = models.ForeignKey(
        User, verbose_name="kaydeden", on_delete=models.PROTECT, null=True, related_name="+"
    )
    consumed_at = models.DateTimeField("zaman")
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
        verbose_name = "dolum tüketimi"
        verbose_name_plural = "dolum tüketimleri"
        ordering = ["run", "consumed_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="filling_consumption_quantity_positive"
            )
        ]

    def __str__(self) -> str:
        return f"{self.run_id} {self.lot_id} {self.quantity}"


class ScrapRecord(BaseModel):
    """Fire kaydı: bulk, ambalaj ya da mamul (dolup ayrılan adet). `SCRAP` hareketi yazar; mamul
    firesi parti bitişinde, mamul girişinin ardından düşülür."""

    class Kind(models.TextChoices):
        BULK = "BULK", "Bulk"
        PACKAGING = "PACKAGING", "Ambalaj"
        FINISHED = "FINISHED", "Mamul"

    class Reason(models.TextChoices):
        OVERFILL = "OVERFILL", "Fazla dolum"
        UNDERFILL = "UNDERFILL", "Eksik dolum"
        LEAK = "LEAK", "Sızıntı"
        LABEL_ERROR = "LABEL_ERROR", "Etiket hatası"
        CAP_ERROR = "CAP_ERROR", "Kapak hatası"
        DAMAGED_PACKAGING = "DAMAGED_PACKAGING", "Hasarlı ambalaj"
        SETUP_LOSS = "SETUP_LOSS", "Hat ayar kaybı"
        OTHER = "OTHER", "Diğer"

    run = models.ForeignKey(
        FillingRun, verbose_name="dolum partisi", on_delete=models.PROTECT, related_name="scraps"
    )
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar (temel birim)", max_digits=18, decimal_places=4)
    reason_code = models.CharField("neden", max_length=24, choices=Reason.choices)
    note = models.TextField("not", blank=True)
    recorded_by = models.ForeignKey(
        User, verbose_name="kaydeden", on_delete=models.PROTECT, null=True, related_name="+"
    )
    recorded_at = models.DateTimeField("zaman")
    # Mamul firesinde parti bitişinde dolar.
    movement = models.OneToOneField(
        StockMovement,
        verbose_name="stok hareketi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "fire kaydı"
        verbose_name_plural = "fire kayıtları"
        ordering = ["run", "recorded_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="filling_scrap_quantity_positive"
            )
        ]

    def __str__(self) -> str:
        return f"{self.run_id} {self.material_id} {self.quantity} {self.reason_code}"
