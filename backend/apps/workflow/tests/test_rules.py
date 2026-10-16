"""Kural tablosu: her satır için görev/bildirim açılıyor ve kapanış olayıyla kapanıyor mu.

Lot, mal kabul ve üretim emri modelleri sonraki adımlarda geliyor; olaylar burada doğrudan
yayınlanır ve kayıt yerine test modeli (`Widget`) kullanılır. Payload biçimi
docs/DECISIONS.md'deki "İş akışı olay sözleşmesi"dir.
"""

import pytest

from apps.core import event_names as ev
from apps.workflow import rules
from apps.workflow.models import Notification, Task
from apps.workflow.tests.factories import WidgetFactory, ref

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(make_user):
    """Her rolden bir kullanıcı."""
    return {
        role: make_user(role, username=role)
        for role in (
            "depo",
            "uretim",
            "laboratuvar",
            "planlama",
            "yonetim",
            "satin_alma",
            "dolum",
            "sevkiyat",
        )
    }


def titles_for(user):
    return sorted(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def lot_ref(lot, **extra):
    return ref(
        lot, lot_no=f"H-261015-{lot.pk:03d}", material_code="LAS", material_name="LAS %96", **extra
    )


def order_ref(order, **extra):
    return ref(order, number=f"UE-2026-{order.pk:05d}", **extra)


def sample_ref(sample, lot, *, stage, number="NM-2026-00001", **extra):
    return ref(
        sample,
        number=number,
        stage=stage,
        lot_no=f"H-261015-{lot.pk:03d}",
        material_code="LAS",
        material_name="LAS %96",
        lot=lot_ref(lot),
        **extra,
    )


# --- sample.created (giriş) → Giriş kontrolü (laboratuvar) -------------------------------------


def test_incoming_sample_opens_incoming_qc_task(fire, staff):
    sample, lot = WidgetFactory(), WidgetFactory()

    fire(ev.SAMPLE_CREATED, sample_ref(sample, lot, stage="INCOMING"), staff["depo"])

    task = Task.objects.get()
    assert task.rule_code == "incoming_qc"
    assert task.title == f"Giriş kontrolü: H-261015-{lot.pk:03d}"
    assert task.description == "LAS LAS %96 — numune NM-2026-00001"
    assert task.assigned_role.name == "laboratuvar"
    assert task.related_object == sample
    assert task.status == Task.Status.OPEN
    assert task.created_by == staff["depo"]
    assert titles_for(staff["laboratuvar"]) == [f"Yeni görev: {task.title}"]
    assert titles_for(staff["depo"]) == []


@pytest.mark.parametrize("closing_event", [ev.SAMPLE_DECIDED, ev.SAMPLE_CANCELLED])
def test_incoming_qc_task_closes_on_sample_decision(fire, staff, closing_event):
    sample, other, lot = WidgetFactory(), WidgetFactory(), WidgetFactory()
    fire(ev.SAMPLE_CREATED, sample_ref(sample, lot, stage="INCOMING"))
    fire(ev.SAMPLE_CREATED, sample_ref(other, lot, stage="INCOMING"))

    fire(closing_event, sample_ref(sample, lot, stage="INCOMING"), staff["laboratuvar"])

    assert Task.objects.get(related_object_id=sample.pk).status == Task.Status.DONE
    assert Task.objects.get(related_object_id=other.pk).status == Task.Status.OPEN


# --- lot.rejected → bildirim (depo, satin_alma) -------------------------------------------------


def test_lot_rejected_warns_depo_and_purchasing(fire, staff):
    lot = WidgetFactory()

    fire(
        ev.LOT_REJECTED,
        lot_ref(lot, material_type="RAW", note="Renk uygun değil."),
        staff["laboratuvar"],
    )

    title = f"Lot reddedildi: H-261015-{lot.pk:03d}"
    for role in ("depo", "satin_alma"):
        notification = Notification.objects.get(recipient=staff[role])
        assert notification.title == title
        assert notification.body == "LAS LAS %96. Renk uygun değil."
        assert notification.level == Notification.Level.WARNING
        assert notification.related_object_id == lot.pk
    assert titles_for(staff["planlama"]) == []


# --- production_order.approved → Malzeme hazırla (depo) -----------------------------------------


def test_order_approved_opens_material_prep_and_closes_on_material_ready(fire, staff):
    order = WidgetFactory()

    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order, priority=3), staff["planlama"])

    prep = Task.objects.get(rule_code="material_prep")
    assert prep.title == f"Malzeme hazırla: UE-2026-{order.pk:05d}"
    assert prep.assigned_role.name == "depo"
    assert prep.priority == Task.Priority.HIGH
    assert prep.related_object == order

    fire(ev.PRODUCTION_ORDER_MATERIAL_READY, order_ref(order), staff["depo"])

    prep.refresh_from_db()
    assert prep.status == Task.Status.DONE


