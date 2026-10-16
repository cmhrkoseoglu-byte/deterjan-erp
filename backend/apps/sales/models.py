"""Satış: müşteri siparişi ve satırları (Faz 3, Adım 3.1), sevkiyat (Adım 3.2).

Bu dosyada iş mantığı yoktur. Sipariş durumu yalnızca `services` içinden, `state.py`'deki izin
tablosuna göre değişir. Stok rezervasyonu `inventory.StockReservation` kaydıdır (kaynak belge:
sipariş satırı) ve yalnızca `inventory.services.reserve / release_reservation /
consume_reservation` ile yazılır.
"""

from typing import ClassVar

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, User
from apps.inventory.models import PickRecord, StockMovement, StockReservation
from apps.masterdata.models import Customer, Location, Material, UnitOfMeasure


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


class Shipment(DocumentModel):
    """Sevkiyat (`SV-`). Karar D-10: bir sevkiyat tek siparişe bağlıdır; aynı araca yüklenen
    siparişler aynı plakayla ayrı sevkiyat ve irsaliyedir."""

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planlandı"
        PICKING = "PICKING", "Toplanıyor"
        LOADED = "LOADED", "Yüklendi"
        DISPATCHED = "DISPATCHED", "Sevk edildi"
        CANCELLED = "CANCELLED", "İptal"

    # KVKK: şoför kimlik numarası denetim günlüğüne maskeli yazılır.
    AUDIT_MASKED_FIELDS: ClassVar[tuple[str, ...]] = ("driver_id_no",)

    sales_order = models.ForeignKey(
        SalesOrder, verbose_name="sipariş", on_delete=models.PROTECT, related_name="shipments"
    )
    planned_date = models.DateField("planlanan tarih")
    loading_location = models.ForeignKey(
        Location,
        verbose_name="sevk alanı",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Toplanan ürün sevk edilene kadar burada bekler",
    )
    vehicle_plate = models.CharField("araç plakası", max_length=20, blank=True)
    driver_name = models.CharField("şoför adı", max_length=100, blank=True)
    driver_id_no = models.CharField("şoför TC kimlik no", max_length=11, blank=True)
    carrier = models.CharField("taşıyıcı", max_length=100, blank=True)
    notes = models.TextField("notlar", blank=True)
    loaded_at = models.DateTimeField("yükleme zamanı", null=True, blank=True, editable=False)
    loaded_by = models.ForeignKey(
        User,
        verbose_name="yükleyen",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    dispatched_at = models.DateTimeField("sevk zamanı", null=True, blank=True, editable=False)
    dispatched_by = models.ForeignKey(
        User,
        verbose_name="sevki onaylayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "sevkiyat"
        verbose_name_plural = "sevkiyatlar"
        ordering = ["-planned_date", "-id"]


class ShipmentLine(BaseModel):
    """Sevkiyatın planlanan satırı: sipariş satırından bu sevkiyatla gidecek miktar (temel
    birimde). Toplanan lotlar `ShipmentPick` kayıtlarıdır."""

    shipment = models.ForeignKey(
        Shipment, verbose_name="sevkiyat", on_delete=models.PROTECT, related_name="lines"
    )
    order_line = models.ForeignKey(
        SalesOrderLine,
        verbose_name="sipariş satırı",
        on_delete=models.PROTECT,
        related_name="shipment_lines",
    )
    quantity = models.DecimalField(
        "planlanan miktar (temel birim)", max_digits=18, decimal_places=4
    )

    class Meta:
        verbose_name = "sevkiyat satırı"
        verbose_name_plural = "sevkiyat satırları"
        ordering = ["shipment", "order_line__line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["shipment", "order_line"], name="sales_shipment_line_uniq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="sales_shipment_line_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.shipment_id}/{self.order_line_id}"


class ShipmentPick(PickRecord):
    """Okutularak toplanan lot: depodan sevk alanına transfer edilen miktar. Sevkte `SHIPMENT`
    hareketi yazılır (`movement`); geri alınan okutma (`returned_at`) geldiği yere döner."""

    line = models.ForeignKey(
        ShipmentLine, verbose_name="sevkiyat satırı", on_delete=models.PROTECT, related_name="picks"
    )
    # Rezervasyondan farklı lot okutulduysa gerekçe.
    deviation_reason = models.CharField("farklı lot gerekçesi", max_length=200, blank=True)
    movement = models.OneToOneField(
        StockMovement,
        verbose_name="sevk hareketi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "toplanan lot"
        verbose_name_plural = "toplanan lotlar"
        ordering = ["line", "picked_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="sales_shipment_pick_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.line_id} {self.lot_id}"
