"""Sipariş talebi: gönderme, geri çekme, siparişe çevirme, reddetme; durum makinesi, iş akışı
görevi, firma süzgeci ve yetki (docs/plan/musteri-siparis-takibi.md §4.4)."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.roles import PLANLAMA, SEVKIYAT
from apps.masterdata.models import Customer, Material
from apps.masterdata.tests.factories import CustomerFactory, MaterialFactory, unit
from apps.portal import services
from apps.portal.models import OrderRequest, PortalAccount
from apps.portal.tests.helpers import session_client
from apps.sales.models import SalesOrder
from apps.sales.tests.factories import finished_product
from apps.workflow.models import Task

pytestmark = pytest.mark.django_db

Commit = Callable[[], AbstractContextManager[Any]]
BASE = "/api/v1/portal/customer/requests/"
STAFF = "/api/v1/portal/requests/"


@pytest.fixture
def commit(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> Commit:
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def seller(make_user: Callable[..., User]) -> User:
    return make_user(SEVKIYAT, username="sevkiyat")


@pytest.fixture
def product() -> Material:
    return finished_product(code="MM-TALEP")


def _line(product: Material, quantity: str = "3", code: str = "KOLI") -> dict[str, Any]:
    return {"product": product, "quantity": Decimal(quantity), "unit": unit(code)}


def _submit(account: PortalAccount, product: Material, **data: Any) -> OrderRequest:
    return services.submit_request(
        account.user,
        {"customer_po_no": "PO-77", "note": "Rampaya teslim", **data},
        [_line(product)],
    )


# --- gönderme -----------------------------------------------------------------------------------


def test_submit_opens_request_and_task(
    customer_account: PortalAccount,
    customer: Customer,
    product: Material,
    seller: User,
    commit: Commit,
) -> None:
    with commit():
        request = _submit(customer_account, product, requested_delivery_date=timezone.localdate())

    assert request.number.startswith("MT-")
    assert request.status == OrderRequest.Status.SUBMITTED
    assert request.customer == customer and request.delivery_address == customer.address
    [line] = request.lines.all()
    assert (line.product, line.quantity, line.unit.code) == (product, Decimal("3"), "KOLI")
    task = Task.objects.get(rule_code="portal_order_request")
    assert task.title == f"Portal talebi incele: {request.number}"
    assert task.status == Task.Status.OPEN


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"lines": []}, "request_empty"),
        ({"quantity": "0"}, "invalid_quantity"),
        ({"unit": "KG"}, "invalid_unit"),
        ({"raw": True}, "product_not_orderable"),
        ({"inactive": True}, "product_not_orderable"),
        ({"past": True}, "requested_date_past"),
    ],
)
def test_submit_rules(
    customer_account: PortalAccount, product: Material, change: dict[str, Any], code: str
) -> None:
    item = _line(product, change.get("quantity", "3"), change.get("unit", "KOLI"))
    if change.get("raw"):
        item["product"] = MaterialFactory.create(material_type=Material.Type.RAW)
    if change.get("inactive"):
        Material.objects.filter(pk=product.pk).update(is_active=False)
        product.refresh_from_db()
    data: dict[str, Any] = {}
    if change.get("past"):
        data["requested_delivery_date"] = timezone.localdate() - timedelta(days=1)
    lines = change.get("lines", [item])
    with pytest.raises(BusinessRuleError) as error:
        services.submit_request(customer_account.user, data, lines)
    assert error.value.code == code
    assert not OrderRequest.objects.exists()


def test_only_customer_portal_submits(
    seller: User, supplier_account: PortalAccount, product: Material
) -> None:
    for actor in (seller, supplier_account.user):
        with pytest.raises(PermissionDenied):
            services.submit_request(actor, {}, [_line(product)])


# --- geri çekme, çevirme, reddetme ------------------------------------------------------------


def test_withdraw_own_request_closes_task(
    customer_account: PortalAccount, product: Material, seller: User, commit: Commit
) -> None:
    with commit():
        request = _submit(customer_account, product)
    other_account, _ = services.create_account(
        User.objects.get(username="sistem"),
        username="baska.musteri",
        full_name="Başka",
        customer=CustomerFactory.create(),
    )
    with pytest.raises(PermissionDenied):
        services.withdraw_request(other_account.user, request)

    with commit():
        services.withdraw_request(customer_account.user, request)

    request.refresh_from_db()
    assert request.status == OrderRequest.Status.WITHDRAWN
    assert Task.objects.get(rule_code="portal_order_request").status == Task.Status.DONE
    with pytest.raises(BusinessRuleError) as again:
        services.withdraw_request(customer_account.user, request)
    assert again.value.code == "request_not_open"


def test_convert_creates_draft_order(
    customer_account: PortalAccount,
    customer: Customer,
    product: Material,
    seller: User,
    commit: Commit,
) -> None:
    wanted = timezone.localdate() + timedelta(days=5)
    with commit():
        request = _submit(customer_account, product, requested_delivery_date=wanted)
    with commit():
        order = services.convert_request(seller, request)

    request.refresh_from_db()
    assert request.status == OrderRequest.Status.CONVERTED
    assert request.sales_order == order and request.decided_by == seller
    assert order.status == SalesOrder.Status.DRAFT and order.customer == customer
    assert order.requested_delivery_date == wanted and order.customer_po_no == "PO-77"
    assert order.notes == f"Portal talebi {request.number}: Rampaya teslim"
    [line] = order.lines.all()
    assert (line.product, line.quantity, line.unit.code, line.unit_price) == (
        product,
        Decimal("3"),
        "KOLI",
        None,
    )
    assert Task.objects.get(rule_code="portal_order_request").status == Task.Status.DONE
    with pytest.raises(BusinessRuleError) as again:
        services.convert_request(seller, request)
    assert again.value.code == "request_not_open"


def test_reject_needs_reason_and_access(
    customer_account: PortalAccount,
    product: Material,
    seller: User,
    make_user: Callable[..., User],
    commit: Commit,
) -> None:
    with commit():
        request = _submit(customer_account, product)
    planner = make_user(PLANLAMA, username="planlama")
    with pytest.raises(PermissionDenied):
        services.reject_request(planner, request, "stok yok")
    with pytest.raises(PermissionDenied):
        services.convert_request(planner, request)
    with pytest.raises(BusinessRuleError) as empty:
        services.reject_request(seller, request, "  ")
    assert empty.value.code == "reason_required"

    with commit():
        services.reject_request(seller, request, "Bu ürünü artık üretmiyoruz")

    request.refresh_from_db()
    assert request.status == OrderRequest.Status.REJECTED
    assert request.reject_reason == "Bu ürünü artık üretmiyoruz"
    assert Task.objects.get(rule_code="portal_order_request").status == Task.Status.DONE
    with pytest.raises(BusinessRuleError):
        services.convert_request(seller, request)


# --- API --------------------------------------------------------------------------------------


def test_customer_api_flow(
    customer_account: PortalAccount, product: Material, seller: User, commit: Commit
) -> None:
    client = session_client(customer_account.user)
    products = client.get("/api/v1/portal/customer/products/").json()["results"]
    [row] = [item for item in products if item["code"] == "MM-TALEP"]
    assert [u["code"] for u in row["units"]] == ["ADET", "KOLI", "PALET"]
    assert "price" not in row and "stock" not in row

    koli = next(u["id"] for u in row["units"] if u["code"] == "KOLI")
    with commit():
        created = client.post(
            BASE,
            {
                "customer_po_no": "PO-9",
                "lines": [{"product": product.pk, "quantity": "2", "unit": koli}],
            },
            format="json",
        )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "SUBMITTED" and body["number"].startswith("MT-")
    assert body["lines"][0]["unit_code"] == "KOLI"

    with commit():
        services.convert_request(seller, OrderRequest.objects.get(pk=body["id"]))
    detail = client.get(f"{BASE}{body['id']}/").json()
    assert detail["status_display"] == "Siparişe çevrildi"
    assert detail["order_number"].startswith("SS-")
    assert detail["order_id"] is None  # taslak sipariş müşteriye bağlantı vermez

    withdraw = client.post(f"{BASE}{body['id']}/withdraw/")
    assert withdraw.status_code == 400 and withdraw.json()["code"] == "request_not_open"


def test_customer_sees_only_own_requests(
    customer_account: PortalAccount, sysadmin: User, product: Material
) -> None:
    mine = _submit(customer_account, product)
    other_account, _ = services.create_account(
        sysadmin, username="obur.musteri", full_name="Öbür", customer=CustomerFactory.create()
    )
    theirs = _submit(other_account, product)
    client = session_client(customer_account.user)

    assert [r["number"] for r in client.get(BASE).json()["results"]] == [mine.number]
    assert client.get(f"{BASE}{theirs.pk}/").status_code == 404
    assert client.post(f"{BASE}{theirs.pk}/withdraw/").status_code == 404


def test_staff_api_and_access(
    customer_account: PortalAccount,
    product: Material,
    seller: User,
    client_for: Callable[..., APIClient],
    commit: Commit,
) -> None:
    with commit():
        first = _submit(customer_account, product)
        second = _submit(customer_account, product)
    staff = APIClient()
    staff.force_authenticate(seller)

    listed = staff.get(STAFF, {"status": "SUBMITTED"}).json()
    assert {r["number"] for r in listed["results"]} == {first.number, second.number}
    row = staff.get(f"{STAFF}{first.pk}/").json()
    assert customer_account.customer is not None
    assert row["customer_code"] == customer_account.customer.code
    assert row["created_by_name"] == "Müşteri Yetkili"

    converted = staff.post(f"{STAFF}{first.pk}/convert/")
    assert converted.status_code == 200 and converted.json()["sales_order"]
    rejected = staff.post(f"{STAFF}{second.pk}/reject/", {"reason": "Mükerrer"}, format="json")
    assert rejected.status_code == 200 and rejected.json()["reject_reason"] == "Mükerrer"

    planner = client_for(PLANLAMA)
    assert planner.get(STAFF).status_code == 200
    assert planner.post(f"{STAFF}{first.pk}/convert/").status_code == 403
    for role in ("uretim", "laboratuvar", "dolum", "satin_alma"):
        assert client_for(role).get(STAFF).status_code == 403

    portal = session_client(customer_account.user).get(STAFF)
    assert portal.status_code == 403 and portal.json()["code"] == "portal_forbidden"
    assert staff.get(BASE).status_code == 403