# --- production_order.material_ready → Şarjı başlat (uretim) ------------------------------------


def test_material_ready_opens_start_batch_and_closes_on_batch_started(fire, staff):
    order, batch, other_order = WidgetFactory(), WidgetFactory(), WidgetFactory()
    fire(ev.PRODUCTION_ORDER_MATERIAL_READY, order_ref(order), staff["depo"])
    fire(ev.PRODUCTION_ORDER_MATERIAL_READY, order_ref(other_order), staff["depo"])

    task = Task.objects.get(rule_code="start_batch", related_object_id=order.pk)
    assert task.title == f"Şarjı başlat: UE-2026-{order.pk:05d}"
    assert task.assigned_role.name == "uretim"

    fire(
        ev.PRODUCTION_BATCH_STARTED,
        ref(batch, batch_no="B-261015-001", order=order_ref(order)),
        staff["uretim"],
    )

    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    assert Task.objects.get(related_object_id=other_order.pk).status == Task.Status.OPEN


# --- production.deviation → bildirim (planlama, laboratuvar) ------------------------------------


def test_deviation_warns_planning_and_lab(fire, staff):
    batch = WidgetFactory()

    fire(
        ev.PRODUCTION_DEVIATION,
        ref(
            batch,
            batch_no="B-261015-001",
            order_number="UE-2026-00007",
            material_code="NAOH",
            lot_no="H-261001-002",
            planned_quantity="12.0000",
            actual_quantity="12.6000",
            deviation_pct="5.00",
            note="Fazla döküldü.",
        ),
        staff["uretim"],
    )

    for role in ("planlama", "laboratuvar"):
        notification = Notification.objects.get(recipient=staff[role])
        assert notification.title == "Tartım sapması: UE-2026-00007"
        assert "planlanan 12.0000, tartılan 12.6000 (%5.00)" in notification.body
        assert notification.level == Notification.Level.WARNING
    assert titles_for(staff["uretim"]) == []


# --- sample.created (şarj sırası / son) → Numune analizi (laboratuvar) ------------------------


@pytest.mark.parametrize("stage", ["IN_PROCESS", "FINAL"])
def test_batch_sample_opens_sample_analysis_task(fire, staff, stage):
    sample, lot = WidgetFactory(), WidgetFactory()

    fire(ev.SAMPLE_CREATED, sample_ref(sample, lot, stage=stage), staff["uretim"])

    task = Task.objects.get(rule_code="batch_sample_analysis")
    assert task.title == f"Numune analizi: H-261015-{lot.pk:03d}"
    assert task.assigned_role.name == "laboratuvar"
    assert task.related_object == sample

    fire(ev.SAMPLE_DECIDED, sample_ref(sample, lot, stage=stage, decision="RELEASE"))

    task.refresh_from_db()
    assert task.status == Task.Status.DONE


# --- sample.awaiting_approval → Şartlı kabul onayı (yönetim) ------------------------------------


@pytest.mark.parametrize("closing_event", [ev.SAMPLE_DECIDED, ev.SAMPLE_IN_TEST])
def test_conditional_release_opens_management_task(fire, staff, closing_event):
    sample, lot = WidgetFactory(), WidgetFactory()

    fire(
        ev.SAMPLE_AWAITING_APPROVAL,
        sample_ref(sample, lot, stage="FINAL", decision="CONDITIONAL_RELEASE", reason="pH 8,2"),
        staff["laboratuvar"],
    )

    task = Task.objects.get(rule_code="conditional_release_approval")
    assert task.title == f"Şartlı kabul onayı: H-261015-{lot.pk:03d}"
    assert task.description == "LAS LAS %96 — numune NM-2026-00001. pH 8,2"
    assert task.assigned_role.name == "yonetim"
    assert task.related_object == sample

    fire(closing_event, sample_ref(sample, lot, stage="FINAL"), staff["yonetim"])

    task.refresh_from_db()
    assert task.status == Task.Status.DONE


