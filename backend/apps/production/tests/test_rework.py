"""Yeniden işleme emri (Faz 2, Adım 2.1): REWORK kararıyla bloke edilen bulk lot, düzeltme
listesiyle ya da reçeteyle harmanlanarak yeniden işlenir; soy ağacı ve asıl emrin kapanışı."""

from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.inventory import selectors as inventory_selectors
from apps.inventory.models import Lot
from apps.inventory.services import current_balance
from apps.masterdata.tests.factories import unit
from apps.production import services
from apps.production.models import ProductionOrder
from apps.production.tests.factories import build_plant, ready_order, weigh_all
from apps.quality.models import QualityDecision, SampleStage
from apps.quality.testing import open_sample_for, pass_sample
from apps.workflow.models import Task

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
Status = ProductionOrder.Status
REWORK = QualityDecision.Decision.REWORK


@pytest.fixture
def plant(planner):
    return build_plant(planner)


@pytest.fixture
def blocked(plant, planner, depo, operator, lab, commit):
    """Şarjı biten, son kontrolde REWORK kararıyla bloke edilen bulk lot (1000 kg, tankta)."""
    order = ready_order(plant, planner, depo)
    with commit():
        batch = services.start_batch(operator, order)
        weigh_all(plant, batch, operator)
        services.finish_batch(operator, batch, D("1000"))
    lot = batch.output_lot
    with commit():
        pass_sample(lab, open_sample_for(lot, SampleStage.FINAL), decision=REWORK)
    lot.refresh_from_db()
    assert lot.status == Lot.Status.BLOCKED
    order.refresh_from_db()
    assert order.status == Status.QC_PENDING
    return order, lot


def rework_data(plant, lot, quantity="1000", **extra):
    return {
        "rework_lot": lot,
        "planned_quantity": D(quantity),
        "unit": unit("KG"),
        "planned_date": date(2026, 10, 21),
        "equipment": plant.tank2,
        **extra,
    }


def run_rework(plant, order, depo, operator, commit, output="1020"):
    """Emri onaylanmış hâlinden şarj bitimine götürür: sabit lot hazırlanmaz, kendi yerinden
    tüketilir; diğer satırlar serbest lotlardan hazırlanıp tartılır."""
    for requirement in order.requirements.exclude(lot__isnull=False).filter(is_water=False):
        lot = Lot.objects.filter(material=requirement.material, status=Lot.Status.RELEASED).first()
        services.pick_material(depo, order, requirement, lot, requirement.required_quantity)
    services.mark_material_ready(depo, order)
    with commit():
        batch = services.start_batch(operator, order)
    for requirement in order.requirements.order_by("sequence"):
        lot = (
            requirement.lot
            or Lot.objects.filter(material=requirement.material, status=Lot.Status.RELEASED).first()
        )
        services.record_consumption(
            operator, batch, requirement, lot, services.batch_line_quantity(requirement, batch)
        )
    with commit():
        services.finish_batch(operator, batch, D(output))
    return batch


def test_rework_with_correction_list(plant, blocked, planner, depo, operator, lab, commit):
    original, lot = blocked
    task = Task.objects.get(rule_code="rework_order", related_object_id=lot.pk)
    order = services.create_order(
        planner,
        rework_data(
            plant,
            lot,
            additions=[
                {"material": plant.sles, "quantity": D("20"), "unit": unit("KG")},
                {
                    "material": plant.water,
                    "quantity": D("5"),
                    "unit": unit("KG"),
                    "is_water": True,
                    "instruction": "Viskozite için",
                },
            ],
        ),
    )
    assert order.recipe_version is None and order.product == lot.material
    with commit():
        services.approve_order(planner, order)
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    rows = list(order.requirements.order_by("sequence"))
    assert [(r.material, r.lot, r.required_quantity) for r in rows] == [
        (lot.material, lot, D("1000")),
        (plant.sles, None, D("20")),
        (plant.water, None, D("5")),
    ]
    assert rows[0].tolerance_pct == 0 and not rows[0].is_picked
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_material(depo, order, rows[0], lot, D("1000"))
    assert exc.value.code == "rework_lot_not_picked"

    batch = run_rework(plant, order, depo, operator, commit)
    new_lot = batch.output_lot
    assert current_balance(lot, plant.tank.location) == 0
    backward = inventory_selectors.lot_trace_backward(new_lot)
    used = {child["lot_no"]: child["quantity"] for child in backward["children"]}
    assert used[lot.lot_no] == D("1000")
    assert len(used) == 3

    # Yeni lot serbest bırakılınca yeniden işleme emri, ardından asıl emir tamamlanır.
    with commit():
        pass_sample(lab, open_sample_for(new_lot, SampleStage.FINAL))
    order.refresh_from_db()
    original.refresh_from_db()
    assert order.status == Status.COMPLETED
    assert original.status == Status.COMPLETED


def test_rework_blended_with_recipe(plant, blocked, planner, depo, operator, commit):
    _original, lot = blocked
    with pytest.raises(BusinessRuleError) as exc:
        services.approve_order(
            planner,
            services.create_order(
                planner, rework_data(plant, lot, "1000", recipe_version=plant.version)
            ),
        )
    assert exc.value.code == "rework_quantity_too_small"
    order = ProductionOrder.objects.get(rework_lot=lot)
    order = services.update_order(planner, order, {"planned_quantity": D("2000")})
    services.approve_order(planner, order)
    rows = {(r.material.code, r.lot_id): r.required_quantity for r in order.requirements.all()}
    assert rows == {
        (lot.material.code, lot.pk): D("1000"),
        ("LAS", None): D("600"),
        ("SLES", None): D("300"),
        ("SU", None): D("100"),
    }
    batch = run_rework(plant, order, depo, operator, commit, output="2000")
    assert current_balance(batch.output_lot, plant.tank2.location) == D("2000")


def test_rework_order_rules(plant, blocked, planner, depo, operator, commit):
    _original, lot = blocked
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, {**rework_data(plant, lot), "rework_lot": None})
    assert exc.value.code == "recipe_version_required"
    services.create_order(planner, rework_data(plant, lot))
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, rework_data(plant, lot))
    assert exc.value.code == "rework_order_exists"
    released = Lot.objects.filter(material=plant.las).first()
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, rework_data(plant, released))
    assert exc.value.code == "invalid_rework_lot"


def test_rework_lot_must_be_blocked(plant, planner, depo, operator, lab, commit):
    order = ready_order(plant, planner, depo)
    with commit():
        batch = services.start_batch(operator, order)
        weigh_all(plant, batch, operator)
        services.finish_batch(operator, batch, D("1000"))
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, rework_data(plant, batch.output_lot))
    assert exc.value.code == "rework_lot_not_blocked"
