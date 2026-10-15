from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.test import override_settings

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.filling import selectors, services
from apps.filling.models import (
    ConsumptionKind,
    FillingOrder,
    FillingRun,
    PackagingSpec,
    ScrapRecord,
)
from apps.filling.state import filling_order_states, filling_run_states, packaging_spec_states
from apps.filling.tests.factories import (
    Line,
    approved_order,
    order_data,
    packaging_material,
    pick_all,
    ready_order,
    requirement,
    started_run,
)
from apps.inventory.models import Lot, LotLink, StockMovement
from apps.inventory.services import current_balance
from apps.inventory.tests.factories import quarantine_location, stocked_lot
from apps.masterdata.models import Location, Material
from apps.masterdata.tests.factories import BulkMaterialFactory, MaterialFactory, unit
from apps.quality.models import Sample, SampleStage
from apps.quality.testing import open_sample_for, pass_sample

pytestmark = pytest.mark.django_db

D = Decimal
Status = FillingOrder.Status
RunStatus = FillingRun.Status
Movement = StockMovement.Type
Reason = ScrapRecord.Reason
Kind = ScrapRecord.Kind


def event_names(published):
    return [event.name for event in published]


# --- durum makineleri ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("machine", "allowed", "forbidden"),
    [
        (
            filling_order_states,
            [
                ("DRAFT", "APPROVED"),
                ("DRAFT", "CANCELLED"),
                ("APPROVED", "MATERIAL_PREP"),
                ("APPROVED", "CANCELLED"),
                ("MATERIAL_PREP", "MATERIAL_READY"),
                ("MATERIAL_PREP", "CANCELLED"),
                ("MATERIAL_READY", "IN_PROGRESS"),
                ("IN_PROGRESS", "QC_PENDING"),
                ("QC_PENDING", "COMPLETED"),
            ],
            [("DRAFT", "IN_PROGRESS"), ("IN_PROGRESS", "CANCELLED"), ("COMPLETED", "DRAFT")],
        ),
        (
            filling_run_states,
            [("IN_PROGRESS", "COMPLETED"), ("IN_PROGRESS", "CANCELLED")],
            [("COMPLETED", "IN_PROGRESS"), ("CANCELLED", "COMPLETED")],
        ),
        (
            packaging_spec_states,
            [("DRAFT", "APPROVED"), ("APPROVED", "OBSOLETE")],
            [("DRAFT", "OBSOLETE"), ("OBSOLETE", "APPROVED")],
        ),
    ],
)
def test_state_machines(machine, allowed, forbidden):
    for source, target in allowed:
        machine.assert_can_transition(source, target)
    for source, target in forbidden:
        with pytest.raises(BusinessRuleError) as exc:
            machine.assert_can_transition(source, target)
        assert exc.value.code == "invalid_transition"


# --- ambalaj reçetesi ------------------------------------------------------------------------


def test_spec_is_versioned_and_new_approval_obsoletes_previous(line: Line, planner):
    assert line.spec.status == PackagingSpec.Status.APPROVED
    assert line.spec.version_no == 1
    draft = services.copy_spec(planner, line.spec, "Kapak değişti")
    assert draft.version_no == 2
    assert draft.lines.count() == 4

    services.approve_spec(planner, draft)

    line.spec.refresh_from_db()
    assert line.spec.status == PackagingSpec.Status.OBSOLETE
    assert services.approved_spec(line.finished) == draft


def test_approved_spec_is_locked(line: Line, planner):
    with pytest.raises(BusinessRuleError) as exc:
        services.update_spec(planner, line.spec, {"fill_quantity": D("700")})
    assert exc.value.code == "packaging_spec_locked"
    with pytest.raises(BusinessRuleError):
        services.add_spec_line(
            planner, line.spec, {"material": line.bottle, "quantity_per_unit": 1}
        )


