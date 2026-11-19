"""Müşteri sipariş takibi: vade, gecikme, kalan miktar, biten siparişler, müşteri özeti ve yetki
(docs/plan/musteri-siparis-takibi.md §3.2)."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User
from apps.core.roles import DEPO
from apps.masterdata.models import Customer, Location
from apps.masterdata.tests.factories import CustomerFactory
from apps.sales import selectors, services
from apps.sales.models import SalesOrder
from apps.sales.tests.factories import (
    draft_order,
    finished_lot,
    finished_product,
    shipping_location,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

ORDERS = "/api/v1/sales/tracking/orders/"
CUSTOMERS = "/api/v1/sales/tracking/customers/"
Client = Callable[..., APIClient]


def today() -> date:
    return timezone.localdate()


@pytest.fixture
def picker(make_user: Callable[..., User]) -> User:
    return make_user(DEPO, username="depo")


def _order(seller: User, customer: Customer, **data: Any) -> SalesOrder:
    """Onaylı sipariş: 24 ADET (2 KOLI), satır fiyatı 10 TL/KOLI."""
    product = finished_product()
    finished_lot(product, "100")
    order = draft_order(seller, [(product, "2", "KOLI")], customer=customer, **data)
    line = order.lines.get()
    line.unit_price = Decimal("10")
    line.currency = "TRY"
    line.save(update_fields=["unit_price", "currency"])
    return services.confirm_order(seller, order)


def _make_late(order: SalesOrder, days: int) -> None:
    """Vadeyi geçmişe çeker (onaydan sonra termin geçmişe girilemez; zaman geçmiş gibi)."""
    SalesOrder.objects.filter(pk=order.pk).update(promised_date=today() - timedelta(days=days))


def _ship(seller: User, picker: User, order: SalesOrder, quantity: str | None = None) -> None:
    """Siparişin ilk satırından `quantity` (temel birim; boşsa tamamı) sevk eder."""
    if not Location.objects.filter(location_type=Location.Type.SHIPPING).exists():
        shipping_location(code="SEVK")
    line = order.lines.get()
    items = None if quantity is None else [{"order_line": line, "quantity": Decimal(quantity)}]
    shipment = services.plan_shipment(
        seller,
        order,
        {"planned_date": today(), "vehicle_plate": "34 A 1", "driver_name": "Ali"},
        items,
    )
    reservation = line.reservations.filter(status="ACTIVE").first()
    assert reservation is not None
    services.pick_lot(picker, shipment, reservation.lot)
    services.mark_loaded(picker, shipment)
    services.dispatch_shipment(seller, shipment)


# --- selectors ----------------------------------------------------------------------------------


def test_due_date_falls_back_to_requested_date(seller: User) -> None:
    customer = CustomerFactory.create()
    order = _order(seller, customer, requested_delivery_date=today() + timedelta(days=2))
    SalesOrder.objects.filter(pk=order.pk).update(promised_date=None)

    tracked = selectors.tracked_orders().get(pk=order.pk)

    assert tracked.due_date == today() + timedelta(days=2)  # type: ignore[attr-defined]
    assert selectors.days_late(tracked) == 0


def test_late_order_days_and_remaining_after_partial_shipment(seller: User, picker: User) -> None:
    customer = CustomerFactory.create()
    order = _order(seller, customer)
    _ship(seller, picker, order, "12")
    _make_late(order, 3)

    tracked = selectors.tracked_orders().get(pk=order.pk)
    line = tracked.lines.all()[0]

    assert tracked.status == SalesOrder.Status.PARTIALLY_SHIPPED
    assert selectors.days_late(tracked) == 3
    assert selectors.line_remaining(line) == Decimal("12")
    assert selectors.in_order_unit(line, selectors.line_remaining(line)) == Decimal("1")
    assert tracked.last_dispatched_at is not None  # type: ignore[attr-defined]
    assert selectors.tracked_orders().filter(selectors.late_filter()).count() == 1


def test_finished_orders_only_on_request_and_within_window(seller: User, picker: User) -> None:
    customer = CustomerFactory.create()
    shipped = _order(seller, customer)
    _ship(seller, picker, shipped)
    closed = _order(seller, customer)
    _ship(seller, picker, closed, "12")
    services.close_order(seller, closed)
    open_order = _order(seller, customer)
    cancelled = _order(seller, customer)
    services.cancel_order(seller, cancelled, "müşteri vazgeçti")
    never_confirmed = draft_order(seller, [(finished_product(), "1", "ADET")], customer=customer)
    services.cancel_order(seller, never_confirmed, "yanlış")
    SalesOrder.objects.filter(pk=closed.pk).update(
        closed_at=timezone.now() - timedelta(days=selectors.FINISHED_WINDOW_DAYS + 1)
    )

    open_ids = set(selectors.tracked_orders().values_list("pk", flat=True))
    all_ids = set(selectors.tracked_orders(include_finished=True).values_list("pk", flat=True))

    assert open_ids == {open_order.pk}
    assert all_ids == {open_order.pk, shipped.pk, cancelled.pk}


def test_shipped_order_lateness_uses_last_dispatch(seller: User, picker: User) -> None:
    customer = CustomerFactory.create()
    order = _order(seller, customer)
    _make_late(order, 2)
    _ship(seller, picker, order)

    tracked = selectors.tracked_orders(include_finished=True).get(pk=order.pk)

    assert tracked.status == SalesOrder.Status.SHIPPED
    assert selectors.days_late(tracked) == 2


def test_customer_summary_counts(seller: User) -> None:
    late_customer = CustomerFactory.create(code="M-GEC")
    on_time = CustomerFactory.create(code="M-ZAMAN")
    CustomerFactory.create(code="M-BOS")
    first = _order(seller, late_customer)
    _make_late(first, 5)
    second = _order(seller, late_customer)
    _make_late(second, 1)
    _order(seller, on_time, promised_date=today() + timedelta(days=3))
    _order(seller, on_time, promised_date=today() + timedelta(days=30))

    rows = {c.code: c for c in selectors.customer_tracking_summary()}

    assert set(rows) == {"M-GEC", "M-ZAMAN"}
    assert list(rows) == ["M-GEC", "M-ZAMAN"]
    late = rows["M-GEC"]
    assert (late.open_orders, late.late_orders) == (2, 2)  # type: ignore[attr-defined]
    assert late.oldest_due_date == today() - timedelta(days=5)  # type: ignore[attr-defined]
    fine = rows["M-ZAMAN"]
    assert (fine.open_orders, fine.late_orders, fine.due_soon) == (2, 0, 1)  # type: ignore[attr-defined]


# --- API ----------------------------------------------------------------------------------------


def test_api_tracked_orders(client_for: Client, seller: User, picker: User) -> None:
    customer = CustomerFactory.create(code="M-1")
    late = _order(seller, customer)
    _ship(seller, picker, late, "12")
    _make_late(late, 4)
    _order(seller, CustomerFactory.create(code="M-2"))
    client = client_for("planlama")

    data = client.get(ORDERS).json()
    assert data["count"] == 2
    first = data["results"][0]
    assert first["number"] == late.number
    assert first["days_late"] == 4
    assert first["is_late"] is True
    assert first["totals"] == [{"currency": "TRY", "amount": "20.00"}]
    [line] = first["lines"]
    assert line["shipped_quantity"] == "12.0000"
    assert line["remaining_quantity"] == "12.0000"
    assert (line["shipped_in_unit"], line["remaining_in_unit"]) == ("1.0000", "1.0000")
    assert [row["status"] for row in first["shipments"]] == ["DISPATCHED"]

    only_late = client.get(ORDERS, {"late": "true"}).json()
    assert [row["number"] for row in only_late["results"]] == [late.number]
    by_customer = client.get(ORDERS, {"customer": customer.pk}).json()
    assert by_customer["count"] == 1
    assert client.get(ORDERS, {"search": "M-2"}).json()["count"] == 1
    due = client.get(ORDERS, {"due_before": str(today())}).json()
    assert [row["number"] for row in due["results"]] == [late.number]
    assert client.get(ORDERS, {"include_finished": "true"}).json()["count"] == 2


def test_api_customer_summary(client_for: Client, seller: User) -> None:
    late_customer = CustomerFactory.create(code="M-GEC", name="Geciken")
    order = _order(seller, late_customer)
    _make_late(order, 6)
    _order(seller, CustomerFactory.create(code="M-ZAMAN"))
    client = client_for("sevkiyat")

    data = client.get(CUSTOMERS).json()
    assert [row["code"] for row in data["results"]] == ["M-GEC", "M-ZAMAN"]
    assert data["results"][0]["max_days_late"] == 6
    assert data["results"][0]["late_orders"] == 1
    assert client.get(CUSTOMERS, {"late": "true"}).json()["count"] == 1
    assert client.get(CUSTOMERS, {"search": "Geciken"}).json()["count"] == 1


@pytest.mark.parametrize("role", ["uretim", "dolum", "laboratuvar", "satin_alma"])
def test_api_tracking_forbidden_for_unrelated_roles(client_for: Client, role: str) -> None:
    client = client_for(role)
    assert client.get(ORDERS).status_code == 403
    assert client.get(CUSTOMERS).status_code == 403


def test_api_tracking_is_read_only(client_for: Client) -> None:
    client = client_for("sevkiyat")
    assert client.post(ORDERS, {}, format="json").status_code == 405
    assert client.post(CUSTOMERS, {}, format="json").status_code == 405