# --- sample.decided (REWORK) → Yeniden işleme emri aç (planlama) --------------------------------


def test_rework_decision_opens_planning_task_closed_by_rework_order(fire, staff):
    sample, lot, order = WidgetFactory(), WidgetFactory(), WidgetFactory()

    fire(
        ev.SAMPLE_DECIDED,
        sample_ref(sample, lot, stage="FINAL", decision="REWORK", reason="Viskozite düşük"),
        staff["laboratuvar"],
    )

    task = Task.objects.get(rule_code="rework_order")
    assert task.title == f"Yeniden işleme emri aç: H-261015-{lot.pk:03d}"
    assert task.description == "LAS LAS %96 — numune NM-2026-00001. Viskozite düşük"
    assert task.assigned_role.name == "planlama"
    assert task.related_object == lot

    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order, rework_lot=lot_ref(lot)))

    task.refresh_from_db()
    assert task.status == Task.Status.DONE


def test_other_decisions_open_no_rework_task(fire, staff):
    sample, lot = WidgetFactory(), WidgetFactory()

    fire(ev.SAMPLE_DECIDED, sample_ref(sample, lot, stage="FINAL", decision="REJECT"))

    assert not Task.objects.filter(rule_code="rework_order").exists()


def test_in_process_reject_notifies_production_and_planning(fire, staff):
    sample, lot = WidgetFactory(), WidgetFactory()

    fire(
        ev.SAMPLE_DECIDED,
        sample_ref(sample, lot, stage="IN_PROCESS", decision="REJECT", reason="pH yüksek"),
        staff["laboratuvar"],
    )
    fire(ev.SAMPLE_DECIDED, sample_ref(sample, lot, stage="FINAL", decision="REJECT"))

    expected = [f"Ara kontrol uygun değil: H-261015-{lot.pk:03d}"]
    assert titles_for(staff["uretim"]) == expected
    assert titles_for(staff["planlama"]) == expected


# --- lot.released (BULK) → bildirim (planlama, uretim) ------------------------------------------


def test_bulk_lot_released_notifies_planning_and_production(fire, staff):
    lot = WidgetFactory()

    fire(
        ev.LOT_RELEASED, ref(lot, lot_no="B-261015-001", material_type="BULK"), staff["laboratuvar"]
    )

    for role in ("planlama", "uretim"):
        assert titles_for(staff[role]) == ["Bulk lot serbest bırakıldı: B-261015-001"]
    assert titles_for(staff["depo"]) == []


def test_raw_lot_released_sends_no_notification(fire, staff):
    lot = WidgetFactory()

    fire(ev.LOT_RELEASED, ref(lot, lot_no="H-261015-001", material_type="RAW"))

    assert Notification.objects.count() == 0


# --- lot.rejected (BULK) → bildirim (planlama, uretim) ------------------------------------------


def test_bulk_lot_rejected_notifies_planning_and_production(fire, staff):
    lot = WidgetFactory()

    fire(
        ev.LOT_REJECTED,
        ref(lot, lot_no="B-261015-001", material_type="BULK", note="Viskozite düşük"),
        staff["laboratuvar"],
    )

    for role in ("planlama", "uretim"):
        assert titles_for(staff[role]) == ["Bulk lot reddedildi: B-261015-001"]
    # Genel red bildirimi depo ve satın almaya ayrıca gider.
    assert titles_for(staff["depo"]) == ["Lot reddedildi: B-261015-001"]


# --- production.low_yield → bildirim (planlama, yonetim) ----------------------------------------


def test_low_yield_warns_planning_and_management(fire, staff):
    batch = WidgetFactory()

    fire(
        ev.PRODUCTION_LOW_YIELD,
        ref(
            batch,
            batch_no="B-261015-001",
            order_number="UE-2026-00007",
            yield_pct="94.50",
            threshold_pct="97.00",
        ),
    )

    for role in ("planlama", "yonetim"):
        notification = Notification.objects.get(recipient=staff[role])
        assert notification.title == "Düşük verim: UE-2026-00007"
        assert notification.body == "Şarj B-261015-001: verim %94.50 (eşik %97.00)."
        assert notification.level == Notification.Level.WARNING


