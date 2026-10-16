"""Sevkiyat API'si: planla, okut (lot no / etiket), farklı lot gerekçesi, geri al, yükle, sevk et,
irsaliye (JSON ve PDF), toplama önerisi, müşteriye sevk edilen lotlar ve rol yetkileri."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User
from apps.masterdata.models import Location
from apps.masterdata.tests.factories import CustomerFactory
from apps.sales import services
from apps.sales.models import SalesOrder, Shipment
from apps.sales.tests.factories import (
    confirmed_order,
    finished_lot,
    finished_product,
    shipping_location,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

URL = "/api/v1/sales/shipments/"
Client = Callable[..., APIClient]


@pytest.fixture
def dock() -> Location:
    return shipping_location(code="SEVK")


def plan_body(order: SalesOrder) -> dict[str, object]:
    return {
        "sales_order": order.pk,
        "planned_date": str(timezone.localdate()),
        "vehicle_plate": "34 ABC 123",
        "driver_name": "Ali Veli",
        "driver_id_no": "12345678901",
        "carrier": "Kendi aracımız",
    }


def test_full_shipment_flow(client_for: Client, seller: User, dock: Location) -> None:
    sevkiyat = client_for("sevkiyat")
    depo = client_for("depo")
    product = finished_product(name="Sıvı deterjan 1 L")
    lot = finished_lot(product, "100", expiry_date=timezone.localdate() + timedelta(days=300))
    order = confirmed_order(seller, [(product, "5", "KOLI")])

    created = sevkiyat.post(URL, plan_body(order), format="json")
    assert created.status_code == 201, created.json()
    data = created.json()
    shipment_id = data["id"]
    assert data["status"] == "PLANNED"
    assert data["driver_id_no_masked"] == "*******8901"
    assert "driver_id_no" not in data
    assert data["lines"][0]["quantity"] == "60.0000"

    suggestions = depo.get(f"{URL}{shipment_id}/suggestions/").json()
    assert suggestions[0]["remaining_quantity"] == "60.0000"
    assert suggestions[0]["suggestions"][0]["lot_no"] == lot.lot_no
    assert suggestions[0]["suggestions"][0]["reserved"] is True

    picked = depo.post(f"{URL}{shipment_id}/pick/", {"lot_no": f"LOT:{lot.lot_no}"}, format="json")
    assert picked.status_code == 200, picked.json()
    body = picked.json()
    assert body["status"] == "PICKING"
    assert body["lines"][0]["picked_quantity"] == "60.0000"
    assert body["picks"][0]["to_location_code"] == "SEVK"

    assert sevkiyat.get(f"{URL}{shipment_id}/waybill/").status_code == 400
    assert depo.post(f"{URL}{shipment_id}/load/", {}, format="json").status_code == 200

    waybill = sevkiyat.get(f"{URL}{shipment_id}/waybill/")
    assert waybill.status_code == 200
    payload = waybill.json()
    assert payload["driver_id_no"] == "*******8901"
    assert payload["lines"][0]["lot_no"] == lot.lot_no
    assert payload["lines"][0]["cases"] == 5
    assert payload["total_cases"] == 5

    dispatched = sevkiyat.post(f"{URL}{shipment_id}/dispatch/", {}, format="json")
    assert dispatched.status_code == 200, dispatched.json()
    assert dispatched.json()["status"] == "DISPATCHED"
    assert dispatched.json()["picks"][0]["is_shipped"] is True

    pdf = sevkiyat.get(f"{URL}{shipment_id}/waybill.pdf")
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    order_data = sevkiyat.get(f"/api/v1/sales/orders/{order.pk}/").json()
    assert order_data["status"] == "SHIPPED"
    assert order_data["shipments"][0]["number"] == data["number"]
    assert order_data["lines"][0]["shipped_quantity"] == "60.0000"
    assert order_data["lines"][0]["plannable_quantity"] == "0.0000"

    lots = sevkiyat.get("/api/v1/sales/shipped-lots/", {"customer": str(order.customer_id)}).json()
    assert [(r["lot_no"], r["quantity"], r["shipment_number"]) for r in lots["results"]] == [
        (lot.lot_no, "60.0000", data["number"])
    ]
    listed = sevkiyat.get(URL, {"status": "DISPATCHED", "customer": str(order.customer_id)}).json()
    assert [row["id"] for row in listed["results"]] == [shipment_id]


def test_other_lot_reason_and_undo(client_for: Client, seller: User, dock: Location) -> None:
    sevkiyat = client_for("sevkiyat")
    depo = client_for("depo")
    product = finished_product()
    today = timezone.localdate()
    finished_lot(product, "50", expiry_date=today + timedelta(days=100))
    late = finished_lot(product, "50", expiry_date=today + timedelta(days=200))
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment_id = sevkiyat.post(URL, plan_body(order), format="json").json()["id"]

    refused = depo.post(f"{URL}{shipment_id}/pick/", {"lot_no": late.lot_no}, format="json")
    assert refused.status_code == 400
    assert refused.json()["code"] == "lot_not_reserved"
    picked = depo.post(
        f"{URL}{shipment_id}/pick/",
        {"lot_no": late.lot_no, "reason": "Önde duran palet"},
        format="json",
    ).json()
    assert picked["picks"][0]["deviation_reason"] == "Önde duran palet"

    pick_id = picked["picks"][0]["id"]
    undone = depo.post(f"{URL}{shipment_id}/undo-pick/", {"pick": pick_id}, format="json")
    assert undone.status_code == 200
    assert undone.json()["picks"][0]["returned_at"] is not None
    assert undone.json()["lines"][0]["picked_quantity"] == "0.0000"


def test_shelf_life_block_and_unknown_lot(client_for: Client, seller: User, dock: Location) -> None:
    depo = client_for("depo")
    product = finished_product()
    customer = CustomerFactory.create(min_remaining_shelf_life_days=180)
    short = finished_lot(product, "10", expiry_date=timezone.localdate() + timedelta(days=30))
    finished_lot(product, "10", expiry_date=timezone.localdate() + timedelta(days=365))
    order = confirmed_order(seller, [(product, "5", "ADET")], customer=customer)
    shipment = services.plan_shipment(seller, order, {"planned_date": timezone.localdate()})

    blocked = depo.post(
        f"{URL}{shipment.pk}/pick/", {"lot_no": short.lot_no, "reason": "x"}, format="json"
    )
    assert blocked.status_code == 400
    assert blocked.json()["code"] == "shelf_life_too_short"
    missing = depo.post(f"{URL}{shipment.pk}/pick/", {"lot_no": "YOK-1"}, format="json")
    assert missing.json()["code"] == "lot_not_found"
    empty = depo.post(f"{URL}{shipment.pk}/pick/", {"lot_no": ""}, format="json")
    assert empty.status_code == 400


def test_update_and_cancel(client_for: Client, seller: User, dock: Location) -> None:
    sevkiyat = client_for("sevkiyat")
    product = finished_product()
    finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "5", "ADET")])
    shipment_id = sevkiyat.post(URL, plan_body(order), format="json").json()["id"]

    updated = sevkiyat.patch(
        f"{URL}{shipment_id}/", {"vehicle_plate": "06 xy 99", "notes": "Rampa 2"}, format="json"
    )
    assert updated.status_code == 200, updated.json()
    assert updated.json()["vehicle_plate"] == "06 XY 99"
    assert updated.json()["driver_id_no_masked"] == "*******8901"

    cancelled = sevkiyat.post(f"{URL}{shipment_id}/cancel/", {"reason": "Araç yok"}, format="json")
    assert cancelled.json()["status"] == "CANCELLED"
    assert Shipment.objects.get(pk=shipment_id).cancel_reason == "Araç yok"


@pytest.mark.parametrize(
    ("role", "method", "path", "expected"),
    [
        ("depo", "post", "", 403),
        ("depo", "post", "dispatch/", 403),
        ("depo", "post", "cancel/", 403),
        ("sevkiyat", "post", "pick/", 403),
        ("sevkiyat", "post", "load/", 403),
        ("planlama", "post", "pick/", 403),
        ("planlama", "get", "", 200),
        ("dolum", "get", "", 403),
        ("laboratuvar", "get", "waybill/", 403),
    ],
)
def test_role_permissions(
    client_for: Client,
    seller: User,
    dock: Location,
    role: str,
    method: str,
    path: str,
    expected: int,
) -> None:
    product = finished_product()
    finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "5", "ADET")])
    shipment = services.plan_shipment(seller, order, {"planned_date": timezone.localdate()})
    client = client_for(role)
    url = f"{URL}{shipment.pk}/{path}" if path else URL
    if method == "get":
        response = client.get(url)
    else:
        response = client.post(url, {"sales_order": order.pk, "lot_no": "X"}, format="json")
    assert response.status_code == expected


def test_shipped_lots_require_customer_and_role(client_for: Client) -> None:
    assert client_for("sevkiyat").get("/api/v1/sales/shipped-lots/").status_code == 400
    assert client_for("depo").get("/api/v1/sales/shipped-lots/?customer=1").status_code == 403


def test_anonymous_gets_401(api_client: APIClient) -> None:
    assert api_client.get(URL).status_code in (401, 403)


def test_vehicle_fields_are_length_checked(
    client_for: Client, seller: User, dock: Location
) -> None:
    sevkiyat = client_for("sevkiyat")
    product = finished_product()
    finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "5", "ADET")])

    response = sevkiyat.post(
        URL,
        {**plan_body(order), "vehicle_plate": "3" * 21, "driver_name": "A" * 101},
        format="json",
    )
    assert response.status_code == 400
    assert set(response.json()["errors"]) >= {"vehicle_plate", "driver_name"}
    response = sevkiyat.post(URL, {**plan_body(order), "carrier": "T" * 101}, format="json")
    assert response.status_code == 400
    assert "carrier" in response.json()["errors"]


def test_lot_no_shared_by_two_products_must_be_picked_from_list(
    client_for: Client, seller: User, dock: Location
) -> None:
    from apps.inventory.models import Lot

    depo = client_for("depo")
    first, second = finished_product(), finished_product()
    lot_a = finished_lot(first, "10")
    lot_b = finished_lot(second, "10")
    Lot.objects.filter(pk__in=[lot_a.pk, lot_b.pk]).update(lot_no="ORTAK-1")
    order = confirmed_order(seller, [(first, "5", "ADET"), (second, "5", "ADET")])
    shipment = services.plan_shipment(seller, order, {"planned_date": timezone.localdate()})

    scanned = depo.post(f"{URL}{shipment.pk}/pick/", {"lot_no": "ORTAK-1"}, format="json")
    assert scanned.status_code == 400
    assert scanned.json()["code"] == "ambiguous_lot"
    picked = depo.post(f"{URL}{shipment.pk}/pick/", {"lot": lot_b.pk}, format="json")
    assert picked.status_code == 200, picked.json()


def test_dock_stock_is_not_a_reservation_candidate(
    client_for: Client, seller: User, dock: Location
) -> None:
    sevkiyat = client_for("sevkiyat")
    product = finished_product()
    finished_lot(product, "50", location=dock)
    order = confirmed_order(seller, [(product, "10", "ADET")])
    line = order.lines.get()

    response = sevkiyat.get(f"/api/v1/sales/orders/{order.pk}/candidates/?line={line.pk}")
    assert response.status_code == 200
    assert response.json() == []
    stock = finished_lot(product, "20")
    response = sevkiyat.get(f"/api/v1/sales/orders/{order.pk}/candidates/?line={line.pk}")
    assert [row["lot"] for row in response.json()] == [stock.pk]


def test_order_shows_reservation_location_type(
    client_for: Client, make_user: Callable[..., User], seller: User, dock: Location
) -> None:
    product = finished_product()
    lot = finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = services.plan_shipment(seller, order, {"planned_date": timezone.localdate()})
    services.pick_lot(make_user("depo"), shipment, lot)

    data = client_for("sevkiyat").get(f"/api/v1/sales/orders/{order.pk}/").json()
    active = [r for r in data["reservations"] if r["status"] == "ACTIVE"]
    assert [(r["location_code"], r["location_type"]) for r in active] == [("SEVK", "SHIPPING")]
