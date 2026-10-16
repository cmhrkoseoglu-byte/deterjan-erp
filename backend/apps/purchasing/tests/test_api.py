from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core.models import User
from apps.inventory import services as inventory
from apps.masterdata.tests.factories import SupplierFactory, unit
from apps.purchasing import services
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import approved_order, line, raw_material, receipt_locations

pytestmark = pytest.mark.django_db
BASE = "/api/v1/purchasing"


def order_body(material_id: int, supplier_id: int, **extra: object) -> dict[str, object]:
    return {
        "supplier": supplier_id,
        "order_date": "2026-10-16",
        "currency": "TRY",
        "lines": [
            {
                "material": material_id,
                "quantity": "100",
                "unit": unit("KG").pk,
                "unit_price": "12.5",
                "expected_date": "2026-10-20",
            }
        ],
        **extra,
    }


def test_order_flow_over_api(client_for: Callable[..., APIClient], invariants: None) -> None:
    buyer = client_for("satin_alma")
    manager = client_for("yonetim")
    material = raw_material()
    supplier = SupplierFactory.create(email="a@b.com")
    response = buyer.post(f"{BASE}/orders/", order_body(material.pk, supplier.pk), format="json")
    assert response.status_code == 201, response.json()
    order = response.json()
    assert order["number"].startswith("SA-")
    assert order["total"] == "1250.00" and order["total_try"] == "1250.00"
    assert order["can_approve"] is False  # limit girilmedi
    order_id = order["id"]
    response = buyer.post(f"{BASE}/orders/{order_id}/approve/")
    assert response.status_code == 400
    assert response.json()["code"] == "approval_limit_exceeded"
    assert buyer.post(f"{BASE}/orders/{order_id}/submit/").json()["status"] == "PENDING_APPROVAL"
    response = manager.get(f"{BASE}/orders/{order_id}/")
    assert response.json()["can_approve"] is True
    assert manager.post(f"{BASE}/orders/{order_id}/approve/").json()["status"] == "APPROVED"
    response = buyer.post(f"{BASE}/orders/{order_id}/send/", {"email": "a@b.com"}, format="json")
    assert response.json()["sent_to"] == "a@b.com"
    pdf = buyer.get(f"{BASE}/orders/{order_id}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"

    depo = client_for("depo")
    locations = receipt_locations()
    order_line = response.json()["lines"][0]["id"]
    response = depo.post(
        f"{BASE}/orders/{order_id}/receive/",
        {
            "receipt_date": "2026-10-18",
            "quarantine_location": locations["quarantine_location"].pk,
            "storage_location": locations["storage_location"].pk,
            "lines": [{"order_line": order_line, "quantity": "100", "supplier_lot_no": "X"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    receipt_id = response.json()["id"]
    links = depo.get(f"{BASE}/receipt-links/", {"receipt": receipt_id}).json()
    assert links[0]["order_number"] == order["number"]
    assert depo.post(f"/api/v1/inventory/goods-receipts/{receipt_id}/post/").status_code == 200
    detail = buyer.get(f"{BASE}/orders/{order_id}/").json()
    assert detail["status"] == "RECEIVED"
    assert detail["lines"][0]["received_quantity"] == "100.0000"
    assert detail["lines"][0]["pending_quantity"] == "0"
    assert detail["receipts"][0]["status"] == "POSTED"


def test_depo_sees_orders_without_prices(
    client_for: Callable[..., APIClient], manager: User
) -> None:
    order = approved_order(manager, [line(raw_material(), "10", "99")])
    depo = client_for("depo")
    listed = depo.get(f"{BASE}/orders/").json()["results"][0]
    detail = depo.get(f"{BASE}/orders/{order.pk}/").json()
    expected = depo.get(f"{BASE}/expected-deliveries/").json()
    for data in (listed, detail, detail["lines"][0], expected[0]):
        assert "unit_price" not in data and "total" not in data and "total_try" not in data
        assert "line_total" not in data and "exchange_rate" not in data
    assert expected[0]["pending_quantity"] == "10.0000"
    assert depo.get(f"{BASE}/orders/{order.pk}/pdf/").status_code == 403
    buyer = client_for("satin_alma")
    assert buyer.get(f"{BASE}/orders/{order.pk}/").json()["lines"][0]["unit_price"] == "99.0000"


def test_permissions(client_for: Callable[..., APIClient], manager: User) -> None:
    lab = client_for("laboratuvar")
    depo = client_for("depo")
    planner = client_for("planlama")
    order = approved_order(manager, [line(raw_material())])
    assert lab.get(f"{BASE}/orders/").status_code == 403
    assert lab.get(f"{BASE}/requests/").status_code == 403
    assert planner.get(f"{BASE}/orders/").status_code == 403
    assert planner.get(f"{BASE}/suggestions/").status_code == 200
    assert depo.get(f"{BASE}/suggestions/").status_code == 403
    assert depo.post(f"{BASE}/orders/", {}, format="json").status_code == 403
    assert depo.post(f"{BASE}/orders/{order.pk}/cancel/", {"reason": "x"}).status_code == 403
    assert depo.get(f"{BASE}/supplier-performance/").status_code == 403
    assert depo.get(f"{BASE}/settings/").status_code == 403
    assert (
        client_for("satin_alma")
        .patch(f"{BASE}/settings/", {"approval_limit_try": "5"}, format="json")
        .status_code
        == 403
    )
    response = client_for("yonetim").patch(
        f"{BASE}/settings/", {"approval_limit_try": "50000"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["approval_limit_try"] == "50000.00"


def test_requests_api(client_for: Callable[..., APIClient]) -> None:
    depo = client_for("depo")
    material = raw_material()
    response = depo.post(
        f"{BASE}/requests/",
        {"material": material.pk, "quantity": "25", "need_date": "2026-10-30", "reason": "Eksik"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    data = response.json()
    assert data["number"].startswith("ST-") and data["source"] == "MANUAL"
    assert data["unit_code"] == "KG"
    response = depo.post(f"{BASE}/requests/{data['id']}/cancel/", {"reason": ""}, format="json")
    assert response.status_code == 400
    response = depo.post(f"{BASE}/requests/{data['id']}/cancel/", {"reason": "Bulundu"})
    assert response.json()["status"] == "CANCELLED"
    assert depo.get(f"{BASE}/requests/", {"status": "OPEN"}).json()["count"] == 0


def test_supplier_performance_and_suggestions_api(
    client_for: Callable[..., APIClient], manager: User, depo: User
) -> None:
    material = raw_material(min_stock=Decimal("40"))
    order = approved_order(manager, [line(material, "10")])
    receipt = services.create_receipt_from_order(
        depo,
        order,
        {"receipt_date": date(2026, 10, 19), **receipt_locations()},
        [{"order_line": order.lines.get().pk, "quantity": Decimal("10")}],
    )
    inventory.post_goods_receipt(depo, receipt)
    buyer = client_for("satin_alma")
    rows = buyer.get(
        f"{BASE}/supplier-performance/", {"date_from": "2026-10-01", "date_to": "2026-10-31"}
    ).json()
    assert rows[0]["on_time_rate"] == "100.0"
    assert rows[0]["received_lots"] == 1
    bad = buyer.get(
        f"{BASE}/supplier-performance/", {"date_from": "2026-11-01", "date_to": "2026-10-01"}
    )
    assert bad.status_code == 400
    suggestions = buyer.get(f"{BASE}/suggestions/").json()
    assert suggestions[0]["material_code"] == material.code
    assert suggestions[0]["suggested"] == "30.0000"  # min 40 − serbest/karantina 10


def test_draft_order_update_over_api(client_for: Callable[..., APIClient]) -> None:
    buyer = client_for("satin_alma")
    material = raw_material()
    supplier = SupplierFactory.create()
    order = buyer.post(f"{BASE}/orders/", order_body(material.pk, supplier.pk), format="json")
    order_id = order.json()["id"]
    line_id = order.json()["lines"][0]["id"]
    response = buyer.patch(
        f"{BASE}/orders/{order_id}/",
        {
            "currency": "USD",
            "exchange_rate": "34.5",
            "lines": [
                {
                    "id": line_id,
                    "material": material.pk,
                    "quantity": "200",
                    "unit": unit("KG").pk,
                    "unit_price": "1",
                    "expected_date": "2026-10-21",
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["total"] == "200.00" and data["total_try"] == "6900.00"
    assert PurchaseOrder.objects.get(pk=order_id).lines.get().quantity == Decimal("200")
