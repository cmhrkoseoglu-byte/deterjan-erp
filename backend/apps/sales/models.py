"""Satış: müşteri siparişi ve satırları (Faz 3, Adım 3.1).

Bu dosyada iş mantığı yoktur. Sipariş durumu yalnızca `services` içinden, `state.py`'deki izin
tablosuna göre değişir. Stok rezervasyonu `inventory.StockReservation` kaydıdır (kaynak belge:
sipariş satırı) ve yalnızca `inventory.services.reserve / release_reservation /
consume_reservation` ile yazılır.
"""

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, User
from apps.inventory.models import StockReservation
from apps.masterdata.models import Customer, Material, UnitOfMeasure


class Currency(models.TextChoices):
    TRY = "TRY", "TL"
    EUR = "EUR", "Euro"
    USD = "USD", "ABD doları"


class SalesOrder(DocumentModel):
    """Müşteri siparişi (`SS-`)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        CONFIRMED = "CONFIRMED", "Onaylandı"
        PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED", "Kısmen sevk edildi"
        SHIPPED = "SHIPPED", "Sevk edildi"
        CLOSED = "CLOSED", "Kapandı"
        CANCELLED = "CANCELLED", "İptal"

    customer = models.ForeignKey(
        Customer, verbose_name="müşteri", on_delete=models.PROTECT, related_name="sales_orders"
    )
    order_date = models.DateField("sipariş tarihi")
    requested_delivery_date = models.DateField("istenen teslim tarihi", null=True, blank=True)
    delivery_address = models.TextField("teslim adresi", blank=True)
    customer_po_no = models.CharField("müşteri sipariş no", max_length=64, blank=True)
    notes = models.TextField("notlar", blank=True)
    confirmed_by = models.ForeignKey(
        User,
        verbose_name="onaylayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    confirmed_at = models.DateTimeField("onay zamanı", null=True, blank=True, editable=False)
    closed_at = models.DateTimeField("kapanma zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "satış siparişi"
        verbose_name_plural = "satış siparişleri"
        ordering = ["-order_date", "-id"]


class SalesOrderLine(BaseModel):
    """Sipariş satırı: mamul, birim (ADET / KOLI / PALET) ve temel birime çevrilmiş miktar."""

    order = models.ForeignKey(
        SalesOrder, verbose_name="sipariş", on_delete=models.CASCADE, related_name="lines"
    )
    line_no = models.PositiveIntegerField("satır no")
    product = models.ForeignKey(
        Material, verbose_name="mamul", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    base_quantity = models.DecimalField(
        "miktar (temel birim)", max_digits=18, decimal_places=4, editable=False
    )
    # Karar D-9: fiyat isteğe bağlı; fatura muhasebe programında kesilir.
    unit_price = models.DecimalField(
        "birim fiyat", max_digits=18, decimal_places=4, null=True, blank=True
    )
    currency = models.CharField(
        "para birimi", max_length=3, choices=Currency.choices, blank=True, default=""
    )
    note = models.CharField("not", max_length=200, blank=True)
    reservations = GenericRelation(
        StockReservation,
        content_type_field="source_content_type",
        object_id_field="source_object_id",
        related_query_name="sales_order_line",
    )

    class Meta:
        verbose_name = "sipariş satırı"
        verbose_name_plural = "sipariş satırları"
        ordering = ["order", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="sales_line_no_uniq"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="sales_line_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__isnull=True) | Q(unit_price__gte=0),
                name="sales_line_price_non_negative",
                violation_error_message="Birim fiyat negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}/{self.line_no} {self.product_id}"
