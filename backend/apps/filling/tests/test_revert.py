"""Dolum emrini geri alma (DECISIONS 2026-11-14): fiilen yapılmamış dolumun bütün stok hareketleri
ters kayıtla geri alınır, partiler ve açık numuneler iptal edilir, emir iptal olur.

Canlı durum: DO-2026-00008 (dolumda, yalnız bulk tüketimi) ve DO-2026-00009 (bir partisi
tamamlanmış, ikinci partisi iptal) aynı hatta, aynı ambalaj lotlarını paylaşıyor."""

from collections.abc import Callable
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.filling import services
from apps.filling.models import FillingConsumption, FillingOrder, FillingRun, ScrapRecord
from apps.filling.state import (
    filling_order_revert_states,
    filling_order_states,
    filling_run_revert_states,
    filling_run_states,
)
from apps.filling.tests.factories import (
    Line,
    approved_order,
    order_data,
    pick_all,
    ready_order,
    requirement,
    started_run,
)
from apps.inventory import services as inventory
from apps.inventory.models import Lot, LotLink, StockMovement
from apps.inventory.services import current_balance
from apps.inventory.testing import assert_stock_invariants
from apps.inventory.tests.factories import stocked_lot
from apps.quality.models import Sample, SampleStage
from apps.quality.testing import open_sample_for
from apps.workflow.models import Task

pytestmark = pytest.mark.django_db

D = Decimal
Status = FillingOrder.Status
RunStatus = FillingRun.Status
Movement = StockMovement.Type
Reason = ScrapRecord.Reason
Kind = ScrapRecord.Kind
REASON = "Dolum fiilen yapılmadı"


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


def names(published):
    return [event.name for event in published]


def order_movements(order: FillingOrder):
    return StockMovement.objects.filter(
        source_object_id=order.pk, source_content_type__model="fillingorder"
    )


def assert_fully_reversed(order: FillingOrder) -> None:
    """Emrin REVERSAL dışı her hareketinin ters kaydı var; lot ve lokasyon bazında net sıfır."""
    originals = order_movements(order).exclude(movement_type=Movement.REVERSAL)
    assert originals.exists()
    assert not originals.filter(reversed_by__isnull=True).exists()
    net: dict[tuple[int, int], Decimal] = {}
    for movement in order_movements(order):
        key = (movement.lot_id, movement.location_id)
        net[key] = net.get(key, D(0)) + movement.quantity
    assert set(net.values()) == {D(0)}


def assert_packaging_home(line: Line, lots: dict[str, Lot] | None = None) -> None:
    for lot in (lots or line.lots).values():
        if lot.material == line.bulk:
            continue
        assert current_balance(lot, line.line_location) == D(0), lot.lot_no
        assert current_balance(lot, line.storage) == D("5000"), lot.lot_no


def completed_run_order(line: Line, planner, depo, filler, commit) -> tuple[FillingRun, FillingRun]:
    """DO-2026-00009 gibi: 1. parti bulk, ambalaj ve mamul firesiyle tamamlandı (son kontrol
    numunesi ve "Mamul kontrolü" görevi açık), 2. parti yanlış başlatılıp iptal edildi."""
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("787"))
    services.record_scrap(
        filler,
        run,
        kind=Kind.BULK,
        quantity=D("5"),
        reason_code=Reason.SETUP_LOSS,
        lot=line.lots["bulk"],
    )
    services.record_scrap(
        filler,
        run,
        kind=Kind.PACKAGING,
        quantity=D("3"),
        reason_code=Reason.DAMAGED_PACKAGING,
        lot=line.lots["bottle"],
    )
    services.record_scrap(
        filler, run, kind=Kind.FINISHED, quantity=D("10"), reason_code=Reason.LEAK
    )
    with commit():
        services.finish_run(filler, run, 1000)
    second = services.start_run(filler, run.order)
    services.cancel_run(filler, second, "Yanlış başlatıldı")
    run.refresh_from_db()
    second.refresh_from_db()
    return run, second


# --- durum makineleri ------------------------------------------------------------------------


