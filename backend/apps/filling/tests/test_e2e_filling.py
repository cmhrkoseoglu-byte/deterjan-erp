"""Uçtan uca dolum akışı (Faz 2 kabul testi).

Üretim emri iki şarja bölünür → iki bulk lot son kontrol numunesiyle serbest → dolum emri → onay →
ambalaj hazırlama → dolum (iki bulk lottan, bulk / ambalaj / mamul firesiyle) → mamul son kontrolü
→ serbest mamul lot → emir tamam. Her adımda görevler, bildirimler, stok değişmezleri; sonunda çok
seviyeli izlenebilirlik (D lot → bulk lotlar + ambalaj lotları → bulkun hammadde lotları) ve teorik
/ gerçek tüketim raporu doğrulanır.
"""

from decimal import Decimal

import pytest
from django.test import override_settings

from apps.core.roles import DEPO, DOLUM, LABORATUVAR, PLANLAMA, SEVKIYAT, URETIM, YONETIM
from apps.filling import selectors
from apps.filling import services as filling
from apps.filling.models import FillingOrder, ScrapRecord
from apps.filling.tests.factories import build_line, order_data, requirement
from apps.inventory import selectors as inventory_selectors
from apps.inventory.models import Lot
from apps.inventory.services import current_balance
from apps.inventory.testing import assert_stock_invariants
from apps.production import services as production
from apps.production.tests.factories import build_plant
from apps.production.tests.factories import order_data as production_order_data
from apps.quality.models import Sample
from apps.quality.testing import open_sample_for, pass_sample
from apps.workflow.models import Notification, Task

D = Decimal
Status = FillingOrder.Status
Reason = ScrapRecord.Reason
Kind = ScrapRecord.Kind


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


def produce_two_bulk_lots(staff, plant, commit):
    """1500 kg emir, 1000 kg'lık iki tanka bölünür (D-4); iki bulk lot serbest bırakılır."""
    with commit():
        order = production.create_order(staff[PLANLAMA], production_order_data(plant, "1500"))
        production.approve_order(staff[PLANLAMA], order)
        for material in (plant.las, plant.sles):
            row = plant.requirement(order, material)
            production.pick_material(
                staff[DEPO], order, row, plant.lots[material.code.lower()], row.required_quantity
            )
        production.mark_material_ready(staff[DEPO], order)
        first = production.start_batch(staff[URETIM], order)
        second = production.start_batch(staff[URETIM], order, plant.tank2)
    for batch in (first, second):
        for row in order.requirements.order_by("sequence"):
            lot = plant.lots["water" if row.is_water else row.material.code.lower()]
            production.record_consumption(
                staff[URETIM], batch, row, lot, production.batch_line_quantity(row, batch)
            )
    with commit():
        production.finish_batch(staff[URETIM], first, D("1000"))
        production.finish_batch(staff[URETIM], second, D("500"))
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(first.output_lot, "FINAL"))
        pass_sample(staff[LABORATUVAR], open_sample_for(second.output_lot, "FINAL"))
    first.output_lot.refresh_from_db()
    second.output_lot.refresh_from_db()
    assert first.output_lot.status == second.output_lot.status == Lot.Status.RELEASED
    return first.output_lot, second.output_lot


