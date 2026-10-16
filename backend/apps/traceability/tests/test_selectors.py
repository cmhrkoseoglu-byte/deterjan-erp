import time
from decimal import Decimal

import pytest

from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockMovement
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.models import Material
from apps.masterdata.tests.factories import BulkMaterialFactory, MaterialFactory, SupplierFactory
from apps.returns.tests.factories import finished_product
from apps.traceability import selectors
from apps.traceability.tests.perfdata import build_trace_data

D = Decimal
T = StockMovement.Type

pytestmark = pytest.mark.usefixtures("invariants")


def produce(parents: list[tuple[Lot, str]], material: Material, source: str, qty: str) -> Lot:
    """Girdi lotlardan tüketip yeni lot üretir (servislerle; soy ağacı bağlarıyla)."""
    location = storage_location()
    lot = inventory.create_lot(None, material=material, source=source, status=Lot.Status.RELEASED)
    for parent, used in parents:
        place = parent.balances.filter(quantity__gt=0).first().location  # type: ignore[union-attr]
        inventory.post_movement(
            None, parent.material, parent, place, -D(used), T.ISSUE_PRODUCTION, None
        )
        inventory.link_lots(None, parent, lot, D(used))
    inventory.post_movement(None, lot.material, lot, location, D(qty), T.PRODUCTION_OUTPUT, None)
    return lot


@pytest.fixture
def chain(db: None) -> dict[str, Lot]:
    """Hammadde A, B → bulk → iki mamul lotu; mamul 1'den 30 adet sevk, 5 adet iade."""
    supplier = SupplierFactory.create(name="Kimya A.Ş.")
    raw_a = stocked_lot("500", material=MaterialFactory.create(code="HM-A"))
    raw_a.supplier = supplier
    raw_a.supplier_lot_no = "TL-77"
    raw_a.save()
    raw_b = stocked_lot("500", material=MaterialFactory.create(code="HM-B"))
    bulk = produce(
        [(raw_a, "100"), (raw_b, "50")], BulkMaterialFactory.create(), "PRODUCTION", "150"
    )
    product = finished_product(code="MM-1")
    fin1 = produce([(bulk, "60")], product, "FILLING", "80")
    fin2 = produce([(bulk, "40")], product, "FILLING", "50")
    store = fin1.balances.get().location
    inventory.post_movement(None, product, fin1, store, D(-30), T.SHIPMENT, None)
    inventory.post_movement(None, product, fin1, storage_location(), D(5), T.RETURN, None)
    return {"raw_a": raw_a, "raw_b": raw_b, "bulk": bulk, "fin1": fin1, "fin2": fin2}


def find(node: dict, lot: Lot) -> dict:
    if node["id"] == lot.pk:
        return node
    for child in node["children"]:
        found = find(child, lot)
        if found:
            return found
    return {}


def test_backward_trace_reaches_supplier(chain: dict[str, Lot]) -> None:
    tree = selectors.backward_trace(chain["fin1"])
    raw = find(tree, chain["raw_a"])
    assert raw["supplier_name"] == "Kimya A.Ş."
    assert raw["supplier_lot_no"] == "TL-77"
    assert find(tree, chain["bulk"])["quantity"] == D(60)
    assert find(tree, chain["raw_b"])["quantity"] == D(50)


def test_backward_trace_shows_goods_receipt(db: None, make_user: object) -> None:
    supplier = SupplierFactory.create()
    material = MaterialFactory.create(requires_incoming_qc=False)
    receipt = inventory.create_goods_receipt(
        None,
        {
            "supplier": supplier,
            "receipt_date": "2026-10-16",
            "storage_location": storage_location(),
        },
        [
            {
                "material": material,
                "quantity": D(10),
                "unit": material.base_unit,
                "supplier_lot_no": "X1",
            }
        ],
    )
    inventory.post_goods_receipt(None, receipt)
    lot = receipt.lines.get().created_lot
    assert lot is not None
    child = produce([(lot, "5")], BulkMaterialFactory.create(), "PRODUCTION", "5")
    node = find(selectors.backward_trace(child), lot)
    assert node["receipt_number"] == receipt.number
    assert node["supplier_lot_no"] == "X1"


def test_forward_trace_quantities(chain: dict[str, Lot]) -> None:
    tree = selectors.forward_trace(chain["raw_a"])
    fin1 = find(tree, chain["fin1"])
    assert fin1["on_hand"] == D(55)
    assert fin1["shipped"] == D(30)
    assert fin1["returned"] == D(5)
    assert [row["quantity"] for row in fin1["shipments"]] == [D(30)]
    assert find(tree, chain["fin2"])["on_hand"] == D(50)
    assert find(tree, chain["bulk"])["on_hand"] == D(50)


def test_shipment_reversal_is_netted(chain: dict[str, Lot]) -> None:
    movement = StockMovement.objects.get(lot=chain["fin1"], movement_type=T.SHIPMENT)
    inventory.reverse_movement(None, movement, "Yanlış sevk")
    assert selectors.shipped_by_lot([chain["fin1"].pk]) == {}
    assert selectors.shipment_rows([chain["fin1"].pk]) == []


def test_recall_simulation(chain: dict[str, Lot]) -> None:
    result = selectors.recall_simulation([chain["raw_b"]])
    lots = {row["lot_no"]: row for row in result["lots"]}
    assert set(lots) == {chain[k].lot_no for k in ("raw_b", "bulk", "fin1", "fin2")}
    assert lots[chain["raw_b"].lot_no]["is_selected"]
    assert not lots[chain["fin1"].lot_no]["is_selected"]
    assert result["summary"]["finished_lot_count"] == 2
    assert result["summary"]["shipped_lot_count"] == 1
    stock = {(r["lot_no"], r["location_code"]): r["quantity"] for r in result["stock"]}
    assert sum(q for (lot_no, _), q in stock.items() if lot_no == chain["fin1"].lot_no) == D(55)
    assert [r["quantity"] for r in result["shipments"]] == [D(30)]
    assert result["customers"][0]["quantity"] == D(30)
    assert result["customers"][0]["lots"] == [chain["fin1"].lot_no]


def test_recall_of_unrelated_lot_is_only_itself(chain: dict[str, Lot]) -> None:
    result = selectors.recall_simulation([chain["fin2"]])
    assert [r["lot_no"] for r in result["lots"]] == [chain["fin2"].lot_no]
    assert result["shipments"] == []


def test_recall_performance_on_deep_wide_data(db: None) -> None:
    data = build_trace_data()
    assert data.movement_count >= 10_000
    start = time.perf_counter()
    result = selectors.recall_simulation([data.suspect])
    elapsed = time.perf_counter() - start
    assert result["summary"]["lot_count"] == 1 + 300 + 1000
    assert result["summary"]["finished_lot_count"] == 1000
    assert sum(r["quantity"] for r in result["shipments"]) == D(80_000)
    assert result["summary"]["shipment_count"] == 400
    print(f"Geri çağırma simülasyonu: {elapsed:.3f} sn, {data.movement_count} hareket")
    assert elapsed < 1.0, f"Geri çağırma simülasyonu {elapsed:.2f} sn sürdü"
    start = time.perf_counter()
    tree = selectors.backward_trace(data.finished_lot)
    assert time.perf_counter() - start < 1.0
    # Mamul → bulk-3 → bulk-2 → bulk-1 → hammadde: 5 seviye.
    depth, node = 1, tree
    while node["children"]:
        node = node["children"][0]
        depth += 1
    assert depth == 5
