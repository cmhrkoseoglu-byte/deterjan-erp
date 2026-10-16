"""Bakım (Faz 4, Adım 4.4): bakım planı, bakım iş emri (`BK-`), yedek parça, duruş, temizliksiz
ürün geçişi kuralları ve ayarlar.

Bu dosyada iş mantığı yoktur. Durumlar yalnızca `services` içinden, `state.py`'deki izin tablosuna
göre değişir. Ekipman kontrolleri (duruş, ürün değişimi temizliği, kalibrasyon) üretim ve dolum
modüllerine `masterdata.services.register_equipment_guard` kancasıyla bağlanır.
"""

from django.db import models
from django.db.models import F, Q

from apps.core.models import BaseModel, DocumentModel, MasterDataModel, User
from apps.core.roles import DOLUM, LABORATUVAR, PLANLAMA, URETIM, YONETIM
from apps.inventory.models import Lot, StockMovement
from apps.masterdata.models import Equipment, Location, Material

ROLE_CHOICES = [
    (URETIM, "Üretim"),
    (DOLUM, "Dolum"),
    (LABORATUVAR, "Laboratuvar"),
    (PLANLAMA, "Planlama"),
    (YONETIM, "Yönetim"),
]


class MaintenanceKind(models.TextChoices):
    PERIODIC = "PERIODIC", "Periyodik bakım"
    CLEANING = "CLEANING", "Temizlik"
    CALIBRATION = "CALIBRATION", "Kalibrasyon"
    REPAIR = "REPAIR", "Arıza onarımı"


class MaintenanceSettings(BaseModel):
    """Tek satırlık ayar."""

    calibration_warning_days = models.PositiveIntegerField(
        "kalibrasyon uyarı süresi (gün)",
        default=7,
        help_text="Kalibrasyonu bu kadar gün içinde dolacak terazi tartım ekranında uyarı verir.",
    )
    plan_lead_days = models.PositiveIntegerField(
        "bakım iş emri açma süresi (gün)",
        default=7,
        help_text="Sıradaki tarihine bu kadar gün kalan plan için günlük kontrolde iş emri açılır.",
    )

    class Meta:
        verbose_name = "bakım ayarı"
        verbose_name_plural = "bakım ayarları"

    def __str__(self) -> str:
        return "Bakım ayarları"