# --- production_order.cancelled → açık görevleri iptal + bildirim -------------------------------


def test_order_cancelled_cancels_open_tasks_and_notifies_roles(fire, staff, make_user):
    order, other = WidgetFactory(), WidgetFactory()
    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))
    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(other))
    Notification.objects.all().delete()

    fire(
        ev.PRODUCTION_ORDER_CANCELLED,
        order_ref(order, from_status="MATERIAL_PREP"),
        staff["yonetim"],
    )

    task = Task.objects.get(related_object_id=order.pk)
    assert task.status == Task.Status.CANCELLED
    assert task.completion_note == f"Üretim emri iptal edildi: UE-2026-{order.pk:05d}"
    assert Task.objects.get(related_object_id=other.pk).status == Task.Status.OPEN
    # İptal edilen görevin rolü (depo) ve planlama haberdar olur; tetikleyen yönetim almaz.
    expected = [f"Üretim emri iptal edildi: UE-2026-{order.pk:05d}"]
    assert titles_for(staff["depo"]) == expected
    assert titles_for(staff["planlama"]) == expected
    assert titles_for(staff["yonetim"]) == []
    assert titles_for(staff["uretim"]) == []


# --- 07:00 kontrolleri: SKT ve minimum stok (depo, planlama) ------------------------------------


def test_expiring_lots_warn_depo_and_planning(fire, staff):
    fire(
        ev.LOTS_EXPIRING,
        {
            "days": 30,
            "lots": [
                {
                    "lot_no": "H-260901-001",
                    "material_code": "PRF",
                    "material_name": "Parfüm",
                    "expiry_date": "2026-11-01",
                }
            ],
        },
    )

    for role in ("depo", "planlama"):
        notification = Notification.objects.get(recipient=staff[role])
        assert notification.title == "SKT'si 30 gün içinde dolacak lotlar"
        assert notification.body == "H-260901-001 — PRF Parfüm (SKT 2026-11-01)"
        assert notification.related_content_type is None


def test_below_min_stock_warns_depo_and_planning(fire, staff):
    fire(
        ev.BELOW_MIN_STOCK,
        {
            "materials": [
                {
                    "code": "NAOH",
                    "name": "Kostik",
                    "quantity": "40.0000",
                    "min_stock": "100.0000",
                    "unit": "KG",
                }
            ]
        },
    )

    for role in ("depo", "planlama"):
        notification = Notification.objects.get(recipient=staff[role])
        assert notification.title == "Minimum stok altındaki malzemeler"
        assert notification.body == "NAOH Kostik: 40.0000 (en az 100.0000 KG)"


def test_empty_daily_check_lists_send_nothing(fire, staff):
    fire(ev.LOTS_EXPIRING, {"days": 30, "lots": []})
    fire(ev.BELOW_MIN_STOCK, {"materials": []})

    assert Notification.objects.count() == 0


# --- Faz 2 dolum: emir, parti, bulk farkı, mamul lotu -------------------------------------------


def filling_ref(order, **extra):
    return ref(order, number=f"DO-2026-{order.pk:05d}", **extra)


def test_filling_order_approved_opens_packaging_prep_closed_on_material_ready(fire, staff):
    order = WidgetFactory()

    fire(ev.FILLING_ORDER_APPROVED, filling_ref(order, product_code="BL-750"), staff["planlama"])

    task = Task.objects.get(rule_code="packaging_prep")
    assert task.title == f"Ambalaj malzemesi hazırla: DO-2026-{order.pk:05d}"
    assert "BL-750" in task.description
    assert task.assigned_role.name == "depo"
    assert task.related_object == order

    fire(ev.FILLING_ORDER_MATERIAL_READY, filling_ref(order), staff["depo"])

    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    start = Task.objects.get(rule_code="start_filling")
    assert start.title == f"Dolumu başlat: DO-2026-{order.pk:05d}"
    assert start.assigned_role.name == "dolum"

    run = WidgetFactory()
    fire(ev.FILLING_RUN_STARTED, ref(run, lot_no="D-261015-001", order=filling_ref(order)))

    start.refresh_from_db()
    assert start.status == Task.Status.DONE


