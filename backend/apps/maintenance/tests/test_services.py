from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.inventory.models import Lot, StockMovement
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.maintenance import selectors, services
from apps.maintenance.models import Downtime, MaintenanceKind, MaintenanceWorkOrder
from apps.maintenance.state import work_order_states
from apps.maintenance.tests.factories import plan, run_batch, scale, second_product
from apps.masterdata.models import Equipment
from apps.masterdata.tests.factories import EquipmentFactory, MaterialFactory
from apps.production import services as production
from apps.production.tests.factories import order_data, ready_order
from apps.workflow.models import Notification, Task

pytestmark = pytest.mark.django_db

Status = MaintenanceWorkOrder.Status


# --- durum makinesi ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("OPEN", "IN_PROGRESS"),
        ("OPEN", "COMPLETED"),
        ("OPEN", "CANCELLED"),
        ("IN_PROGRESS", "COMPLETED"),
        ("IN_PROGRESS", "CANCELLED"),
    ],
)
def test_work_order_allowed_transitions(source, target):
    assert work_order_states.can_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [("COMPLETED", "OPEN"), ("CANCELLED", "OPEN"), ("COMPLETED", "CANCELLED")],
)
def test_work_order_forbidden_transitions(source, target):
    with pytest.raises(BusinessRuleError) as exc:
        work_order_states.assert_can_transition(source, target)
    assert exc.value.code == "invalid_transition"


# --- plan --------------------------------------------------------------------------------------


def test_create_plan_defaults_next_due_and_role(operator, lab):
    tank = EquipmentFactory.create()
    created = plan(operator, tank)
    assert created.next_due_date == timezone.localdate() + timedelta(days=30)
    assert created.responsible_role == "uretim"
    assert created.checklist == ["Conta kontrolü", "Yağlama"]
    calibration = plan(lab, scale(), kind=MaintenanceKind.CALIBRATION, title="Kalibrasyon")
    assert calibration.responsible_role == "laboratuvar"
    assert AuditLog.objects.filter(object_id=str(created.pk), action="create").exists()


def test_plan_needs_exactly_one_interval(operator):
    with pytest.raises(BusinessRuleError) as exc:
        plan(operator, EquipmentFactory.create(), interval_runs=10)
    assert exc.value.code == "invalid_interval"


def test_calibration_plan_only_for_scales(lab):
    with pytest.raises(BusinessRuleError) as exc:
        plan(lab, EquipmentFactory.create(), kind=MaintenanceKind.CALIBRATION)
    assert exc.value.code == "calibration_scale_only"


def test_plan_requires_maintenance_role(depo):
    with pytest.raises(PermissionDenied):
        plan(depo, EquipmentFactory.create())


def test_update_and_deactivate_plan(operator):
    created = plan(operator, EquipmentFactory.create())
    updated = services.update_plan(operator, created, {"title": "Haftalık bakım"})
    assert updated.title == "Haftalık bakım"
    assert not services.set_plan_active(operator, updated, False).is_active


# --- günlük kontrol ve iş emri -----------------------------------------------------------------


def test_daily_check_opens_work_order_for_due_plan_once(operator, commit):
    tank = EquipmentFactory.create()
    due = plan(operator, tank, next_due_date=timezone.localdate() + timedelta(days=3))
    plan(operator, tank, title="Uzak", next_due_date=timezone.localdate() + timedelta(days=40))
    with commit():
        created = services.create_due_work_orders()
    assert [o.plan_id for o in created] == [due.pk]
    order = created[0]
    assert order.number.startswith("BK-")
    assert order.status == Status.OPEN
    assert [row["item"] for row in order.checklist] == ["Conta kontrolü", "Yağlama"]
    task = Task.objects.get(rule_code="maintenance_work_order_uretim")
    assert order.number in task.title
    assert services.create_due_work_orders() == []


def test_overdue_plan_notifies_management(operator, manager, commit):
    plan(
        operator, EquipmentFactory.create(), next_due_date=timezone.localdate() - timedelta(days=1)
    )
    with commit():
        services.create_due_work_orders()
    notification = Notification.objects.get(recipient=manager)
    assert notification.title == "Süresi geçmiş bakım: 1 plan"


def test_run_based_plan_due_after_batches(plant, planner, depo, operator, commit):
    created = plan(operator, plant.tank, interval_days=None, interval_runs=2)
    assert selectors.plan_status(created).runs_done == 0
    run_batch(plant, planner, depo, operator)
    assert not selectors.plan_status(created).is_due
    run_batch(plant, planner, depo, operator)
    status = selectors.plan_status(created)
    assert (status.runs_done, status.is_due) == (2, True)
    with commit():
        [order] = services.create_due_work_orders()
    services.complete_work_order(
        operator, order, work_done="Karıştırıcı bakımı", checklist=[{"done": True}] * 2
    )
    created.refresh_from_db()
    assert created.last_done_at is not None
    assert selectors.plan_status(created).runs_done == 0