class MaintenancePlan(MasterDataModel):
    """Ekipmanın periyodik bakım / temizlik / kalibrasyon planı.

    Periyot gün (`interval_days`) ya da çalışma sayısıdır (`interval_runs`: tankta biten şarj,
    dolum hattında biten dolum partisi). Kalibrasyon planı gün bazlıdır. `next_due_date` gün
    bazlı planlarda tutulur; iş emri tamamlanınca servis ileri atar.
    """

    equipment = models.ForeignKey(
        Equipment,
        verbose_name="ekipman",
        on_delete=models.PROTECT,
        related_name="maintenance_plans",
    )
    kind = models.CharField(
        "tür",
        max_length=16,
        choices=[c for c in MaintenanceKind.choices if c[0] != MaintenanceKind.REPAIR],
    )
    title = models.CharField("başlık", max_length=200)
    interval_days = models.PositiveIntegerField("periyot (gün)", null=True, blank=True)
    interval_runs = models.PositiveIntegerField("periyot (çalışma sayısı)", null=True, blank=True)
    checklist = models.JSONField("kontrol listesi", default=list, blank=True)
    responsible_role = models.CharField("sorumlu rol", max_length=32, choices=ROLE_CHOICES)
    next_due_date = models.DateField("sıradaki tarih", null=True, blank=True)
    last_done_at = models.DateTimeField("son yapılma", null=True, blank=True, editable=False)
    note = models.TextField("not", blank=True)

    class Meta:
        verbose_name = "bakım planı"
        verbose_name_plural = "bakım planları"
        ordering = ["equipment__code", "kind", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(interval_days__isnull=False) & Q(interval_runs__isnull=True))
                | (Q(interval_days__isnull=True) & Q(interval_runs__isnull=False)),
                name="maintenance_plan_one_interval",
                violation_error_message="Periyot gün ya da çalışma sayısı olarak girilmelidir.",
            ),
            models.CheckConstraint(
                condition=Q(interval_days__isnull=True) | Q(interval_days__gt=0),
                name="maintenance_plan_days_positive",
                violation_error_message="Periyot sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(interval_runs__isnull=True) | Q(interval_runs__gt=0),
                name="maintenance_plan_runs_positive",
                violation_error_message="Periyot sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.equipment.code} - {self.title}"


class MaintenanceWorkOrder(DocumentModel):
    """Bakım iş emri (`BK-`): plan, arıza ya da ürün değişimi temizliği kaynaklı."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Açık"
        IN_PROGRESS = "IN_PROGRESS", "Yapılıyor"
        COMPLETED = "COMPLETED", "Tamamlandı"
        CANCELLED = "CANCELLED", "İptal"

    class Source(models.TextChoices):
        PLAN = "PLAN", "Bakım planı"
        BREAKDOWN = "BREAKDOWN", "Arıza"
        CHANGEOVER = "CHANGEOVER", "Ürün değişimi"
        MANUAL = "MANUAL", "Elle"

    class CalibrationResult(models.TextChoices):
        PASSED = "PASSED", "Uygun"
        FAILED = "FAILED", "Uygun değil"

    equipment = models.ForeignKey(
        Equipment,
        verbose_name="ekipman",
        on_delete=models.PROTECT,
        related_name="work_orders",
    )
    plan = models.ForeignKey(
        MaintenancePlan,
        verbose_name="bakım planı",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="work_orders",
    )
    source = models.CharField("kaynak", max_length=16, choices=Source.choices)
    kind = models.CharField("tür", max_length=16, choices=MaintenanceKind.choices)
    title = models.CharField("başlık", max_length=200)
    description = models.TextField("açıklama", blank=True)
    responsible_role = models.CharField("sorumlu rol", max_length=32, choices=ROLE_CHOICES)
    due_date = models.DateField("termin", null=True, blank=True)
    # Kontrol listesi: [{"item": "...", "done": bool, "note": "..."}]
    checklist = models.JSONField("kontrol listesi", default=list, blank=True)
    # Ürün değişimi temizliği için bilgi: tanktaki önceki ürün.
    previous_product = models.ForeignKey(
        Material,
        verbose_name="önceki ürün",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    started_at = models.DateTimeField("başlama", null=True, blank=True, editable=False)
    started_by = models.ForeignKey(
        User,
        verbose_name="başlayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    completed_at = models.DateTimeField(
        "tamamlanma", null=True, blank=True, editable=False, db_index=True
    )
    completed_by = models.ForeignKey(
        User,
        verbose_name="tamamlayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    work_done = models.TextField("yapılan iş", blank=True, editable=False)
    duration_minutes = models.PositiveIntegerField(
        "süre (dakika)", null=True, blank=True, editable=False
    )
    calibration_result = models.CharField(
        "kalibrasyon sonucu",
        max_length=8,
        choices=CalibrationResult.choices,
        blank=True,
        editable=False,
    )
    certificate_no = models.CharField("sertifika no", max_length=64, blank=True, editable=False)

    class Meta:
        verbose_name = "bakım iş emri"
        verbose_name_plural = "bakım iş emirleri"
        ordering = ["-created_at", "-id"]


class WorkOrderPart(BaseModel):
    """İş emrinde kullanılan yedek parça. Stoklu parça (malzeme + lot + lokasyon)
    `ISSUE_MAINTENANCE` hareketiyle düşülür; stoksuz parça yalnızca açıklama ve miktardır."""

    work_order = models.ForeignKey(
        MaintenanceWorkOrder,
        verbose_name="iş emri",
        on_delete=models.PROTECT,
        related_name="parts",
    )
    material = models.ForeignKey(
        Material,
        verbose_name="malzeme",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    lot = models.ForeignKey(
        Lot, verbose_name="lot", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    location = models.ForeignKey(
        Location,
        verbose_name="lokasyon",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    description = models.CharField("açıklama", max_length=200, blank=True)
    # Stoklu parçada malzemenin temel biriminde.
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit_text = models.CharField("birim", max_length=16, blank=True)
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
        verbose_name = "yedek parça"
        verbose_name_plural = "yedek parçalar"
        ordering = ["work_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="maintenance_part_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return self.description or str(self.material_id)


class Downtime(BaseModel):
    """Ekipman duruşu. Bitişi boş duruş "açık"tır; açık duruştaki ekipman kullanılamaz."""

    class Reason(models.TextChoices):
        BREAKDOWN = "BREAKDOWN", "Arıza"
        PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE", "Planlı bakım"
        CLEANING = "CLEANING", "Temizlik"
        CALIBRATION = "CALIBRATION", "Kalibrasyon"
        NO_MATERIAL = "NO_MATERIAL", "Malzeme yok"
        NO_OPERATOR = "NO_OPERATOR", "Personel yok"
        OTHER = "OTHER", "Diğer"

    equipment = models.ForeignKey(
        Equipment, verbose_name="ekipman", on_delete=models.PROTECT, related_name="downtimes"
    )
    reason = models.CharField("neden", max_length=24, choices=Reason.choices)
    started_at = models.DateTimeField("başlangıç", db_index=True)
    ended_at = models.DateTimeField("bitiş", null=True, blank=True, db_index=True)
    note = models.TextField("not", blank=True)
    end_note = models.TextField("bitiş notu", blank=True)
    work_order = models.ForeignKey(
        MaintenanceWorkOrder,
        verbose_name="iş emri",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="downtimes",
    )
    ended_by = models.ForeignKey(
        User,
        verbose_name="bitiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "duruş"
        verbose_name_plural = "duruşlar"
        ordering = ["-started_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=F("started_at")),
                name="maintenance_downtime_end_after_start",
                violation_error_message="Bitiş başlangıçtan önce olamaz.",
            ),
            models.UniqueConstraint(
                fields=["equipment"],
                condition=Q(ended_at__isnull=True),
                name="maintenance_downtime_one_open",
                violation_error_message="Bu ekipmanda açık bir duruş var.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.equipment_id} {self.get_reason_display()} {self.started_at:%Y-%m-%d %H:%M}"


class ChangeoverRule(MasterDataModel):
    """Temizliksiz ürün geçişi (Karar D-14 "İstisnalı"): tankta `from_product`'tan sonra
    `to_product` temizlik kaydı olmadan üretilebilir (yönlü; ör. açık renkten koyuya).
    Kuralları laboratuvar tanımlar."""

    from_product = models.ForeignKey(
        Material, verbose_name="önceki ürün", on_delete=models.PROTECT, related_name="+"
    )
    to_product = models.ForeignKey(
        Material, verbose_name="sonraki ürün", on_delete=models.PROTECT, related_name="+"
    )
    note = models.TextField("gerekçe", blank=True)

    class Meta:
        verbose_name = "temizliksiz geçiş"
        verbose_name_plural = "temizliksiz geçişler"
        ordering = ["from_product__code", "to_product__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_product", "to_product"],
                name="maintenance_changeover_pair_uniq",
                violation_error_message="Bu geçiş zaten tanımlı.",
            ),
            models.CheckConstraint(
                condition=~Q(from_product=F("to_product")),
                name="maintenance_changeover_distinct",
                violation_error_message="Aynı ürün için kural gerekmez.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_product_id} → {self.to_product_id}"
