"""Cari hesaplar: yazma işlemleri ve iş kuralları (docs/plan/cari-hesaplar.md §2.1).

- Sevkiyat ve mal kabul cariye `sync_source` ile yazılır: belgenin bugünkü tutarı defterdeki
  kayıtlarıyla karşılaştırılır, fark varsa kayıt yazılır (idempotent). İlk kayıt belge tarihli,
  sonraki düzeltmeler düzeltme günü tarihlidir.
- Tahsilat, ödeme, iade dekontu, borç/alacak dekontu ve açılış bakiyesi `post_manual_entry` ile
  girilir; iptal `reverse_entry` ile ters kayıttır. Kayıtlar değiştirilmez ve silinmez.
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.models import Currency, User
from apps.core.services import next_document_number, save_with_audit
from apps.inventory.models import GoodsReceipt
from apps.ledger.amounts import ZERO, DocumentAmount, money, receipt_amount, shipment_amount
from apps.ledger.models import LedgerEntry, ShipmentLinePrice, Side
from apps.ledger.notices import SUPPLIER_CLOSING_DATE, SUPPLIER_CLOSING_DESCRIPTION
from apps.masterdata.models import Customer, Supplier
from apps.returns.models import CustomerReturn
from apps.sales.models import Shipment, ShipmentLine

logger = logging.getLogger(__name__)

Kind = LedgerEntry.Kind
Method = LedgerEntry.Method
DEBIT, CREDIT = "debit", "credit"

# Elle girilebilen türler ve yönleri (None: kullanıcı seçer).
MANUAL_KINDS: dict[str, dict[str, str | None]] = {
    Side.CUSTOMER: {
        Kind.COLLECTION: CREDIT,
        Kind.RETURN_CREDIT: CREDIT,
        Kind.DEBIT_NOTE: DEBIT,
        Kind.CREDIT_NOTE: CREDIT,
        Kind.OPENING: None,
    },
    Side.SUPPLIER: {
        Kind.PAYMENT: DEBIT,
        Kind.DEBIT_NOTE: DEBIT,
        Kind.CREDIT_NOTE: CREDIT,
        Kind.OPENING: None,
    },
}
PAYMENT_KINDS = frozenset({Kind.COLLECTION, Kind.PAYMENT})
NOTE_KINDS = frozenset({Kind.DEBIT_NOTE, Kind.CREDIT_NOTE})
AUTO_KINDS = frozenset({Kind.SALE, Kind.PURCHASE})


def _new_entry(actor: User | None, entry: LedgerEntry, note: str) -> LedgerEntry:
    entry.number = next_document_number("CH")
    return save_with_audit(entry, actor, note=note)


def _set_amount(entry: LedgerEntry, direction: str, amount: Decimal) -> None:
    entry.debit = amount if direction == DEBIT else ZERO
    entry.credit = amount if direction == CREDIT else ZERO


# --- belgeden kayıt (sevkiyat, mal kabul) -----------------------------------------------------


@dataclass(frozen=True)
class _Posted:
    net: Decimal
    vat: Decimal


def _posted_by_currency(**source: object) -> dict[str, _Posted]:
    """Belgenin defterdeki kayıtlarının para birimi başına matrah ve KDV toplamı (işaretli:
    belgenin doğal yönü pozitif)."""
    rows = (
        LedgerEntry.objects.filter(**source)
        .values("currency")
        .annotate(net=Sum("net_amount"), vat=Sum("vat_amount"))
    )
    return {row["currency"]: _Posted(row["net"] or ZERO, row["vat"] or ZERO) for row in rows}


def _sync(
    actor: User | None,
    amount: DocumentAmount,
    *,
    source: dict[str, object],
    template: LedgerEntry,
    direction: str,
    label: str,
) -> list[LedgerEntry]:
    posted = _posted_by_currency(**source)
    first = not posted
    today = timezone.localdate()
    created: list[LedgerEntry] = []
    for currency in sorted(set(posted) | set(amount.by_currency)):
        target = amount.by_currency.get(currency)
        before = posted.get(currency, _Posted(ZERO, ZERO))
        net = (target.net if target else ZERO) - before.net
        vat = (target.vat if target else ZERO) - before.vat
        gross = net + vat
        if gross == 0:
            # Matrah ile KDV birbirini götürüyorsa (oran değişikliği) brüt bakiye zaten doğru.
            continue
        entry = LedgerEntry(
            customer=template.customer,
            supplier=template.supplier,
            kind=template.kind,
            currency=currency,
            net_amount=net,
            vat_amount=vat,
            exchange_rate=target.exchange_rate if target and currency != Currency.TRY else None,
            shipment=template.shipment,
            goods_receipt=template.goods_receipt,
        )
        if first:
            entry.entry_date = amount.document_date or today
            entry.description = label
        else:
            entry.entry_date = today
            entry.description = f"Düzeltme: {label}"
        positive = gross > 0
        _set_amount(entry, direction if positive else _opposite(direction), abs(gross))
        created.append(_new_entry(actor, entry, entry.description))
    return created


def _opposite(direction: str) -> str:
    return CREDIT if direction == DEBIT else DEBIT


@transaction.atomic
def sync_shipment(actor: User | None, shipment: Shipment) -> list[LedgerEntry]:
    """Sevk edilmiş sevkiyatı müşteri carisine borç olarak yazar ya da düzeltir. Sevk edilmemiş
    sevkiyatta bir şey yapmaz. Aynı sevkiyat için tekrar çağrılabilir (idempotent)."""
    shipment = (
        Shipment.objects.select_for_update()
        .select_related("sales_order__customer")
        .get(pk=shipment.pk)
    )
    amount = shipment_amount(shipment)
    return _sync(
        actor,
        amount,
        source={"shipment": shipment, "kind": Kind.SALE},
        template=LedgerEntry(
            customer=shipment.sales_order.customer, kind=Kind.SALE, shipment=shipment
        ),
        direction=DEBIT,
        label=f"Sevkiyat {shipment.number}",
    )


@transaction.atomic
def sync_receipt(actor: User | None, receipt: GoodsReceipt) -> list[LedgerEntry]:
    """Kaydedilmiş mal kabulü tedarikçi carisine alacak olarak yazar ya da düzeltir (fiyat
    düzeltmesi). Aynı kabul için tekrar çağrılabilir (idempotent)."""
    receipt = GoodsReceipt.objects.select_for_update().select_related("supplier").get(pk=receipt.pk)
    amount = receipt_amount(receipt)
    label = f"Mal kabul {receipt.number}"
    if receipt.delivery_note_no:
        label += f" (irsaliye {receipt.delivery_note_no})"
    return _sync(
        actor,
        amount,
        source={"goods_receipt": receipt, "kind": Kind.PURCHASE},
        template=LedgerEntry(supplier=receipt.supplier, kind=Kind.PURCHASE, goods_receipt=receipt),
        direction=CREDIT,
        label=label,
    )


def sync_all(actor: User | None = None) -> int:
    """Bütün sevk edilmiş sevkiyatları ve kaydedilmiş mal kabulleri eşitler (geçmiş veri ve
    kaçan olaylar için; `manage.py sync_ledger` ve günlük kontrol). Yazılan kayıt sayısını döner.
    Hata veren belge loglanır, ötekiler sürer."""
    written = 0
    for shipment in Shipment.objects.filter(status=Shipment.Status.DISPATCHED).order_by("id"):
        try:
            written += len(sync_shipment(actor, shipment))
        except Exception:
            logger.exception("Cari eşitleme başarısız: sevkiyat %s", shipment.pk)
    for receipt in GoodsReceipt.objects.filter(status=GoodsReceipt.Status.POSTED).order_by("id"):
        try:
            written += len(sync_receipt(actor, receipt))
        except Exception:
            logger.exception("Cari eşitleme başarısız: mal kabul %s", receipt.pk)
    return written


@transaction.atomic
def set_shipment_line_price(
    actor: User,
    line: ShipmentLine,
    unit_price: Decimal,
    currency: str,
    note: str = "",
) -> list[LedgerEntry]:
    """Siparişinde fiyatı olmayan sevk edilmiş satıra cari için birim fiyat (sipariş biriminde)
    girer ya da değiştirir ve sevkiyatı eşitler. Sipariş değişmez."""
    line = ShipmentLine.objects.select_related("shipment", "order_line").get(pk=line.pk)
    if line.shipment.status != Shipment.Status.DISPATCHED:
        raise BusinessRuleError(
            "shipment_not_dispatched", "Fiyat yalnız sevk edilmiş sevkiyatın satırına girilir."
        )
    if line.order_line.unit_price is not None:
        raise BusinessRuleError(
            "order_line_has_price",
            "Bu satırın fiyatı siparişte var; cari tutarı sipariş fiyatından yazılır.",
        )
    if unit_price is None or unit_price < 0:
        raise BusinessRuleError("invalid_price", "Birim fiyat negatif olamaz.")
    if currency not in Currency.values:
        raise BusinessRuleError("invalid_currency", "Para birimi TRY, EUR ya da USD olmalıdır.")
    price = ShipmentLinePrice.objects.filter(shipment_line=line).first() or ShipmentLinePrice(
        shipment_line=line
    )
    price.unit_price = unit_price
    price.currency = currency
    price.note = note.strip()
    save_with_audit(price, actor, note=f"Cari fiyatı: {line.shipment.number}")
    return sync_shipment(actor, line.shipment)


# --- elle kayıt ------------------------------------------------------------------------------


@transaction.atomic
def post_manual_entry(
    actor: User,
    *,
    partner: Customer | Supplier,
    kind: str,
    entry_date: date,
    currency: str,
    amount: Decimal,
    direction: str | None = None,
    method: str = "",
    reference: str = "",
    description: str = "",
    exchange_rate: Decimal | None = None,
    customer_return: CustomerReturn | None = None,
) -> LedgerEntry:
    """Tahsilat, ödeme, iade dekontu, borç/alacak dekontu ya da açılış bakiyesi girer.

    Yön türden gelir; açılış bakiyesinde `direction` (borç / alacak) zorunludur. Tutar 2 ondalık,
    tarih bugünden ileri olamaz. Tahsilat ve ödemede ödeme şekli, dekontta açıklama, iade
    dekontunda aynı müşterinin teslim alınmış iadesi zorunludur."""
    side = Side.CUSTOMER if isinstance(partner, Customer) else Side.SUPPLIER
    kinds = MANUAL_KINDS[side]
    if kind not in kinds:
        raise BusinessRuleError(
            "invalid_entry_kind",
            f"{Side(side).label} carisine bu tür kayıt girilemez.",
        )
    fixed = kinds[kind]
    if fixed is None:
        if direction not in (DEBIT, CREDIT):
            raise BusinessRuleError(
                "direction_required", "Açılış bakiyesinin borç mu alacak mı olduğunu seçin."
            )
    else:
        direction = fixed
    if currency not in Currency.values:
        raise BusinessRuleError("invalid_currency", "Para birimi TRY, EUR ya da USD olmalıdır.")
    if amount is None or amount <= 0:
        raise BusinessRuleError("invalid_amount", "Tutar sıfırdan büyük olmalıdır.")
    if money(amount) != amount:
        raise BusinessRuleError("invalid_amount", "Tutar en fazla 2 ondalık olabilir.")
    if entry_date > timezone.localdate():
        raise BusinessRuleError("entry_date_in_future", "Kayıt tarihi bugünden ileri olamaz.")
    if currency == Currency.TRY:
        exchange_rate = None
    elif exchange_rate is not None and exchange_rate <= 0:
        raise BusinessRuleError("invalid_exchange_rate", "Kur sıfırdan büyük olmalıdır.")
    method = method or ""
    if kind in PAYMENT_KINDS:
        if method not in Method.values:
            raise BusinessRuleError("method_required", "Ödeme şeklini seçin.")
    else:
        method = ""
    description = (description or "").strip()
    if kind in NOTE_KINDS and not description:
        raise BusinessRuleError("description_required", "Dekontun açıklamasını yazın.")
    if kind == Kind.RETURN_CREDIT:
        if customer_return is None:
            raise BusinessRuleError("return_required", "İade dekontunun iadesini seçin.")
        if customer_return.customer_id != partner.pk:
            raise BusinessRuleError("return_other_customer", "İade bu müşterinin değil.")
        if customer_return.status not in (
            CustomerReturn.Status.RECEIVED,
            CustomerReturn.Status.CLOSED,
        ):
            raise BusinessRuleError(
                "return_not_received", "Yalnız teslim alınmış iade için dekont girilir."
            )
    else:
        customer_return = None
    entry = LedgerEntry(
        customer=partner if isinstance(partner, Customer) else None,
        supplier=partner if isinstance(partner, Supplier) else None,
        kind=kind,
        entry_date=entry_date,
        currency=currency,
        exchange_rate=exchange_rate,
        method=method,
        reference=(reference or "").strip(),
        description=description or (f"İade {customer_return.number}" if customer_return else ""),
        customer_return=customer_return,
    )
    assert direction is not None
    _set_amount(entry, direction, amount)
    return _new_entry(actor, entry, f"{Kind(kind).label} girildi")


@transaction.atomic
def reverse_entry(actor: User, entry: LedgerEntry, reason: str) -> LedgerEntry:
    """Elle girilmiş kaydı ters kayıtla iptal eder (bugün tarihli, gerekçe zorunlu). Sevkiyat ve
    mal kabul kayıtları belgeyi izler, iptal edilemez; fark dekontla düzeltilir."""
    reason = (reason or "").strip()
    if not reason:
        raise BusinessRuleError("reversal_reason_required", "İptal nedenini yazın.")
    entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.kind in AUTO_KINDS:
        raise BusinessRuleError(
            "auto_entry_not_reversible",
            "Sevkiyat ve mal kabul kaydı iptal edilemez; farkı dekontla düzeltin.",
        )
    if entry.kind == Kind.REVERSAL:
        raise BusinessRuleError("cannot_reverse_reversal", "İptal kaydı iptal edilemez.")
    if LedgerEntry.objects.filter(reversal_of=entry).exists():
        raise BusinessRuleError("already_reversed", "Bu kayıt zaten iptal edilmiş.")
    reversal = LedgerEntry(
        customer_id=entry.customer_id,
        supplier_id=entry.supplier_id,
        kind=Kind.REVERSAL,
        entry_date=timezone.localdate(),
        currency=entry.currency,
        debit=entry.credit,
        credit=entry.debit,
        exchange_rate=entry.exchange_rate,
        description=f"İptal: {entry.number} ({reason})"[:255],
        customer_return_id=entry.customer_return_id,
        reversal_of=entry,
    )
    return _new_entry(actor, reversal, f"{entry.number} iptal edildi: {reason}")


# --- devir sıfırlama -------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierClosing:
    """Tedarikçinin bir para birimindeki kapatılacak bakiyesi (borç − alacak)."""

    supplier: Supplier
    currency: str
    balance: Decimal

    @property
    def direction(self) -> str:
        # Bakiyeyi sıfırlayan yön: verecek (alacak bakiyesi) borçla, avans alacakla kapanır.
        return DEBIT if self.balance < 0 else CREDIT


def supplier_closings(as_of: date) -> list[SupplierClosing]:
    """`as_of` günü dahil, sıfır olmayan tedarikçi bakiyeleri (tedarikçi ve para birimi başına).
    Bu tarihten sonraki kayıtlar hesaba girmez."""
    rows = (
        LedgerEntry.objects.filter(supplier__isnull=False, entry_date__lte=as_of)
        .values("supplier", "currency")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("supplier", "currency")
    )
    suppliers = Supplier.objects.in_bulk({row["supplier"] for row in rows})
    closings = []
    for row in rows:
        balance = (row["debit"] or ZERO) - (row["credit"] or ZERO)
        if balance != 0:
            closings.append(SupplierClosing(suppliers[row["supplier"]], row["currency"], balance))
    closings.sort(key=lambda item: (item.supplier.code, item.currency))
    return closings


@transaction.atomic
def close_supplier_balances(
    actor: User,
    *,
    as_of: date = SUPPLIER_CLOSING_DATE,
    description: str = SUPPLIER_CLOSING_DESCRIPTION,
) -> list[LedgerEntry]:
    """Tedarikçi carilerini `as_of` itibarıyla sıfırlar: sıfır olmayan her tedarikçi ve para
    birimi bakiyesi için `as_of` tarihli, açıklamalı açılış (devir) kaydı yazar. Eski kayıtlar
    silinmez ve değişmez; ekstrede görünür. Tekrar çağrılabilir (bakiye sıfırsa yazmaz).
    Müşteri carilerine dokunmaz (DECISIONS 2026-11-20)."""
    created = []
    for closing in supplier_closings(as_of):
        created.append(
            post_manual_entry(
                actor,
                partner=closing.supplier,
                kind=Kind.OPENING,
                entry_date=as_of,
                currency=closing.currency,
                amount=abs(closing.balance),
                direction=closing.direction,
                description=description,
            )
        )
    return created
