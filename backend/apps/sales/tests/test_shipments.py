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


# --- sevk alanları, toplanan miktar ve kenar durumları ---------------------------------------


def test_stock_at_shipping_location_is_not_reserved_or_suggested(
    seller: User, picker: User, dock: Location
) -> None:
    """Sevk alanındaki stok başka sevkiyatın okutulmuş malıdır: FEFO, elle rezervasyon, aday
    listesi ve toplama önerisi onu kullanmaz."""
    product = finished_product()
    staged = finished_lot(product, "50", location=dock)
    order = confirmed_order(seller, [(product, "10", "ADET")])
    line = order.lines.get()
    assert reservations(order) == []
    assert services.shortage_quantity(line) == D("10")
    with pytest.raises(BusinessRuleError) as exc:
        services.reserve_lot(seller, line, lot=staged, location=dock, quantity=D("10"))
    assert exc.value.code == "invalid_reservation_location"

    stock = finished_lot(product, "20")
    shipment = plan(seller, order)
    [row] = selectors.pick_suggestions(shipment)
    assert [s["lot"] for s in row["suggestions"]] == [stock.pk]


def test_suggestions_list_partly_reserved_lot_once(seller: User, dock: Location) -> None:
    """Satıra kısmen rezerve edilen lot, rezerve ve rezervesiz kısmıyla tek satırda önerilir."""
    product = finished_product()
    lot = finished_lot(product, "100", expiry_date=today() + timedelta(days=300))
    later = finished_lot(product, "30", expiry_date=today() + timedelta(days=600))
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order)

    [row] = selectors.pick_suggestions(shipment)
    assert [
        (s["lot"], s["quantity"], s["reserved_quantity"], s["reserved"]) for s in row["suggestions"]
    ] == [(lot.pk, D("100"), D("10"), True), (later.pk, D("30"), D("0"), False)]