def test_revert_state_machines_and_main_tables_unchanged():
    for source in ("MATERIAL_READY", "IN_PROGRESS", "QC_PENDING"):
        filling_order_revert_states.assert_can_transition(source, "CANCELLED")
    for source in ("IN_PROGRESS", "COMPLETED"):
        filling_run_revert_states.assert_can_transition(source, "CANCELLED")
    forbidden = [
        (filling_order_revert_states, "COMPLETED", "CANCELLED"),
        (filling_order_revert_states, "DRAFT", "CANCELLED"),
        (filling_order_revert_states, "IN_PROGRESS", "QC_PENDING"),
        (filling_run_revert_states, "CANCELLED", "CANCELLED"),
        (filling_run_revert_states, "IN_PROGRESS", "COMPLETED"),
        # Ana tablolar değişmedi: sıradan iptal başlamış emri ve tamamlanmış partiyi iptal etmez.
        (filling_order_states, "IN_PROGRESS", "CANCELLED"),
        (filling_order_states, "QC_PENDING", "CANCELLED"),
        (filling_order_states, "MATERIAL_READY", "CANCELLED"),
        (filling_run_states, "COMPLETED", "CANCELLED"),
    ]
    for machine, source, target in forbidden:
        with pytest.raises(BusinessRuleError) as exc:
            machine.assert_can_transition(source, target)
        assert exc.value.code == "invalid_transition"
    # Olay adları ana makinelerinkiyle aynı.
    assert filling_order_revert_states.event_name("CANCELLED") == ev.FILLING_ORDER_CANCELLED
    assert filling_run_revert_states.event_name("CANCELLED") == ev.FILLING_RUN_CANCELLED
    assert filling_order_revert_states.label("QC_PENDING") == "Analiz bekliyor"


def test_cancel_order_still_refuses_started_order(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_order(planner, run.order, "Plan değişti")
    assert exc.value.code == "invalid_transition"


# --- mutlu yol -------------------------------------------------------------------------------


@pytest.mark.usefixtures("invariants")
def test_revert_in_progress_order_with_bulk_only(
    line: Line, planner, depo, filler, manager, published, commit
):
    """DO-2026-00008 gibi: parti dolumda, yalnız bulk tüketildi."""
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("400"))
    order = run.order

    with commit():
        order = services.revert_order(manager, order, f"  {REASON} ")

    assert order.status == Status.CANCELLED
    assert order.cancel_reason == REASON
    assert order.cancelled_by == manager
    run.refresh_from_db()
    assert run.status == RunStatus.CANCELLED
    assert run.cancel_reason == REASON
    assert current_balance(line.lots["bulk"], line.tank) == D("1000")
    assert_packaging_home(line)
    assert not order.picks.filter(returned_at__isnull=True).exists()
    assert_fully_reversed(order)
    reversal = order_movements(order).filter(movement_type=Movement.REVERSAL).first()
    assert reversal is not None and REASON in reversal.note and order.number in reversal.note
    # Soy ağacı geçmiş olarak kalır; lot karantinada stoksuz.
    assert LotLink.objects.filter(parent_lot=line.lots["bulk"], child_lot=run.output_lot).exists()
    run.output_lot.refresh_from_db()
    assert run.output_lot.status == Lot.Status.QUARANTINE
    assert ev.FILLING_RUN_CANCELLED in names(published)
    assert ev.FILLING_ORDER_CANCELLED in names(published)
    cancelled = next(e for e in published if e.name == ev.FILLING_RUN_CANCELLED)
    assert cancelled.payload["output_lot"]["id"] == run.output_lot.pk
    assert cancelled.payload["reason"] == REASON
    trail = AuditLog.objects.filter(object_id=order.pk, content_type__model="fillingorder")
    assert trail.filter(action=AuditLog.Action.CANCEL).exists()
    # Bulk tüketiminin ters kaydı + dört hazırlamanın iki bacağı.
    assert trail.filter(note="Dolum geri alındı: 9 stok hareketi ters kaydedildi.").exists()


@pytest.mark.usefixtures("invariants")
def test_revert_order_with_completed_run_output_scrap_and_sample(
    line: Line, planner, depo, filler, manager, published, commit
):
    """DO-2026-00009 gibi: tamamlanmış parti (ambalaj tüketimi, mamul girişi, fire, son kontrol
    numunesi ve laboratuvar görevi) ve iptal edilmiş ikinci parti."""
    run, second = completed_run_order(line, planner, depo, filler, commit)
    lot = run.output_lot
    assert current_balance(lot, line.finished_store) == D("1000")
    sample = open_sample_for(lot, SampleStage.FINAL)
    task = Task.objects.get(rule_code="finished_qc", related_object_id=lot.pk)
    assert task.status == Task.Status.OPEN

    with commit():
        order = services.revert_order(manager, run.order, REASON)

    assert order.status == Status.CANCELLED
    run.refresh_from_db()
    second.refresh_from_db()
    assert run.status == RunStatus.CANCELLED
    assert second.status == RunStatus.CANCELLED
    assert second.cancel_reason == "Yanlış başlatıldı"  # önceden iptal; değişmez
    assert current_balance(lot, line.finished_store) == D("0")
    assert current_balance(line.lots["bulk"], line.tank) == D("1000")
    assert_packaging_home(line)
    assert_fully_reversed(order)
    sample.refresh_from_db()
    assert sample.status == Sample.Status.CANCELLED
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    lot.refresh_from_db()
    assert lot.status == Lot.Status.QUARANTINE
    # Yalnız birinci parti iptal oldu (ikincisi zaten iptaldi).
    assert names(published).count(ev.FILLING_RUN_CANCELLED) == 1


