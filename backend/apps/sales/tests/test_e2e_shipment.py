"""Uçtan uca satış ve sevkiyat akışı (Faz 3 kabul testi).

Mal kabul → giriş kontrolü → üretim şarjı → bulk lot serbest → dolum → mamul lot serbest →
satış siparişi → FEFO rezervasyonu (rezerve stok ikinci siparişe verilmez) → sevkiyat planı →
lot okutarak toplama (karantinadaki lot okutulamaz) → yükleme → sevk → irsaliye PDF → ileri
izlemede doğru müşteri ve miktar, geri izlemede tedarikçi → geri çağırma simülasyonu → sevkiyata
bağlı iade ve QC kararıyla yeniden sevke uygun. Her adımda görevler, bildirimler ve stok
değişmezleri doğrulanır.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.core.roles import DEPO, DOLUM, LABORATUVAR, PLANLAMA, SEVKIYAT, URETIM, YONETIM
from apps.filling import services as filling
from apps.filling.tests.factories import build_line
from apps.filling.tests.factories import order_data as filling_order_data
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockMovement
from apps.inventory.services import current_balance
from apps.inventory.testing import assert_stock_invariants
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.models import Location, MaterialUnitConversion
from apps.masterdata.tests.factories import CustomerFactory, LocationFactory, SupplierFactory, unit
from apps.production import services as production
from apps.production.tests.factories import build_plant
from apps.production.tests.factories import order_data as production_order_data
from apps.quality.testing import open_sample_for, pass_sample
from apps.returns import services as returns
from apps.returns.models import CustomerReturnLine
from apps.sales import services as sales
from apps.sales.models import SalesOrder, Shipment
from apps.sales.waybill import waybill_pdf
from apps.traceability import selectors as traceability
from apps.workflow.models import Notification, Task

D = Decimal


@pytest.fixture
def staff(make_user):
    return {
        role: make_user(role, username=role)
        for role in (DEPO, URETIM, LABORATUVAR, PLANLAMA, YONETIM, DOLUM, SEVKIYAT)
    }


def task_for(rule_code, subject):
    return Task.objects.get(rule_code=rule_code, related_object_id=subject.pk)


def titles(user):
    return set(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def released_finished_lot(staff, commit):
    """Mal kabulden serbest mamul lotuna (Faz 1 ve Faz 2 akışları, kısaltılmış)."""
    plant = build_plant(staff[PLANLAMA], stock=False)
    supplier = SupplierFactory.create(name="Kimya Tedarik A.Ş.")
    kg = unit("KG")
    receipt = inventory.create_goods_receipt(
        staff[DEPO],
        {
            "supplier": supplier,
            "receipt_date": date.today(),
            "delivery_note_no": "IRS-77",
            "quarantine_location": plant.quarantine,
            "storage_location": plant.storage,
        },
        [
            {"material": plant.las, "quantity": D("2000"), "unit": kg, "supplier_lot_no": "TL-1"},
            {"material": plant.sles, "quantity": D("1000"), "unit": kg},
            {"material": plant.water, "quantity": D("5000"), "unit": kg},
        ],
    )
    with commit():
        inventory.post_goods_receipt(staff[DEPO], receipt)
    lots = {line.material.code: line.created_lot for line in receipt.lines.all()}
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(lots["LAS"], "INCOMING"))
        pass_sample(staff[LABORATUVAR], open_sample_for(lots["SLES"], "INCOMING"))

    with commit():
        order = production.create_order(staff[PLANLAMA], production_order_data(plant, "1000"))
        production.approve_order(staff[PLANLAMA], order)
        for material in (plant.las, plant.sles):
            row = plant.requirement(order, material)
            production.pick_material(
                staff[DEPO], order, row, lots[material.code], row.required_quantity
            )
        production.mark_material_ready(staff[DEPO], order)
        batch = production.start_batch(staff[URETIM], order)
    for row in order.requirements.order_by("sequence"):
        lot = lots["SU" if row.is_water else row.material.code]
        production.record_consumption(
            staff[URETIM], batch, row, lot, production.batch_line_quantity(row, batch)
        )
    with commit():
        production.finish_batch(staff[URETIM], batch, D("1000"))
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(batch.output_lot, "FINAL"))
    bulk = batch.output_lot
    bulk.refresh_from_db()
    assert bulk.status == Lot.Status.RELEASED

    line = build_line(staff[PLANLAMA], bulk=plant.product, warehouse=plant.warehouse)
    with commit():
        fill = filling.create_order(staff[PLANLAMA], filling_order_data(line, 1000))
        filling.approve_order(staff[PLANLAMA], fill)
        for row in fill.requirements.select_related("material"):
            key = {"SISE-750": "bottle", "KAPAK-28": "cap", "ETIKET-750": "label"}.get(
                row.material.code, "case"
            )
            filling.pick_packaging(staff[DEPO], fill, row, line.lots[key], row.required_quantity)
        filling.mark_material_ready(staff[DEPO], fill)
        run = filling.start_run(staff[DOLUM], fill)
        filling.consume_bulk(staff[DOLUM], run, bulk, D("780"))
    with commit():
        filling.finish_run(staff[DOLUM], run, 1000)
        filling.finish_filling(staff[DOLUM], fill)
    finished = run.output_lot
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(finished, "FINAL"))
    finished.refresh_from_db()
    assert finished.status == Lot.Status.RELEASED
    assert current_balance(finished, line.finished_store) == D("1000")
    assert_stock_invariants()
    return plant, line, lots, finished, supplier


def test_goods_receipt_to_shipment_waybill_trace_and_return(staff, commit):
    plant, line, raw_lots, finished, supplier = released_finished_lot(staff, commit)
    product = line.finished
    if not MaterialUnitConversion.objects.filter(material=product, unit=unit("KOLI")).exists():
        MaterialUnitConversion.objects.create(
            material=product, unit=unit("KOLI"), factor_to_base=12
        )
    dock = LocationFactory.create(
        warehouse=plant.warehouse, code="SEVK", location_type=Location.Type.SHIPPING
    )
    market = CustomerFactory.create(
        code="ZM-01", name="Zincir Market A.Ş.", min_remaining_shelf_life_days=180
    )
    other = CustomerFactory.create(code="TB-02", name="Toptancı B")

    # 1. Sipariş onayı → FEFO ile tüm miktar rezerve, sevkiyata "Sevkiyat planla".
    with commit():
        order = sales.create_order(
            staff[SEVKIYAT],
            {"customer": market, "order_date": date.today(), "customer_po_no": "PO-9"},
            [{"product": product, "quantity": D("50"), "unit": unit("KOLI")}],
        )
        sales.confirm_order(staff[SEVKIYAT], order)
    order_line = order.lines.get()
    assert sales.reserved_quantity(order_line) == D("600")
    plan_task = task_for("plan_shipment", order)
    assert plan_task.status == Task.Status.OPEN

    # 2. İkinci sipariş rezerve stoğu alamaz: yalnızca kalan 400 adet, eksik planlamaya görev.
    with commit():
        second = sales.create_order(
            staff[SEVKIYAT],
            {"customer": other, "order_date": date.today()},
            [{"product": product, "quantity": D("450"), "unit": unit("ADET")}],
        )
        sales.confirm_order(staff[SEVKIYAT], second)
    assert sales.reserved_quantity(second.lines.get()) == D("400")
    assert task_for("sales_shortage", second).status == Task.Status.OPEN

    # 3. Sevkiyat planı → "Sevkiyat planla" kapanır, depoya "Toplama yap".
    with commit():
        shipment = sales.plan_shipment(
            staff[SEVKIYAT],
            order,
            {
                "planned_date": date.today(),
                "vehicle_plate": "41 ABC 41",
                "driver_name": "Mehmet Yılmaz",
                "driver_id_no": "12345678901",
            },
        )
    assert shipment.loading_location == dock
    assert task_for("plan_shipment", order).status == Task.Status.DONE
    assert f"Yeni görev: Toplama yap: {shipment.number}" in titles(staff[DEPO])

    # 4. Karantinadaki lot okutulamaz; serbest lot okutulur ve sevk alanına taşınır.
    quarantined = stocked_lot(
        "100",
        material=product,
        location=line.finished_store,
        status=Lot.Status.QUARANTINE,
        source=Lot.Source.FILLING,
    )
    with pytest.raises(BusinessRuleError, match="lot_not_released"):
        sales.pick_lot(staff[DEPO], shipment, quarantined, reason="deneme")
    with commit():
        sales.pick_lot(staff[DEPO], shipment, finished)
        sales.mark_loaded(staff[DEPO], shipment)
    assert current_balance(finished, dock) == D("600")
    assert current_balance(finished, line.finished_store) == D("400")
    assert task_for("pick_shipment", shipment).status == Task.Status.DONE
    assert task_for("dispatch_shipment", shipment).status == Task.Status.OPEN
    assert_stock_invariants()

    # 5. Sevk onayı → SHIPMENT hareketi, sipariş sevk edildi, siparişi açana ve yönetime bildirim.
    with commit():
        sales.dispatch_shipment(staff[SEVKIYAT], shipment)
    shipment.refresh_from_db()
    order.refresh_from_db()
    assert shipment.status == Shipment.Status.DISPATCHED
    assert order.status == SalesOrder.Status.SHIPPED
    movement = StockMovement.objects.get(movement_type=StockMovement.Type.SHIPMENT)
    assert (movement.lot, movement.location, movement.quantity) == (finished, dock, D("-600"))
    assert task_for("dispatch_shipment", shipment).status == Task.Status.DONE
    assert f"Sevk edildi: {shipment.number}" in titles(staff[YONETIM])
    assert_stock_invariants()

    # 6. İrsaliye PDF'i.
    pdf = waybill_pdf(shipment)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000

    # 7. İleri izleme: hammadde lotundan müşteriye; geri izleme tedarikçiye iner.
    forward = traceability.forward_trace(raw_lots["LAS"])
    shipments = [row for node in traceability._walk(forward) for row in node.get("shipments", [])]
    assert [(r["customer_code"], r["quantity"], r["document_number"]) for r in shipments] == [
        ("ZM-01", D("600"), shipment.number)
    ]
    backward = traceability.backward_trace(finished)
    las_nodes = [
        node for node in traceability._walk(backward) if node["lot_no"] == raw_lots["LAS"].lot_no
    ]
    assert las_nodes[0]["supplier_name"] == supplier.name
    assert las_nodes[0]["supplier_lot_no"] == "TL-1"
    recall = traceability.recall_simulation([raw_lots["LAS"]])
    assert [(c["customer_name"], c["quantity"]) for c in recall["customers"]] == [
        ("Zincir Market A.Ş.", D("600"))
    ]

    # 8. Sevkiyata bağlı iade: sevk edilenden fazlası alınmaz; kabulde karantina ve iade
    #    numunesi; QC serbest kararıyla yeniden sevke uygun.
    quarantine = plant.quarantine
    header = {
        "customer": market,
        "shipment": shipment,
        "return_date": date.today(),
        "reason": "Hasarlı koli",
        "quarantine_location": quarantine,
    }
    with pytest.raises(BusinessRuleError, match="return_exceeds_shipped"):
        returns.create_return(
            staff[SEVKIYAT],
            header,
            [{"product": product, "lot": finished, "quantity": D("51"), "unit": unit("KOLI")}],
        )
    with commit():
        document = returns.create_return(
            staff[SEVKIYAT],
            header,
            [{"product": product, "lot": finished, "quantity": D("1"), "unit": unit("KOLI")}],
        )
        returns.receive_return(staff[DEPO], document)
    assert current_balance(finished, quarantine) == D("12")
    with commit():
        pass_sample(
            staff[LABORATUVAR],
            open_sample_for(finished, "RETURN"),
            release_location=line.finished_store,
        )
    assert document.lines.get().disposition == CustomerReturnLine.Disposition.RESTOCK
    assert traceability.returned_by_lot([finished.pk]) == {finished.pk: D("12")}
    assert_stock_invariants()
