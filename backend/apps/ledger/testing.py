"""Test yardımcısı: cari defter değişmezleri (stoktaki `assert_stock_invariants` gibi)."""

from decimal import Decimal

from django.db.models import Sum

from apps.inventory.models import GoodsReceipt
from apps.ledger.amounts import ZERO, receipt_amount, shipment_amount
from apps.ledger.models import LedgerEntry
from apps.sales.models import Shipment


def _posted(**source: object) -> dict[str, tuple[Decimal, Decimal]]:
    rows = (
        LedgerEntry.objects.filter(**source)
        .values("currency")
        .annotate(net=Sum("net_amount"), vat=Sum("vat_amount"))
    )
    return {
        row["currency"]: (row["net"] or ZERO, row["vat"] or ZERO)
        for row in rows
        if (row["net"] or ZERO) + (row["vat"] or ZERO) != 0
    }


def assert_ledger_invariants(*, all_documents: bool = False) -> None:
    """Defterde kaydı olan (eşitlenmiş) her sevkiyatın ve mal kabulün matrah ve KDV toplamı
    belgenin bugünkü tutarına eşittir; her kaydın brüt tutarı (borç ya da alacak) matrah + KDV'dir;
    ters kayıt asıl kaydın tersidir. `all_documents`: sevk edilmiş her sevkiyat ve kaydedilmiş her
    mal kabul eşitlenmiş olmalıdır (olaylar çalıştırılmış ya da `sync_all` yapılmış testte)."""
    shipments = Shipment.objects.filter(status=Shipment.Status.DISPATCHED)
    receipts = GoodsReceipt.objects.filter(status=GoodsReceipt.Status.POSTED)
    if not all_documents:
        shipments = shipments.filter(pk__in=LedgerEntry.objects.values("shipment"))
        receipts = receipts.filter(pk__in=LedgerEntry.objects.values("goods_receipt"))
    for shipment in shipments:
        expected = {
            currency: (amount.net, amount.vat)
            for currency, amount in shipment_amount(shipment).by_currency.items()
            if amount.gross != 0
        }
        assert _posted(shipment=shipment) == expected, shipment.number
    for receipt in receipts:
        expected = {
            currency: (amount.net, amount.vat)
            for currency, amount in receipt_amount(receipt).by_currency.items()
            if amount.gross != 0
        }
        assert _posted(goods_receipt=receipt) == expected, receipt.number
    for entry in LedgerEntry.objects.select_related("reversal_of"):
        assert (entry.debit == 0) != (entry.credit == 0), entry.number
        if entry.net_amount is not None:
            signed = entry.debit - entry.credit
            if entry.kind == LedgerEntry.Kind.PURCHASE:
                signed = -signed
            assert signed == entry.net_amount + (entry.vat_amount or ZERO), entry.number
        if entry.reversal_of is not None:
            original = entry.reversal_of
            assert (entry.debit, entry.credit) == (original.credit, original.debit)
            assert entry.currency == original.currency
            assert entry.side == original.side
