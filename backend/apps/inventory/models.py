"""Stok ve lot: lot, stok hareket defteri, bakiye, lot soy ağacı, mal kabul, sayım düzeltme.

Bu dosyada iş mantığı yoktur. Stoka dokunmanın tek yolu `inventory.services.post_movement`'tır
(CLAUDE.md §4.1): hareketler değiştirilmez ve silinmez, bakiye yalnızca o fonksiyonda güncellenir.
Lot durumu ve belge durumları yalnızca `services` içinden, `state.py`'deki izin tablosuna göre
değişir.
"""

from typing import Any, NoReturn

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, Currency, DocumentModel, User
from apps.masterdata.models import Location, Material, Supplier, UnitOfMeasure


class Lot(BaseModel):
    class Status(models.TextChoices):
        QUARANTINE = "QUARANTINE", "Karantina"
        RELEASED = "RELEASED", "Serbest"
        REJECTED = "REJECTED", "Reddedildi"
        BLOCKED = "BLOCKED", "Bloke"

    class Source(models.TextChoices):
        PURCHASE = "PURCHASE", "Satın alma"
        PRODUCTION = "PRODUCTION", "Üretim"
        FILLING = "FILLING", "Dolum"
        OPENING = "OPENING", "Açılış stoku"
        RETURN = "RETURN", "İade"

    lot_no = models.CharField("lot no", max_length=64)
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="lots"
    )
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.QUARANTINE,
        db_index=True,
        editable=False,
    )
    source = models.CharField("kaynak", max_length=16, choices=Source.choices)
    supplier = models.ForeignKey(
        Supplier,
        verbose_name="tedarikçi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lots",
    )
    supplier_lot_no = models.CharField("tedarikçi lot no", max_length=64, blank=True)
    manufactured_at = models.DateField("üretim tarihi", null=True, blank=True)
    expiry_date = models.DateField("son kullanma tarihi", null=True, blank=True, db_index=True)
    released_by = models.ForeignKey(
        User,
        verbose_name="serbest bırakan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    released_at = models.DateTimeField("serbest bırakılma zamanı", null=True, blank=True)
    status_note = models.TextField("durum notu", blank=True)
    # Maliyet (Faz 4, Adım 4.1): TL / temel birim. Yalnızca `inventory.services.set_lot_cost`
    # yazar (costing modülü hesaplar); döküm `costing.LotCost`'tadır. Tutarlar yalnızca yonetim
    # ve admin rolüne gösterilir.
    unit_cost = models.DecimalField(
        "birim maliyet", null=True, blank=True, editable=False, max_digits=18, decimal_places=4
    )
    cost_is_estimated = models.BooleanField("tahmini maliyet", default=False, editable=False)

    class Meta:
        verbose_name = "lot"
        verbose_name_plural = "lotlar"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["material", "lot_no"],
                name="inventory_lot_material_lot_no_uniq",
                violation_error_message="Bu malzemede bu lot numarası zaten var.",
            )
        ]

    def __str__(self) -> str:
        return self.lot_no


