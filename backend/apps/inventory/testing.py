"""Stok değişmezleri için ortak test yardımcısı (CLAUDE.md §7).

Stoka dokunan her test sonunda `assert_stock_invariants()` çağırır; üretim, dolum ve sevkiyat
modüllerinin testleri de bunu kullanır.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import F, Sum

from apps.inventory.models import LotLink, StockBalance, StockMovement


def assert_stock_invariants() -> None:
    """Kural 1-3'ü doğrular:

    1. Her (malzeme, lot, lokasyon) için `StockBalance` = hareketlerin toplamı; hareketi olmayan
       bakiye satırı sıfırdır.
    2. Hiçbir bakiye negatif değildir.
    3. Her hareketin ve bakiyenin malzemesi lotun malzemesidir; soy ağacı bağları pozitif
       miktarlıdır ve lot kendisine bağlanmaz. Her ters kayıt, geri aldığı hareketin tam tersidir.
    """
    sums: dict[tuple[int, int, int], Decimal] = defaultdict(Decimal)
    for row in StockMovement.objects.values("material_id", "lot_id", "location_id").annotate(
        total=Sum("quantity")
    ):
        sums[(row["material_id"], row["lot_id"], row["location_id"])] = row["total"]

    balances = {
        (b.material_id, b.lot_id, b.location_id): b.quantity for b in StockBalance.objects.all()
    }
    for key, total in sums.items():
        assert balances.get(key, Decimal(0)) == total, (
            f"Bakiye hareket toplamına eşit değil (malzeme, lot, lokasyon)={key}: "
            f"bakiye={balances.get(key)}, hareketler={total}"
        )
    for key, quantity in balances.items():
        assert quantity >= 0, f"Negatif bakiye {key}: {quantity}"
        if key not in sums:
            assert quantity == 0, f"Hareketi olmayan bakiye {key}: {quantity}"

    mismatched = StockMovement.objects.exclude(material_id=F("lot__material_id")).count()
    assert mismatched == 0, f"Lotun malzemesinden farklı malzemeli {mismatched} hareket var."
    mismatched_balances = StockBalance.objects.exclude(material_id=F("lot__material_id")).count()
    assert mismatched_balances == 0, "Lotun malzemesinden farklı malzemeli bakiye var."

    for link in LotLink.objects.all():
        assert link.quantity > 0, f"Soy ağacı bağı pozitif değil: {link}"
        assert link.parent_lot_id != link.child_lot_id, f"Lot kendisine bağlı: {link}"

    for reversal in StockMovement.objects.filter(reversal_of__isnull=False).select_related(
        "reversal_of"
    ):
        original = reversal.reversal_of
        assert original is not None
        assert reversal.quantity == -original.quantity, f"Ters kayıt tutarsız: {reversal.pk}"
        assert (reversal.lot_id, reversal.location_id) == (
            original.lot_id,
            original.location_id,
        ), f"Ters kayıt farklı lot/lokasyonda: {reversal.pk}"
