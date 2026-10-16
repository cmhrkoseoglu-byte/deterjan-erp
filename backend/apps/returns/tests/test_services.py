from collections.abc import Callable
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.inventory.models import Lot, StockMovement
from apps.inventory.services import current_balance
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.tests.factories import MaterialFactory, unit
from apps.quality import services as quality
from apps.quality.models import QualityDecision, Sample, SampleStage, TestDefinition
from apps.quality.testing import pass_sample
from apps.returns import services
from apps.returns.models import CustomerReturn, CustomerReturnLine
from apps.returns.tests.factories import Setup, draft_return, shipped_lot
from apps.workflow.models import Task

D = Decimal
Commit = Callable[[], AbstractContextManager[Any]]
Decision = QualityDecision.Decision
Disposition = CustomerReturnLine.Disposition

pytestmark = pytest.mark.usefixtures("invariants")


def received(shipper: User, setup: Setup, commit: Commit, **kwargs: Any) -> CustomerReturn:
    with commit():
        document = services.receive_return(shipper, draft_return(shipper, setup, **kwargs))
    return document


def line_of(document: CustomerReturn) -> CustomerReturnLine:
    return document.lines.select_related("lot", "sample").get()


# --- taslak ----------------------------------------------------------------------------------


def test_create_return_draft(shipper: User, setup: Setup) -> None:
    document = draft_return(shipper, setup)
    assert document.number.startswith("IA-")
    assert document.status == CustomerReturn.Status.DRAFT
    line = line_of(document)
    assert line.line_no == 1
    assert line.disposition == Disposition.PENDING
    assert not StockMovement.objects.filter(movement_type=StockMovement.Type.RETURN).exists()


def test_only_shipping_creates_returns(lab: User, setup: Setup) -> None:
    with pytest.raises(PermissionDenied):
        draft_return(lab, setup)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("location", "invalid_quarantine_location"),
        ("reason", "reason_required"),
        ("lot", "lot_material_mismatch"),
        ("product", "return_material_type"),
    ],
)
def test_create_return_rules(shipper: User, setup: Setup, change: str, code: str) -> None:
    data: dict[str, Any] = {
        "customer": setup.customer,
        "return_date": "2026-10-16",
        "reason": "Hasarlı koli",
        "quarantine_location": setup.quarantine,
    }
    line: dict[str, Any] = {
        "product": setup.product,
        "lot": setup.lot,
        "quantity": D(5),
        "unit": unit("ADET"),
    }
    if change == "location":
        data["quarantine_location"] = setup.store
    elif change == "reason":
        data["reason"] = "  "
    elif change == "lot":
        line["product"] = MaterialFactory.create(material_type="FINISHED", base_unit=unit("ADET"))
    else:
        raw = MaterialFactory.create()
        line["product"] = raw
        line["lot"] = shipped_lot(raw, setup.store)
    with pytest.raises(BusinessRuleError) as exc:
        services.create_return(shipper, data, [line])
    assert exc.value.code == code


def test_update_and_cancel_draft(shipper: User, setup: Setup) -> None:
    document = draft_return(shipper, setup)
    line = line_of(document)
    services.update_return(
        shipper,
        document,
        {"note": "Araçla geldi"},
        [
            {
                "id": line.pk,
                "product": setup.product,
                "lot": setup.lot,
                "quantity": D(3),
                "unit": unit("ADET"),
            }
        ],
    )
    assert line_of(document).quantity == D(3)
    services.cancel_return(shipper, document, "Yanlış müşteri")
    document.refresh_from_db()
    assert document.status == CustomerReturn.Status.CANCELLED
    with pytest.raises(BusinessRuleError) as exc:
        services.update_return(shipper, document, {"note": "x"})
    assert exc.value.code == "document_locked"


# --- teslim alma -----------------------------------------------------------------------------


def test_receive_puts_goods_in_quarantine_and_holds_lot(
    shipper: User, setup: Setup, commit: Commit
) -> None:
    document = received(shipper, setup, commit)
    assert document.status == CustomerReturn.Status.RECEIVED
    line = line_of(document)
    assert line.base_quantity == D(12)
    assert line.movement is not None
    assert line.movement.movement_type == StockMovement.Type.RETURN
    assert current_balance(setup.lot, setup.quarantine) == D(12)
    # Lot numarası korunur, lotun tamamı bekletilir.
    setup.lot.refresh_from_db()
    assert setup.lot.status == Lot.Status.BLOCKED
    assert line.lot_id == setup.lot.pk
    sample = line.sample
    assert sample is not None
    assert sample.stage == SampleStage.RETURN
    assert sample.origin == Sample.Origin.RETURN
    task = Task.objects.get(rule_code="return_qc")
    assert task.title == f"İade kontrolü: {setup.lot.lot_no}"


def test_receive_twice_is_rejected(shipper: User, setup: Setup, commit: Commit) -> None:
    document = received(shipper, setup, commit)
    with pytest.raises(BusinessRuleError) as exc:
        services.receive_return(shipper, document)
    assert exc.value.code == "invalid_transition"
    with pytest.raises(BusinessRuleError):
        services.cancel_return(shipper, document, "Vazgeçildi")


def test_lab_cannot_receive(lab: User, shipper: User, setup: Setup) -> None:
    with pytest.raises(PermissionDenied):
        services.receive_return(lab, draft_return(shipper, setup))