def test_spec_without_lines_cannot_be_approved(line: Line, planner):
    spec = services.create_spec(
        planner,
        {
            "finished_product": line.finished,
            "bulk_product": line.bulk,
            "fill_quantity": D("1"),
            "fill_unit": unit("LT"),
            "units_per_case": 12,
        },
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.approve_spec(planner, spec)
    assert exc.value.code == "packaging_spec_has_no_lines"


def test_spec_line_must_be_packaging(line: Line, planner):
    draft = services.copy_spec(planner, line.spec)
    with pytest.raises(BusinessRuleError) as exc:
        services.add_spec_line(
            planner, draft, {"material": MaterialFactory.create(), "quantity_per_unit": D("1")}
        )
    assert exc.value.code == "invalid_packaging_material"


def test_spec_needs_count_finished_unit_and_convertible_fill(line: Line, planner):
    kg_product = MaterialFactory.create(material_type=Material.Type.FINISHED)
    base = {
        "bulk_product": line.bulk,
        "fill_quantity": D("750"),
        "fill_unit": unit("ML"),
        "units_per_case": 12,
    }
    with pytest.raises(BusinessRuleError) as exc:
        services.create_spec(planner, {**base, "finished_product": kg_product})
    assert exc.value.code == "finished_unit_not_count"

    no_density = BulkMaterialFactory.create(density=None)
    with pytest.raises(BusinessRuleError) as exc:
        services.create_spec(
            planner, {**base, "finished_product": line.finished, "bulk_product": no_density}
        )
    assert exc.value.code == "no_conversion"


def test_only_planning_writes_specs(line: Line, depo):
    with pytest.raises(PermissionDenied):
        services.copy_spec(depo, line.spec)


def test_removing_draft_line_is_audited(line: Line, planner):
    draft = services.copy_spec(planner, line.spec)
    removed = draft.lines.get(material=line.case)

    services.remove_spec_line(planner, removed)

    assert draft.lines.count() == 3
    log = AuditLog.objects.filter(object_id=draft.pk, action=AuditLog.Action.UPDATE).first()
    assert log is not None and "silindi" in log.note


# --- dolum emri ------------------------------------------------------------------------------


def test_create_order_fixes_approved_spec(line: Line, planner):
    order = services.create_order(planner, order_data(line))

    assert order.number.startswith("DO-")
    assert order.status == Status.DRAFT
    assert order.packaging_spec == line.spec


def test_order_needs_approved_spec(line: Line, planner):
    other = MaterialFactory.create(material_type=Material.Type.FINISHED, base_unit=unit("ADET"))
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(line, finished_product=other))
    assert exc.value.code == "no_approved_packaging_spec"


def test_order_validates_line_and_output_location(line: Line, planner):
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(line, output_location=quarantine_location()))
    assert exc.value.code == "invalid_output_location"

    line.filling_line.location = line.storage
    line.filling_line.save()
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(line))
    assert exc.value.code == "invalid_filling_line"


def test_approve_builds_requirements_with_allowance_and_rounding(
    line: Line, planner, published, commit
):
    with commit():
        order = approved_order(line, planner, units=1000)

    assert order.status == Status.APPROVED
    quantities = {r.material.code: r.required_quantity for r in order.requirements.all()}
    # Şişe/kapak/koli %2, etiket %3 fire payı; koli 1000/12 × 1,02 = 85,0 → 85 (adet yukarı).
    assert quantities == {
        "SISE-750": D("1020"),
        "KAPAK-28": D("1020"),
        "ETIKET-750": D("1030"),
        "KOLI-12": D("85"),
    }
    assert ev.FILLING_ORDER_APPROVED in event_names(published)


def test_approved_order_is_locked(line: Line, planner):
    order = approved_order(line, planner)
    with pytest.raises(BusinessRuleError) as exc:
        services.update_order(planner, order, {"planned_units": 10})
    assert exc.value.code == "document_locked"


def test_approve_rejects_obsolete_spec(line: Line, planner):
    order = services.create_order(planner, order_data(line))
    services.approve_spec(planner, services.copy_spec(planner, line.spec))

    with pytest.raises(BusinessRuleError) as exc:
        services.approve_order(planner, order)
    assert exc.value.code == "packaging_spec_not_approved"

    order = services.update_order(planner, order, {"notes": "yeni sürüm"})
    assert order.packaging_spec.version_no == 2
    services.approve_order(planner, order)


def test_only_planning_creates_orders(line: Line, filler):
    with pytest.raises(PermissionDenied):
        services.create_order(filler, order_data(line))


# --- ambalaj hazırlama -----------------------------------------------------------------------


@pytest.mark.usefixtures("invariants")
def test_pick_moves_packaging_to_line(line: Line, planner, depo):
    order = approved_order(line, planner)
    row = requirement(order, line.bottle)

    pick = services.pick_packaging(depo, order, row, line.lots["bottle"], D("1020"))

    order.refresh_from_db()
    assert order.status == Status.MATERIAL_PREP
    assert pick.from_location == line.storage
    assert pick.to_location == line.line_location
    assert current_balance(line.lots["bottle"], line.line_location) == D("1020")


