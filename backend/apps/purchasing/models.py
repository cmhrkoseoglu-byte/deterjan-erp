"""Satın alma (Faz 4, Adım 4.2): talep (`ST-`), sipariş (`SA-`), onay limiti ayarı ve siparişten
mal kabul bağlantısı.

Bu dosyada iş mantığı yoktur; durumlar yalnızca `services` içinden, `state.py`'deki izin tablosuna
göre değişir. Mal kabul `inventory` modülünün belgesidir; siparişle bağı bu uygulamadaki
`ReceiptLineLink` tablosunda tutulur (inventory, purchasing'i import etmez).
"""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, User
from apps.inventory.models import GoodsReceiptLine
from apps.masterdata.models import Material, Supplier, UnitOfMeasure
from apps.sales.models import Currency


class PurchasingSettings(BaseModel):
    """Tek satırlık ayar (Karar D-13). Limit boşsa her sipariş yönetim onayına gider."""

    approval_limit_try = models.DecimalField(
        "onay limiti (TL)",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Bu tutara kadar (dahil) siparişi satın alma onaylar; üstünü yönetim onaylar.",
    )
    over_receipt_tolerance_pct = models.DecimalField(
        "fazla teslim toleransı (%)",
        max_digits=6,
        decimal_places=2,
        default=10,
        help_text="Sipariş satırının kalanından en fazla bu oranda fazla mal kabul edilir.",
    )

    class Meta:
        verbose_name = "satın alma ayarı"
        verbose_name_plural = "satın alma ayarları"
        constraints = [
            models.CheckConstraint(
                condition=Q(approval_limit_try__isnull=True) | Q(approval_limit_try__gte=0),
                name="purchasing_settings_limit_non_negative",
                violation_error_message="Onay limiti negatif olamaz.",
            ),
            models.CheckConstraint(
                condition=Q(over_receipt_tolerance_pct__gte=0),
                name="purchasing_settings_tolerance_non_negative",
                violation_error_message="Tolerans negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return "Satın alma ayarları"


class PurchaseOrder(DocumentModel):
    """Satın alma siparişi (`SA-`)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Yönetim onayında"
        APPROVED = "APPROVED", "Onaylandı"
        SENT = "SENT", "Gönderildi"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Kısmen teslim alındı"
        RECEIVED = "RECEIVED", "Teslim alındı"
        CANCELLED = "CANCELLED", "İptal"

    supplier = models.ForeignKey(
        Supplier,
        verbose_name="tedarikçi",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    order_date = models.DateField("sipariş tarihi")
    currency = models.CharField(
        "para birimi", max_length=3, choices=Currency.choices, default=Currency.TRY
    )
    # TL karşılığı = tutar × kur (D-13: dövizli sipariş limitle bu kurla karşılaştırılır).
    exchange_rate = models.DecimalField("kur (TL)", max_digits=18, decimal_places=6, default=1)
    notes = models.TextField("notlar", blank=True)
    # Onaya gönderildiği / onaylandığı andaki TL tutar ve geçerli limit (denetim için saklanır).
    approval_total_try = models.DecimalField(
        "onay tutarı (TL)", max_digits=18, decimal_places=2, null=True, blank=True, editable=False
    )
    approval_limit_try = models.DecimalField(
        "onaydaki limit (TL)",
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
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
    sent_at = models.DateTimeField("gönderim zamanı", null=True, blank=True, editable=False)
    sent_by = models.ForeignKey(
        User,
        verbose_name="gönderen",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    sent_to = models.EmailField("gönderilen e-posta", blank=True, editable=False)
    closed_note = models.TextField("kapanış notu", blank=True, editable=False)

    class Meta:
        verbose_name = "satın alma siparişi"
        verbose_name_plural = "satın alma siparişleri"
        ordering = ["-order_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(exchange_rate__gt=0),
                name="purchasing_order_rate_positive",
                violation_error_message="Kur sıfırdan büyük olmalıdır.",
            ),
        ]


class PurchaseOrderLine(BaseModel):
    """Sipariş satırı: miktar ve fiyat satır biriminde; `base_quantity` temel birimde."""

    order = models.ForeignKey(
        PurchaseOrder, verbose_name="sipariş", on_delete=models.CASCADE, related_name="lines"
    )
    line_no = models.PositiveIntegerField("satır no")
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    base_quantity = models.DecimalField(
        "miktar (temel birim)", max_digits=18, decimal_places=4, editable=False
    )
    unit_price = models.DecimalField(
        "birim fiyat", max_digits=18, decimal_places=4, help_text="Satır biriminde"
    )
    expected_date = models.DateField("teslim tarihi")
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        verbose_name = "sipariş satırı"
        verbose_name_plural = "sipariş satırları"
        ordering = ["order", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="purchasing_line_no_uniq"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="purchasing_line_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="purchasing_line_price_non_negative",
                violation_error_message="Birim fiyat negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}/{self.line_no} {self.material_id}"


class PurchaseRequest(DocumentModel):
    """Satın alma talebi (`ST-`). Talep eden `created_by`'dır (otomatik talepte boş)."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Açık"
        ORDERED = "ORDERED", "Siparişe bağlandı"
        CANCELLED = "CANCELLED", "İptal"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manuel"
        AUTO = "AUTO", "Otomatik"

    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar (temel birim)", max_digits=18, decimal_places=4)
    need_date = models.DateField("ihtiyaç tarihi")
    reason = models.TextField("gerekçe", blank=True)
    source = models.CharField(
        "kaynak", max_length=16, choices=Source.choices, default=Source.MANUAL
    )
    order_line = models.ForeignKey(
        PurchaseOrderLine,
        verbose_name="sipariş satırı",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requests",
        editable=False,
    )

    class Meta:
        verbose_name = "satın alma talebi"
        verbose_name_plural = "satın alma talepleri"
        ordering = ["need_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="purchasing_request_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
        ]


class ReceiptLineLink(BaseModel):
    """Mal kabul satırı → sipariş satırı. Taslak mal kabul satırı silinirse bağ da silinir;
    kaydedilmiş mal kabul satırı silinmez."""

    receipt_line = models.OneToOneField(
        GoodsReceiptLine,
        verbose_name="mal kabul satırı",
        on_delete=models.CASCADE,
        related_name="purchase_link",
    )
    order_line = models.ForeignKey(
        PurchaseOrderLine,
        verbose_name="sipariş satırı",
        on_delete=models.PROTECT,
        related_name="receipt_links",
    )

    class Meta:
        verbose_name = "mal kabul–sipariş bağı"
        verbose_name_plural = "mal kabul–sipariş bağları"

    def __str__(self) -> str:
        return f"{self.receipt_line_id} → {self.order_line_id}"