class LotNumberSequence(models.Model):
    """Lot numarası sayacı: önek + gün başına (`H-261015-001`). Karar D-2."""

    prefix = models.CharField("önek", max_length=4)
    day = models.DateField("gün")
    last_number = models.PositiveIntegerField("son numara", default=0)

    class Meta:
        verbose_name = "lot numarası sayacı"
        verbose_name_plural = "lot numarası sayaçları"
        constraints = [
            models.UniqueConstraint(fields=["prefix", "day"], name="inventory_lot_seq_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.prefix}-{self.day:%y%m%d}: {self.last_number}"


class ImmutableQuerySet(models.QuerySet):
    """Toplu güncelleme ve silmeyi reddeden QuerySet (hareket defteri, soy ağacı)."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise TypeError(f"{self.model._meta.verbose_name} kayıtları değiştirilemez.")

    def delete(self) -> NoReturn:  # type: ignore[override]
        raise TypeError(f"{self.model._meta.verbose_name} kayıtları silinemez.")


class ImmutableModel(models.Model):
    """Oluşturulduktan sonra değiştirilemeyen ve silinemeyen kayıt."""

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise TypeError(f"{self._meta.verbose_name} kaydı değiştirilemez.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise TypeError(f"{self._meta.verbose_name} kaydı silinemez.")


class StockMovement(ImmutableModel):
    """Stok hareket defteri. Miktar işaretlidir ve malzemenin temel birimindedir
    (giriş +, çıkış −). Düzeltme ters kayıtla (`REVERSAL`) yapılır."""

    class Type(models.TextChoices):
        OPENING = "OPENING", "Açılış"
        RECEIPT = "RECEIPT", "Mal kabul"
        ISSUE_PRODUCTION = "ISSUE_PRODUCTION", "Üretime çıkış"
        PRODUCTION_OUTPUT = "PRODUCTION_OUTPUT", "Üretimden giriş"
        TRANSFER_OUT = "TRANSFER_OUT", "Transfer çıkışı"
        TRANSFER_IN = "TRANSFER_IN", "Transfer girişi"
        ADJUSTMENT = "ADJUSTMENT", "Sayım düzeltme"
        SCRAP = "SCRAP", "Fire / imha"
        SHIPMENT = "SHIPMENT", "Sevkiyat"
        RETURN = "RETURN", "İade"
        REVERSAL = "REVERSAL", "Ters kayıt"

    movement_type = models.CharField("hareket türü", max_length=20, choices=Type.choices)
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    lot = models.ForeignKey(
        Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="movements"
    )
    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar (temel birim)", max_digits=18, decimal_places=4)
    source_content_type = models.ForeignKey(
        ContentType,
        verbose_name="kaynak belge türü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    source_object_id = models.BigIntegerField("kaynak belge no", null=True, blank=True)
    source = GenericForeignKey("source_content_type", "source_object_id")
    document_number = models.CharField("belge no", max_length=32, blank=True, db_index=True)
    reversal_of = models.OneToOneField(
        "self",
        verbose_name="ters kaydı yapılan hareket",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversed_by",
    )
    transfer_group = models.UUIDField("transfer grubu", null=True, blank=True, db_index=True)
    note = models.TextField("not", blank=True)
    created_at = models.DateTimeField("zaman", auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="kaydeden",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "stok hareketi"
        verbose_name_plural = "stok hareketleri"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["source_content_type", "source_object_id"])]
        constraints = [
            models.CheckConstraint(
                condition=~Q(quantity=0),
                name="inventory_movement_quantity_nonzero",
                violation_error_message="Hareket miktarı sıfır olamaz.",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_movement_type_display()} {self.lot} {self.quantity}"


class StockBalance(models.Model):
    """Malzeme + lot + lokasyon bakiyesi (temel birimde). Yalnızca `post_movement` günceller."""

    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    lot = models.ForeignKey(
        Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="balances"
    )
    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(
        "miktar (temel birim)", default=0, max_digits=18, decimal_places=4
    )
    updated_at = models.DateTimeField("güncellenme zamanı", auto_now=True)

    class Meta:
        verbose_name = "stok bakiyesi"
        verbose_name_plural = "stok bakiyeleri"
        ordering = ["material__code", "lot__lot_no", "location__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["material", "lot", "location"], name="inventory_balance_uniq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0),
                name="inventory_balance_non_negative",
                violation_error_message="Stok negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.lot} @ {self.location.code}: {self.quantity}"


class LotLink(ImmutableModel):
    """Lot soy ağacı: `parent_lot` (girdi) → `child_lot` (çıktı), girdi lottan kullanılan miktar
    (temel birimde). CLAUDE.md §4.3."""

    parent_lot = models.ForeignKey(
        Lot, verbose_name="girdi lot", on_delete=models.PROTECT, related_name="child_links"
    )
    child_lot = models.ForeignKey(
        Lot, verbose_name="çıktı lot", on_delete=models.PROTECT, related_name="parent_links"
    )
    quantity = models.DecimalField(
        "kullanılan miktar (temel birim)", max_digits=18, decimal_places=4
    )
    source_content_type = models.ForeignKey(
        ContentType,
        verbose_name="kaynak belge türü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    source_object_id = models.BigIntegerField("kaynak belge no", null=True, blank=True)
    source = GenericForeignKey("source_content_type", "source_object_id")
    created_at = models.DateTimeField("zaman", auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="kaydeden",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "lot bağı"
        verbose_name_plural = "lot soy ağacı"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="inventory_lotlink_quantity_positive",
                violation_error_message="Kullanılan miktar sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=~Q(parent_lot=models.F("child_lot")),
                name="inventory_lotlink_not_self",
                violation_error_message="Lot kendisine bağlanamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent_lot} → {self.child_lot} ({self.quantity})"


class GoodsReceipt(DocumentModel):
    """Mal kabul (`MK-`). DRAFT → POSTED | CANCELLED."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        POSTED = "POSTED", "Kaydedildi"
        CANCELLED = "CANCELLED", "İptal"

    supplier = models.ForeignKey(
        Supplier, verbose_name="tedarikçi", on_delete=models.PROTECT, related_name="receipts"
    )
    receipt_date = models.DateField("kabul tarihi")
    delivery_note_no = models.CharField("irsaliye no", max_length=64, blank=True)
    quarantine_location = models.ForeignKey(
        Location,
        verbose_name="karantina lokasyonu",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Giriş kontrolü gereken malzemeler buraya alınır",
    )
    storage_location = models.ForeignKey(
        Location,
        verbose_name="depo lokasyonu",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Giriş kontrolü gerekmeyen malzemeler buraya alınır",
    )
    note = models.TextField("not", blank=True)
    posted_at = models.DateTimeField("kaydedilme zamanı", null=True, blank=True, editable=False)
    posted_by = models.ForeignKey(
        User,
        verbose_name="kaydeden",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "mal kabul"
        verbose_name_plural = "mal kabuller"
        ordering = ["-receipt_date", "-id"]


class GoodsReceiptLine(BaseModel):
    receipt = models.ForeignKey(
        GoodsReceipt, verbose_name="mal kabul", on_delete=models.PROTECT, related_name="lines"
    )
    line_no = models.PositiveIntegerField("satır no")
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure, verbose_name="birim", on_delete=models.PROTECT, related_name="+"
    )
    supplier_lot_no = models.CharField("tedarikçi lot no", max_length=64, blank=True)
    manufactured_at = models.DateField("üretim tarihi", null=True, blank=True)
    expiry_date = models.DateField("son kullanma tarihi", null=True, blank=True)
    unit_price = models.DecimalField(
        "birim fiyat",
        null=True,
        blank=True,
        help_text="Satır biriminde, satırın para biriminde",
        max_digits=18,
        decimal_places=4,
    )
    currency = models.CharField(
        "para birimi", max_length=3, choices=Currency.choices, default=Currency.TRY
    )
    # 1 birim yabancı para = kaç TL; TL satırda boştur.
    exchange_rate = models.DecimalField(
        "kur", null=True, blank=True, max_digits=18, decimal_places=4
    )
    # Kaydedilince dolar.
    base_quantity = models.DecimalField(
        "miktar (temel birim)",
        null=True,
        blank=True,
        editable=False,
        max_digits=18,
        decimal_places=4,
    )
    created_lot = models.OneToOneField(
        Lot,
        verbose_name="oluşan lot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="receipt_line",
        editable=False,
    )

    class Meta:
        verbose_name = "mal kabul satırı"
        verbose_name_plural = "mal kabul satırları"
        ordering = ["receipt", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "line_no"], name="inventory_receipt_line_no_uniq"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="inventory_receipt_line_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__isnull=True) | Q(unit_price__gte=0),
                name="inventory_receipt_line_price_non_negative",
                violation_error_message="Birim fiyat negatif olamaz.",
            ),
            models.CheckConstraint(
                condition=Q(exchange_rate__isnull=True) | Q(exchange_rate__gt=0),
                name="inventory_receipt_line_rate_positive",
                violation_error_message="Kur sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.receipt_id}/{self.line_no} {self.material_id}"


class GoodsReceiptExtraCost(BaseModel):
    """Mal kabulün ek masrafı (nakliye, gümrük, diğer), TL. Satırlara miktar ya da tutar oranında
    dağıtılıp lot maliyetine eklenir (costing). Kaydedilmiş mal kabule de sonradan girilebilir."""

    class Kind(models.TextChoices):
        FREIGHT = "FREIGHT", "Nakliye"
        CUSTOMS = "CUSTOMS", "Gümrük"
        OTHER = "OTHER", "Diğer"

    class Allocation(models.TextChoices):
        QUANTITY = "QUANTITY", "Miktar oranında"
        VALUE = "VALUE", "Tutar oranında"

    receipt = models.ForeignKey(
        GoodsReceipt, verbose_name="mal kabul", on_delete=models.PROTECT, related_name="extra_costs"
    )
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    description = models.CharField("açıklama", max_length=200, blank=True)
    amount = models.DecimalField("tutar (TL)", max_digits=18, decimal_places=2)
    allocation = models.CharField(
        "dağıtım", max_length=16, choices=Allocation.choices, default=Allocation.QUANTITY
    )

    class Meta:
        verbose_name = "mal kabul ek masrafı"
        verbose_name_plural = "mal kabul ek masrafları"
        ordering = ["receipt", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="inventory_receipt_extra_cost_positive",
                violation_error_message="Tutar sıfırdan büyük olmalıdır.",
            )
        ]

    def __str__(self) -> str:
        return f"{self.receipt_id} {self.kind} {self.amount}"


class StockAdjustment(DocumentModel):
    """Sayım farkı / stok düzeltme (`SD-`). DRAFT → POSTED | CANCELLED. Karar D-3: depo onaylar."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        POSTED = "POSTED", "Kaydedildi"
        CANCELLED = "CANCELLED", "İptal"

    adjustment_date = models.DateField("sayım tarihi")
    note = models.TextField("not", blank=True)
    posted_at = models.DateTimeField("kaydedilme zamanı", null=True, blank=True, editable=False)
    posted_by = models.ForeignKey(
        User,
        verbose_name="onaylayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "sayım düzeltme"
        verbose_name_plural = "sayım düzeltmeleri"
        ordering = ["-adjustment_date", "-id"]


class StockAdjustmentLine(BaseModel):
    adjustment = models.ForeignKey(
        StockAdjustment,
        verbose_name="sayım düzeltme",
        on_delete=models.PROTECT,
        related_name="lines",
    )
    line_no = models.PositiveIntegerField("satır no")
    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    # Taslakta bilgi amaçlıdır; kaydedilirken o anki bakiyeyle yeniden okunur.
    system_quantity = models.DecimalField(
        "sistem miktarı", default=0, max_digits=18, decimal_places=4
    )
    counted_quantity = models.DecimalField("sayılan miktar", max_digits=18, decimal_places=4)
    difference = models.DecimalField("fark", default=0, max_digits=18, decimal_places=4)
    reason = models.CharField("neden", max_length=255)
    movement = models.OneToOneField(
        StockMovement,
        verbose_name="hareket",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "sayım düzeltme satırı"
        verbose_name_plural = "sayım düzeltme satırları"
        ordering = ["adjustment", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["adjustment", "line_no"], name="inventory_adjustment_line_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["adjustment", "lot", "location"],
                name="inventory_adjustment_lot_location_uniq",
                violation_error_message="Aynı lot ve lokasyon belgede bir kez sayılır.",
            ),
            models.CheckConstraint(
                condition=Q(counted_quantity__gte=0),
                name="inventory_adjustment_counted_non_negative",
                violation_error_message="Sayılan miktar negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.adjustment_id}/{self.line_no} {self.lot_id}"


class PalletLabel(BaseModel):
    """SSCC'li palet etiketi kaydı (Karar D-6). SSCC bir kez verilir, tekrar basılabilir."""

    sscc = models.CharField("SSCC", max_length=18, unique=True, editable=False)
    lot = models.ForeignKey(
        Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="pallet_labels"
    )
    case_count = models.PositiveIntegerField("koli sayısı")
    units_per_case = models.PositiveIntegerField("koli içi adet", null=True, blank=True)

    class Meta:
        verbose_name = "palet etiketi"
        verbose_name_plural = "palet etiketleri"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(case_count__gte=1),
                name="inventory_pallet_case_count_positive",
                violation_error_message="Koli sayısı en az 1 olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return self.sscc


class PickRecord(BaseModel):
    """Ortak hazırlama kaydı (soyut): depodan bir belgenin kullanım lokasyonuna transfer edilen lot.

    Üretimde malzeme hazırlama (`production.MaterialPick`) ve dolumda ambalaj hazırlama
    (`filling.PackagingPick`) bu alanları kullanır; yazma `inventory.picking` servisleriyle olur.
    """

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
    # Belge hazırlıkta iptal edilince malzeme kaynağa geri transfer edilir.
    returned_at = models.DateTimeField("iade zamanı", null=True, blank=True, editable=False)

    class Meta:
        abstract = True


class StockReservation(BaseModel):
    """Stok rezervasyonu (Faz 3, Adım 3.1): bir belgenin (satışta sipariş satırı) bir lot ve
    lokasyondaki stoktan ayırdığı miktar (temel birimde).

    Rezervasyon stok hareketi değildir; kullanılabilir stok = bakiye − aktif rezervasyonlar.
    Kaynak belge genel bağla tutulur (stok hareketindeki gibi), böylece inventory satış modülüne
    bağımlı olmaz. Yazma yalnızca `inventory.services.reserve / release_reservation /
    consume_reservation` ile.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Aktif"
        CONSUMED = "CONSUMED", "Kullanıldı"
        RELEASED = "RELEASED", "Bırakıldı"

    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    lot = models.ForeignKey(
        Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="reservations"
    )
    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField("miktar (temel birim)", max_digits=18, decimal_places=4)
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
        editable=False,
    )
    source_content_type = models.ForeignKey(
        ContentType, verbose_name="kaynak belge türü", on_delete=models.PROTECT, related_name="+"
    )
    source_object_id = models.BigIntegerField("kaynak belge no")
    source = GenericForeignKey("source_content_type", "source_object_id")
    document_number = models.CharField("belge no", max_length=32, blank=True, db_index=True)
    note = models.TextField("not", blank=True)
    closed_at = models.DateTimeField("kapanma zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "stok rezervasyonu"
        verbose_name_plural = "stok rezervasyonları"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["source_content_type", "source_object_id"]),
            models.Index(fields=["lot", "location", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="inventory_reservation_quantity_positive",
                violation_error_message="Rezervasyon miktarı sıfırdan büyük olmalıdır.",
            )
        ]

    def __str__(self) -> str:
        return f"{self.document_number or self.source_object_id}: {self.lot} {self.quantity}"