@override_settings(FILL_VARIANCE_THRESHOLD_PCT="1.5")
def test_released_bulk_to_released_finished_lot_with_traceability(staff, commit):
    plant = build_plant(staff[PLANLAMA])
    bulk_a, bulk_b = produce_two_bulk_lots(staff, plant, commit)
    line = build_line(staff[PLANLAMA], bulk=plant.product, warehouse=plant.warehouse)
    assert_stock_invariants()

    # 1. Planlama dolum emrini açar ve onaylar → depoya "Ambalaj malzemesi hazırla".
    with commit():
        order = filling.create_order(staff[PLANLAMA], order_data(line, 1000))
        filling.approve_order(staff[PLANLAMA], order)
    prep_task = task_for("packaging_prep", order)
    assert prep_task.status == Task.Status.OPEN
    assert prep_task.assigned_role.name == DEPO
    assert f"Yeni görev: Ambalaj malzemesi hazırla: {order.number}" in titles(staff[DEPO])

    # 2. Depo ambalaj lotlarını okutup hat başına taşır ve hazır der → dolum görevi açılır.
    with commit():
        for key, material in zip(("bottle", "cap", "label", "case"), line.packaging, strict=True):
            row = requirement(order, material)
            filling.pick_packaging(staff[DEPO], order, row, line.lots[key], row.required_quantity)
        filling.mark_material_ready(staff[DEPO], order)
    assert task_for("packaging_prep", order).status == Task.Status.DONE
    start_task = task_for("start_filling", order)
    assert start_task.status == Task.Status.OPEN
    assert start_task.assigned_role.name == DOLUM
    assert current_balance(line.lots["bottle"], line.line_location) == D("1020")
    assert_stock_invariants()

    # 3. Dolumcu partiyi başlatır → karantinada D lotu, "Dolumu başlat" kapanır.
    with commit():
        run = filling.start_run(staff[DOLUM], order)
    finished_lot = run.output_lot
    assert finished_lot.lot_no.startswith("D-")
    assert finished_lot.status == Lot.Status.QUARANTINE
    assert task_for("start_filling", order).status == Task.Status.DONE

    # 4. İki bulk lottan tüketim (ilk tank bitince ikinciye geçilir), ambalaj lotu okutma, fire.
    with commit():
        filling.consume_bulk(staff[DOLUM], run, bulk_b, D("500"))
        filling.consume_bulk(staff[DOLUM], run, bulk_a, D("290"))
        filling.scan_packaging_lot(staff[DOLUM], run, line.lots["bottle"])
        filling.record_scrap(
            staff[DOLUM],
            run,
            kind=Kind.BULK,
            quantity=D("3"),
            reason_code=Reason.SETUP_LOSS,
            lot=bulk_a,
        )
        filling.record_scrap(
            staff[DOLUM],
            run,
            kind=Kind.PACKAGING,
            quantity=D("4"),
            reason_code=Reason.LABEL_ERROR,
            lot=line.lots["label"],
        )
        filling.record_scrap(
            staff[DOLUM], run, kind=Kind.FINISHED, quantity=D("5"), reason_code=Reason.LEAK
        )
    assert current_balance(bulk_b, plant.tank2.location) == 0
    assert current_balance(bulk_a, plant.tank.location) == D("707")
    assert_stock_invariants()

    # 5. Parti biter: ambalaj düşülür, mamul depoya girer, laboratuvara "Mamul kontrolü"; bulk
    #    farkı eşiği aştığı için (793 / 780 = %1,67) planlama ve yönetime bildirim.
    with commit():
        run = filling.finish_run(staff[DOLUM], run, 1000, "Vardiya sonu")
        order = filling.finish_filling(staff[DOLUM], order)
    assert order.status == Status.QC_PENDING
    assert current_balance(finished_lot, line.finished_store) == D("1000")
    assert run.bulk_variance_pct == D("1.67")
    variance = f"Dolum bulk farkı: {order.number}"
    assert variance in titles(staff[PLANLAMA])
    assert variance in titles(staff[YONETIM])
    assert variance not in titles(staff[DEPO])
    sample = open_sample_for(finished_lot, "FINAL")
    assert sample.origin == Sample.Origin.FILLING
    qc_task = task_for("finished_qc", finished_lot)
    assert qc_task.status == Task.Status.OPEN
    assert qc_task.title == f"Mamul kontrolü: {finished_lot.lot_no}"
    # Bulkun son kontrol görevi mamul numunesi için ayrıca açılmaz.
    assert not Task.objects.filter(rule_code="batch_sample_analysis", status="OPEN").exists()
    assert_stock_invariants()

    # 6. Laboratuvar mamul kontrollerini girer ve serbest bırakır → görev kapanır, sevkiyata
    #    "Sevke hazır", emir tamamlanır.
    with commit():
        pass_sample(staff[LABORATUVAR], sample)
    finished_lot.refresh_from_db()
    order.refresh_from_db()
    assert finished_lot.status == Lot.Status.RELEASED
    assert order.status == Status.COMPLETED
    assert task_for("finished_qc", finished_lot).status == Task.Status.DONE
    assert f"Sevke hazır: {finished_lot.lot_no}" in titles(staff[SEVKIYAT])
    assert not Task.objects.filter(status__in=Task.OPEN_STATUSES).exists()

    # 7. Çok seviyeli geri izleme: D lot → iki bulk lot + dört ambalaj lotu → hammadde lotları.
    tree = inventory_selectors.lot_trace_backward(finished_lot)
    children = {child["lot_no"]: child for child in tree["children"]}
    assert set(children) == {
        bulk_a.lot_no,
        bulk_b.lot_no,
        *(line.lots[key].lot_no for key in ("bottle", "cap", "label", "case")),
    }
    assert children[bulk_b.lot_no]["quantity"] == D("500")
    assert children[bulk_a.lot_no]["quantity"] == D("290")
    assert children[line.lots["bottle"].lot_no]["quantity"] == D("1005")
    raw_lots = {plant.lots[key].lot_no for key in ("las", "sles", "water")}
    for bulk in (bulk_a, bulk_b):
        assert {c["lot_no"] for c in children[bulk.lot_no]["children"]} == raw_lots

    # İleri izleme: hammadde lotundan mamul lota iki seviye.
    forward = inventory_selectors.lot_trace_forward(plant.lots["las"])
    reached = {
        grandchild["lot_no"] for child in forward["children"] for grandchild in child["children"]
    }
    assert reached == {finished_lot.lot_no}

    # 8. Teorik / gerçek tüketim raporu.
    report = selectors.consumption_report(order)
    assert report.good_units == 1000
    assert (report.bulk.theoretical, report.bulk.consumed, report.bulk.scrap) == (
        D("780"),
        D("790"),
        D("3"),
    )
    assert report.bulk_over_threshold
    rows = {row.line.material.code: row for row in report.packaging}
    assert rows["SISE-750"].consumed == D("1005")  # 1000 sağlam + 5 sızdıran
    assert rows["ETIKET-750"].actual == D("1009")  # + 4 hatalı etiket
    assert_stock_invariants()