@pytest.mark.usefixtures("invariants")
def test_revert_qc_pending_order(line: Line, planner, depo, filler, manager, commit):
    run, _second = completed_run_order(line, planner, depo, filler, commit)
    order = services.finish_filling(filler, run.order)
    assert order.status == Status.QC_PENDING

    order = services.revert_order(manager, order, REASON)

    assert order.status == Status.CANCELLED
    assert current_balance(run.output_lot, line.finished_store) == D("0")
    assert_packaging_home(line)


@pytest.mark.usefixtures("invariants")
def test_revert_material_ready_order_returns_packaging(
    line: Line, planner, depo, manager, make_user
):
    order = ready_order(line, planner, depo)
    admin = make_user("admin", username="admin")

    order = services.revert_order(admin, order, REASON)

    assert order.status == Status.CANCELLED
    assert_packaging_home(line)
    assert_fully_reversed(order)


@pytest.mark.usefixtures("invariants")
def test_revert_skips_movements_reversed_by_hand(
    line: Line, planner, depo, filler, manager, commit
):
    """Elle ters kaydedilmiş mamul girişi ve hazırlama atlanır; hazırlama yine iade edildi olur."""
    run, _second = completed_run_order(line, planner, depo, filler, commit)
    order = run.order
    # Mamul firesi önce elle geri alınır ki mamul girişinin ters kaydı negatife düşmesin.
    finished_scrap = run.scraps.get(kind=Kind.FINISHED)
    assert finished_scrap.movement is not None
    inventory.reverse_movement(manager, finished_scrap.movement, "Elle düzeltme")
    assert run.output_movement is not None
    inventory.reverse_movement(manager, run.output_movement, "Elle düzeltme")
    # Etiket: önce tüketim, sonra hazırlama transferi elle geri alınır.
    label_pick = order.picks.get(lot=line.lots["label"])
    label_consumptions = FillingConsumption.objects.filter(run=run, lot=line.lots["label"])
    for consumption in label_consumptions:
        inventory.reverse_movement(manager, consumption.movement, "Elle düzeltme")
    first_leg = StockMovement.objects.filter(transfer_group=label_pick.transfer_group).first()
    assert first_leg is not None
    inventory.reverse_movement(manager, first_leg, "Elle düzeltme")

    order = services.revert_order(manager, order, REASON)

    assert order.status == Status.CANCELLED
    label_pick.refresh_from_db()
    assert label_pick.returned_at is not None
    assert_packaging_home(line)
    assert_fully_reversed(order)


# --- canlı durum: aynı hatta iki emir, aynı ambalaj lotları ----------------------------------


def two_orders_on_one_line(
    line: Line, planner, depo, filler, commit, *, shared_lots: bool
) -> tuple[FillingOrder, FillingOrder, dict[str, Lot]]:
    """A (DO-2026-00008): dolumda, yalnız bulk tüketimi. B (DO-2026-00009): bir partisi tamam,
    ambalajı hat başından (önce A'nın hazırladığı, daha eski lotlardan) tüketti.

    `shared_lots=True`: B, A ile aynı lotları hazırladı (canlıdaki gibi). Yoksa B kendi
    lotlarını hazırladı ama tüketim A'nın lotlarından düştü."""
    a = ready_order(line, planner, depo)
    run_a = services.start_run(filler, a)
    services.consume_bulk(filler, run_a, line.lots["bulk"], D("400"))

    b = approved_order(line, planner)
    extra: dict[str, Lot] = {}
    if shared_lots:
        pick_all(line, b, depo)
    else:
        for key, material in zip(("bottle", "cap", "label", "case"), line.packaging, strict=True):
            extra[key] = stocked_lot("5000", material=material, location=line.storage)
            row = requirement(b, material)
            services.pick_packaging(depo, b, row, extra[key], row.required_quantity)
    b = services.mark_material_ready(depo, b)
    run_b = services.start_run(filler, b)
    services.consume_bulk(filler, run_b, line.lots["bulk"], D("550"))
    with commit():
        services.finish_run(filler, run_b, 700)
    # Ön koşul: B'nin ambalajı A'nın hazırladığı lotlardan düştü.
    consumed = {c.lot_id for c in FillingConsumption.objects.filter(run=run_b, kind="PACKAGING")}
    assert consumed == {line.lots[key].pk for key in ("bottle", "cap", "label", "case")}
    return a, b, extra