def test_pick_does_not_touch_another_docks_picked_stock(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    second_dock = shipping_location(code="SEVK-2")
    first = finished_lot(product, "60", expiry_date=today() + timedelta(days=400))
    other = finished_lot(product, "40", expiry_date=today() + timedelta(days=500))
    order = confirmed_order(seller, [(product, "100", "ADET")])
    line = order.lines.get()
    s1 = services.plan_shipment(
        seller, order, {"planned_date": today()}, [{"order_line": line, "quantity": "60"}]
    )
    s2 = services.plan_shipment(
        seller,
        order,
        {"planned_date": today(), "loading_location": second_dock},
        [{"order_line": line, "quantity": "40"}],
    )
    services.pick_lot(picker, s1, first)

    # İkinci rampa ilk sevkiyatın okuttuğu lotu "rezerve" saymaz: farklı lot gerekçesi ister.
    with pytest.raises(BusinessRuleError) as exc:
        services.pick_lot(picker, s2, first)
    assert exc.value.code == "lot_not_reserved"
    suggestions = selectors.pick_suggestions(s2)[0]["suggestions"]
    assert [(s["lot"], s["reserved"]) for s in suggestions] == [(other.pk, True)]
    services.pick_lot(picker, s2, other)

    assert current_balance(first, dock) == D("60")
    assert current_balance(other, second_dock) == D("40")
    services.mark_loaded(picker, s1)
    services.mark_loaded(picker, s2)


def test_dock_reservation_cannot_be_released_from_the_order(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    lot = finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order)
    services.pick_lot(picker, shipment, lot, D("5"))
    services.pick_lot(picker, shipment, lot, D("5"))
    staged = StockReservation.objects.filter(location=dock, status="ACTIVE").first()
    assert staged is not None

    with pytest.raises(BusinessRuleError) as exc:
        services.release_line_reservation(seller, staged)
    assert exc.value.code == "reservation_on_loading"


def test_dispatch_needs_dock_reservation_for_all_picks_of_a_lot(
    seller: User, picker: User, dock: Location
) -> None:
    """Aynı lottan iki okutma tek rezervasyon havuzunu paylaşır; havuz okutulan toplamdan az
    kalırsa yükleme ve sevk reddedilir (sevk edilen = CONSUMED rezervasyon)."""
    product = finished_product()
    lot = finished_lot(product, "100")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    services.pick_lot(picker, shipment, lot, D("5"))
    services.pick_lot(picker, shipment, lot, D("5"))
    services.mark_loaded(picker, shipment)
    # Havuzdan 5 kaybolur (ör. eski yoldan bırakılmış rezervasyon).
    staged = StockReservation.objects.filter(location=dock, status="ACTIVE").first()
    assert staged is not None
    inventory.release_reservation(seller, staged, "test")

    with pytest.raises(BusinessRuleError) as exc:
        services.dispatch_shipment(seller, shipment)
    assert exc.value.code == "picked_lot_unreserved"
    assert not StockMovement.objects.filter(movement_type=StockMovement.Type.SHIPMENT).exists()


def test_picking_that_covers_shortage_closes_shortage_task(
    seller: User, picker: User, dock: Location, commit: Commit
) -> None:
    product = finished_product()
    with commit():
        order = confirmed_order(seller, [(product, "30", "ADET")])
    task = Task.objects.get(rule_code="sales_shortage")
    lot = finished_lot(product, "40")
    shipment = plan(seller, order)

    with commit():
        services.pick_lot(picker, shipment, lot)

    task.refresh_from_db()
    assert task.status == Task.Status.DONE


def test_undo_pick_after_loading_lets_rest_ship(
    seller: User, picker: User, dock: Location, commit: Commit
) -> None:
    product = finished_product()
    bad = finished_lot(product, "10", expiry_date=today() + timedelta(days=100))
    good = finished_lot(product, "10", expiry_date=today() + timedelta(days=200))
    order = confirmed_order(seller, [(product, "20", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    [bad_pick] = services.pick_lot(picker, shipment, bad)
    services.pick_lot(picker, shipment, good)
    services.mark_loaded(picker, shipment)
    admin = User.objects.create_superuser("yonetici", password="x")
    with commit():
        inventory.block_lot(admin, bad, "Şikâyet")
    with pytest.raises(BusinessRuleError) as exc:
        services.dispatch_shipment(seller, shipment)
    assert exc.value.code == "picked_lot_unusable"

    services.undo_pick(picker, bad_pick)
    shipment.refresh_from_db()
    assert shipment.status == Status.LOADED
    services.dispatch_shipment(seller, shipment)

    order.refresh_from_db()
    assert order.status == SalesOrder.Status.PARTIALLY_SHIPPED
    assert services.shipped_quantity(order.lines.get()) == D("10")
    assert current_balance(bad, dock) == 0


def test_dispatch_without_active_picks_is_refused(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    lot = finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    [pick] = services.pick_lot(picker, shipment, lot)
    services.mark_loaded(picker, shipment)
    services.undo_pick(picker, pick)

    with pytest.raises(BusinessRuleError) as exc:
        services.dispatch_shipment(seller, shipment)
    assert exc.value.code == "nothing_picked"
    services.cancel_shipment(seller, shipment, "Lot kalmadı")


def test_pick_locks_order_and_lot_before_balances(
    seller: User, picker: User, dock: Location
) -> None:
    """Kilit sırası sevkiyat → sipariş → lot → bakiye/rezervasyon; lot kilidi yalnızca lot
    satırını kilitler (malzeme ve ortak birim satırını değil)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    product = finished_product()
    lot = finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = plan(seller, order)
    with CaptureQueriesContext(connection) as queries:
        services.pick_lot(picker, shipment, lot)
    locked = [q["sql"] for q in queries.captured_queries if "FOR UPDATE" in q["sql"]]

    def first(table: str) -> int:
        return next(i for i, sql in enumerate(locked) if f'FROM "{table}"' in sql)

    assert first("sales_shipment") < first("sales_salesorder") < first("inventory_lot")
    assert first("inventory_lot") < first("inventory_stockreservation")
    assert first("inventory_lot") < first("inventory_stockbalance")
    lot_locks = [sql for sql in locked if 'FROM "inventory_lot"' in sql]
    assert all('FOR UPDATE OF "inventory_lot"' in sql for sql in lot_locks)


def test_suggestions_mark_expired_reserved_lot(seller: User, picker: User, dock: Location) -> None:
    product = finished_product()
    lot = finished_lot(product, "10", expiry_date=today() + timedelta(days=5))
    order = confirmed_order(seller, [(product, "10", "ADET")])
    Lot.objects.filter(pk=lot.pk).update(expiry_date=today() - timedelta(days=1))
    shipment = plan(seller, order)

    [row] = selectors.pick_suggestions(shipment)
    assert [(s["lot"], s["reserved"], s["meets_shelf_life"]) for s in row["suggestions"]] == [
        (lot.pk, True, False)
    ]


def test_waybill_uses_local_date_and_does_not_add_mixed_units(
    seller: User, picker: User, dock: Location
) -> None:
    from datetime import UTC, datetime

    from apps.masterdata.models import Material
    from apps.masterdata.tests.factories import MaterialFactory, unit
    from apps.sales.waybill import waybill_pdf

    product = finished_product()
    bulk = MaterialFactory.create(material_type=Material.Type.FINISHED, base_unit=unit("KG"))
    finished_lot(product, "24")
    finished_lot(bulk, "50")
    order = confirmed_order(seller, [(product, "24", "ADET"), (bulk, "20", "KG")])
    shipment = plan(seller, order, **VEHICLE)
    for reservation in services.active_reservations(order):
        services.pick_lot(picker, shipment, reservation.lot)
    services.mark_loaded(picker, shipment)
    services.dispatch_shipment(seller, shipment)
    # 16 Ekim 22:30 UTC = 17 Ekim 01:30 İstanbul.
    Shipment.objects.filter(pk=shipment.pk).update(
        dispatched_at=datetime(2026, 10, 16, 22, 30, tzinfo=UTC)
    )
    shipment.refresh_from_db()

    data = selectors.waybill_data(shipment)
    assert data["date"].isoformat() == "2026-10-17"
    assert (data["total_quantity"], data["total_unit"]) == (None, "")
    assert waybill_pdf(shipment).startswith(b"%PDF")

    single = selectors.waybill_data(
        Shipment.objects.get(pk=plan_single(seller, picker, product).pk)
    )
    assert (single["total_quantity"], single["total_unit"]) == (D("12"), "ADET")


def plan_single(seller: User, picker: User, product: Any) -> Shipment:
    lot = finished_lot(product, "12")
    order = confirmed_order(seller, [(product, "12", "ADET")])
    shipment = plan(seller, order)
    services.pick_lot(picker, shipment, lot)
    return shipment


def test_reversed_shipment_movement_is_not_counted_as_shipped(
    seller: User, picker: User, dock: Location
) -> None:
    product = finished_product()
    lot = finished_lot(product, "30")
    order = confirmed_order(seller, [(product, "30", "ADET")])
    shipment = plan(seller, order, **VEHICLE)
    services.pick_lot(picker, shipment, lot)
    services.mark_loaded(picker, shipment)
    services.dispatch_shipment(seller, shipment)
    assert selectors.shipped_by_shipment_lot(shipment) == {lot.pk: D("30")}
    movement = StockMovement.objects.get(movement_type=StockMovement.Type.SHIPMENT)

    inventory.reverse_movement(picker, movement, "Yanlış sevk kaydı")

    assert selectors.shipped_by_shipment_lot(shipment) == {}
    assert list(selectors.customer_shipped_lots(order.customer)) == []


def test_waybill_seller_comes_from_company_profile(
    seller: User, picker: User, dock: Location
) -> None:
    from apps.masterdata import services as masterdata
    from apps.masterdata.models import CompanyProfile
    from apps.sales.waybill import waybill_pdf

    profile = masterdata.get_company_profile()
    CompanyProfile.objects.filter(pk=profile.pk).update(
        legal_name="Örnek Deterjan A.Ş.",
        address="OSB 1. Cadde\nKocaeli",
        tax_office="Gebze",
        tax_number="1234567890",
        trade_registry_no="Gebze 12345",
        mersis_no="0123456789000017",
    )
    shipment = plan_single(seller, picker, finished_product())
    assert selectors.waybill_data(shipment)["company"] == {
        "name": "Örnek Deterjan A.Ş.",
        "address": "OSB 1. Cadde\nKocaeli",
        "tax_office": "Gebze",
        "tax_no": "1234567890",
        "registry": "Ticaret sicil no: Gebze 12345  MERSİS no: 0123456789000017",
    }
    assert waybill_pdf(shipment).startswith(b"%PDF")