def test_second_return_of_same_lot_shares_open_sample(
    shipper: User, setup: Setup, commit: Commit
) -> None:
    first = received(shipper, setup, commit)
    second = received(shipper, setup, commit, quantity="3")
    assert line_of(first).sample_id == line_of(second).sample_id
    assert current_balance(setup.lot, setup.quarantine) == D(15)


def test_rejected_lot_goes_straight_to_scrap(
    shipper: User, depo: User, lab: User, setup: Setup, commit: Commit
) -> None:
    first = received(shipper, setup, commit)
    with commit():
        pass_sample(lab, line_of(first).sample, decision=Decision.REJECT)  # type: ignore[arg-type]
    document = received(shipper, setup, commit, quantity="2")
    line = line_of(document)
    assert line.sample is None
    assert line.disposition == Disposition.SCRAP
    assert Task.objects.filter(rule_code="return_scrap", status__in=Task.OPEN_STATUSES).exists()


# --- kalite kararı ---------------------------------------------------------------------------


def test_release_restocks_and_closes(
    shipper: User, lab: User, setup: Setup, commit: Commit
) -> None:
    document = received(shipper, setup, commit)
    with commit():
        pass_sample(lab, line_of(document).sample)  # type: ignore[arg-type]
    setup.lot.refresh_from_db()
    assert setup.lot.status == Lot.Status.RELEASED
    # Karantinadaki iade miktarı lotun son bulunduğu depoya taşınır.
    assert current_balance(setup.lot, setup.quarantine) == D(0)
    assert current_balance(setup.lot, setup.store) == D(72)
    line = line_of(document)
    assert line.disposition == Disposition.RESTOCK
    document.refresh_from_db()
    assert document.status == CustomerReturn.Status.CLOSED
    assert document.closed_at is not None
    assert not Task.objects.filter(rule_code="return_qc", status__in=Task.OPEN_STATUSES).exists()


def test_release_to_chosen_location(shipper: User, lab: User, setup: Setup, commit: Commit) -> None:
    other = storage_location(code="MAMUL-2")
    document = received(shipper, setup, commit)
    with commit():
        pass_sample(lab, line_of(document).sample, release_location=other)  # type: ignore[arg-type]
    assert current_balance(setup.lot, other) == D(12)


def test_reject_then_scrap(
    shipper: User, depo: User, lab: User, setup: Setup, commit: Commit
) -> None:
    document = received(shipper, setup, commit)
    line = line_of(document)
    with pytest.raises(BusinessRuleError) as exc:
        services.scrap_line(depo, line)
    assert exc.value.code == "scrap_not_decided"
    with commit():
        pass_sample(lab, line.sample, decision=Decision.REJECT)  # type: ignore[arg-type]
    setup.lot.refresh_from_db()
    assert setup.lot.status == Lot.Status.REJECTED
    line.refresh_from_db()
    assert line.disposition == Disposition.SCRAP
    document.refresh_from_db()
    assert document.status == CustomerReturn.Status.RECEIVED
    task = Task.objects.get(rule_code="return_scrap")
    assert task.status in Task.OPEN_STATUSES
    with pytest.raises(PermissionDenied):
        services.scrap_line(lab, line)
    with commit():
        services.scrap_line(depo, line, "Atık firmasına verildi")
    line.refresh_from_db()
    assert line.scrap_movement is not None
    assert line.scrap_movement.movement_type == StockMovement.Type.SCRAP
    assert current_balance(setup.lot, setup.quarantine) == D(0)
    document.refresh_from_db()
    assert document.status == CustomerReturn.Status.CLOSED
    task.refresh_from_db()
    assert task.status not in Task.OPEN_STATUSES
    with pytest.raises(BusinessRuleError) as exc:
        services.scrap_line(depo, line)
    assert exc.value.code == "already_scrapped"


def test_rework_on_returned_finished_lot(
    shipper: User, lab: User, setup: Setup, commit: Commit
) -> None:
    document = received(shipper, setup, commit)
    with commit():
        pass_sample(lab, line_of(document).sample, decision=Decision.REWORK)  # type: ignore[arg-type]
    setup.lot.refresh_from_db()
    assert setup.lot.status == Lot.Status.BLOCKED
    assert line_of(document).disposition == Disposition.REWORK
    document.refresh_from_db()
    assert document.status == CustomerReturn.Status.CLOSED
    assert Task.objects.filter(rule_code="return_rework").exists()
    assert not Task.objects.filter(rule_code="rework_order").exists()


def test_rework_still_bulk_only_outside_returns(lab: User, setup: Setup) -> None:
    lot = stocked_lot("10", material=setup.product, status=Lot.Status.QUARANTINE)
    sample = quality.open_sample(lab, lot, SampleStage.FINAL)
    with pytest.raises(BusinessRuleError) as exc:
        pass_sample(lab, sample, decision=Decision.REWORK)
    assert exc.value.code == "rework_not_allowed"


def test_return_sample_falls_back_to_final_spec(
    shipper: User, lab: User, setup: Setup, commit: Commit
) -> None:
    spec = quality.create_specification(
        lab,
        material=setup.product,
        sample_stage=SampleStage.FINAL,
        lines=[{"test": TestDefinition.objects.get(code="RENK")}],
    )
    quality.approve_specification(lab, spec)
    document = received(shipper, setup, commit)
    sample = line_of(document).sample
    assert sample is not None
    assert sample.specification_id == spec.pk