@pytest.mark.usefixtures("invariants")
@pytest.mark.parametrize("first", ["A", "B"])
def test_live_case_two_orders_sharing_lots_revert_in_either_order(
    first, line: Line, planner, depo, filler, manager, commit
):
    a, b, _extra = two_orders_on_one_line(line, planner, depo, filler, commit, shared_lots=True)
    sequence = [a, b] if first == "A" else [b, a]

    for order in sequence:
        with commit():
            reverted = services.revert_order(manager, order, REASON)
        assert reverted.status == Status.CANCELLED
        assert_stock_invariants()

    for order in (a, b):
        assert_fully_reversed(order)
    assert current_balance(line.lots["bulk"], line.tank) == D("1000")
    assert_packaging_home(line)


@pytest.mark.usefixtures("invariants")
def test_order_whose_packaging_was_used_by_another_order_must_wait(
    line: Line, planner, depo, filler, manager, commit
):
    """B kendi lotlarını hazırladı ama A'nın lotlarını tüketti: A önce geri alınamaz (B'yi adıyla
    söyler, hiçbir şey değişmez); B, sonra A geri alınır."""
    a, b, extra = two_orders_on_one_line(line, planner, depo, filler, commit, shared_lots=False)
    before = StockMovement.objects.count()

    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, a, REASON)

    assert exc.value.code == "packaging_used_elsewhere"
    assert b.number in exc.value.message
    assert StockMovement.objects.count() == before
    a.refresh_from_db()
    assert a.status == Status.IN_PROGRESS

    services.revert_order(manager, b, REASON)
    services.revert_order(manager, a, REASON)
    assert_packaging_home(line)
    assert_packaging_home(line, extra)
    assert current_balance(line.lots["bulk"], line.tank) == D("1000")


@pytest.mark.usefixtures("invariants")
def test_packaging_used_by_a_finished_order_is_not_sent_to_revert_it(
    line: Line, planner, depo, filler, manager, commit
):
    """Ambalajı tüketen emir geri alınamaz durumdaysa (ör. tamamlanmış) ileti onu geri almayı
    önermez; hiçbir şey değişmez."""
    a, b, _extra = two_orders_on_one_line(line, planner, depo, filler, commit, shared_lots=False)
    # Kurgu: B'nin dolumu gerçekten yapılmış ve emir tamamlanmış sayılır.
    FillingOrder.objects.filter(pk=b.pk).update(status=Status.COMPLETED)
    before = StockMovement.objects.count()

    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, a, REASON)

    assert exc.value.code == "packaging_used_elsewhere"
    assert b.number in exc.value.message
    assert "geri alınamayan" in exc.value.message
    assert "Önce" not in exc.value.message
    assert StockMovement.objects.count() == before


# --- kural ihlalleri -------------------------------------------------------------------------


def test_revert_requires_access(line: Line, planner, depo, filler, make_user):
    run = started_run(line, planner, depo, filler)
    for user in (planner, depo, filler, make_user("laboratuvar", username="lab")):
        with pytest.raises(PermissionDenied):
            services.revert_order(user, run.order, REASON)
    with pytest.raises(PermissionDenied):
        services.revert_order(None, run.order, REASON)


def test_revert_requires_reason(line: Line, planner, depo, filler, manager):
    run = started_run(line, planner, depo, filler)
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, "  ")
    assert exc.value.code == "cancel_reason_required"


@pytest.mark.usefixtures("invariants")
def test_revert_refuses_orders_not_started_or_closed(
    line: Line, planner, depo, filler, lab, manager, commit
):
    draft = services.create_order(planner, order_data(line))
    approved = approved_order(line, planner)
    cancelled = services.cancel_order(planner, approved_order(line, planner), "Plan değişti")
    for order in (draft, approved, cancelled):
        with pytest.raises(BusinessRuleError) as exc:
            services.revert_order(manager, order, REASON)
        assert exc.value.code == "order_not_revertible"

    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("780"))
    services.finish_run(filler, run, 1000)
    order = services.finish_filling(filler, run.order)
    with commit():
        inventory.release_lot(lab, run.output_lot, "Analiz uygun", quality_decision=True)
    order.refresh_from_db()
    assert order.status == Status.COMPLETED
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, order, REASON)
    assert exc.value.code == "order_not_revertible"


