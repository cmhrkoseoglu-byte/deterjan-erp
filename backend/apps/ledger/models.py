"""Cari hesaplar (docs/plan/cari-hesaplar.md): müşteri ve tedarikçinin cari hareket defteri.

Bu dosyada iş mantığı yoktur; yazma işlemleri `services.py` üzerinden yapılır. Defter kayıtları
stok defteri gibi değiştirilmez ve silinmez; düzeltme ters kayıtla ya da düzeltme kaydıyla yapılır.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, Currency
from apps.inventory.models import GoodsReceipt, ImmutableModel
from apps.masterdata.models import Customer, Supplier
from apps.returns.models import CustomerReturn
from apps.sales.models import Shipment, ShipmentLine


class Side(models.TextChoices):
    CUSTOMER = "customer", "Müşteri"
    SUPPLIER = "supplier", "Tedarikçi"


class LedgerEntry(ImmutableModel, BaseModel):
    """Cari hareket. Bakiye = borç − alacak (carinin bizim defterimizdeki hesabı): sevkiyat
    müşteriyi borçlandırır, tahsilat alacaklandırır; mal kabul tedarikçiyi alacaklandırır, ödeme
    borçlandırır. Tutarlar kaydın para birimindedir; her para biriminin bakiyesi ayrıdır."""

    class Kind(models.TextChoices):
        SALE = "SALE", "Satış (sevkiyat)"
        PURCHASE = "PURCHASE", "Alış (mal kabul)"
        COLLECTION = "COLLECTION", "Tahsilat"
        PAYMENT = "PAYMENT", "Ödeme"
        RETURN_CREDIT = "RETURN_CREDIT", "İade alacak dekontu"
        DEBIT_NOTE = "DEBIT_NOTE", "Borç dekontu"
        CREDIT_NOTE = "CREDIT_NOTE", "Alacak dekontu"
        OPENING = "OPENING", "Açılış bakiyesi"
        REVERSAL = "REVERSAL", "İptal (ters kayıt)"

    class Method(models.TextChoices):
        CASH = "CASH", "Nakit"
        TRANSFER = "TRANSFER", "Havale / EFT"
        CHECK = "CHECK", "Çek"
        NOTE = "NOTE", "Senet"
        CARD = "CARD", "Kredi kartı"
        OFFSET = "OFFSET", "Mahsup"
        OTHER = "OTHER", "Diğer"

    number = models.CharField("kayıt no", max_length=32, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer,
        verbose_name="müşteri",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    supplier = models.ForeignKey(
        Supplier,
        verbose_name="tedarikçi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    entry_date = models.DateField("tarih", db_index=True)
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    currency = models.CharField("para birimi", max_length=3, choices=Currency.choices)
    debit = models.DecimalField("borç", default=0, max_digits=18, decimal_places=2)
    credit = models.DecimalField("alacak", default=0, max_digits=18, decimal_places=2)
    # Otomatik kayıtta (sevkiyat, mal kabul) matrah ve KDV; elle kayıtta boş.
    net_amount = models.DecimalField(
        "matrah", null=True, blank=True, max_digits=18, decimal_places=2
    )
    vat_amount = models.DecimalField("KDV", null=True, blank=True, max_digits=18, decimal_places=2)
    # 1 birim yabancı para = kaç TL; TL'de ve bilinmiyorsa boş.
    exchange_rate = models.DecimalField(
        "kur (TL)", null=True, blank=True, max_digits=18, decimal_places=6
    )
    method = models.CharField("ödeme şekli", max_length=16, choices=Method.choices, blank=True)
    reference = models.CharField(
        "belge / çek no", max_length=64, blank=True, help_text="Dekont, çek ya da senet no"
    )
    description = models.CharField("açıklama", max_length=255, blank=True)
    shipment = models.ForeignKey(
        Shipment,
        verbose_name="sevkiyat",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    goods_receipt = models.ForeignKey(
        GoodsReceipt,
        verbose_name="mal kabul",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    customer_return = models.ForeignKey(
        CustomerReturn,
        verbose_name="müşteri iadesi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    reversal_of = models.OneToOneField(
        "self",
        verbose_name="iptal edilen kayıt",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal",
    )

    class Meta:
        verbose_name = "cari hareket"
        verbose_name_plural = "cari hareketler"
        ordering = ["entry_date", "id"]
        indexes = [
            models.Index(fields=["customer", "currency", "entry_date"]),
            models.Index(fields=["supplier", "currency", "entry_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(customer__isnull=False) & Q(supplier__isnull=True))
                | (Q(customer__isnull=True) & Q(supplier__isnull=False)),
                name="ledger_entry_one_party",
                violation_error_message="Kayıt bir müşteriye ya da bir tedarikçiye ait olmalıdır.",
            ),
            models.CheckConstraint(
                condition=(Q(debit__gt=0) & Q(credit=0)) | (Q(debit=0) & Q(credit__gt=0)),
                name="ledger_entry_one_side",
                violation_error_message="Tutar sıfırdan büyük olmalı; borç ya da alacak girilir.",
            ),
            models.CheckConstraint(
                condition=Q(exchange_rate__isnull=True) | Q(exchange_rate__gt=0),
                name="ledger_entry_rate_positive",
                violation_error_message="Kur sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.get_kind_display()}"

    @property
    def side(self) -> str:
        return Side.CUSTOMER if self.customer_id is not None else Side.SUPPLIER

    @property
    def amount(self) -> object:
        """Borç ya da alacak tutarı (hangisi doluysa)."""
        return self.debit or self.credit


class ShipmentLinePrice(BaseModel):
    """Siparişinde fiyatı olmayan sevkiyat satırının cari için girilen birim fiyatı (sipariş
    biriminde). Sipariş değişmez; yalnız cari kaydı bu fiyatla yazılır."""

    shipment_line = models.OneToOneField(
        ShipmentLine,
        verbose_name="sevkiyat satırı",
        on_delete=models.PROTECT,
        related_name="ledger_price",
    )
    unit_price = models.DecimalField(
        "birim fiyat", max_digits=18, decimal_places=4, help_text="Sipariş satırının biriminde"
    )
    currency = models.CharField("para birimi", max_length=3, choices=Currency.choices)
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        verbose_name = "sevkiyat satırı cari fiyatı"
        verbose_name_plural = "sevkiyat satırı cari fiyatları"
        constraints = [
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="ledger_shipment_price_non_negative",
                violation_error_message="Birim fiyat negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.shipment_line_id}: {self.unit_price} {self.currency}"