def test_filling_run_completed_opens_finished_qc_closed_by_sample_decision(fire, staff):
    order, run, lot, sample = WidgetFactory(), WidgetFactory(), WidgetFactory(), WidgetFactory()
    lot_payload = ref(lot, lot_no="D-261015-001", material_code="BL-750", material_name="Bulaşık")

    fire(
        ev.FILLING_RUN_COMPLETED,
        ref(
            run,
            lot_no="D-261015-001",
            order=filling_ref(order),
            order_number=f"DO-2026-{order.pk:05d}",
            output_lot={**lot_payload, "material_type": "FINISHED"},
            sample_number="NM-2026-00007",
        ),
        staff["dolum"],
    )

    task = Task.objects.get(rule_code="finished_qc")
    assert task.title == "Mamul kontrolü: D-261015-001"
    assert task.assigned_role.name == "laboratuvar"
    assert task.related_object == lot
    assert "NM-2026-00007" in task.description

    fire(
        ev.SAMPLE_DECIDED,
        ref(sample, number="NM-2026-00007", stage="FINAL", lot=lot_payload, decision="RELEASE"),
    )

    task.refresh_from_db()
    assert task.status == Task.Status.DONE


def test_finished_final_sample_opens_no_batch_analysis_task(fire, staff):
    lot, sample = WidgetFactory(), WidgetFactory()

    fire(
        ev.SAMPLE_CREATED,
        sample_ref(sample, lot, stage="FINAL", material_type="FINISHED"),
    )

    assert not Task.objects.filter(rule_code="batch_sample_analysis").exists()


def test_bulk_variance_warns_planning_and_management(fire, staff):
    order = WidgetFactory()

    fire(
        ev.FILLING_BULK_VARIANCE,
        filling_ref(
            order,
            lot_no="D-261015-001",
            product_code="BL-750",
            good_units=1000,
            theoretical_quantity="780.0000 KG",
            actual_quantity="800.0000 KG",
            variance_pct="2.56",
            threshold_pct="1.5",
        ),
        staff["dolum"],
    )

    expected = [f"Dolum bulk farkı: DO-2026-{order.pk:05d}"]
    assert titles_for(staff["planlama"]) == expected
    assert titles_for(staff["yonetim"]) == expected
    notification = Notification.objects.get(recipient=staff["planlama"])
    assert notification.level == "WARNING"
    assert "teorik 780.0000 KG, gerçek 800.0000 KG (%2.56, eşik %1.5)" in notification.body
    assert titles_for(staff["dolum"]) == []


def test_finished_lot_released_tells_shipping_ready(fire, staff):
    lot = WidgetFactory()

    fire(ev.LOT_RELEASED, lot_ref(lot, material_type="FINISHED"), staff["laboratuvar"])

    title = f"Sevke hazır: H-261015-{lot.pk:03d}"
    assert titles_for(staff["sevkiyat"]) == [title]
    assert titles_for(staff["planlama"]) == [title]
    assert titles_for(staff["uretim"]) == []


def test_finished_lot_rejected_warns_planning_and_filling(fire, staff):
    lot = WidgetFactory()

    fire(ev.LOT_REJECTED, lot_ref(lot, material_type="FINISHED", note="Sızıntı"))

    title = f"Mamul lot reddedildi: H-261015-{lot.pk:03d}"
    assert title in titles_for(staff["planlama"])
    assert title in titles_for(staff["dolum"])


def test_filling_order_cancelled_cancels_its_tasks(fire, staff):
    order = WidgetFactory()
    fire(ev.FILLING_ORDER_APPROVED, filling_ref(order))
    Notification.objects.all().delete()

    fire(ev.FILLING_ORDER_CANCELLED, filling_ref(order, from_status="APPROVED"), staff["yonetim"])

    task = Task.objects.get(rule_code="packaging_prep")
    assert task.status == Task.Status.CANCELLED
    expected = [f"Dolum emri iptal edildi: DO-2026-{order.pk:05d}"]
    assert titles_for(staff["depo"]) == expected
    assert titles_for(staff["planlama"]) == expected


# --- Genel davranış -----------------------------------------------------------------------------


