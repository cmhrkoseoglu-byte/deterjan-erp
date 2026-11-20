"""Portal hesabı: bir kullanıcıyı tek bir müşteriye ya da tek bir tedarikçiye bağlar
(docs/plan/musteri-siparis-takibi.md §4.2). İş mantığı `services.py`'dedir."""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, User
from apps.masterdata.models import Customer, Material, Supplier, UnitOfMeasure
from apps.sales.models import SalesOrder


class PortalAccount(BaseModel):
    """Portal kullanıcısının bağlı olduğu firma. Firma sonradan değişmez (yanlış bağlanan hesap
    kapatılıp yenisi açılır); hesabın açık/kapalı durumu kullanıcının `is_active` alanıdır."""

    user = models.OneToOneField(
        User,
        verbose_name="kullanıcı",
        on_delete=models.PROTECT,
        related_name="portal_account",
        editable=False,
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name="müşteri",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="portal_accounts",
        editable=False,
    )
    supplier = models.ForeignKey(
        Supplier,
        verbose_name="tedarikçi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="portal_accounts",
        editable=False,
    )
    # Müşteri yetkilisi sipariş ve sevk e-postalarını Güvenlik sayfasından kapatabilir.
    email_opt_out = models.BooleanField("e-postaları kapattı", default=False)

    class Meta:
        verbose_name = "portal hesabı"
        verbose_name_plural = "portal hesapları"
        ordering = ["user__username"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(customer__isnull=False, supplier__isnull=True)
                    | Q(customer__isnull=True, supplier__isnull=False)
                ),
                name="portal_account_one_firm",
                violation_error_message=(
                    "Portal hesabı tek bir müşteriye ya da tedarikçiye bağlanır."
                ),
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.username} ({self.firm})"

    @property
    def firm(self) -> Customer | Supplier:
        """Bağlı müşteri ya da tedarikçi."""
        firm = self.customer if self.customer_id else self.supplier
        assert firm is not None
        return firm

    @property
    def kind(self) -> str:
        """`customer` ya da `supplier`."""
        return "customer" if self.customer_id else "supplier"


class OrderRequest(DocumentModel):
    """Müşterinin portaldan gönderdiği sipariş talebi (`MT-`; docs/plan/musteri-siparis-takibi.md
    §4.4). Talep sipariş değildir: sevkiyat siparişe çevirir ya da gerekçeyle reddeder. Fiyat
    yoktur. Durum makinesi `portal.state.order_request_states`."""

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Gönderildi"
        CONVERTED = "CONVERTED", "Siparişe çevrildi"
        REJECTED = "REJECTED", "Reddedildi"
        WITHDRAWN = "WITHDRAWN", "Geri çekildi"

    customer = models.ForeignKey(
        Customer,
        verbose_name="müşteri",
        on_delete=models.PROTECT,
        related_name="order_requests",
        editable=False,
    )
    requested_delivery_date = models.DateField("istenen teslim tarihi", null=True, blank=True)
    customer_po_no = models.CharField("müşteri sipariş no", max_length=64, blank=True)
    delivery_address = models.TextField("teslim adresi", blank=True)
    note = models.TextField("not", blank=True)
    sales_order = models.OneToOneField(
        SalesOrder,
        verbose_name="satış siparişi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="portal_request",
        editable=False,
    )
    reject_reason = models.TextField("ret gerekçesi", blank=True, editable=False)
    decided_at = models.DateTimeField("karar zamanı", null=True, blank=True, editable=False)
    decided_by = models.ForeignKey(
        User,
        verbose_name="karar veren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "sipariş talebi"
        verbose_name_plural = "sipariş talepleri"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.number


class OrderRequestLine(BaseModel):
    """Talep satırı: aktif mamul, miktar ve birim (mamulün temel birimi ya da tanımlı birimi)."""

    request = models.ForeignKey(
        OrderRequest, verbose_name="talep", on_delete=models.PROTECT, related_name="lines"
    )
    line_no = models.PositiveIntegerField("satır no")
    product = models.ForeignKey(
        Material, verbose_name="mamul", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "talep satırı"
        verbose_name_plural = "talep satırları"
        ordering = ["request", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["request", "line_no"], name="portal_request_line_no"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="portal_request_line_qty"),
        ]


class OutboundEmail(models.Model):
    """Müşteriye giden portal e-postasının günlüğü (§4.5): alıcı, konu, ilgili kayıt, durum ve
    gönderim zamanı. İçerik saklanmaz; gönderimde kayıttan yeniden üretilir. Aynı kayıt için aynı
    kullanıcıya aynı tür e-posta bir kez yazılır."""

    class Kind(models.TextChoices):
        ORDER_CONFIRMED = "ORDER_CONFIRMED", "Sipariş onaylandı"
        SHIPMENT_DISPATCHED = "SHIPMENT_DISPATCHED", "Sevk edildi"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Sırada"
        SENT = "SENT", "Gönderildi"
        FAILED = "FAILED", "Gönderilemedi"
        SKIPPED = "SKIPPED", "Gönderilmedi (SMTP tanımlı değil)"

    kind = models.CharField("tür", max_length=32, choices=Kind.choices, editable=False)
    customer = models.ForeignKey(
        Customer,
        verbose_name="müşteri",
        on_delete=models.PROTECT,
        related_name="portal_emails",
        editable=False,
    )
    user = models.ForeignKey(
        User,
        verbose_name="alıcı kullanıcı",
        on_delete=models.PROTECT,
        related_name="portal_emails",
        editable=False,
    )
    to_address = models.EmailField("alıcı e-posta", editable=False)
    subject = models.CharField("konu", max_length=200, editable=False)
    related_model = models.CharField("ilgili kayıt türü", max_length=64, editable=False)
    related_id = models.PositiveBigIntegerField("ilgili kayıt", editable=False)
    related_number = models.CharField("ilgili belge no", max_length=40, editable=False)
    status = models.CharField(
        "durum", max_length=16, choices=Status.choices, default=Status.QUEUED, editable=False
    )
    attempts = models.PositiveSmallIntegerField("deneme", default=0, editable=False)
    last_error = models.CharField("son hata", max_length=200, blank=True, editable=False)
    created_at = models.DateTimeField("oluşturma zamanı", auto_now_add=True)
    sent_at = models.DateTimeField("gönderim zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "portal e-postası"
        verbose_name_plural = "portal e-postaları"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "related_model", "related_id", "user"],
                name="portal_email_once",
            )
        ]

    def __str__(self) -> str:
        return f"{self.related_number} → {self.to_address}"