def test_pick_rules(line: Line, planner, depo):
    order = approved_order(line, planner)
    row = requirement(order, line.bottle)
    quarantined = stocked_lot(
        "100", material=line.bottle, location=line.storage, status=Lot.Status.QUARANTINE
    )

    with pytest.raises(BusinessRuleError) as exc:
        services.pick_packaging(depo, order, row, quarantined, D("10"))
    assert exc.value.code == "lot_not_released"
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_packaging(depo, order, row, line.lots["cap"], D("10"))
    assert exc.value.code == "lot_material_mismatch"
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_packaging(depo, order, row, line.lots["bottle"], D("2041"))
    assert exc.value.code == "pick_exceeds_requirement"
    with pytest.raises(PermissionDenied):
        services.pick_packaging(planner, order, row, line.lots["bottle"], D("10"))


def test_mark_ready_needs_net_requirement(line: Line, planner, depo, published, commit):
    order = approved_order(line, planner)
    for material in (line.bottle, line.cap, line.label):
        services.pick_packaging(
            depo, order, requirement(order, material), line.lots[_key(line, material)], D("1000")
        )
    with pytest.raises(BusinessRuleError) as exc:
        services.mark_material_ready(depo, order)
    assert exc.value.code == "material_not_ready"
    assert "KOLI-12" in exc.value.message

    # Fire payı hariç ihtiyaç (koli 84) yeterli.
    services.pick_packaging(depo, order, requirement(order, line.case), line.lots["case"], D("84"))
    with commit():
        order = services.mark_material_ready(depo, order)
    assert order.status == Status.MATERIAL_READY
    assert ev.FILLING_ORDER_MATERIAL_READY in event_names(published)


def _key(line: Line, material: Material) -> str:
    return {line.bottle: "bottle", line.cap: "cap", line.label: "label", line.case: "case"}[
        material
    ]


@pytest.mark.usefixtures("invariants")
def test_cancel_returns_picked_packaging(line: Line, planner, depo):
    order = approved_order(line, planner)
    pick_all(line, order, depo)

    services.cancel_order(planner, order, "Plan değişti")

    order.refresh_from_db()
    assert order.status == Status.CANCELLED
    assert current_balance(line.lots["bottle"], line.storage) == D("5000")
    assert current_balance(line.lots["bottle"], line.line_location) == D("0")
    assert not order.picks.filter(returned_at__isnull=True).exists()


# --- dolum partisi ---------------------------------------------------------------------------


def test_start_run_opens_quarantined_d_lot(line: Line, planner, depo, filler, published, commit):
    order = ready_order(line, planner, depo)
    with commit():
        run = services.start_run(filler, order)

    lot = run.output_lot
    assert lot.lot_no.startswith("D-")
    assert lot.status == Lot.Status.QUARANTINE
    assert lot.source == Lot.Source.FILLING
    assert lot.material == line.finished
    assert lot.expiry_date is not None
    order.refresh_from_db()
    assert order.status == Status.IN_PROGRESS
    assert ev.FILLING_RUN_STARTED in event_names(published)

    with pytest.raises(BusinessRuleError) as exc:
        services.start_run(filler, order)
    assert exc.value.code == "run_in_progress"


def test_run_needs_ready_order(line: Line, planner, filler):
    order = approved_order(line, planner)
    with pytest.raises(BusinessRuleError) as exc:
        services.start_run(filler, order)
    assert exc.value.code == "order_not_ready"


