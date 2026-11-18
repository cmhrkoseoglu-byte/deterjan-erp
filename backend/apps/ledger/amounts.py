"""Belgenin bugünkü cari tutarı: sevk edilen sevkiyat ve kaydedilmiş mal kabul (plan §2.1).

Tutar para birimi başına matrah ve KDV'dir; satır bazında 2 ondalığa yuvarlanır. Fiyatı olmayan
satır tutara girmez, "tutarı eksik" listesinde döner.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.inventory.models import GoodsReceipt, GoodsReceiptLine
from apps.masterdata.models import Material
from apps.sales.models import Shipment, ShipmentLine

ZERO = Decimal(0)
MONEY_STEP = Decimal("0.01")
RATE_STEP = Decimal("0.000001")
HUNDRED = Decimal(100)


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def vat_of(net: Decimal, material: Material, exempt: bool) -> Decimal:
    """Satır KDV'si: KDV muaf caride 0, değilse matrah × malzemenin KDV oranı."""
    if exempt:
        return ZERO
    return money(net * material.vat_rate / HUNDRED)


@dataclass
class CurrencyAmount:
    net: Decimal = ZERO
    vat: Decimal = ZERO
    # Kurlu satırların TL matrahı ve döviz matrahı (ağırlıklı kur için).
    rated_tl: Decimal = ZERO
    rated_net: Decimal = ZERO
    unrated: bool = False

    @property
    def gross(self) -> Decimal:
        return self.net + self.vat

    @property
    def exchange_rate(self) -> Decimal | None:
        """Satırların ağırlıklı kuru; kursuz satır varsa ya da kur yoksa boş."""
        if self.unrated or self.rated_net <= 0:
            return None
        return (self.rated_tl / self.rated_net).quantize(RATE_STEP, rounding=ROUND_HALF_UP)


@dataclass
class MissingLine:
    """Fiyatı olmadığı için cariye yazılmamış satır."""

    line_id: int
    material_code: str
    material_name: str
    quantity: Decimal
    unit_code: str


@dataclass
class DocumentAmount:
    document_date: date | None
    by_currency: dict[str, CurrencyAmount] = field(default_factory=dict)
    missing: list[MissingLine] = field(default_factory=list)


def _bucket(amounts: dict[str, CurrencyAmount], currency: str) -> CurrencyAmount:
    return amounts.setdefault(currency, CurrencyAmount())


def shipped_quantities(shipment: Shipment) -> dict[int, Decimal]:
    """Sevkiyat satırı başına sevk edilen miktar (temel birimde; sevk hareketi yazılmış
    toplamalar). Hareketin sonradan ters kaydı ticari tutarı değiştirmez (dekontla düzeltilir)."""
    rows = (
        ShipmentLine.objects.filter(shipment=shipment)
        .annotate(
            shipped=Sum("picks__quantity", filter=Q(picks__movement__isnull=False)),
        )
        .values_list("pk", "shipped")
    )
    return {pk: shipped for pk, shipped in rows if shipped}


def shipment_amount(shipment: Shipment) -> DocumentAmount:
    """Sevk edilmiş sevkiyatın müşteri borcu: sevk edilen miktar (sipariş birimine çevrilir) ×
    sipariş fiyatı (yoksa cari için girilen fiyat), KDV müşterinin muafiyetine ve malzemenin
    oranına göre."""
    if shipment.status != Shipment.Status.DISPATCHED:
        return DocumentAmount(document_date=None)
    dispatched = shipment.dispatched_at
    result = DocumentAmount(
        document_date=timezone.localtime(dispatched).date() if dispatched else None
    )
    exempt = shipment.sales_order.customer.vat_exempt
    shipped = shipped_quantities(shipment)
    lines = (
        ShipmentLine.objects.filter(pk__in=shipped)
        .select_related("order_line__product__base_unit", "order_line__unit", "ledger_price")
        .order_by("order_line__line_no")
    )
    for line in lines:
        order_line = line.order_line
        base_quantity = shipped[line.pk]
        # Sipariş birimine çevir (fiyat sipariş biriminde).
        quantity = base_quantity * order_line.quantity / order_line.base_quantity
        price, currency = order_line.unit_price, order_line.currency
        if price is None:
            override = getattr(line, "ledger_price", None)
            if override is None:
                result.missing.append(
                    MissingLine(
                        line_id=line.pk,
                        material_code=order_line.product.code,
                        material_name=order_line.product.name,
                        quantity=quantity,
                        unit_code=order_line.unit.code,
                    )
                )
                continue
            price, currency = override.unit_price, override.currency
        net = money(quantity * price)
        bucket = _bucket(result.by_currency, currency)
        bucket.net += net
        bucket.vat += vat_of(net, order_line.product, exempt)
        bucket.unrated = bucket.unrated or currency != "TRY"
    return result


def receipt_amount(receipt: GoodsReceipt) -> DocumentAmount:
    """Kaydedilmiş mal kabulün tedarikçi alacağı: satır miktarı × birim fiyat, KDV tedarikçinin
    muafiyetine ve malzemenin oranına göre. Ek masraflar cariye yazılmaz (yalnız maliyete)."""
    if receipt.status != GoodsReceipt.Status.POSTED:
        return DocumentAmount(document_date=None)
    result = DocumentAmount(document_date=receipt.receipt_date)
    exempt = receipt.supplier.vat_exempt
    lines = GoodsReceiptLine.objects.filter(receipt=receipt).select_related("material", "unit")
    for line in lines.order_by("line_no"):
        if line.unit_price is None:
            result.missing.append(
                MissingLine(
                    line_id=line.pk,
                    material_code=line.material.code,
                    material_name=line.material.name,
                    quantity=line.quantity,
                    unit_code=line.unit.code,
                )
            )
            continue
        net = money(line.quantity * line.unit_price)
        bucket = _bucket(result.by_currency, line.currency)
        bucket.net += net
        bucket.vat += vat_of(net, line.material, exempt)
        if line.currency != "TRY":
            if line.exchange_rate is None:
                bucket.unrated = True
            else:
                bucket.rated_net += net
                bucket.rated_tl += net * line.exchange_rate
    return result
