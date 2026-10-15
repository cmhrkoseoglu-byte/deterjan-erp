"""Uçtan uca üretim akışı (Faz 1, Adım 1.8).

Mal kabul → lot serbest bırak → üretim emri → onay → malzeme hazırlama → şarj + tartım (biri
tolerans dışı) → şarj bitir → bulk lot serbest bırak → emir tamam. Her adımda doğru görevin açılıp
kapandığı, doğru bildirimin gittiği, stok değişmezlerinin sağlandığı ve soy ağacının doğru olduğu
kontrol edilir. İkinci senaryo: tank kapasitesini aşan emir iki şarja bölünür (Karar D-4).
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA, SATIN_ALMA, URETIM, YONETIM
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory
from apps.inventory.models import Lot
from apps.inventory.services import current_balance
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.tests.factories import SupplierFactory, unit
from apps.production import services
from apps.production.models import ProductionOrder
from apps.production.tests.factories import build_plant, order_data
from apps.workflow.models import Notification, Task

D = Decimal
Status = ProductionOrder.Status


@pytest.fixture
def staff(make_user):
    return {
        role: make_user(role, username=role)
        for role in (DEPO, URETIM, LABORATUVAR, PLANLAMA, YONETIM, SATIN_ALMA)
    }


def task_for(rule_code, subject):
    return Task.objects.get(rule_code=rule_code, related_object_id=subject.pk)


def titles(user):
    return set(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def check():
    assert_stock_invariants()


def receive(staff, plant, commit):
    """Mal kabul: LAS ve SLES giriş kontrollü (karantina), su kontrolsüz (serbest)."""
    kg = unit("KG")
    receipt = inventory.create_goods_receipt(
        staff[DEPO],
        {
            "supplier": SupplierFactory.create(),
            "receipt_date": date.today(),
            "delivery_note_no": "IRS-1",
            "quarantine_location": plant.quarantine,
            "storage_location": plant.storage,
        },
        [
            {"material": plant.las, "quantity": D("2000"), "unit": kg},
            {"material": plant.sles, "quantity": D("1000"), "unit": kg},
            {"material": plant.water, "quantity": D("5000"), "unit": kg},
        ],
    )
    with commit():
        inventory.post_goods_receipt(staff[DEPO], receipt)
    lines = {line.material.code: line for line in receipt.lines.select_related("created_lot")}
    return {code: line.created_lot for code, line in lines.items()}


def test_goods_receipt_to_completed_order(staff, commit):
    plant = build_plant(staff[PLANLAMA], stock=False)

    # 1. Mal kabul → laboratuvara giriş kontrolü görevleri (yalnızca kontrollü lotlar).
    lots = receive(staff, plant, commit)
    las, sles, water = lots["LAS"], lots["SLES"], lots["SU"]
    assert las.status == sles.status == Lot.Status.QUARANTINE
    assert water.status == Lot.Status.RELEASED
    assert task_for("incoming_qc", las).status == Task.Status.OPEN
    assert task_for("incoming_qc", sles).status == Task.Status.OPEN
    assert not Task.objects.filter(rule_code="incoming_qc", related_object_id=water.pk).exists()
    check()

    # 2. Laboratuvar lotları serbest bırakır → stok depoya geçer, görevler kapanır.
    with commit():
        inventory.release_lot(staff[LABORATUVAR], las, "Uygun", to_location=plant.storage)
        inventory.release_lot(staff[LABORATUVAR], sles, "Uygun", to_location=plant.storage)
    assert task_for("incoming_qc", las).status == Task.Status.DONE
    assert task_for("incoming_qc", sles).status == Task.Status.DONE
    assert current_balance(las, plant.storage) == D("2000")
    check()

    # 3. Planlama emri açar ve onaylar → depoya "Malzeme hazırla".
    with commit():
        order = services.create_order(staff[PLANLAMA], order_data(plant, "1000"))
        services.approve_order(staff[PLANLAMA], order)
    prep_task = task_for("material_prep", order)
    assert prep_task.status == Task.Status.OPEN
    assert prep_task.assigned_role.name == DEPO
    assert f"Yeni görev: Malzeme hazırla: {order.number}" in titles(staff[DEPO])

    # 4. Depo karantinadaki lotu seçemez; serbest lotları okutur ve hazır der.
    las_req = plant.requirement(order, plant.las)
    sles_req = plant.requirement(order, plant.sles)
    with pytest.raises(BusinessRuleError, match="lot_not_released"):
        quarantined = inventory.create_lot(
            staff[DEPO], material=plant.las, source=Lot.Source.PURCHASE
        )
        services.pick_material(staff[DEPO], order, las_req, quarantined, D("1"))
    with commit():
        services.pick_material(staff[DEPO], order, las_req, las, D("620"))
        services.pick_material(staff[DEPO], order, sles_req, sles, D("300"))
        services.mark_material_ready(staff[DEPO], order)
    assert task_for("material_prep", order).status == Task.Status.DONE
    start_task = task_for("start_batch", order)
    assert start_task.status == Task.Status.OPEN
    assert start_task.assigned_role.name == URETIM
    assert current_balance(las, plant.production) == D("620")
    check()

    # 5. Üretim şarjı başlatır → "Şarjı başlat" kapanır.
    with commit():
        batch = services.start_batch(staff[URETIM], order)
    assert task_for("start_batch", order).status == Task.Status.DONE
    order.refresh_from_db()
    assert order.status == Status.IN_PRODUCTION

    # 6. Tartım: LAS toleransın üstünde (notlu) → planlama ve laboratuvara sapma bildirimi.
    with commit():
        services.record_consumption(
            staff[URETIM], batch, las_req, las, D("620"), note="Fazla ilave edildi"
        )
        services.record_consumption(staff[URETIM], batch, sles_req, sles, D("300"))
        services.record_consumption(
            staff[URETIM], batch, plant.requirement(order, plant.water), water, D("100")
        )
    deviation = f"Tartım sapması: {order.number}"
    assert deviation in titles(staff[PLANLAMA])
    assert deviation in titles(staff[LABORATUVAR])
    assert deviation not in titles(staff[DEPO])
    assert current_balance(las, plant.production) == 0
    assert current_balance(water, plant.storage) == D("4900")
    check()

    # 7. Şarj biter → çıktı tanka girer, laboratuvara "Numune analizi", emir analiz bekler.
    with commit():
        services.finish_batch(staff[URETIM], batch, D("1015"))
    output = batch.output_lot
    sample_task = task_for("batch_sample_analysis", output)
    assert sample_task.status == Task.Status.OPEN
    assert sample_task.title == f"Numune analizi: {output.lot_no}"
    assert current_balance(output, plant.tank.location) == D("1015")
    order.refresh_from_db()
    assert order.status == Status.QC_PENDING
    check()

    # 8. Soy ağacı: bulk lotun girdileri (miktarlarıyla) ve hammadde lotunun kullanıldığı şarj.
    backward = inventory_selectors.lot_trace_backward(output)
    used = {child["lot_no"]: child["quantity"] for child in backward["children"]}
    assert used == {las.lot_no: D("620"), sles.lot_no: D("300"), water.lot_no: D("100")}
    forward = inventory_selectors.lot_trace_forward(las)
    assert [child["lot_no"] for child in forward["children"]] == [output.lot_no]

    # 9. Laboratuvar bulk lotu serbest bırakır → görev kapanır, bildirim gider, emir tamamlanır.
    with commit():
        inventory.release_lot(staff[LABORATUVAR], output, "Analiz uygun")
    assert task_for("batch_sample_analysis", output).status == Task.Status.DONE
    assert f"Bulk lot serbest bırakıldı: {output.lot_no}" in titles(staff[PLANLAMA])
    assert f"Bulk lot serbest bırakıldı: {output.lot_no}" in titles(staff[URETIM])
    order.refresh_from_db()
    assert order.status == Status.COMPLETED
    assert not Task.objects.filter(status__in=Task.OPEN_STATUSES).exists()
    check()


def test_split_order_two_batches_low_yield_and_completion(staff, commit):
    """D-4: 1500 kg emir 1000 kg'lık iki tanka bölünür; düşük verim bildirimi; iki lot da serbest
    olunca emir tamamlanır."""
    plant = build_plant(staff[PLANLAMA])
    with commit():
        order = services.create_order(staff[PLANLAMA], order_data(plant, "1500"))
        services.approve_order(staff[PLANLAMA], order)
        for material in (plant.las, plant.sles):
            requirement = plant.requirement(order, material)
            services.pick_material(
                staff[DEPO],
                order,
                requirement,
                plant.lots[material.code.lower()],
                requirement.required_quantity,
            )
        services.mark_material_ready(staff[DEPO], order)

    with commit():
        first = services.start_batch(staff[URETIM], order)
        second = services.start_batch(staff[URETIM], order, plant.tank2)
    assert (first.planned_quantity, second.planned_quantity) == (D("1000"), D("500"))
    assert first.batch_no != second.batch_no

    for batch in (first, second):
        for requirement in order.requirements.order_by("sequence"):
            lot = plant.lots["water" if requirement.is_water else requirement.material.code.lower()]
            services.record_consumption(
                staff[URETIM],
                batch,
                requirement,
                lot,
                services.batch_line_quantity(requirement, batch),
            )
    with commit():
        services.finish_batch(staff[URETIM], first, D("990"))
        services.finish_batch(staff[URETIM], second, D("450"))
    assert f"Düşük verim: {order.number}" in titles(staff[YONETIM])
    order.refresh_from_db()
    assert order.status == Status.QC_PENDING
    assert Task.objects.filter(rule_code="batch_sample_analysis").count() == 2

    with commit():
        inventory.release_lot(staff[LABORATUVAR], first.output_lot)
    order.refresh_from_db()
    assert order.status == Status.QC_PENDING
    with commit():
        inventory.release_lot(staff[LABORATUVAR], second.output_lot)
    order.refresh_from_db()
    assert order.status == Status.COMPLETED

    # Her şarjın kendi soy ağacı var; LAS lotu iki şarjda da görünür.
    forward = inventory_selectors.lot_trace_forward(plant.lots["las"])
    assert {c["lot_no"] for c in forward["children"]} == {first.batch_no, second.batch_no}
    assert_stock_invariants()


def test_cancelled_order_cancels_open_tasks(staff, commit):
    plant = build_plant(staff[PLANLAMA])
    with commit():
        order = services.create_order(staff[PLANLAMA], order_data(plant))
        services.approve_order(staff[PLANLAMA], order)
        services.pick_material(
            staff[DEPO], order, plant.requirement(order, plant.las), plant.lots["las"], D("100")
        )
    with commit():
        services.cancel_order(staff[PLANLAMA], order, "Müşteri siparişi iptal")

    assert task_for("material_prep", order).status == Task.Status.CANCELLED
    assert f"Üretim emri iptal edildi: {order.number}" in titles(staff[DEPO])
    assert current_balance(plant.lots["las"], plant.storage) == D("5000")
    assert_stock_invariants()


def test_events_follow_contract(staff, commit, published):
    """Üretimin yayınladığı olaylar sözleşmedeki alanları taşır (DECISIONS.md)."""
    plant = build_plant(staff[PLANLAMA])
    with commit():
        order = services.create_order(staff[PLANLAMA], order_data(plant))
        services.approve_order(staff[PLANLAMA], order)
    by_name = {event.name: event.payload for event in published}
    assert {"model", "id", "number", "from_status", "to_status", "priority"} <= set(
        by_name[ev.PRODUCTION_ORDER_APPROVED]
    )