@pytest.mark.usefixtures("invariants")
def test_consume_bulk_issues_and_links(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    bulk_lot = line.lots["bulk"]

    consumption = services.consume_bulk(filler, run, bulk_lot, D("400"))

    assert consumption.kind == ConsumptionKind.BULK
    assert consumption.location == line.tank
    assert consumption.movement.movement_type == Movement.ISSUE_PRODUCTION
    assert current_balance(bulk_lot, line.tank) == D("600")
    link = LotLink.objects.get(parent_lot=bulk_lot, child_lot=run.output_lot)
    assert link.quantity == D("400")


def test_consume_bulk_rules(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    quarantined = stocked_lot(
        "500",
        material=line.bulk,
        location=line.tank,
        status=Lot.Status.QUARANTINE,
        source=Lot.Source.PRODUCTION,
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.consume_bulk(filler, run, quarantined, D("10"))
    assert exc.value.code == "lot_not_released"
    with pytest.raises(BusinessRuleError) as exc:
        services.consume_bulk(filler, run, line.lots["bottle"], D("10"))
    assert exc.value.code == "lot_material_mismatch"
    with pytest.raises(BusinessRuleError) as exc:
        services.consume_bulk(filler, run, line.lots["bulk"], D("1001"))
    assert exc.value.code == "negative_stock"
    with pytest.raises(PermissionDenied):
        services.consume_bulk(depo, run, line.lots["bulk"], D("10"))


def test_scan_rejects_wrong_material_and_lots_not_at_line(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    stranger = packaging_material("POSET", "Poşet")
    with pytest.raises(BusinessRuleError) as exc:
        services.scan_packaging_lot(filler, run, stocked_lot("10", material=stranger))
    assert exc.value.code == "lot_material_mismatch"

    not_picked = stocked_lot("10", material=line.bottle, location=line.storage)
    with pytest.raises(BusinessRuleError) as exc:
        services.scan_packaging_lot(filler, run, not_picked)
    assert exc.value.code == "lot_not_at_line"

    scanned = services.scan_packaging_lot(filler, run, line.lots["bottle"])
    assert services.scan_packaging_lot(filler, run, line.lots["bottle"]) == scanned


@pytest.mark.usefixtures("invariants")
def test_scrap_records(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)

    bulk = services.record_scrap(
        filler,
        run,
        kind=Kind.BULK,
        quantity=D("5"),
        reason_code=Reason.SETUP_LOSS,
        lot=line.lots["bulk"],
    )
    bottle = services.record_scrap(
        filler,
        run,
        kind=Kind.PACKAGING,
        quantity=D("3"),
        reason_code=Reason.DAMAGED_PACKAGING,
        lot=line.lots["bottle"],
    )
    finished = services.record_scrap(
        filler, run, kind=Kind.FINISHED, quantity=D("4"), reason_code=Reason.LEAK
    )

    assert bulk.movement is not None
    assert bulk.movement.movement_type == Movement.SCRAP
    assert bulk.location == line.tank
    assert bottle.location == line.line_location
    assert current_balance(line.lots["bottle"], line.line_location) == D("1017")
    assert finished.lot == run.output_lot
    assert finished.movement is None  # bitişte düşülür

    with pytest.raises(BusinessRuleError) as exc:
        services.record_scrap(
            filler,
            run,
            kind=Kind.PACKAGING,
            quantity=D("1"),
            reason_code=Reason.OTHER,
            lot=line.lots["cap"],
        )
    assert exc.value.code == "scrap_note_required"
    with pytest.raises(BusinessRuleError) as exc:
        services.record_scrap(
            filler, run, kind=Kind.FINISHED, quantity=D("1.5"), reason_code=Reason.LEAK
        )
    assert exc.value.code == "invalid_quantity"


@pytest.mark.usefixtures("invariants")
def test_finish_run_consumes_packaging_posts_output_and_opens_sample(
    line: Line, planner, depo, filler, published, commit
):
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("787"))
    services.scan_packaging_lot(filler, run, line.lots["bottle"])
    services.record_scrap(
        filler, run, kind=Kind.FINISHED, quantity=D("10"), reason_code=Reason.LEAK
    )

    with commit():
        run = services.finish_run(filler, run, 1000, "Vardiya sonu")

    assert run.status == RunStatus.COMPLETED
    lot = run.output_lot
    # 1010 adet doldu (1000 sağlam + 10 fire); 10 adet fire olarak düşüldü.
    assert run.output_movement is not None
    assert run.output_movement.quantity == D("1010")
    assert current_balance(lot, line.finished_store) == D("1000")
    consumed = {
        c.material.code: c.quantity for c in run.consumptions.filter(kind=ConsumptionKind.PACKAGING)
    }
    assert consumed == {
        "SISE-750": D("1010"),
        "KAPAK-28": D("1010"),
        "ETIKET-750": D("1010"),
        "KOLI-12": D("85"),  # 1010 / 12 = 84,17 → 85
    }
    for material in line.packaging:
        assert LotLink.objects.filter(parent_lot__material=material, child_lot=lot).exists()
    # Teorik bulk 1000 × 0,75 lt × 1,04 = 780 kg; gerçek 787 → %0,90 (eşik altı).
    assert run.theoretical_bulk == D("780")
    assert run.actual_bulk == D("787")
    assert run.bulk_variance_pct == D("0.90")
    names = event_names(published)
    assert ev.FILLING_RUN_COMPLETED in names
    assert ev.FILLING_BULK_VARIANCE not in names
    sample = open_sample_for(lot, SampleStage.FINAL)
    assert sample.origin == Sample.Origin.FILLING


@pytest.mark.usefixtures("invariants")
@override_settings(FILL_VARIANCE_THRESHOLD_PCT="1.5")
def test_bulk_variance_event_above_threshold(line: Line, planner, depo, filler, published, commit):
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("790"))
    services.record_scrap(
        filler,
        run,
        kind=Kind.BULK,
        quantity=D("5"),
        reason_code=Reason.SETUP_LOSS,
        lot=line.lots["bulk"],
    )

    with commit():
        run = services.finish_run(filler, run, 1000)

    # Gerçek = 790 + 5 fire = 795 → (795 − 780) / 780 = %1,92.
    assert run.actual_bulk == D("795")
    assert run.bulk_variance_pct == D("1.92")
    event = next(e for e in published if e.name == ev.FILLING_BULK_VARIANCE)
    assert event.payload["variance_pct"] == "1,92"
    assert event.payload["model"] == "filling.fillingorder"


def test_finish_run_rules(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    with pytest.raises(BusinessRuleError) as exc:
        services.finish_run(filler, run, 100)
    assert exc.value.code == "run_has_no_bulk"

    services.consume_bulk(filler, run, line.lots["bulk"], D("900"))
    with pytest.raises(BusinessRuleError) as exc:
        services.finish_run(filler, run, 1100)  # hatta 1020 şişe var
    assert exc.value.code == "packaging_short"
    with pytest.raises(BusinessRuleError) as exc:
        services.finish_run(filler, run, 0)
    assert exc.value.code == "invalid_quantity"


def test_cancel_run_only_without_records(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("1"))
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_run(filler, run, "yanlış")
    assert exc.value.code == "run_has_records"

    other = FillingRun.objects.get(pk=run.pk)
    services.finish_run(filler, other, 1)
    fresh = services.start_run(filler, run.order)
    services.cancel_run(filler, fresh, "Yanlış başlatıldı")
    fresh.refresh_from_db()
    assert fresh.status == RunStatus.CANCELLED


# --- kapanış ve rapor ------------------------------------------------------------------------


@pytest.mark.usefixtures("invariants")
def test_order_completes_when_lots_released(line: Line, planner, depo, filler, lab, commit):
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("780"))
    with commit():
        services.finish_run(filler, run, 1000)
        order = services.finish_filling(filler, run.order)
    assert order.status == Status.QC_PENDING

    with commit():
        pass_sample(lab, open_sample_for(run.output_lot, SampleStage.FINAL))

    order.refresh_from_db()
    run.output_lot.refresh_from_db()
    assert run.output_lot.status == Lot.Status.RELEASED
    assert order.status == Status.COMPLETED
    assert order.completed_at is not None


def test_finish_filling_rules(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    with pytest.raises(BusinessRuleError) as exc:
        services.finish_filling(filler, run.order)
    assert exc.value.code == "run_in_progress"
    services.cancel_run(filler, run, "Yanlış")
    with pytest.raises(BusinessRuleError) as exc:
        services.finish_filling(filler, run.order)
    assert exc.value.code == "order_has_no_runs"


def test_consumption_report(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("790"))
    services.record_scrap(
        filler,
        run,
        kind=Kind.PACKAGING,
        quantity=D("6"),
        reason_code=Reason.LABEL_ERROR,
        lot=line.lots["label"],
    )
    services.finish_run(filler, run, 1000)

    report = selectors.consumption_report(run.order)

    assert report.good_units == 1000
    assert report.bulk.theoretical == D("780")
    assert report.bulk.actual == D("790")
    assert report.bulk.variance == D("10")
    assert report.bulk.variance_pct == D("1.28")
    assert not report.bulk_over_threshold
    rows = {row.line.material.code: row for row in report.packaging}
    label = rows["ETIKET-750"]
    assert (label.theoretical, label.consumed, label.scrap, label.actual) == (
        D("1000"),
        D("1000"),
        D("6"),
        D("1006"),
    )
    assert label.variance_pct == D("0.60")
    assert not label.over_allowance
    case = rows["KOLI-12"]
    assert case.theoretical == D("83.3330")
    assert case.consumed == D("84")


def test_line_location_must_be_production(line: Line, planner):
    line.line_location.location_type = Location.Type.STORAGE
    line.line_location.save()
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(planner, order_data(line))
    assert exc.value.code == "invalid_filling_line"
