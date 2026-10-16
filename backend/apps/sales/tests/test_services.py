"""Satış siparişi servisleri: oluşturma, birim çevrimi, onayda FEFO rezervasyonu, raf ömrü
(D-11), eksik görevi, elle rezervasyon, iptal, kapanış ve durum makinesi."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.services import transition_status
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory
from apps.inventory.models import StockReservation
from apps.inventory.tests.factories import quarantine_location, stocked_lot, storage_location
from apps.masterdata.tests.factories import CustomerFactory, MaterialFactory, unit
from apps.sales import selectors, services
from apps.sales.models import SalesOrder
from apps.sales.state import sales_order_states
from apps.sales.tests.factories import draft_order, finished_lot, finished_product
from apps.workflow.models import Task

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

D = Decimal
Status = SalesOrder.Status
Commit = Callable[[], AbstractContextManager[Any]]


def today() -> date:
    return timezone.localdate()


def line_values(order: SalesOrder) -> list[tuple[Any, ...]]:
    return list(
        selectors.order_lines(order).values_list(  # type: ignore[misc]
            "base_quantity", "reserved_quantity", "shipped_quantity", "shortage_quantity"
        )
    )


# --- oluşturma ve düzenleme --------------------------------------------------------------------


def test_create_order_converts_units_and_numbers(seller: User) -> None:
    product = finished_product()
    customer = CustomerFactory.create(address="Ankara")

    order = draft_order(
        seller,
        [(product, "2", "PALET"), (product, "3", "KOLI"), (product, "5", "ADET")],
        customer=customer,
    )

    assert order.number.startswith(f"SS-{today().year}-")
    assert order.status == Status.DRAFT
    assert order.delivery_address == "Ankara"
    assert [line.base_quantity for line in order.lines.order_by("line_no")] == [
        D("960"),
        D("36"),
        D("5"),
    ]


def test_order_line_rules(seller: User) -> None:
    product = finished_product()
    raw = MaterialFactory.create()
    with pytest.raises(BusinessRuleError) as exc:
        draft_order(seller, [(raw, "1", "KG")])
    assert exc.value.code == "sales_material_type"
    with pytest.raises(BusinessRuleError) as exc:
        draft_order(seller, [(product, "1", "KG")])
    assert exc.value.code == "no_conversion"
    with pytest.raises(BusinessRuleError) as exc:
        services.create_order(
            seller,
            {"customer": CustomerFactory.create(), "order_date": today()},
            [{"product": product, "quantity": D("1"), "unit": unit("ADET"), "unit_price": D("5")}],
        )
    assert exc.value.code == "currency_required"


def test_only_sales_roles_create_orders(planner: User) -> None:
    with pytest.raises(PermissionDenied):
        draft_order(planner, [(finished_product(), "1", "ADET")])


def test_update_syncs_lines_only_in_draft(seller: User) -> None:
    product = finished_product()
    order = draft_order(seller, [(product, "1", "KOLI"), (product, "1", "ADET")])
    first = order.lines.get(line_no=1)

    services.update_order(
        seller,
        order,
        {"customer_po_no": "PO-7"},
        [{"id": first.pk, "product": product, "quantity": D("2"), "unit": unit("KOLI")}],
    )

    order.refresh_from_db()
    assert order.customer_po_no == "PO-7"
    assert list(order.lines.values_list("line_no", "base_quantity")) == [(1, D("24"))]

    finished_lot(product, "100")
    services.confirm_order(seller, order)
    with pytest.raises(BusinessRuleError) as exc:
        services.update_order(seller, order, {"notes": "x"})
    assert exc.value.code == "document_locked"


def test_order_totals_by_currency(seller: User) -> None:
    product = finished_product()
    order = services.create_order(
        seller,
        {"customer": CustomerFactory.create(), "order_date": today()},
        [
            {
                "product": product,
                "quantity": D("2"),
                "unit": unit("KOLI"),
                "unit_price": D("150.5"),
                "currency": "TRY",
            },
            {
                "product": product,
                "quantity": D("3"),
                "unit": unit("ADET"),
                "unit_price": D("1.333"),
                "currency": "EUR",
            },
            {"product": product, "quantity": D("1"), "unit": unit("ADET")},
        ],
    )

    assert selectors.order_totals(order) == [
        {"currency": "EUR", "amount": "4.00"},
        {"currency": "TRY", "amount": "301.00"},
    ]


# --- onay ve rezervasyon -----------------------------------------------------------------------


def test_confirm_reserves_by_fefo(seller: User, commit: Commit) -> None:
    product = finished_product()
    late = finished_lot(product, "100", expiry_date=today() + timedelta(days=400))
    early = finished_lot(product, "50", expiry_date=today() + timedelta(days=200))
    stocked_lot("500", material=product, location=quarantine_location(), status="QUARANTINE")
    order = draft_order(seller, [(product, "10", "KOLI")])

    with commit():
        services.confirm_order(seller, order)

    order.refresh_from_db()
    assert order.status == Status.CONFIRMED
    assert order.confirmed_by == seller
    reservations = list(selectors.order_reservations(order))
    assert [(r.lot_id, r.quantity) for r in reservations] == [
        (early.pk, D("50")),
        (late.pk, D("70")),
    ]
    assert all(r.document_number == order.number for r in reservations)
    assert line_values(order) == [(D("120"), D("120"), D("0"), D("0"))]
    task = Task.objects.get(rule_code="plan_shipment")
    assert task.title == f"Sevkiyat planla: {order.number}"
    assert task.assigned_role is not None and task.assigned_role.name == "sevkiyat"
    assert not Task.objects.filter(rule_code="sales_shortage").exists()


def test_reserved_stock_is_not_given_to_another_order(seller: User) -> None:
    """Kabul kriteri: rezerve stok başka siparişe ayrılamaz; `available` hesabı doğru."""
    product = finished_product()
    lot = finished_lot(product, "100")
    first = draft_order(seller, [(product, "70", "ADET")])
    second = draft_order(seller, [(product, "50", "ADET")])

    services.confirm_order(seller, first)
    services.confirm_order(seller, second)

    assert line_values(first) == [(D("70"), D("70"), D("0"), D("0"))]
    assert line_values(second) == [(D("50"), D("30"), D("0"), D("20"))]
    balance = inventory_selectors.balances().get(lot=lot)
    assert (balance.quantity, balance.reserved_quantity, balance.available_quantity) == (  # type: ignore[attr-defined]
        D("100"),
        D("100"),
        D("0"),
    )
    assert not inventory_selectors.available_lots(product).exists()
    with pytest.raises(BusinessRuleError) as exc:
        services.reserve_lot(
            seller,
            second.lines.get(),
            lot=lot,
            location=balance.location,
            quantity=D("1"),
        )
    assert exc.value.code == "insufficient_available"


def test_shortage_opens_planning_task_and_closes_when_reserved(
    seller: User, commit: Commit
) -> None:
    product = finished_product(code="MM-1", name="Sıvı deterjan 1 lt")
    location = storage_location()
    finished_lot(product, "30", location=location)
    order = draft_order(seller, [(product, "5", "KOLI")])

    with commit():
        services.confirm_order(seller, order)

    task = Task.objects.get(rule_code="sales_shortage")
    assert task.status == Task.Status.OPEN
    assert task.assigned_role is not None and task.assigned_role.name == "planlama"
    assert "MM-1 Sıvı deterjan 1 lt: 30 ADET" in task.description

    with commit():
        assert services.reserve_shortages(seller, order)[0].quantity == D("30")
    assert Task.objects.filter(rule_code="sales_shortage").count() == 1

    finished_lot(product, "40", location=location)
    with commit():
        assert services.reserve_shortages(seller, order) == []

    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    assert line_values(order) == [(D("60"), D("60"), D("0"), D("0"))]


def test_shelf_life_requirement_skips_short_lots(seller: User) -> None:
    """D-11: müşterinin asgari kalan raf ömrünü karşılamayan lot rezerve edilmez."""
    product = finished_product()
    customer = CustomerFactory.create(min_remaining_shelf_life_days=180)
    short = finished_lot(product, "100", expiry_date=today() + timedelta(days=90))
    long = finished_lot(product, "100", expiry_date=today() + timedelta(days=365))
    order = draft_order(seller, [(product, "150", "ADET")], customer=customer)

    services.confirm_order(seller, order)

    assert [(r.lot_id, r.quantity) for r in selectors.order_reservations(order)] == [
        (long.pk, D("100"))
    ]
    assert line_values(order)[0][3] == D("50")
    with pytest.raises(BusinessRuleError) as exc:
        services.reserve_lot(
            seller,
            order.lines.get(),
            lot=short,
            location=short.balances.get().location,
            quantity=D("10"),
        )
    assert exc.value.code == "shelf_life_too_short"


def test_shelf_life_is_measured_at_requested_delivery_date(seller: User) -> None:
    product = finished_product()
    customer = CustomerFactory.create(min_remaining_shelf_life_days=30)
    lot = finished_lot(product, "10", expiry_date=today() + timedelta(days=40))
    soon = draft_order(seller, [(product, "5", "ADET")], customer=customer)
    later = draft_order(
        seller,
        [(product, "5", "ADET")],
        customer=customer,
        requested_delivery_date=today() + timedelta(days=20),
    )

    assert services.shelf_life_error(lot, soon) is None
    error = services.shelf_life_error(lot, later)
    assert error is not None and error.code == "shelf_life_too_short"


def test_expired_and_blocked_lots_are_not_reserved(seller: User) -> None:
    product = finished_product()
    finished_lot(product, "100", expiry_date=today() - timedelta(days=1))
    order = draft_order(seller, [(product, "10", "ADET")])

    services.confirm_order(seller, order)

    assert line_values(order) == [(D("10"), D("0"), D("0"), D("10"))]


def test_manual_reserve_and_release(seller: User, commit: Commit) -> None:
    product = finished_product()
    location = storage_location()
    early = finished_lot(product, "10", location=location, expiry_date=today() + timedelta(10))
    late = finished_lot(product, "10", location=location, expiry_date=today() + timedelta(90))
    order = draft_order(seller, [(product, "10", "ADET")])
    services.confirm_order(seller, order)
    line = order.lines.get()
    reservation = StockReservation.objects.get(lot=early)

    with pytest.raises(BusinessRuleError) as exc:
        services.reserve_lot(seller, line, lot=late, location=location, quantity=D("1"))
    assert exc.value.code == "reservation_exceeds_line"

    with commit():
        services.release_line_reservation(seller, reservation, "müşteri uzun SKT istedi")
        services.reserve_lot(seller, line, lot=late, location=location, quantity=D("10"))

    assert [r.lot_id for r in selectors.order_reservations(order) if r.status == "ACTIVE"] == [
        late.pk
    ]
    with pytest.raises(BusinessRuleError) as exc:
        services.reserve_lot(seller, line, lot=stocked_lot("5"), location=location, quantity=D("1"))
    assert exc.value.code == "lot_material_mismatch"


def test_cancel_releases_reservations_and_cancels_tasks(seller: User, commit: Commit) -> None:
    product = finished_product()
    finished_lot(product, "5")
    order = draft_order(seller, [(product, "10", "ADET")])
    with commit():
        services.confirm_order(seller, order)
    assert Task.objects.filter(status=Task.Status.OPEN).count() == 2

    with pytest.raises(BusinessRuleError):
        services.cancel_order(seller, order, " ")
    with commit():
        services.cancel_order(seller, order, "Müşteri vazgeçti")

    order.refresh_from_db()
    assert order.status == Status.CANCELLED
    assert not StockReservation.objects.filter(status="ACTIVE").exists()
    assert not Task.objects.filter(status__in=Task.OPEN_STATUSES).exists()
    assert inventory_selectors.available_lots(product).get().available_quantity == D("5")  # type: ignore[attr-defined]


def test_close_partially_shipped_order_releases_rest(seller: User, commit: Commit) -> None:
    product = finished_product()
    location = storage_location()
    lot = finished_lot(product, "100", location=location)
    order = draft_order(seller, [(product, "100", "ADET")])
    services.confirm_order(seller, order)
    # Sevkiyat (Adım 3.2) yerine: rezervasyonun bir kısmı kullanılır ve çıkış yazılır.
    reservation = StockReservation.objects.get(lot=lot)
    inventory.consume_reservation(seller, reservation, D("40"))
    inventory.post_movement(seller, product, lot, location, D("-40"), "SHIPMENT", order)
    transition_status(order, Status.PARTIALLY_SHIPPED, seller, machine=sales_order_states)
    assert line_values(order) == [(D("100"), D("60"), D("40"), D("0"))]

    with commit():
        services.close_order(seller, order, "Kalan iptal")

    order.refresh_from_db()
    assert order.status == Status.CLOSED
    assert order.closed_at is not None
    assert line_values(order) == [(D("100"), D("0"), D("40"), D("60"))]
    assert inventory_selectors.available_lots(product).get().available_quantity == D("60")  # type: ignore[attr-defined]


def test_lot_leaving_released_releases_reservations(
    seller: User, commit: Commit, make_user: Callable[..., User]
) -> None:
    product = finished_product()
    lot = finished_lot(product, "100")
    order = draft_order(seller, [(product, "50", "ADET")])
    with commit():
        services.confirm_order(seller, order)

    with commit():
        inventory.block_lot(make_user("laboratuvar"), lot, "Müşteri şikâyeti")

    assert not StockReservation.objects.filter(status="ACTIVE").exists()
    task = Task.objects.get(rule_code="sales_shortage")
    assert "bloke" in task.description


def test_reserved_lots_expiring_notification(
    seller: User, commit: Commit, make_user: Callable[..., User]
) -> None:
    sevkiyat = make_user("sevkiyat", username="sevk2")
    product = finished_product(code="MM-9")
    lot = finished_lot(product, "100", expiry_date=today() + timedelta(days=10))
    finished_lot(product, "100", expiry_date=today() + timedelta(days=11))  # rezerve değil
    order = draft_order(seller, [(product, "100", "ADET")])
    services.confirm_order(seller, order)

    with commit():
        events.publish(ev.DAILY_CHECK, {})

    note = sevkiyat.notifications.get(rule_code="reserved_lots_expiring")
    assert note.level == "WARNING"
    assert lot.lot_no in note.body and order.number in note.body
    assert note.body.count("\n") == 0


# --- durum makinesi ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("DRAFT", "CONFIRMED"),
        ("DRAFT", "CANCELLED"),
        ("CONFIRMED", "PARTIALLY_SHIPPED"),
        ("CONFIRMED", "SHIPPED"),
        ("CONFIRMED", "CANCELLED"),
        ("PARTIALLY_SHIPPED", "SHIPPED"),
        ("PARTIALLY_SHIPPED", "CLOSED"),
        ("SHIPPED", "CLOSED"),
    ],
)
def test_allowed_transitions(source: str, target: str) -> None:
    assert sales_order_states.can_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("DRAFT", "SHIPPED"),
        ("CONFIRMED", "CLOSED"),
        ("CONFIRMED", "DRAFT"),
        ("PARTIALLY_SHIPPED", "CANCELLED"),
        ("SHIPPED", "CANCELLED"),
        ("CLOSED", "CONFIRMED"),
        ("CANCELLED", "CONFIRMED"),
    ],
)
def test_forbidden_transitions(source: str, target: str) -> None:
    assert not sales_order_states.can_transition(source, target)


def test_close_draft_order_is_rejected(seller: User) -> None:
    order = draft_order(seller, [(finished_product(), "1", "ADET")])
    with pytest.raises(BusinessRuleError) as exc:
        services.close_order(seller, order)
    assert exc.value.code == "invalid_transition"


def test_confirm_empty_order_is_rejected(seller: User) -> None:
    order = services.create_order(
        seller, {"customer": CustomerFactory.create(), "order_date": today()}
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.confirm_order(seller, order)
    assert exc.value.code == "document_empty"
