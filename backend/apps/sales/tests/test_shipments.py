"""Sevkiyat servisleri (Adım 3.2): planlama, lot okutarak toplama, raf ömrü ve lot engelleri,
farklı lot gerekçesi, geri alma, yükleme, sevk (SHIPMENT hareketi, rezervasyon kullanımı,
sipariş durumu), iptal, iş akışı görevleri ve durum makinesi."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.roles import DEPO, YONETIM
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockMovement, StockReservation
from apps.inventory.services import current_balance
from apps.inventory.tests.factories import storage_location
from apps.masterdata.models import Location
from apps.masterdata.tests.factories import CustomerFactory
from apps.sales import selectors, services
from apps.sales.models import SalesOrder, Shipment
from apps.sales.state import shipment_states
from apps.sales.tests.factories import (
    confirmed_order,
    finished_lot,
    finished_product,
    shipping_location,
)
from apps.workflow.models import Notification, Task

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

D = Decimal
Status = Shipment.Status
Commit = Callable[[], AbstractContextManager[Any]]
VEHICLE = {"vehicle_plate": "34 abc 123", "driver_name": "Ali Veli", "driver_id_no": "12345678901"}


@pytest.fixture
def picker(make_user: Callable[..., User]) -> User:
    return make_user(DEPO, username="depo")


@pytest.fixture
def dock() -> Location:
    return shipping_location(code="SEVK")


def today() -> Any:
    return timezone.localdate()


def reservations(order: SalesOrder, **filters: Any) -> list[tuple[str, str, Decimal, str]]:
    return [
        (r.lot.lot_no, r.location.code, r.quantity, r.status)
        for r in StockReservation.objects.filter(sales_order_line__order=order, **filters)
        .select_related("lot", "location")
        .order_by("id")
    ]


def plan(seller: User, order: SalesOrder, **data: Any) -> Shipment:
    return services.plan_shipment(seller, order, {"planned_date": today(), **data})


# --- planlama --------------------------------------------------------------------------------


def test_plan_defaults_to_remaining_quantity(seller: User, dock: Location) -> None:
    product = finished_product()
    finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "5", "KOLI")])

    shipment = plan(seller, order, **VEHICLE)

    assert shipment.number.startswith(f"SV-{today().year}-")
    assert shipment.status == Status.PLANNED
    assert shipment.loading_location == dock
    assert shipment.vehicle_plate == "34 ABC 123"
    assert [line.quantity for line in shipment.lines.all()] == [D("60")]
    # Tamamı planlandı: ikinci sevkiyat planlanamaz.
    with pytest.raises(BusinessRuleError) as exc:
        plan(seller, order)
    assert exc.value.code == "nothing_to_ship"


def test_plan_rules(seller: User, picker: User, dock: Location) -> None:
    product = finished_product()
    finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "60", "ADET")])
    line = order.lines.get()
    with pytest.raises(BusinessRuleError) as exc:
        services.plan_shipment(
            seller, order, {"planned_date": today()}, [{"order_line": line, "quantity": "61"}]
        )
    assert exc.value.code == "shipment_exceeds_order"
    with pytest.raises(BusinessRuleError) as exc:
        plan(seller, order, driver_id_no="123")
    assert exc.value.code == "invalid_driver_id"
    with pytest.raises(PermissionDenied):
        plan(picker, order)

    partial = services.plan_shipment(
        seller, order, {"planned_date": today()}, [{"order_line": line, "quantity": "20"}]
    )
    assert services.plannable_quantity(line) == D("40")
    assert partial.lines.get().quantity == D("20")


def test_plan_requires_confirmed_order_and_loading_location(seller: User) -> None:
    from apps.sales.tests.factories import draft_order

    product = finished_product()
    order = draft_order(seller, [(product, "1", "ADET")])
    with pytest.raises(BusinessRuleError) as exc:
        plan(seller, order)
    assert exc.value.code == "order_not_shippable"
    finished_lot(product, "10")
    order = services.confirm_order(seller, order)
    with pytest.raises(BusinessRuleError) as exc:
        plan(seller, order)
    assert exc.value.code == "no_loading_location"


# --- toplama ---------------------------------------------------------------------------------


def test_pick_reserved_lot_moves_stock_and_reservation(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    depot = storage_location(code="MAMUL")
    lot = finished_lot(product, "100", location=depot)
    order = confirmed_order(seller, [(product, "60", "ADET")])
    shipment = plan(seller, order)

    picks = services.pick_lot(picker, shipment, lot)

    assert [(p.quantity, p.from_location, p.to_location) for p in picks] == [(D("60"), depot, dock)]
    shipment.refresh_from_db()
    assert shipment.status == Status.PICKING
    assert current_balance(lot, depot) == D("40")
    assert current_balance(lot, dock) == D("60")
    assert reservations(order, status=StockReservation.Status.ACTIVE) == [
        (lot.lot_no, "SEVK", D("60.0000"), "ACTIVE")
    ]
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_lot(picker, shipment, lot)
    assert exc.value.code == "line_already_picked"


def test_pick_partial_quantity_and_exceeding_line(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    lot = finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "60", "ADET")])
    shipment = plan(seller, order)

    services.pick_lot(picker, shipment, lot, D("24"))
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_lot(picker, shipment, lot, D("37"))
    assert exc.value.code == "pick_exceeds_line"
    services.pick_lot(picker, shipment, lot)

    assert services.picked_quantity(shipment.lines.get()) == D("60")
    assert sorted(r[2] for r in reservations(order, status="ACTIVE")) == [D("24"), D("36")]


@pytest.mark.parametrize(
    ("status", "expiry_days", "code"),
    [
        (Lot.Status.QUARANTINE, 365, "lot_not_released"),
        (Lot.Status.RELEASED, -1, "lot_expired"),
        (Lot.Status.RELEASED, 100, "shelf_life_too_short"),
    ],
)
def test_unshippable_lots_cannot_be_picked(
    seller: User, picker: User, dock: Location, status: str, expiry_days: int, code: str
) -> None:
    product = finished_product()
    customer = CustomerFactory.create(min_remaining_shelf_life_days=180)
    good = finished_lot(product, "100", expiry_date=today() + timedelta(days=365))
    bad = finished_lot(
        product, "100", status=status, expiry_date=today() + timedelta(days=expiry_days)
    )
    order = confirmed_order(seller, [(product, "10", "ADET")], customer=customer)
    shipment = plan(seller, order)

    with pytest.raises(BusinessRuleError) as exc:
        services.pick_lot(picker, shipment, bad, reason="deneme")
    assert exc.value.code == code
    assert current_balance(bad, dock) == 0
    services.pick_lot(picker, shipment, good)


def test_pick_other_lot_needs_reason_and_releases_reservation(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    early = finished_lot(product, "50", expiry_date=today() + timedelta(days=100))
    late = finished_lot(product, "50", expiry_date=today() + timedelta(days=200))
    order = confirmed_order(seller, [(product, "30", "ADET")])
    assert [r[0] for r in reservations(order)] == [early.lot_no]
    shipment = plan(seller, order)

    with pytest.raises(BusinessRuleError) as exc:
        services.pick_lot(picker, shipment, late)
    assert exc.value.code == "lot_not_reserved"

    [pick] = services.pick_lot(picker, shipment, late, reason="Ön sıradaki palet")

    assert pick.deviation_reason == "Ön sıradaki palet"
    assert reservations(order, status="ACTIVE") == [(late.lot_no, "SEVK", D("30.0000"), "ACTIVE")]
    line = order.lines.get()
    assert services.reserved_quantity(line) == D("30")
    assert services.shortage_quantity(line) == 0


def test_pick_unreserved_lot_when_line_has_shortage(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    order = confirmed_order(seller, [(product, "30", "ADET")])
    assert reservations(order) == []
    lot = finished_lot(product, "40")
    shipment = plan(seller, order)

    services.pick_lot(picker, shipment, lot)

    assert reservations(order, status="ACTIVE") == [(lot.lot_no, "SEVK", D("30.0000"), "ACTIVE")]


def test_pick_rules_for_role_and_product(seller: User, picker: User, dock: Location) -> None:
    product = finished_product()
    other = finished_product()
    lot = finished_lot(product, "10")
    stranger = finished_lot(other, "10")
    order = confirmed_order(seller, [(product, "5", "ADET")])
    shipment = plan(seller, order)
    with pytest.raises(PermissionDenied):
        services.pick_lot(seller, shipment, lot)
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_lot(picker, shipment, stranger)
    assert exc.value.code == "lot_not_in_shipment"


def test_undo_pick_returns_lot_and_reserves_again(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    depot = storage_location()
    lot = finished_lot(product, "100", location=depot)
    order = confirmed_order(seller, [(product, "60", "ADET")])
    shipment = plan(seller, order)
    [pick] = services.pick_lot(picker, shipment, lot)

    services.undo_pick(picker, pick)

    pick.refresh_from_db()
    assert pick.returned_at is not None
    assert current_balance(lot, depot) == D("100")
    assert current_balance(lot, dock) == 0
    assert [r[1:] for r in reservations(order, status="ACTIVE")] == [
        (depot.code, D("60.0000"), "ACTIVE")
    ]
    with pytest.raises(BusinessRuleError) as exc:
        services.undo_pick(picker, pick)
    assert exc.value.code == "pick_already_returned"


# --- yükleme ve sevk -------------------------------------------------------------------------


def test_load_and_dispatch_ships_stock(
    seller: User, picker: User, dock: Location, commit: Commit
) -> None:
    product = finished_product()
    lot = finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "5", "KOLI")])
    shipment = plan(seller, order)
    with pytest.raises(BusinessRuleError) as exc:
        services.mark_loaded(picker, shipment)
    assert exc.value.code == "invalid_transition"
    services.pick_lot(picker, shipment, lot)
    services.mark_loaded(picker, shipment)
    shipment.refresh_from_db()
    assert shipment.status == Status.LOADED
    with pytest.raises(BusinessRuleError) as exc:
        services.dispatch_shipment(seller, shipment)
    assert exc.value.code == "vehicle_required"
    services.update_shipment(seller, shipment, VEHICLE)
    with pytest.raises(PermissionDenied):
        services.dispatch_shipment(picker, shipment)

    with commit():
        services.dispatch_shipment(seller, shipment)

    shipment.refresh_from_db()
    order.refresh_from_db()
    assert shipment.status == Status.DISPATCHED
    assert order.status == SalesOrder.Status.SHIPPED
    assert current_balance(lot, dock) == 0
    movement = StockMovement.objects.get(movement_type=StockMovement.Type.SHIPMENT)
    assert (movement.quantity, movement.document_number, movement.location) == (
        D("-60"),
        shipment.number,
        dock,
    )
    assert reservations(order, status="ACTIVE") == []
    assert services.shipped_quantity(order.lines.get()) == D("60")
    assert selectors.shipped_by_shipment_lot(shipment) == {lot.pk: D("60")}


def test_partial_dispatch_marks_order_partially_shipped(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    lot = finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "60", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    services.pick_lot(picker, shipment, lot, D("20"))
    services.mark_loaded(picker, shipment)
    services.dispatch_shipment(seller, shipment)

    order.refresh_from_db()
    line = order.lines.get()
    assert order.status == SalesOrder.Status.PARTIALLY_SHIPPED
    assert services.shipped_quantity(line) == D("20")
    assert services.reserved_quantity(line) == D("40")
    assert services.plannable_quantity(line) == D("40")

    second = plan(seller, order, **VEHICLE)
    services.pick_lot(picker, second, lot)
    services.mark_loaded(picker, second)
    services.dispatch_shipment(seller, second)
    order.refresh_from_db()
    assert order.status == SalesOrder.Status.SHIPPED


def test_lot_blocked_after_picking_stops_dispatch(
    seller: User, picker: User, dock: Location, commit: Commit
) -> None:
    product = finished_product()
    lot = finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    [pick] = services.pick_lot(picker, shipment, lot)
    admin = User.objects.create_superuser("yonetici", password="x")
    with commit():
        inventory.block_lot(admin, lot, "Şikâyet")

    with pytest.raises(BusinessRuleError) as exc:
        services.mark_loaded(picker, shipment)
    assert exc.value.code == "picked_lot_unusable"
    services.undo_pick(picker, pick)
    assert current_balance(lot, dock) == 0
    assert reservations(order, status="ACTIVE") == []


def test_cancel_returns_picks(seller: User, picker: User, dock: Location, commit: Commit) -> None:
    product = finished_product()
    depot = storage_location()
    lot = finished_lot(product, "100", location=depot)
    order = confirmed_order(seller, [(product, "60", "ADET")])
    shipment = plan(seller, order)
    services.pick_lot(picker, shipment, lot)
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_order(seller, order, "Müşteri vazgeçti")
    assert exc.value.code == "open_shipments"
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_shipment(seller, shipment, " ")
    assert exc.value.code == "cancel_reason_required"

    with commit():
        services.cancel_shipment(seller, shipment, "Araç gelmedi")

    shipment.refresh_from_db()
    assert shipment.status == Status.CANCELLED
    assert current_balance(lot, depot) == D("100")
    assert [r[1:] for r in reservations(order, status="ACTIVE")] == [
        (depot.code, D("60.0000"), "ACTIVE")
    ]
    assert services.plannable_quantity(order.lines.get()) == D("60")
    assert not Task.objects.filter(rule_code="pick_shipment", status__in=Task.OPEN_STATUSES)


def test_dispatched_shipment_cannot_be_cancelled(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    lot = finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    services.pick_lot(picker, shipment, lot)
    services.mark_loaded(picker, shipment)
    services.dispatch_shipment(seller, shipment)
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_shipment(seller, shipment, "geç")
    assert exc.value.code == "invalid_transition"


# --- iş akışı, KVKK, durum makinesi ----------------------------------------------------------


def test_workflow_tasks_and_dispatch_notification(
    seller: User,
    picker: User,
    dock: Location,
    commit: Commit,
    make_user: Callable[..., User],
) -> None:
    manager = make_user(YONETIM, username="yonetim")
    product = finished_product()
    lot = finished_lot(product, "100")
    with commit():
        order = confirmed_order(seller, [(product, "60", "ADET")])
    plan_task = Task.objects.get(rule_code="plan_shipment")

    with commit():
        shipment = plan(seller, order, **VEHICLE)
    plan_task.refresh_from_db()
    assert plan_task.status == Task.Status.DONE
    pick_task = Task.objects.get(rule_code="pick_shipment")
    assert pick_task.title == f"Toplama yap: {shipment.number}"
    assert pick_task.assigned_role is not None and pick_task.assigned_role.name == DEPO

    with commit():
        services.pick_lot(picker, shipment, lot)
        services.mark_loaded(picker, shipment)
    pick_task.refresh_from_db()
    assert pick_task.status == Task.Status.DONE
    dispatch_task = Task.objects.get(rule_code="dispatch_shipment")
    assert dispatch_task.title == f"Sevki onayla / irsaliye kes: {shipment.number}"

    other = make_user("sevkiyat", username="sevkiyat2")
    with commit():
        services.dispatch_shipment(other, shipment)
    dispatch_task.refresh_from_db()
    assert dispatch_task.status == Task.Status.DONE
    recipients = set(
        Notification.objects.filter(rule_code="shipment_dispatched").values_list(
            "recipient__username", flat=True
        )
    )
    assert recipients == {seller.username, manager.username}


def test_partial_plan_keeps_plan_task_open(seller: User, dock: Location, commit: Commit) -> None:
    product = finished_product()
    finished_lot(product, "100")
    with commit():
        order = confirmed_order(seller, [(product, "60", "ADET")])
        services.plan_shipment(
            seller,
            order,
            {"planned_date": today()},
            [{"order_line": order.lines.get(), "quantity": "10"}],
        )
    assert Task.objects.get(rule_code="plan_shipment").status in Task.OPEN_STATUSES


def test_driver_id_is_masked_in_audit_log(seller: User, dock: Location) -> None:
    product = finished_product()
    finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    shipment = services.update_shipment(seller, shipment, {"driver_id_no": "10987654321"})

    logs = AuditLog.objects.filter(object_id=shipment.pk, content_type__model="shipment")
    text = str(list(logs.values_list("changes", flat=True)))
    assert "12345678901" not in text and "10987654321" not in text
    assert "*******8901" in text and "*******4321" in text
    assert selectors.masked_driver_id(shipment) == "*******4321"


def test_shipment_state_machine() -> None:
    allowed = {
        ("PLANNED", "PICKING"),
        ("PLANNED", "CANCELLED"),
        ("PICKING", "LOADED"),
        ("PICKING", "CANCELLED"),
        ("LOADED", "DISPATCHED"),
        ("LOADED", "CANCELLED"),
    }
    for source in shipment_states.states:
        for target in shipment_states.states:
            assert shipment_states.can_transition(source, target) == ((source, target) in allowed)