def _finished(line: Line, planner, depo, filler) -> FillingRun:
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("780"))
    services.finish_run(filler, run, 1000)
    run.refresh_from_db()
    return run


@pytest.mark.usefixtures("invariants")
def test_output_lot_moved_or_released_cannot_be_reverted(
    line: Line, planner, depo, filler, manager, make_user
):
    run = _finished(line, planner, depo, filler)
    lot = run.output_lot
    # Elle transfer (kaynak belge yok; ör. stok sayfasından).
    inventory.transfer(manager, lot, line.finished_store, line.storage, D("10"))
    before = StockMovement.objects.count()
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, REASON)
    assert exc.value.code == "output_lot_used"
    assert lot.lot_no in exc.value.message
    assert StockMovement.objects.count() == before


@pytest.mark.usefixtures("invariants")
def test_released_output_lot_cannot_be_reverted(
    line: Line, planner, depo, filler, manager, make_user
):
    run = _finished(line, planner, depo, filler)
    admin = make_user("admin", username="admin")
    inventory.release_lot(admin, run.output_lot, "Elle serbest bırakma: test")
    run.output_lot.refresh_from_db()
    assert run.output_lot.status == Lot.Status.RELEASED
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, REASON)
    assert exc.value.code == "output_lot_used"


@pytest.mark.usefixtures("invariants")
def test_output_lot_used_as_input_or_reserved_cannot_be_reverted(
    line: Line, planner, depo, filler, manager
):
    run = _finished(line, planner, depo, filler)
    lot = run.output_lot
    reservation_lot = Lot.objects.get(pk=lot.pk)
    Lot.objects.filter(pk=lot.pk).update(status=Lot.Status.RELEASED)
    reservation_lot.refresh_from_db()
    inventory.reserve(
        manager,
        lot=reservation_lot,
        location=line.finished_store,
        quantity=D("5"),
        source=run.order,
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, REASON)
    assert exc.value.code == "output_lot_reserved"

    child = stocked_lot("1", material=line.finished, location=line.storage)
    inventory.link_lots(manager, lot, child, D("1"))
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, REASON)
    assert exc.value.code == "output_lot_consumed"


@pytest.mark.usefixtures("invariants")
def test_sample_awaiting_approval_blocks_revert(line: Line, planner, depo, filler, manager):
    run = _finished(line, planner, depo, filler)
    sample = open_sample_for(run.output_lot, SampleStage.FINAL)
    Sample.objects.filter(pk=sample.pk).update(status=Sample.Status.AWAITING_APPROVAL)
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, REASON)
    assert exc.value.code == "sample_awaiting_approval"


@pytest.mark.usefixtures("invariants")
def test_packaging_moved_away_from_line_refuses_without_changes(
    line: Line, planner, depo, filler, manager
):
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("400"))
    inventory.transfer(manager, line.lots["cap"], line.line_location, line.storage, D("500"))
    before = StockMovement.objects.count()

    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, REASON)

    assert exc.value.code == "negative_stock"
    assert line.lots["cap"].lot_no in exc.value.message
    assert StockMovement.objects.count() == before
    run.refresh_from_db()
    assert run.status == RunStatus.IN_PROGRESS


@pytest.mark.usefixtures("invariants")
def test_inactive_receiving_location_refuses(line: Line, planner, depo, filler, manager):
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("400"))
    line.tank.is_active = False
    line.tank.save(update_fields=["is_active"])
    with pytest.raises(BusinessRuleError) as exc:
        services.revert_order(manager, run.order, REASON)
    assert exc.value.code == "inactive_reference"
    assert line.tank.code in exc.value.message


@pytest.mark.usefixtures("invariants")
def test_failure_after_reversals_rolls_everything_back(
    line: Line, planner, depo, filler, manager, monkeypatch, published, commit
):
    run, _second = completed_run_order(line, planner, depo, filler, commit)
    before = StockMovement.objects.count()
    published.clear()

    def boom(*args, **kwargs):
        raise BusinessRuleError("boom", "Numune iptal edilemedi.")

    monkeypatch.setattr("apps.quality.services.cancel_lot_samples", boom)
    with commit(), pytest.raises(BusinessRuleError):
        services.revert_order(manager, run.order, REASON)

    assert StockMovement.objects.count() == before
    run.refresh_from_db()
    assert run.status == RunStatus.COMPLETED
    assert not run.order.picks.filter(returned_at__isnull=False).exists()
    assert current_balance(run.output_lot, line.finished_store) == D("1000")
    assert published == []