def test_complete_work_order_advances_plan_and_closes_task(operator, commit):
    tank = EquipmentFactory.create()
    created = plan(operator, tank, next_due_date=timezone.localdate())
    with commit():
        [order] = services.create_due_work_orders()
        services.start_work_order(operator, order)
        done = services.complete_work_order(
            operator,
            order,
            work_done="Contalar değişti",
            duration_minutes=45,
            checklist=[{"done": True}, {"done": True, "note": "yağ eklendi"}],
        )
    assert done.status == Status.COMPLETED
    assert done.checklist[1]["note"] == "yağ eklendi"
    created.refresh_from_db()
    assert created.next_due_date == timezone.localdate() + timedelta(days=30)
    assert Task.objects.get(rule_code="maintenance_work_order_uretim").status == "DONE"


def test_complete_requires_checklist_and_work_done(operator):
    order = services.create_work_order(
        operator,
        {
            "equipment": EquipmentFactory.create(),
            "title": "Pompa kontrolü",
            "checklist": ["Ses kontrolü"],
        },
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.complete_work_order(operator, order, work_done="")
    assert exc.value.code == "work_done_required"
    with pytest.raises(BusinessRuleError) as exc:
        services.complete_work_order(operator, order, work_done="Yapıldı")
    assert exc.value.code == "checklist_incomplete"


def test_only_responsible_role_runs_work_order(operator, filler, manager):
    order = services.create_work_order(
        operator, {"equipment": EquipmentFactory.create(), "title": "Kontrol"}
    )
    with pytest.raises(PermissionDenied):
        services.start_work_order(filler, order)
    assert services.start_work_order(manager, order).status == Status.IN_PROGRESS


def test_cancel_work_order_needs_reason(operator):
    order = services.create_work_order(
        operator, {"equipment": EquipmentFactory.create(), "title": "Kontrol"}
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_work_order(operator, order, " ")
    assert exc.value.code == "cancel_reason_required"
    assert services.cancel_work_order(operator, order, "Gerek kalmadı").status == Status.CANCELLED


def test_spare_part_from_stock_posts_issue_movement(operator, invariants):
    location = storage_location()
    part = MaterialFactory.create(code="CONTA", name="Pompa contası")
    lot = stocked_lot("10", material=part, location=location)
    order = services.create_work_order(
        operator, {"equipment": EquipmentFactory.create(), "title": "Pompa"}
    )
    added = services.add_part(
        operator, order, quantity=Decimal("2"), material=part, lot=lot, location=location
    )
    movement = StockMovement.objects.get(pk=added.movement_id)
    assert movement.movement_type == StockMovement.Type.ISSUE_MAINTENANCE
    assert movement.quantity == Decimal("-2")
    free = services.add_part(operator, order, quantity=Decimal("1"), description="Kayış")
    assert free.movement is None
    with pytest.raises(BusinessRuleError) as exc:
        services.add_part(
            operator, order, quantity=Decimal("20"), material=part, lot=lot, location=location
        )
    assert exc.value.code == "negative_stock"
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_work_order(operator, order, "vazgeçildi")
    assert exc.value.code == "work_order_has_parts"


def test_spare_part_lot_must_be_released(operator, invariants):
    part = MaterialFactory.create()
    location = storage_location()
    lot = stocked_lot("5", material=part, location=location, status=Lot.Status.QUARANTINE)
    order = services.create_work_order(
        operator, {"equipment": EquipmentFactory.create(), "title": "Pompa"}
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.add_part(
            operator, order, quantity=Decimal("1"), material=part, lot=lot, location=location
        )
    assert exc.value.code == "lot_not_released"


# --- duruş -------------------------------------------------------------------------------------


def test_breakdown_opens_work_order_and_downtime(depo, operator, planner, commit):
    tank = EquipmentFactory.create()
    with commit():
        order = services.report_breakdown(depo, tank, "Karıştırıcı motoru çalışmıyor")
    assert order.source == MaintenanceWorkOrder.Source.BREAKDOWN
    assert order.responsible_role == "uretim"
    downtime = selectors.open_downtime(tank)
    assert downtime is not None and downtime.work_order_id == order.pk
    assert Notification.objects.filter(
        recipient=planner, title__startswith="Ekipman durdu"
    ).exists()
    with commit():
        services.complete_work_order(operator, order, work_done="Motor değişti")
    downtime.refresh_from_db()
    assert downtime.ended_at is not None
    assert selectors.open_downtime(tank) is None


def test_breakdown_requires_description(depo):
    with pytest.raises(BusinessRuleError) as exc:
        services.report_breakdown(depo, EquipmentFactory.create(), "")
    assert exc.value.code == "description_required"


def test_only_one_open_downtime(operator):
    tank = EquipmentFactory.create()
    services.start_downtime(operator, tank, Downtime.Reason.NO_MATERIAL)
    with pytest.raises(BusinessRuleError) as exc:
        services.start_downtime(operator, tank, Downtime.Reason.OTHER)
    assert exc.value.code == "downtime_open"


def test_end_downtime_and_summary(operator, published, commit):
    tank = EquipmentFactory.create()
    start = timezone.now() - timedelta(hours=2)
    with commit():
        downtime = services.start_downtime(
            operator, tank, Downtime.Reason.CLEANING, started_at=start
        )
        services.end_downtime(operator, downtime, ended_at=start + timedelta(minutes=90))
    assert [e.name for e in published if e.name.startswith("downtime")] == [
        ev.DOWNTIME_STARTED,
        ev.DOWNTIME_ENDED,
    ]
    today = timezone.localdate()
    [row] = selectors.downtime_summary(today - timedelta(days=1), today)
    assert (row.equipment_code, row.reason, row.count, row.minutes) == (
        tank.code,
        "CLEANING",
        1,
        90,
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.end_downtime(operator, downtime)
    assert exc.value.code == "downtime_closed"


def test_downtime_blocks_order_assignment_and_batch_start(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    services.start_downtime(operator, plant.tank, Downtime.Reason.BREAKDOWN)
    with pytest.raises(BusinessRuleError) as exc:
        production.start_batch(operator, order, plant.tank)
    assert exc.value.code == "equipment_down"
    with pytest.raises(BusinessRuleError) as exc:
        production.create_order(planner, order_data(plant))
    assert exc.value.code == "equipment_down"
    # Diğer tank çalışır.
    production.create_order(planner, order_data(plant, equipment=plant.tank2))


# --- ürün değişimi temizliği (D-14) -------------------------------------------------------------


def test_product_change_requires_cleaning(plant, planner, depo, operator, invariants):
    run_batch(plant, planner, depo, operator)
    other = second_product(plant, planner)
    plant.version, original = other, plant.version
    order = ready_order(plant, planner, depo)
    plant.version = original
    with pytest.raises(BusinessRuleError) as exc:
        production.start_batch(operator, order, plant.tank)
    assert exc.value.code == "cleaning_required"
    assert "BULASIK" in exc.value.message
    cleaning = services.record_cleaning(operator, plant.tank, work_done="Sıcak su ile yıkandı")
    assert cleaning.status == Status.COMPLETED
    assert cleaning.previous_product == plant.product
    assert production.start_batch(operator, order, plant.tank).equipment == plant.tank


def test_same_product_needs_no_cleaning(plant, planner, depo, operator, invariants):
    run_batch(plant, planner, depo, operator)
    order = ready_order(plant, planner, depo)
    assert production.start_batch(operator, order, plant.tank)


def test_changeover_rule_allows_switch_without_cleaning(
    plant, planner, depo, operator, lab, invariants
):
    run_batch(plant, planner, depo, operator)
    other = second_product(plant, planner)
    services.create_changeover_rule(
        lab, {"from_product": plant.product, "to_product": other.recipe.product, "note": "Aynı baz"}
    )
    plant.version, original = other, plant.version
    order = ready_order(plant, planner, depo)
    plant.version = original
    assert production.start_batch(operator, order, plant.tank)


def test_changeover_rule_is_directional(plant, planner, lab):
    other = second_product(plant, planner).recipe.product
    services.create_changeover_rule(lab, {"from_product": plant.product, "to_product": other})
    with pytest.raises(BusinessRuleError) as exc:
        services.create_changeover_rule(lab, {"from_product": plant.product, "to_product": other})
    assert exc.value.code == "duplicate"
    services.create_changeover_rule(lab, {"from_product": other, "to_product": plant.product})


def test_changeover_rule_by_quality_only(plant, planner, operator):
    other = second_product(plant, planner).recipe.product
    with pytest.raises(PermissionDenied):
        services.create_changeover_rule(
            operator, {"from_product": plant.product, "to_product": other}
        )


def test_changeover_rule_bulk_only(lab):
    with pytest.raises(BusinessRuleError) as exc:
        services.create_changeover_rule(
            lab,
            {"from_product": MaterialFactory.create(), "to_product": MaterialFactory.create()},
        )
    assert exc.value.code == "changeover_bulk_only"


# --- kalibrasyon -------------------------------------------------------------------------------


def _calibrated_scale(lab, due: date) -> Equipment:
    terazi = scale()
    plan(lab, terazi, kind=MaintenanceKind.CALIBRATION, title="Kalibrasyon", next_due_date=due)
    return terazi


def _weigh(plant, planner, depo, operator, terazi=None):
    order = ready_order(plant, planner, depo)
    batch = production.start_batch(operator, order, plant.tank)
    requirement = plant.requirement(order, plant.las)
    return production.record_consumption(
        operator, batch, requirement, plant.lots["las"], Decimal("600"), scale=terazi
    )


def test_calibration_status_levels(lab):
    today = timezone.localdate()
    ok = _calibrated_scale(lab, today + timedelta(days=30))
    soon = _calibrated_scale(lab, today + timedelta(days=3))
    late = _calibrated_scale(lab, today - timedelta(days=1))
    none = scale()
    statuses = {row.equipment.pk: row.status for row in selectors.calibration_status()}
    assert statuses == {
        ok.pk: selectors.CAL_OK,
        soon.pk: selectors.CAL_DUE_SOON,
        late.pk: selectors.CAL_OVERDUE,
        none.pk: selectors.CAL_NO_PLAN,
    }


def test_overdue_calibration_blocks_weighing(plant, planner, depo, operator, lab, invariants):
    late = _calibrated_scale(lab, timezone.localdate() - timedelta(days=1))
    with pytest.raises(BusinessRuleError) as exc:
        _weigh(plant, planner, depo, operator, late)
    assert exc.value.code == "calibration_overdue"


def test_due_soon_calibration_warns_but_allows(plant, planner, depo, operator, lab, invariants):
    soon = _calibrated_scale(lab, timezone.localdate() + timedelta(days=2))
    assert services.equipment_guard(soon, "weigh", {}) == [
        f"{soon.code} terazisinin kalibrasyonu 2 gün içinde doluyor."
    ]
    consumption = _weigh(plant, planner, depo, operator, soon)
    assert consumption.scale == soon


def test_scale_required_when_scales_exist(plant, planner, depo, operator, lab, invariants):
    _calibrated_scale(lab, timezone.localdate() + timedelta(days=60))
    with pytest.raises(BusinessRuleError) as exc:
        _weigh(plant, planner, depo, operator)
    assert exc.value.code == "scale_required"


def test_water_needs_no_scale(plant, planner, depo, operator, lab, invariants):
    _calibrated_scale(lab, timezone.localdate() + timedelta(days=60))
    order = ready_order(plant, planner, depo)
    batch = production.start_batch(operator, order, plant.tank)
    water = plant.requirement(order, plant.water)
    consumption = production.record_consumption(
        operator, batch, water, plant.lots["water"], Decimal("100")
    )
    assert consumption.scale is None


def test_failed_calibration_puts_scale_down(plant, planner, depo, operator, lab, invariants):
    terazi = _calibrated_scale(lab, timezone.localdate())
    [order] = services.create_due_work_orders()
    with pytest.raises(BusinessRuleError) as exc:
        services.complete_work_order(
            lab, order, work_done="Ölçüm yapıldı", checklist=[{"done": True}] * 2
        )
    assert exc.value.code == "calibration_result_required"
    services.complete_work_order(
        lab,
        order,
        work_done="Sapma %0,5",
        checklist=[{"done": True}] * 2,
        calibration_result="FAILED",
    )
    downtime = selectors.open_downtime(terazi)
    assert downtime is not None and downtime.reason == Downtime.Reason.CALIBRATION
    with pytest.raises(BusinessRuleError) as exc:
        _weigh(plant, planner, depo, operator, terazi)
    assert exc.value.code == "equipment_down"


def test_passed_calibration_advances_due_date(lab):
    terazi = _calibrated_scale(lab, timezone.localdate())
    [order] = services.create_due_work_orders()
    services.complete_work_order(
        lab,
        order,
        work_done="Uygun",
        checklist=[{"done": True}] * 2,
        calibration_result="PASSED",
        certificate_no="KAL-2026-12",
    )
    status = selectors.scale_calibration(terazi)
    assert status.status == selectors.CAL_OK
    assert status.next_due_date == timezone.localdate() + timedelta(days=30)


def test_settings_only_management(manager, operator):
    assert services.update_settings(manager, {"calibration_warning_days": 14})
    assert selectors.get_settings().calibration_warning_days == 14
    with pytest.raises(PermissionDenied):
        services.update_settings(operator, {"plan_lead_days": 3})


def test_filling_line_downtime_blocks_run(filler, operator):
    line = EquipmentFactory.create(equipment_type=Equipment.Type.FILLING_LINE)
    services.start_downtime(filler, line, Downtime.Reason.BREAKDOWN)
    with pytest.raises(BusinessRuleError) as exc:
        services.equipment_guard(line, "start", {})
    assert exc.value.code == "equipment_down"
