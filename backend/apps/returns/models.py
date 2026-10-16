"""Müşteri iadesi (Faz 3, Adım 3.3).

İade edilen ürün aynı lot numarasıyla `RETURN` hareketiyle karantina lokasyonuna girer; lot
karara kadar bekletilir (serbest lot bloke edilir) ve laboratuvara iade numunesi açılır. Kalite
kararı satırın sonucunu belirler: serbest → yeniden sevke uygun, yeniden işleme, ret → imha.
Bu dosyada iş mantığı yoktur; yazma `returns.services` ile.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, User
from apps.inventory.models import Lot, StockMovement
from apps.masterdata.models import Customer, Location, Material, UnitOfMeasure
from apps.quality.models import Sample
from apps.sales.models import Shipment


class CustomerReturn(DocumentModel):
    """Müşteri iadesi (`IA-`). DRAFT → RECEIVED → CLOSED; taslak iptal edilebilir."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        RECEIVED = "RECEIVED", "Teslim alındı"
        CLOSED = "CLOSED", "Sonuçlandı"
        CANCELLED = "CANCELLED", "İptal"

    customer = models.ForeignKey(
        Customer, verbose_name="müşteri", on_delete=models.PROTECT, related_name="returns"
    )
    # Adım 3.2: iade edilen sevkiyat (isteğe bağlı). Verilirse satırlar o sevkiyatta sevk
    # edilen lot ve miktarla sınırlıdır.
    shipment = models.ForeignKey(
        Shipment,
        verbose_name="sevkiyat",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="returns",
    )
    return_date = models.DateField("iade tarihi")
    reason = models.TextField("iade nedeni")
    quarantine_location = models.ForeignKey(
        Location,
        verbose_name="karantina lokasyonu",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="İade edilen ürün karara kadar burada bekler",
    )
    note = models.TextField("not", blank=True)
    received_at = models.DateTimeField("teslim alma zamanı", null=True, blank=True, editable=False)
    received_by = models.ForeignKey(
        User,
        verbose_name="teslim alan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    closed_at = models.DateTimeField("sonuçlanma zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "müşteri iadesi"
        verbose_name_plural = "müşteri iadeleri"
        ordering = ["-return_date", "-id"]


class CustomerReturnLine(BaseModel):
    """İade satırı. Teslim alınınca temel birim miktarı, `RETURN` hareketi ve numune dolar;
    kalite kararıyla `disposition` belirlenir."""

    class Disposition(models.TextChoices):
        PENDING = "PENDING", "Karar bekliyor"
        RESTOCK = "RESTOCK", "Yeniden sevke uygun"
        REWORK = "REWORK", "Yeniden işleme"
        SCRAP = "SCRAP", "İmha"

    customer_return = models.ForeignKey(
        CustomerReturn, verbose_name="iade", on_delete=models.PROTECT, related_name="lines"
    )
    line_no = models.PositiveIntegerField("satır no")
    product = models.ForeignKey(
        Material, verbose_name="ürün", on_delete=models.PROTECT, related_name="+"
    )
    lot = models.ForeignKey(
        Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="return_lines"
    )
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    base_quantity = models.DecimalField(
        "miktar (temel birim)",
        null=True,
        blank=True,
        editable=False,
        max_digits=18,
        decimal_places=4,
    )
    movement = models.OneToOneField(
        StockMovement,
        verbose_name="iade hareketi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    sample = models.ForeignKey(
        Sample,
        verbose_name="numune",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    disposition = models.CharField(
        "sonuç",
        max_length=16,
        choices=Disposition.choices,
        default=Disposition.PENDING,
        editable=False,
    )
    decided_at = models.DateTimeField("karar zamanı", null=True, blank=True, editable=False)
    scrap_movement = models.OneToOneField(
        StockMovement,
        verbose_name="imha hareketi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "iade satırı"
        verbose_name_plural = "iade satırları"
        ordering = ["customer_return", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer_return", "line_no"], name="returns_line_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["customer_return", "lot"],
                name="returns_line_lot_uniq",
                violation_error_message="Aynı lot iadede bir kez yer alır.",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="returns_line_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer_return_id}/{self.line_no} {self.lot_id}"

    @property
    def is_settled(self) -> bool:
        """Satır sonuçlandı mı: karar verildi ve imha kararıysa imha hareketi yazıldı."""
        if self.disposition == self.Disposition.PENDING:
            return False
        return self.disposition != self.Disposition.SCRAP or self.scrap_movement_id is not None