def test_every_rule_row_is_covered():
    """Faz 1'in 9 satırı + bulk lot reddi + 2 günlük kontrol + Faz 2 kalite ve dolum kuralları +
    Faz 3 satış siparişi, iade ve sevkiyat kuralları + Faz 4 satın alma, rapor, bakım, İSG +
    Faz 5 hesap kilidi, sistem izleme ve sorun bildirimi."""
    assert [rule.code for rule in rules.RULES] == [
        "incoming_qc",
        "lot_rejected",
        "material_prep",
        "start_batch",
        "production_deviation",
        "batch_sample_analysis",
        "conditional_release_approval",
        "rework_order",
        "in_process_out_of_spec",
        "bulk_lot_released",
        "bulk_lot_rejected",
        "production_low_yield",
        "production_order_cancelled",
        "packaging_prep",
        "start_filling",
        "finished_qc",
        "filling_bulk_variance",
        "finished_lot_released",
        "finished_lot_rejected",
        "filling_order_cancelled",
        "return_qc",
        "return_rework",
        "return_scrap",
        "return_closed",
        "lots_expiring",
        "below_min_stock",
        "plan_shipment",
        "sales_shortage",
        "sales_order_cancelled",
        "reserved_lots_expiring",
        "pick_shipment",
        "dispatch_shipment",
        "shipment_dispatched",
        "shipment_cancelled",
        "purchase_request",
        "purchase_order_approval",
        "purchase_order_returned",
        "expected_delivery",
        "purchase_order_received",
        "purchase_order_cancelled",
        "maintenance_work_order_uretim",
        "maintenance_work_order_dolum",
        "maintenance_work_order_laboratuvar",
        "maintenance_work_order_planlama",
        "maintenance_work_order_yonetim",
        "equipment_down",
        "equipment_up",
        "maintenance_overdue",
        "incident_review",
        "incident_injury",
        "storage_limit_exceeded",
        "report_ready",
        "report_failed",
        "user_locked",
        "ops_alert",
        "ops_recovered",
        "problem_reported",
    ]


def test_repeated_event_does_not_duplicate_open_task(fire, staff):
    order = WidgetFactory()

    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))
    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))

    assert Task.objects.filter(rule_code="material_prep").count() == 1


def test_actor_does_not_receive_own_notification_but_role_peers_do(fire, staff, make_user):
    peer = make_user("depo")
    lot = WidgetFactory()

    fire(ev.LOT_REJECTED, lot_ref(lot), staff["depo"])

    assert titles_for(staff["depo"]) == []
    assert len(titles_for(peer)) == 1


def test_inactive_and_admin_users_are_not_role_recipients(fire, staff, make_user):
    inactive = make_user("depo", is_active=False)
    admin = make_user("admin")
    superuser = make_user(is_superuser=True)
    lot = WidgetFactory()

    fire(ev.LOT_REJECTED, lot_ref(lot))

    for user in (inactive, admin, superuser):
        assert titles_for(user) == []


def test_unknown_record_type_still_opens_task_without_link(fire, staff):
    fire(ev.PRODUCTION_ORDER_APPROVED, {"model": "yok.boyle", "id": 1, "number": "UE-2026-00001"})

    task = Task.objects.get()
    assert task.related_content_type is None
    assert task.title == "Malzeme hazırla: UE-2026-00001"


def test_failing_rule_does_not_block_other_rules(fire, staff, monkeypatch, caplog):
    from apps.workflow import services

    def broken(*args, **kwargs):
        raise RuntimeError("bozuk")

    monkeypatch.setattr(services, "auto_close_tasks", broken)
    sample, lot = WidgetFactory(), WidgetFactory()

    fire(ev.SAMPLE_DECIDED, sample_ref(sample, lot, stage="FINAL", decision="REWORK"))

    assert "İş akışı kuralı başarısız" in caplog.text
    assert Task.objects.filter(rule_code="rework_order").count() == 1


def test_rolled_back_transaction_creates_no_task(staff, django_capture_on_commit_callbacks):
    from django.db import transaction

    from apps.core import events

    order = WidgetFactory()
    with django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                events.publish(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))
                raise RuntimeError("geri al")
        except RuntimeError:
            pass

    assert Task.objects.count() == 0
