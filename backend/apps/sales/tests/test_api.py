"""Satış siparişi API'si: oluştur, düzenle, onayla, rezervasyon, iptal, kapanış ve yetki."""

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User
from apps.inventory.models import StockReservation
from apps.inventory.tests.factories import storage_location
from apps.masterdata.tests.factories import CustomerFactory, unit
from apps.sales.tests.factories import draft_order, finished_lot, finished_product

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

URL = "/api/v1/sales/orders/"
Client = Callable[..., APIClient]


def order_body(customer_id: int, product_id: int) -> dict[str, object]:
    return {
        "customer": customer_id,
        "order_date": str(timezone.localdate()),
        "customer_po_no": "PO-1",
        "lines": [
            {
                "product": product_id,
                "quantity": "2",
                "unit": unit("KOLI").pk,
                "unit_price": "100",
                "currency": "TRY",
            }
        ],
    }


def test_create_confirm_and_read_order(client_for: Client) -> None:
    client = client_for("sevkiyat")
    product = finished_product()
    finished_lot(product, "30", expiry_date=timezone.localdate() + timedelta(days=100))
    customer = CustomerFactory.create(min_remaining_shelf_life_days=30)

    created = client.post(URL, order_body(customer.pk, product.pk), format="json")
    assert created.status_code == 201, created.json()
    data = created.json()
    assert data["status"] == "DRAFT"
    assert data["is_editable"] is True
    assert data["lines"][0]["base_quantity"] == "24.0000"
    assert data["totals"] == [{"currency": "TRY", "amount": "200.00"}]
    assert data["min_remaining_shelf_life_days"] == 30

    order_id = data["id"]
    confirmed = client.post(f"{URL}{order_id}/confirm/", {}, format="json")
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "CONFIRMED"
    assert body["has_shortage"] is False
    assert body["lines"][0]["reserved_quantity"] == "24.0000"
    assert body["reservations"][0]["line_no"] == 1
    assert body["reservations"][0]["status"] == "ACTIVE"

    listed = client.get(URL, {"customer": customer.pk, "status": "CONFIRMED"})
    assert listed.status_code == 200
    assert [row["number"] for row in listed.json()["results"]] == [body["number"]]

    patched = client.patch(f"{URL}{order_id}/", {"notes": "x"}, format="json")
    assert patched.status_code == 400
    assert patched.json()["code"] == "document_locked"


def test_shortage_flag_and_manual_reservation(client_for: Client) -> None:
    client = client_for("yonetim")
    product = finished_product()
    location = storage_location()
    finished_lot(product, "10", location=location)
    customer = CustomerFactory.create()
    order = client.post(URL, order_body(customer.pk, product.pk), format="json").json()
    client.post(f"{URL}{order['id']}/confirm/", {}, format="json")

    shortage = client.get(URL, {"has_shortage": "true"}).json()["results"]
    assert [row["id"] for row in shortage] == [order["id"]]

    lot = finished_lot(product, "50", location=location)
    line_id = order["lines"][0]["id"]
    candidates = client.get(f"{URL}{order['id']}/candidates/", {"line": line_id}).json()
    assert [(c["lot"], c["available_quantity"], c["meets_shelf_life"]) for c in candidates] == [
        (lot.pk, "50.0000", True)
    ]
    reserved = client.post(
        f"{URL}{order['id']}/reserve/",
        {"line": line_id, "lot": lot.pk, "location": location.pk, "quantity": "14"},
        format="json",
    )
    assert reserved.status_code == 200, reserved.json()
    assert reserved.json()["has_shortage"] is False

    reservation = StockReservation.objects.get(lot=lot)
    released = client.post(
        f"{URL}{order['id']}/release/", {"reservation": reservation.pk}, format="json"
    )
    assert released.status_code == 200
    assert released.json()["lines"][0]["shortage_quantity"] == "14.0000"

    again = client.post(f"{URL}{order['id']}/reserve-shortages/", format="json")
    assert again.status_code == 200
    assert again.json()["lines"][0]["shortage_quantity"] == "0.0000"

    cancelled = client.post(f"{URL}{order['id']}/cancel/", {"reason": "vazgeçti"}, format="json")
    assert cancelled.json()["status"] == "CANCELLED"
    assert not StockReservation.objects.filter(status="ACTIVE").exists()


def test_reservation_of_other_order_is_rejected(client_for: Client, seller: User) -> None:
    client = client_for("sevkiyat")
    product = finished_product()
    finished_lot(product, "100")
    first = draft_order(seller, [(product, "10", "ADET")])
    second = draft_order(seller, [(product, "10", "ADET")])
    client.post(f"{URL}{first.pk}/confirm/", {}, format="json")
    client.post(f"{URL}{second.pk}/confirm/", {}, format="json")
    reservation = StockReservation.objects.filter(status="ACTIVE").first()
    assert reservation is not None
    other = second if reservation.document_number == first.number else first

    response = client.post(
        f"{URL}{other.pk}/release/", {"reservation": reservation.pk}, format="json"
    )

    assert response.status_code == 400
    assert "reservation" in response.json()["errors"]


@pytest.mark.parametrize("role", ["planlama", "depo"])
def test_read_only_roles(client_for: Client, seller: User, role: str) -> None:
    order = draft_order(seller, [(finished_product(), "1", "ADET")])
    client = client_for(role)

    assert client.get(URL).status_code == 200
    assert client.get(f"{URL}{order.pk}/").status_code == 200
    assert client.post(f"{URL}{order.pk}/confirm/", {}, format="json").status_code == 403
    customer = CustomerFactory.create()
    body = order_body(customer.pk, finished_product().pk)
    assert client.post(URL, body, format="json").status_code == 403


@pytest.mark.parametrize("role", ["uretim", "dolum", "laboratuvar", "satin_alma"])
def test_unrelated_roles_get_403(client_for: Client, role: str) -> None:
    assert client_for(role).get(URL).status_code == 403


def test_anonymous_gets_401(api_client: APIClient) -> None:
    assert api_client.get(URL).status_code in (401, 403)


def test_stock_balances_show_reserved_quantity(client_for: Client, seller: User) -> None:
    product = finished_product()
    finished_lot(product, "100")
    order = draft_order(seller, [(product, "30", "ADET")])
    client_for("sevkiyat").post(f"{URL}{order.pk}/confirm/", {}, format="json")

    rows = (
        client_for("depo")
        .get("/api/v1/inventory/balances/available/", {"material": product.pk})
        .json()
    )

    assert [(r["quantity"], r["reserved_quantity"], r["available_quantity"]) for r in rows] == [
        ("100.0000", "30.0000", "70.0000")
    ]
    assert Decimal(rows[0]["available_quantity"]) == Decimal(70)
