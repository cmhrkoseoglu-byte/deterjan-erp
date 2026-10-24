"""Rapor sorguları ve panolar: gerçek akıştan (conftest `chain`) beklenen değerler."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA, SATIN_ALMA
from apps.inventory.models import Lot
from apps.inventory.testing import assert_stock_invariants
from apps.inventory.tests.factories import stocked_lot
from apps.purchasing import services as purchasing
from apps.purchasing.tests.factories import draft_order, line, raw_material
from apps.quality import services as quality
from apps.quality.models import QualityDecision
from apps.reporting import dashboards, selectors
from apps.workflow import services as workflow

pytestmark = pytest.mark.django_db
D = Decimal


def by(rows, key, value):
    return [r for r in rows if r[key] == value]


def test_reports_follow_the_chain(chain, staff):
    today = timezone.localdate()
    period = {"date_from": today, "date_to": today}

    # Üretim: verim 950/1000, LAS satırı %10 sapma (tolerans dışı) ve notu.
    [batch] = selectors.production(period)
    assert batch["batch_no"] == chain.batch.batch_no
    assert batch["yield_pct"] == D("95.00")
    assert batch["deviation_count"] == 1
    assert batch["max_deviation_pct"] == D("10.00")
    assert batch["deviation_notes"] == "Fazla tartıldı"
    assert batch["lot_status"] == "Serbest"
    assert selectors.production({"date_from": today + timedelta(1)}) == []

    # Dolum: 975 sağlam + 25 fire → %2,5 fire.
    [run] = selectors.filling(period)
    assert run["good_units"] == 975
    assert run["scrap_units"] == D("25")
    assert run["scrap_rate"] == D("2.50")
    assert run["actual_bulk"] == D("780")
    summary = dict((k, v) for k, v, _ in selectors.filling_summary([run]))
    assert summary["scrap_rate"] == D("2.50")

    # QC: 5 karar (3 giriş, bulk, mamul); biri red ve spec dışı sonucu yok.
    samples = selectors.quality(period)
    assert len(samples) == 5
    [rejected] = by(samples, "decision_code", "REJECT")
    assert rejected["lot_no"] == chain.rejected_lot.lot_no
    summary = {k: v for k, v, _ in selectors.quality_summary(samples)}
    assert summary["rejected_count"] == 1
    assert summary["rejection_rate"] == D("20.00")
    assert selectors.quality({**period, "decision": "REJECT"}) == [rejected]

    # Sevkiyat: 600 adet, aynı gün sevk → zamanında.
    [shipped] = selectors.shipments(period)
    assert shipped["number"] == chain.shipment.number
    assert shipped["shipped_quantity"] == D("600")
    assert shipped["on_time"] is True
    assert shipped["lots"] == chain.run.output_lot.lot_no

    # Stok hareketleri: tek malzeme filtresinde giriş / çıkış toplamı.
    rows = selectors.stock_movements({**period, "material": chain.plant.las})
    totals = {k: v for k, v, _ in selectors.stock_movements_summary(rows)}
    assert totals["inbound"] > 0 and totals["outbound"] < 0
    assert all("LAS" in r["material"] for r in rows)
    assert len(rows.page(0, 2)) == 2

    # Stok durumu: mamul deposundaki kalan 375 adet; tutar sütunu hesaplanır (gösterim API'de).
    finished = by(selectors.stock_status({}), "lot_no", chain.run.output_lot.lot_no)
    assert sum(r["quantity"] for r in finished) == D("375")
    assert_stock_invariants()


def test_task_durations_and_bottleneck(chain, staff):
    now = timezone.now()
    late = workflow.create_task(
        staff[PLANLAMA],
        title="Tank etiketini değiştir",
        role=DEPO,
        due_at=now - timedelta(hours=5),
    )
    rows = selectors.task_durations({})
    manual = [r for r in rows if r["task_kind"] == selectors.MANUAL_TASK]
    assert manual and manual[0]["overdue"] == 1 and manual[0]["role"] == "Depo"
    kinds = {r["task_kind"] for r in rows}
    assert "Toplama yap" in kinds and "Sevki onayla / irsaliye kes" in kinds
    summary = {k: v for k, v, _ in selectors.task_durations_summary(rows)}
    assert summary["overdue_count"] == 1
    assert summary["bottleneck"]

    tasks = dashboards.overdue_tasks()
    [depo] = [r for r in tasks["by_role"] if r["role"] == DEPO]
    assert depo["overdue"] == 1 and depo["max_delay_hours"] >= D("5")
    assert late.pk


def test_dashboards_follow_the_chain(chain):
    data = dashboards.management_dashboard(show_costs=False)
    today = data["production"]["today"]
    assert today["bulk"] == [{"unit": "KG", "quantity": D("950"), "batches": 1}]
    assert today["units"] == 975
    assert data["scrap"]["rate"] == D("2.50")
    assert data["stock_value"] is None
    assert data["qc_pending"]["sample_count"] == 0
    assert dashboards.management_dashboard(show_costs=True)["stock_value"]["total"] >= 0
    # Son 14 gün: eskiden yeniye, bugünün çıktısı son günde; üretim olmayan günler sıfır.
    daily = data["daily"]
    assert len(daily) == 14
    assert daily[-1]["date"] == data["date"]
    assert daily[0]["date"] == data["date"] - timedelta(days=13)
    assert daily[-1]["bulk"] == [{"unit": "KG", "quantity": D("950")}]
    assert daily[-1]["units"] == 975
    assert all(day["bulk"] == [] and day["units"] == 0 for day in daily[:-1])
    assert data["shipping"] == {"dispatched_today": 1, "late_orders": 0}
    assert data["approvals"] == {
        "conditional_acceptance": {"count": 0, "oldest_wait_hours": None},
        "purchase_orders": {"count": 0, "total_try": None},
    }

    tanks = dashboards.production_dashboard()["tanks"]
    assert {t["state"] for t in tanks} <= {"EMPTY", "FILLED", "IN_BATCH"}
    shipping = dashboards.shipping_dashboard()
    assert shipping["dispatched_today"] == 1
    lab = dashboards.lab_dashboard()
    assert lab["last_30_days"] == {"decided": 5, "rejected": 1, "rejection_rate": D("20.00")}
    warehouse = dashboards.warehouse_dashboard()
    assert warehouse["shipment_picking"] == []


def test_management_dashboard_shows_pending_approvals(db, make_user, commit):
    buyer = make_user(SATIN_ALMA)
    lab = make_user(LABORATUVAR)
    order = draft_order(buyer, [line(raw_material(), quantity="500", price="12")])
    purchasing.submit_for_approval(buyer, order)
    lot = stocked_lot("10", status=Lot.Status.QUARANTINE)
    with commit():
        sample = quality.open_sample(lab, lot, "INCOMING")
    QualityDecision.objects.create(
        sample=sample,
        decision=QualityDecision.Decision.CONDITIONAL_RELEASE,
        reason="pH sınırda",
        decided_by=lab,
        decided_at=timezone.now() - timedelta(hours=5),
        approval_status=QualityDecision.Approval.PENDING,
    )

    approvals = dashboards.management_dashboard(show_costs=True)["approvals"]

    order.refresh_from_db()
    assert approvals["purchase_orders"] == {"count": 1, "total_try": order.approval_total_try}
    assert order.approval_total_try == D("6000")
    conditional = approvals["conditional_acceptance"]
    assert conditional["count"] == 1
    assert D("5") <= conditional["oldest_wait_hours"] < D("6")
    # Tutar yalnızca yönetim ve admin'e (D-15): diğer rolde toplam yok, sayı var.
    hidden = dashboards.management_dashboard(show_costs=False)["approvals"]["purchase_orders"]
    assert hidden == {"count": 1, "total_try": None}


def test_lab_queue_and_tank_in_batch(db, staff, commit):
    lot = stocked_lot("10", status=Lot.Status.QUARANTINE)
    with commit():
        quality.open_sample(staff["laboratuvar"], lot, "INCOMING")
    lab = dashboards.lab_dashboard()
    assert lab["summary"]["sample_count"] == 1
    assert lab["queue"][0]["lot_no"] == lot.lot_no
    assert dashboards.qc_pending()["lot_count"] == 1


def test_dashboards_show_maintenance_and_hse(db, make_user):
    from apps.core.roles import URETIM
    from apps.hse import services as hse
    from apps.hse.models import Incident
    from apps.maintenance import services as maintenance
    from apps.masterdata.models import Equipment
    from apps.masterdata.tests.factories import EquipmentFactory

    operator = make_user(URETIM)
    tank = EquipmentFactory.create(equipment_type=Equipment.Type.MIXING_TANK)
    maintenance.report_breakdown(operator, tank, "Karıştırıcı arızalı")
    hse.report_incident(
        operator,
        {
            "incident_type": Incident.Type.WORK_ACCIDENT,
            "occurred_at": timezone.now() - timedelta(hours=1),
            "place": "Tank başı",
            "description": "Kayma",
            "injury": True,
            "injured_person": "Operatör",
        },
    )
    [row] = [t for t in dashboards.production_dashboard()["tanks"] if t["id"] == tank.pk]
    assert row["downtime"]["reason"] == "BREAKDOWN"
    data = dashboards.management_dashboard(show_costs=False)
    assert data["maintenance"]["open_work_orders"] == 1
    assert data["maintenance"]["open_downtimes"] == 1
    assert data["hse"] == {"days": 30, "incidents": 1, "injuries": 1, "open_incidents": 1}
