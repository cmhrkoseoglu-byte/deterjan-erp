from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.inventory import selectors, services
from apps.inventory.models import Lot, StockMovement
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.tests.factories import BulkMaterialFactory, MaterialFactory, unit

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal


def test_available_lots_fefo_excludes_unusable(depo, lab):
    material = MaterialFactory()
    today = timezone.localdate()
    a, b = storage_location(code="A-01"), storage_location(code="B-01")
    late = stocked_lot("10", material=material, location=a, expiry_date=today + timedelta(days=90))
    soon = stocked_lot("10", material=material, location=b, expiry_date=today + timedelta(days=5))
    no_expiry = stocked_lot("10", material=material, location=a)
    stocked_lot("10", material=material, status=Lot.Status.QUARANTINE)
    stocked_lot("10", material=material, expiry_date=today - timedelta(days=1))
    blocked = stocked_lot("10", material=material)
    services.block_lot(lab, blocked, "şüpheli")
    empty = stocked_lot("10", material=material, location=a)
    services.post_movement(depo, material, empty, a, D("-10"), StockMovement.Type.SCRAP, None)
    stocked_lot("10")  # başka malzeme

    rows = list(selectors.available_lots(material))
    assert [row.lot for row in rows] == [soon, late, no_expiry]
    assert {row.lot for row in selectors.available_lots(material, fefo=False)} == {
        soon,
        late,
        no_expiry,
    }


def test_stock_by_material_and_location():
    material = MaterialFactory()
    loc = storage_location()
    lot = stocked_lot("7", material=material, location=loc)
    stocked_lot("3", material=material)
    assert sum(row.quantity for row in selectors.stock_by_material(material)) == D("10")
    assert [row.lot for row in selectors.stock_by_location(loc)] == [lot]


def _batch(actor, inputs, material=None):
    """Girdi lotlardan (lot, miktar) yeni bir çıktı lot üretir (üretim adımının yaptığı gibi)."""
    child = services.create_lot(
        actor, material=material or BulkMaterialFactory(), source=Lot.Source.PRODUCTION
    )
    for parent, quantity in inputs:
        services.link_lots(actor, parent, child, D(quantity))
    return child


def test_lot_trace_backward_and_forward(depo):
    las = stocked_lot("100")
    water = stocked_lot("1000")
    salt = stocked_lot("50")
    premix = _batch(depo, [(las, "20"), (water, "100")])
    # Su iki aşamada eklenir: aynı girdi-çıktı çiftinin bağları toplanır.
    bulk = _batch(depo, [(premix, "120"), (water, "300"), (water, "200"), (salt, "5")])
    other = _batch(depo, [(las, "30")])

    tree = selectors.lot_trace_backward(bulk)
    assert tree["lot_no"] == bulk.lot_no and tree["quantity"] is None
    children = {child["lot_no"]: child for child in tree["children"]}
    assert set(children) == {premix.lot_no, water.lot_no, salt.lot_no}
    assert children[water.lot_no]["quantity"] == D("500")
    grand = {c["lot_no"]: c["quantity"] for c in children[premix.lot_no]["children"]}
    assert grand == {las.lot_no: D("20"), water.lot_no: D("100")}

    forward = selectors.lot_trace_forward(las)
    first = {child["lot_no"]: child for child in forward["children"]}
    assert set(first) == {premix.lot_no, other.lot_no}
    assert [c["lot_no"] for c in first[premix.lot_no]["children"]] == [bulk.lot_no]
    assert selectors.lot_trace_forward(bulk)["children"] == []
    with pytest.raises(ValueError):
        selectors.lot_trace(bulk, "sideways")  # type: ignore[arg-type]


def test_lot_trace_quantity_unit_is_input_lot_unit(depo):
    """İleri izlemede dökmeden mamule geçen miktar, mamulün birimiyle (ADET) değil dökmenin
    birimiyle (KG) gösterilir; geri izlemede de girdinin birimi kullanılır."""
    bulk = stocked_lot("500", material=BulkMaterialFactory())
    finished = _batch(depo, [(bulk, "250")], material=MaterialFactory(base_unit=unit("ADET")))

    forward = selectors.lot_trace_forward(bulk)
    assert forward["quantity_unit"] is None
    [child] = forward["children"]
    assert child["lot_no"] == finished.lot_no
    assert (child["quantity"], child["quantity_unit"], child["unit"]) == (D("250"), "KG", "ADET")

    backward = selectors.lot_trace_backward(finished)
    [parent] = backward["children"]
    assert (parent["quantity"], parent["quantity_unit"], parent["unit"]) == (D("250"), "KG", "KG")


def test_expiring_lots():
    today = timezone.localdate()
    soon = stocked_lot("1", expiry_date=today + timedelta(days=30))
    expired = stocked_lot("1", expiry_date=today - timedelta(days=2))
    stocked_lot("1", expiry_date=today + timedelta(days=31))
    stocked_lot("1")
    services.create_lot(
        None, material=MaterialFactory(), source=Lot.Source.PURCHASE, expiry_date=today
    )  # stoksuz
    assert list(selectors.expiring_lots(30)) == [expired, soon]


def test_below_min_stock(lab):
    low = MaterialFactory(code="A-LOW", min_stock=D("100"))
    stocked_lot("60", material=low)
    blocked = stocked_lot("50", material=low)
    services.block_lot(lab, blocked, "şüpheli")  # bloke stok sayılmaz
    ok = MaterialFactory(code="B-OK", min_stock=D("100"))
    stocked_lot("80", material=ok)
    stocked_lot("20", material=ok, status=Lot.Status.QUARANTINE)  # gelen stok sayılır
    MaterialFactory(code="C-NONE", min_stock=D("5"))  # hiç stok yok
    MaterialFactory(code="D-NOMIN")
    MaterialFactory(code="E-INACTIVE", min_stock=D("5"), is_active=False)
    result = list(selectors.below_min_stock())
    assert [m.code for m in result] == ["A-LOW", "C-NONE"]
    assert result[0].stock_quantity == D("60")


def test_daily_check_publishes_stock_events(published, commit, make_user):
    from apps.workflow.models import Notification

    depo_user = make_user("depo")
    today = timezone.localdate()
    lot = stocked_lot("1", expiry_date=today + timedelta(days=3))
    low = MaterialFactory(min_stock=D("10"))
    with commit():
        events.publish(ev.DAILY_CHECK, {})
    [expiring] = [e for e in published if e.name == ev.LOTS_EXPIRING]
    assert expiring.payload["days"] == 30
    assert expiring.payload["lots"] == [
        {
            "model": "inventory.lot",
            "id": lot.pk,
            "lot_no": lot.lot_no,
            "material_code": lot.material.code,
            "material_name": lot.material.name,
            "expiry_date": f"{lot.expiry_date:%d.%m.%Y}",
        }
    ]
    [below] = [e for e in published if e.name == ev.BELOW_MIN_STOCK]
    assert below.payload["materials"] == [
        {
            "model": "masterdata.material",
            "id": low.pk,
            "code": low.code,
            "name": low.name,
            "quantity": "0",
            "min_stock": "10",
            "unit": "KG",
        }
    ]
    titles = set(Notification.objects.filter(recipient=depo_user).values_list("title", flat=True))
    assert titles == {"SKT'si 30 gün içinde dolacak lotlar", "Minimum stok altındaki malzemeler"}
