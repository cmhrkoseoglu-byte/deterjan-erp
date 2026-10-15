"""Üretim servisleri: emir, hazırlama, şarj, tartım, bitiş ve kapanış (CLAUDE.md §7)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.inventory import services as inventory
from apps.inventory.models import Lot, LotLink, StockMovement
from apps.inventory.services import current_balance
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.models import Location
from apps.masterdata.tests.factories import EquipmentFactory, LocationFactory
from apps.production import selectors, services
from apps.production.models import ProductionBatch, ProductionOrder
from apps.production.state import production_batch_states, production_order_states
from apps.production.tests.factories import (
    approved_order,
    order_data,
    pick_all,
    ready_order,
    weigh_all,
)
from apps.recipes import services as recipes

pytestmark = pytest.mark.usefixtures("invariants")
Status = ProductionOrder.Status
D = Decimal


def names(published):
    return [event.name for event in published]


# --- durum makinesi ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("DRAFT", "APPROVED"),
        ("DRAFT", "CANCELLED"),
        ("APPROVED", "MATERIAL_PREP"),
        ("APPROVED", "CANCELLED"),
        ("MATERIAL_PREP", "MATERIAL_READY"),
        ("MATERIAL_PREP", "CANCELLED"),
        ("MATERIAL_READY", "IN_PRODUCTION"),
        ("IN_PRODUCTION", "QC_PENDING"),
        ("QC_PENDING", "COMPLETED"),
    ],
)
def test_order_state_machine_allows(from_state, to_state):
    assert production_order_states.can_transition(from_state, to_state)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("DRAFT", "MATERIAL_PREP"),
        ("MATERIAL_READY", "CANCELLED"),
        ("IN_PRODUCTION", "CANCELLED"),
        ("QC_PENDING", "IN_PRODUCTION"),
        ("COMPLETED", "CANCELLED"),
        ("CANCELLED", "DRAFT"),
    ],
)
def test_order_state_machine_forbids(from_state, to_state):
    assert not production_order_states.can_transition(from_state, to_state)
    with pytest.raises(BusinessRuleError) as exc:
        production_order_states.assert_can_transition(from_state, to_state)
    assert exc.value.code == "invalid_transition"


def test_batch_state_machine():
    assert production_batch_states.can_transition("IN_PROGRESS", "COMPLETED")
    assert production_batch_states.can_transition("IN_PROGRESS", "CANCELLED")
    assert not production_batch_states.can_transition("COMPLETED", "CANCELLED")
    assert not production_batch_states.can_transition("CANCELLED", "IN_PROGRESS")


# --- emir --------------------------------------------------------------------------------------


def test_create_order_pins_approved_version_and_defaults(plant, planner):
    order = services.create_order(planner, order_data(plant, "2000"))

    assert order.number.startswith("UE-")
    assert order.status == Status.DRAFT
    assert order.product == plant.product
    assert order.recipe_version == plant.version
    assert order.planned_base_quantity == D("2000")
    assert order.production_location == plant.production
    assert AuditLog.objects.filter(object_id=order.pk, action=AuditLog.Action.CREATE).exists()


def test_create_order_requires_approved_version(plant, planner):
    draft = recipes.copy_version(planner, plant.version)

    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(plant, recipe_version=draft))
    assert exc.value.code == "recipe_version_not_approved"


def test_create_order_requires_mixing_tank(plant, planner):
    filler = EquipmentFactory(equipment_type="FILLING_LINE", location=None, capacity=None)

    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(plant, equipment=filler))
    assert exc.value.code == "invalid_equipment"


def test_create_order_requires_production_location(plant, planner):
    plant.production.is_active = False
    plant.production.save()

    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(plant))
    assert exc.value.code == "production_location_required"


def test_only_planning_creates_orders(plant, depo):
    with pytest.raises(PermissionDenied):
        services.create_order(depo, order_data(plant))


def test_update_order_only_in_draft(plant, planner):
    order = services.create_order(planner, order_data(plant))
    services.update_order(planner, order, {"planned_quantity": D("1500")})
    order.refresh_from_db()
    assert order.planned_base_quantity == D("1500")

    services.approve_order(planner, order)
    with pytest.raises(BusinessRuleError) as exc:
        services.update_order(planner, order, {"notes": "x"})
    assert exc.value.code == "document_locked"


def test_approve_scales_requirements_and_publishes(plant, planner, commit, published):
    order = services.create_order(planner, order_data(plant, "2000"))
    with commit():
        services.approve_order(planner, order)

    rows = {r.material.code: r for r in order.requirements.all()}
    assert rows["LAS"].required_quantity == D("1200")
    assert rows["SLES"].required_quantity == D("600")
    assert rows["SU"].required_quantity == D("200")
    assert rows["SU"].is_water
    assert rows["LAS"].instruction == "Yavaşça ekle"
    event = next(e for e in published if e.name == ev.PRODUCTION_ORDER_APPROVED)
    assert event.payload["number"] == order.number
    assert event.payload["priority"] == ProductionOrder.Priority.NORMAL

    with pytest.raises(BusinessRuleError) as exc:
        services.approve_order(planner, order)
    assert exc.value.code == "invalid_transition"


def test_approve_rejects_obsolete_version(plant, planner):
    order = services.create_order(planner, order_data(plant))
    copy = recipes.copy_version(planner, plant.version)
    recipes.approve_version(planner, copy)

    with pytest.raises(BusinessRuleError) as exc:
        services.approve_order(planner, order)
    assert exc.value.code == "recipe_version_not_approved"


# --- hazırlama ---------------------------------------------------------------------------------


def test_pick_transfers_to_production_location_and_starts_prep(plant, planner, depo):
    order = approved_order(plant, planner)
    las = plant.requirement(order, plant.las)

    pick = services.pick_material(depo, order, las, plant.lots["las"], D("600"))

    order.refresh_from_db()
    assert order.status == Status.MATERIAL_PREP
    assert pick.from_location == plant.storage
    assert current_balance(plant.lots["las"], plant.production) == D("600")
    assert current_balance(plant.lots["las"], plant.storage) == D("4400")
    moves = StockMovement.objects.filter(transfer_group=pick.transfer_group)
    assert {m.document_number for m in moves} == {order.number}


def test_quarantine_lot_cannot_be_picked(plant, planner, depo):
    order = approved_order(plant, planner)
    quarantined = stocked_lot(
        "500", material=plant.las, location=plant.quarantine, status=Lot.Status.QUARANTINE
    )

    with pytest.raises(BusinessRuleError) as exc:
        services.pick_material(
            depo, order, plant.requirement(order, plant.las), quarantined, D("1")
        )
    assert exc.value.code == "lot_not_released"


def test_expired_lot_cannot_be_picked(plant, planner, depo):
    order = approved_order(plant, planner)
    expired = stocked_lot(
        "500",
        material=plant.las,
        location=plant.storage,
        expiry_date=timezone.localdate() - timedelta(days=1),
    )

    with pytest.raises(BusinessRuleError) as exc:
        services.pick_material(depo, order, plant.requirement(order, plant.las), expired, D("1"))
    assert exc.value.code == "lot_expired"


def test_pick_rules(plant, planner, depo, operator):
    order = approved_order(plant, planner)
    las = plant.requirement(order, plant.las)
    water = plant.requirement(order, plant.water)

    with pytest.raises(BusinessRuleError) as exc:
        services.pick_material(depo, order, las, plant.lots["sles"], D("1"))
    assert exc.value.code == "lot_material_mismatch"
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_material(depo, order, las, plant.lots["las"], D("1201"))
    assert exc.value.code == "pick_exceeds_requirement"
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_material(depo, order, water, plant.lots["water"], D("100"))
    assert exc.value.code == "water_not_picked"
    with pytest.raises(PermissionDenied):
        services.pick_material(operator, order, las, plant.lots["las"], D("1"))


def test_pick_suggestions_are_fefo_and_released_only(plant, planner):
    order = approved_order(plant, planner)
    soon = stocked_lot(
        "50",
        material=plant.las,
        location=plant.storage,
        expiry_date=timezone.localdate() + timedelta(days=5),
    )
    stocked_lot("50", material=plant.las, location=plant.quarantine, status=Lot.Status.QUARANTINE)

    rows = list(selectors.pick_suggestions(order, plant.requirement(order, plant.las)))

    assert [row.lot for row in rows] == [soon, plant.lots["las"]]


def test_mark_ready_requires_all_materials(plant, planner, depo, commit, published):
    order = approved_order(plant, planner)
    services.pick_material(
        depo, order, plant.requirement(order, plant.las), plant.lots["las"], D("600")
    )

    with pytest.raises(BusinessRuleError) as exc:
        services.mark_material_ready(depo, order)
    assert exc.value.code == "material_not_ready"
    assert "SLES" in exc.value.message

    # Tolerans içindeki eksik (%2) kabul edilir.
    sles = plant.requirement(order, plant.sles)
    services.pick_material(depo, order, sles, plant.lots["sles"], D("295"))
    with commit():
        services.mark_material_ready(depo, order)
    order.refresh_from_db()
    assert order.status == Status.MATERIAL_READY
    assert ev.PRODUCTION_ORDER_MATERIAL_READY in names(published)


def test_cancel_in_prep_returns_picked_material(plant, planner, depo, commit, published):
    order = approved_order(plant, planner)
    pick_all(plant, order, depo)

    with commit():
        services.cancel_order(planner, order, "Plan değişti")

    order.refresh_from_db()
    assert order.status == Status.CANCELLED
    assert current_balance(plant.lots["las"], plant.production) == 0
    assert current_balance(plant.lots["las"], plant.storage) == D("5000")
    assert not order.picks.filter(returned_at__isnull=True).exists()
    assert ev.PRODUCTION_ORDER_CANCELLED in names(published)


def test_cancel_rules(plant, planner, depo):
    order = ready_order(plant, planner, depo)
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_order(planner, order, "Geç kaldı")
    assert exc.value.code == "invalid_transition"

    draft = services.create_order(planner, order_data(plant))
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_order(planner, draft, " ")
    assert exc.value.code == "cancel_reason_required"
    with pytest.raises(PermissionDenied):
        services.cancel_order(depo, draft, "x")


# --- şarj (D-4) --------------------------------------------------------------------------------


def test_start_batch_opens_quarantine_output_lot(plant, planner, depo, operator, commit, published):
    order = ready_order(plant, planner, depo)
    with commit():
        batch = services.start_batch(operator, order)

    order.refresh_from_db()
    assert order.status == Status.IN_PRODUCTION
    assert batch.batch_no.startswith("B-")
    assert batch.output_lot.lot_no == batch.batch_no
    assert batch.output_lot.status == Lot.Status.QUARANTINE
    assert batch.output_lot.source == Lot.Source.PRODUCTION
    assert batch.planned_quantity == D("1000")
    event = next(e for e in published if e.name == ev.PRODUCTION_BATCH_STARTED)
    assert event.payload["order"]["number"] == order.number


def test_order_larger_than_tank_is_split(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo, "1500")

    assert services.suggested_batch_quantity(order) == D("1000")
    with pytest.raises(BusinessRuleError) as exc:
        services.start_batch(operator, order, planned_quantity=D("1200"))
    assert exc.value.code == "batch_exceeds_capacity"

    first = services.start_batch(operator, order)
    assert first.planned_quantity == D("1000")
    with pytest.raises(BusinessRuleError) as exc:
        services.start_batch(operator, order)
    assert exc.value.code == "equipment_busy"
    with pytest.raises(BusinessRuleError) as exc:
        services.start_batch(operator, order, plant.tank2, D("600"))
    assert exc.value.code == "batch_exceeds_order"

    second = services.start_batch(operator, order, plant.tank2)
    assert second.planned_quantity == D("500")
    assert second.sequence == 2
    with pytest.raises(BusinessRuleError) as exc:
        services.start_batch(operator, order, plant.tank2)
    assert exc.value.code in ("equipment_busy", "order_fully_batched")


def test_start_batch_rules(plant, planner, depo, operator):
    order = approved_order(plant, planner)
    with pytest.raises(BusinessRuleError) as exc:
        services.start_batch(operator, order)
    assert exc.value.code == "order_not_ready"
    with pytest.raises(PermissionDenied):
        services.start_batch(depo, order)


# --- tartım ------------------------------------------------------------------------------------


def test_consumption_issues_stock_and_links_lots(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    las = plant.requirement(order, plant.las)

    record = services.record_consumption(operator, batch, las, plant.lots["las"], D("600"))

    assert record.deviation_pct == D("0")
    assert record.movement.movement_type == StockMovement.Type.ISSUE_PRODUCTION
    assert record.movement.quantity == D("-600")
    assert record.location == plant.production
    assert current_balance(plant.lots["las"], plant.production) == 0
    link = LotLink.objects.get()
    assert (link.parent_lot, link.child_lot, link.quantity) == (
        plant.lots["las"],
        batch.output_lot,
        D("600"),
    )


def test_water_is_consumed_from_its_own_location(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)

    record = services.record_consumption(
        operator, batch, plant.requirement(order, plant.water), plant.lots["water"], D("100")
    )

    assert record.location == plant.storage
    assert current_balance(plant.lots["water"], plant.storage) == D("9900")


def test_over_tolerance_requires_note_and_publishes_deviation(
    plant, planner, depo, operator, commit, published
):
    order = approved_order(plant, planner)
    las = plant.requirement(order, plant.las)
    services.pick_material(depo, order, las, plant.lots["las"], D("700"))
    services.pick_material(
        depo, order, plant.requirement(order, plant.sles), plant.lots["sles"], D("300")
    )
    services.mark_material_ready(depo, order)
    batch = services.start_batch(operator, order)

    with pytest.raises(BusinessRuleError) as exc:
        services.record_consumption(operator, batch, las, plant.lots["las"], D("650"))
    assert exc.value.code == "deviation_note_required"

    with commit():
        record = services.record_consumption(
            operator, batch, las, plant.lots["las"], D("650"), note="Kova fazla döküldü"
        )
    assert record.deviation_pct == D("8.33")
    event = next(e for e in published if e.name == ev.PRODUCTION_DEVIATION)
    assert event.payload["material_code"] == "LAS"
    assert event.payload["deviation_pct"] == "8,33"
    assert event.payload["note"] == "Kova fazla döküldü"


def test_consumption_cannot_go_negative(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)

    with pytest.raises(BusinessRuleError) as exc:
        services.record_consumption(
            operator, batch, plant.requirement(order, plant.las), plant.lots["las"], D("601"), "x"
        )
    assert exc.value.code == "negative_stock"
    assert not batch.consumptions.exists()


def test_quarantine_lot_cannot_be_consumed(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    quarantined = stocked_lot(
        "50", material=plant.las, location=plant.quarantine, status=Lot.Status.QUARANTINE
    )
    # Karantinadaki lot depo içinde taşınabilir ama tüketilemez.
    inventory.transfer(depo, quarantined, plant.quarantine, plant.production, D("50"))

    with pytest.raises(BusinessRuleError) as exc:
        services.record_consumption(
            operator, batch, plant.requirement(order, plant.las), quarantined, D("10")
        )
    assert exc.value.code == "lot_not_released"


def test_consumption_needs_open_batch_and_operator(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    las = plant.requirement(order, plant.las)
    with pytest.raises(PermissionDenied):
        services.record_consumption(depo, batch, las, plant.lots["las"], D("1"))

    services.cancel_batch(operator, batch, "Yanlış tank")
    with pytest.raises(BusinessRuleError) as exc:
        services.record_consumption(operator, batch, las, plant.lots["las"], D("1"))
    assert exc.value.code == "batch_not_in_progress"


# --- şarj bitişi ve emir kapanışı --------------------------------------------------------------


def test_finish_batch_posts_output_and_awaits_qc(plant, planner, depo, operator, commit, published):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    weigh_all(plant, batch, operator)

    with commit():
        services.finish_batch(operator, batch, D("990"))

    batch.refresh_from_db()
    order.refresh_from_db()
    assert batch.status == ProductionBatch.Status.COMPLETED
    assert batch.yield_pct == D("99.00")
    assert current_balance(batch.output_lot, plant.tank.location) == D("990")
    assert order.status == Status.QC_PENDING
    event = next(e for e in published if e.name == ev.PRODUCTION_BATCH_COMPLETED)
    assert event.payload["output_lot"]["lot_no"] == batch.batch_no
    assert ev.PRODUCTION_LOW_YIELD not in names(published)


def test_low_yield_publishes_event(plant, planner, depo, operator, commit, published):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    weigh_all(plant, batch, operator)

    with commit():
        services.finish_batch(operator, batch, D("950"))

    event = next(e for e in published if e.name == ev.PRODUCTION_LOW_YIELD)
    assert event.payload["yield_pct"] == "95"
    assert event.payload["threshold_pct"] == "97"


def test_finish_with_short_line_requires_note(plant, planner, depo, operator, commit, published):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    services.record_consumption(
        operator, batch, plant.requirement(order, plant.las), plant.lots["las"], D("600")
    )

    with pytest.raises(BusinessRuleError) as exc:
        services.finish_batch(operator, batch, D("600"))
    assert exc.value.code == "deviation_note_required"
    assert "SLES" in exc.value.message and "SU" in exc.value.message

    with commit():
        services.finish_batch(operator, batch, D("600"), note="SLES bitti, eksik üretildi")
    deviations = [e for e in published if e.name == ev.PRODUCTION_DEVIATION]
    assert {e.payload["material_code"] for e in deviations} == {"SLES", "SU"}


def test_finish_rules(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    with pytest.raises(BusinessRuleError) as exc:
        services.finish_batch(operator, batch, D("1000"))
    assert exc.value.code == "batch_has_no_consumption"

    weigh_all(plant, batch, operator)
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_batch(operator, batch, "x")
    assert exc.value.code == "batch_has_consumption"
    with pytest.raises(BusinessRuleError) as exc:
        services.finish_batch(operator, batch, D("0"))
    assert exc.value.code == "invalid_quantity"


def test_cancel_batch_returns_quantity_to_order(plant, planner, depo, operator):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)

    batch = services.cancel_batch(operator, batch, "Yanlış tank")

    assert batch.status == ProductionBatch.Status.CANCELLED
    assert services.remaining_quantity(order) == D("1000")
    services.start_batch(operator, order, plant.tank2)


def test_order_completes_when_output_lot_released(
    plant, planner, depo, operator, lab, commit, published
):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    weigh_all(plant, batch, operator)
    services.finish_batch(operator, batch, D("1000"))

    with pytest.raises(BusinessRuleError) as exc:
        services.complete_order(planner, order)
    assert exc.value.code == "output_lots_not_released"

    with commit():
        inventory.release_lot(lab, batch.output_lot, "Analiz uygun")

    order.refresh_from_db()
    assert order.status == Status.COMPLETED
    assert order.completed_at is not None
    assert "production_order.completed" in names(published)


def test_split_order_completes_after_all_batches(plant, planner, depo, operator, lab, commit):
    order = ready_order(plant, planner, depo, "1500")
    first = services.start_batch(operator, order)
    second = services.start_batch(operator, order, plant.tank2)
    weigh_all(plant, first, operator)
    services.finish_batch(operator, first, D("1000"))
    order.refresh_from_db()
    assert order.status == Status.IN_PRODUCTION

    weigh_all(plant, second, operator)
    services.finish_batch(operator, second, D("500"))
    order.refresh_from_db()
    assert order.status == Status.QC_PENDING

    with commit():
        inventory.release_lot(lab, first.output_lot)
    order.refresh_from_db()
    assert order.status == Status.QC_PENDING

    with commit():
        inventory.release_lot(lab, second.output_lot)
    order.refresh_from_db()
    assert order.status == Status.COMPLETED


def test_rejected_output_lot_keeps_order_waiting(plant, planner, depo, operator, lab, commit):
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    weigh_all(plant, batch, operator)
    services.finish_batch(operator, batch, D("1000"))

    with commit():
        inventory.reject_lot(lab, batch.output_lot, "Viskozite düşük")

    order.refresh_from_db()
    assert order.status == Status.QC_PENDING


def test_production_location_is_any_production_type(plant, planner):
    other = LocationFactory(warehouse=plant.warehouse, location_type=Location.Type.STORAGE)
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(plant, production_location=other))
    assert exc.value.code == "invalid_production_location"
