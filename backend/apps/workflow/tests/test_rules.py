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
        for role in ("depo", "uretim", "laboratuvar", "planlama", "yonetim", "satin_alma")
    }


def titles_for(user):
    return sorted(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def lot_ref(lot, **extra):
    return ref(
        lot, lot_no=f"H-261015-{lot.pk:03d}", material_code="LAS", material_name="LAS %96", **extra
    )


def order_ref(order, **extra):
    return ref(order, number=f"UE-2026-{order.pk:05d}", **extra)


# --- goods_receipt.posted → Giriş kontrolü (laboratuvar) ----------------------------------------


def test_goods_receipt_opens_incoming_qc_task_only_for_qc_lots(fire, staff):
    receipt, qc_lot, free_lot = WidgetFactory(), WidgetFactory(), WidgetFactory()

    fire(
        ev.GOODS_RECEIPT_POSTED,
        ref(
            receipt,
            number="MK-2026-00001",
            lots=[lot_ref(qc_lot, requires_qc=True), lot_ref(free_lot, requires_qc=False)],
        ),
        staff["depo"],
    )

    task = Task.objects.get()
    assert task.rule_code == "incoming_qc"
    assert task.title == f"Giriş kontrolü: H-261015-{qc_lot.pk:03d}"
    assert task.description == "LAS LAS %96 — mal kabul MK-2026-00001"
    assert task.assigned_role.name == "laboratuvar"
    assert task.related_object == qc_lot
    assert task.status == Task.Status.OPEN
    assert task.created_by == staff["depo"]
    assert titles_for(staff["laboratuvar"]) == [f"Yeni görev: {task.title}"]
    assert titles_for(staff["depo"]) == []


@pytest.mark.parametrize("closing_event", [ev.LOT_RELEASED, ev.LOT_REJECTED])
def test_incoming_qc_task_closes_on_lot_decision(fire, staff, closing_event):
    receipt, lot, other = WidgetFactory(), WidgetFactory(), WidgetFactory()
    fire(
        ev.GOODS_RECEIPT_POSTED,
        ref(receipt, lots=[lot_ref(lot, requires_qc=True), lot_ref(other, requires_qc=True)]),
    )

    fire(closing_event, lot_ref(lot, material_type="RAW"), staff["laboratuvar"])

    closed = Task.objects.get(related_object_id=lot.pk)
    assert closed.status == Task.Status.DONE
    assert closed.completed_by == staff["laboratuvar"]
    assert closed.completion_note == f"Otomatik kapandı: {closing_event}"
    # Başka lotun görevi açık kalır.
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


# --- production_batch.completed → Numune analizi (laboratuvar) ----------------------------------


@pytest.mark.parametrize("closing_event", [ev.LOT_RELEASED, ev.LOT_REJECTED])
def test_batch_completed_opens_sample_analysis_for_output_lot(fire, staff, closing_event):
    order, batch, output_lot = WidgetFactory(), WidgetFactory(), WidgetFactory()

    fire(
        ev.PRODUCTION_BATCH_COMPLETED,
        ref(
            batch,
            batch_no="B-261015-001",
            order=order_ref(order),
            output_lot=ref(output_lot, lot_no="B-261015-001", material_code="BULK-BUL"),
        ),
        staff["uretim"],
    )

    task = Task.objects.get(rule_code="batch_sample_analysis")
    assert task.title == "Numune analizi: B-261015-001"
    assert task.assigned_role.name == "laboratuvar"
    assert task.related_object == output_lot
    assert task.description.endswith(f"üretim emri UE-2026-{order.pk:05d}")

    fire(closing_event, ref(output_lot, lot_no="B-261015-001", material_type="BULK"))

    task.refresh_from_db()
    assert task.status == Task.Status.DONE


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


# --- Genel davranış -----------------------------------------------------------------------------


def test_every_rule_row_is_covered():
    """Spesifikasyondaki 9 satır + bulk lot reddi (üretim planı) + 2 günlük kontrol tabloda."""
    assert [rule.code for rule in rules.RULES] == [
        "incoming_qc",
        "lot_rejected",
        "material_prep",
        "start_batch",
        "production_deviation",
        "batch_sample_analysis",
        "bulk_lot_released",
        "bulk_lot_rejected",
        "production_low_yield",
        "production_order_cancelled",
        "lots_expiring",
        "below_min_stock",
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
    lot = WidgetFactory()

    fire(ev.LOT_RELEASED, ref(lot, lot_no="B-1", material_type="BULK"))

    assert "İş akışı kuralı başarısız" in caplog.text
    assert len(titles_for(staff["planlama"])) == 1


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
