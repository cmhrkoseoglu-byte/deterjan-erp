"""Performans testi için derin ve geniş izlenebilirlik verisi (≥ 5 seviye, ≥ 10.000 hareket).

Zincir: hammadde (200 lot) → bulk-1 (100 şarj, her biri 10 hammadde lotu) → bulk-2 (100 harman,
her biri 2 bulk-1) → bulk-3 (100 düzeltme, 1:1) → mamul (1.000 dolum lotu, her bulk-3'ten 10)
→ mamul deposuna transfer → sevkiyat (mamul lotu başına 4 sevkiyat) ve iade. Şüpheli hammadde
lotu bütün bulk-1 şarjlarına girer; ileri soyu zincirin tamamıdır (en kötü durum).

Hız için kayıtlar `bulk_create` ile yazılır; hareket ve bakiyeler birbirine tutarlıdır ve test
sonunda `assert_stock_invariants()` ile doğrulanır.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db import connection

from apps.inventory.models import Lot, LotLink, StockBalance, StockMovement
from apps.inventory.tests.factories import quarantine_location, storage_location
from apps.masterdata.models import Location, Material
from apps.masterdata.tests.factories import BulkMaterialFactory, MaterialFactory, unit

D = Decimal
T = StockMovement.Type


@dataclass
class TraceData:
    suspect: Lot
    finished_lot: Lot
    movement_count: int
    lot_count: int


class _Ledger:
    def __init__(self) -> None:
        self.movements: list[StockMovement] = []
        self.balances: dict[tuple[int, int, int], Decimal] = defaultdict(Decimal)

    def add(self, lot: Lot, location: Location, quantity: Decimal, kind: str, doc: str) -> None:
        self.movements.append(
            StockMovement(
                movement_type=kind,
                material_id=lot.material_id,
                lot=lot,
                location=location,
                quantity=quantity,
                document_number=doc,
            )
        )
        self.balances[(lot.material_id, lot.pk, location.pk)] += quantity

    def save(self) -> None:
        StockMovement.objects.bulk_create(self.movements, batch_size=2000)
        StockBalance.objects.bulk_create(
            [
                StockBalance(material_id=m, lot_id=lot, location_id=loc, quantity=q)
                for (m, lot, loc), q in self.balances.items()
            ],
            batch_size=2000,
        )


def _lots(material: Material, prefix: str, count: int, source: str) -> list[Lot]:
    return Lot.objects.bulk_create(
        [
            Lot(
                lot_no=f"{prefix}-{i:05d}",
                material=material,
                source=source,
                status=Lot.Status.RELEASED,
            )
            for i in range(count)
        ],
        batch_size=2000,
    )


def build_trace_data() -> TraceData:
    store = storage_location(code="PERF-DEPO")
    tank = storage_location(code="PERF-TANK")
    line = storage_location(code="PERF-HAT")
    finished_store = storage_location(code="PERF-MAMUL")
    returns = quarantine_location(code="PERF-IADE")
    raw = MaterialFactory.create(code="PERF-HM")
    bulks = [BulkMaterialFactory.create(code=f"PERF-YM{i}") for i in range(3)]
    finished = MaterialFactory.create(
        code="PERF-MM", material_type=Material.Type.FINISHED, base_unit=unit("ADET")
    )
    ledger = _Ledger()
    links: list[LotLink] = []

    def consume(parent: Lot, child: Lot, qty: Decimal, location: Location) -> None:
        ledger.add(parent, location, -qty, T.ISSUE_PRODUCTION, child.lot_no)
        links.append(LotLink(parent_lot=parent, child_lot=child, quantity=qty))

    raw_lots = _lots(raw, "PH", 200, Lot.Source.PURCHASE)
    for lot in raw_lots:
        ledger.add(lot, store, D(1000), T.RECEIPT, "MK")
    level1 = _lots(bulks[0], "PB1", 100, Lot.Source.PRODUCTION)
    for i, lot in enumerate(level1):
        inputs = [raw_lots[0]] + [raw_lots[1 + (i * 9 + k) % 199] for k in range(9)]
        for parent in inputs:
            consume(parent, lot, D(5), store)
        ledger.add(lot, tank, D(50), T.PRODUCTION_OUTPUT, lot.lot_no)
    level2 = _lots(bulks[1], "PB2", 100, Lot.Source.PRODUCTION)
    for i, lot in enumerate(level2):
        for parent in (level1[i], level1[(i + 1) % 100]):
            consume(parent, lot, D(10), tank)
        ledger.add(lot, tank, D(20), T.PRODUCTION_OUTPUT, lot.lot_no)
    level3 = _lots(bulks[2], "PB3", 100, Lot.Source.PRODUCTION)
    for i, lot in enumerate(level3):
        consume(level2[i], lot, D(20), tank)
        ledger.add(lot, tank, D(20), T.PRODUCTION_OUTPUT, lot.lot_no)
    level4 = _lots(finished, "PD", 1000, Lot.Source.FILLING)
    for i, lot in enumerate(level4):
        consume(level3[i // 10], lot, D(2), tank)
        ledger.add(lot, line, D(100), T.PRODUCTION_OUTPUT, lot.lot_no)
        ledger.add(lot, line, D(-100), T.TRANSFER_OUT, lot.lot_no)
        ledger.add(lot, finished_store, D(100), T.TRANSFER_IN, lot.lot_no)
        for k in range(4):
            ledger.add(lot, finished_store, D(-20), T.SHIPMENT, f"SV-PERF-{(i * 4 + k) // 10:05d}")
        if i % 4 == 0:
            ledger.add(lot, returns, D(5), T.RETURN, f"IA-PERF-{i:05d}")
    LotLink.objects.bulk_create(links, batch_size=2000)
    ledger.save()
    # Canlı veritabanında olduğu gibi tablo istatistikleri güncel olsun.
    with connection.cursor() as cursor:
        cursor.execute(
            "ANALYZE inventory_lot, inventory_lotlink, inventory_stockmovement, "
            "inventory_stockbalance"
        )
    return TraceData(
        suspect=raw_lots[0],
        finished_lot=level4[0],
        movement_count=len(ledger.movements),
        lot_count=len(raw_lots) + 300 + len(level4),
    )
