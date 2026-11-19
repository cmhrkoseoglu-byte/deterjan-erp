"""Tedarikçi portalı okumaları: gönderilmiş siparişler ve PDF, teslimatlar, cari ve ekstre; firma
süzgeci ve yetki (docs/plan/musteri-siparis-takibi.md §4.3a)."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.models import User
from apps.core.roles import DEPO, SATIN_ALMA, YONETIM
from apps.inventory import services as inventory
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Supplier
from apps.masterdata.tests.factories import SupplierFactory
from apps.portal.models import PortalAccount
from apps.portal.tests.helpers import session_client
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import (
    approved_order,
    draft_order,
    line,
    raw_material,
    receipt_locations,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/portal/supplier/"
Commit = Callable[[], AbstractContextManager[Any]]


@pytest.fixture(autouse=True)
def invariants() -> Iterator[None]:
    yield
    assert_stock_invariants()


@pytest.fixture
def commit(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> Commit:
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user(YONETIM, username="yonetim")


@pytest.fixture
def buyer(make_user: Callable[..., User]) -> User:
    return make_user(SATIN_ALMA, username="satin_alma")


@pytest.fixture
def depo(make_user: Callable[..., User]) -> User:
    return make_user(DEPO, username="depo")


@pytest.fixture
def client(supplier_account: PortalAccount) -> APIClient:
    return session_client(supplier_account.user)


def _sent(manager: User, buyer: User, supplier: Supplier, **data: Any) -> PurchaseOrder:
    order = approved_order(
        manager,
        [line(raw_material(), "100", "10", note="iç satır notu")],
        supplier=supplier,
        notes="Teslimde analiz sertifikası ekleyin",
        **data,
    )
    return purchasing.mark_sent(buyer, order)


def _receive(depo: User, order: PurchaseOrder, quantity: str) -> Any:
    receipt = purchasing.create_receipt_from_order(
        depo,
        order,
        {
            "receipt_date": date(2026, 10, 18),
            "delivery_note_no": "TED-IRS-7",
            **receipt_locations(),
        },
        [
            {
                "order_line": order.lines.get().pk,
                "quantity": Decimal(quantity),
                "supplier_lot_no": "TL-55",
            }
        ],
    )
    return inventory.post_goods_receipt(depo, receipt)


def test_only_sent_orders_of_own_supplier(
    client: APIClient, manager: User, buyer: User, supplier: Supplier
) -> None:
    sent = _sent(manager, buyer, supplier)
    approved_order(manager, [line(raw_material())], supplier=supplier)  # gönderilmedi
    draft_order(manager, [line(raw_material())], supplier=supplier)  # taslak
    cancelled = _sent(manager, buyer, supplier)
    purchasing.cancel_order(buyer, cancelled, "tedarikçi teslim edemiyor")
    other = _sent(manager, buyer, SupplierFactory.create())

    numbers = {row["number"] for row in client.get(BASE + "orders/").json()["results"]}
    assert numbers == {sent.number, cancelled.number}

    detail = client.get(f"{BASE}orders/{sent.pk}/").json()
    assert detail["notes"] == "Teslimde analiz sertifikası ekleyin"
    assert detail["total"] == "1000.00" and detail["status"] == "SENT"
    [row] = detail["lines"]
    assert (row["quantity"], row["unit_price"], row["line_total"]) == (
        "100.0000",
        "10.0000",
        "1000.00",
    )
    assert (row["received_quantity"], row["remaining_in_unit"]) == ("0.0000", "100.0000")
    for hidden in (
        "approval_total_try",
        "approval_limit_try",
        "exchange_rate",
        "approved_by",
        "sent_by",
        "sent_to",
        "closed_note",
    ):
        assert hidden not in detail
    assert "note" not in row

    assert client.get(f"{BASE}orders/{other.pk}/").status_code == 404
    assert client.get(f"{BASE}orders/{other.pk}/pdf/").status_code == 404
    pdf = client.get(f"{BASE}orders/{sent.pk}/pdf/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf["Cache-Control"] == "no-store"


def test_receipts_and_received_quantities(
    client: APIClient,
    manager: User,
    buyer: User,
    depo: User,
    supplier: Supplier,
    commit: Commit,
) -> None:
    order = _sent(manager, buyer, supplier)
    with commit():
        receipt = _receive(depo, order, "40")
    other_order = _sent(manager, buyer, SupplierFactory.create())
    with commit():
        _receive(depo, other_order, "10")

    [row] = client.get(f"{BASE}orders/{order.pk}/").json()["lines"]
    assert (row["received_quantity"], row["remaining_quantity"]) == ("40.0000", "60.0000")

    receipts = client.get(BASE + "receipts/").json()["results"]
    assert [r["number"] for r in receipts] == [receipt.number]
    detail = client.get(f"{BASE}receipts/{receipt.pk}/").json()
    assert detail["delivery_note_no"] == "TED-IRS-7"
    [receipt_line] = detail["lines"]
    assert receipt_line["supplier_lot_no"] == "TL-55"
    assert receipt_line["order_number"] == order.number
    for hidden in ("lot", "lot_no", "unit_price", "status", "quarantine_location", "note"):
        assert hidden not in receipt_line and hidden not in detail

    [balance] = client.get(BASE + "ledger/").json()
    assert balance["currency"] == "TRY" and Decimal(balance["balance"]) != 0
    [currency] = client.get(BASE + "ledger/statement/").json()["currencies"]
    assert [r["document"] for r in currency["rows"]] == [receipt.number]
    statement_pdf = client.get(BASE + "ledger/statement-pdf/")
    assert statement_pdf.status_code == 200 and statement_pdf.content.startswith(b"%PDF")


@pytest.mark.parametrize(
    "path", ["orders/", "receipts/", "ledger/", "ledger/statement/", "ledger/statement-pdf/"]
)
def test_only_supplier_portal_opens_supplier_endpoints(
    path: str, customer_account: PortalAccount, make_user: Callable[..., User]
) -> None:
    customer = session_client(customer_account.user).get(BASE + path)
    assert customer.status_code == 403 and customer.json()["code"] == "portal_forbidden"
    staff = APIClient()
    staff.force_authenticate(make_user(SATIN_ALMA, username="satin.calisan"))
    assert staff.get(BASE + path).status_code == 403
    assert APIClient().get(BASE + path).status_code in (401, 403)
