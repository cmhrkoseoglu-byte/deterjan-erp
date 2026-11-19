"""Müşteri portalı okumaları: siparişler, sevkiyatlar, müşteri nüshası irsaliye, cari ve ekstre;
firma süzgeci ve yetki (docs/plan/musteri-siparis-takibi.md §4.3)."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, User
from apps.core.roles import DEPO, SEVKIYAT
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Customer, Location
from apps.masterdata.tests.factories import CustomerFactory
from apps.portal.models import PortalAccount
from apps.portal.tests.helpers import session_client
from apps.sales import services as sales
from apps.sales.models import SalesOrder, Shipment
from apps.sales.tests.factories import (
    draft_order,
    finished_lot,
    finished_product,
    shipping_location,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/portal/customer/"
DRIVER_ID = "12345678901"
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
def seller(make_user: Callable[..., User]) -> User:
    return make_user(SEVKIYAT, username="sevkiyat")


@pytest.fixture
def picker(make_user: Callable[..., User]) -> User:
    return make_user(DEPO, username="depo")


@pytest.fixture
def client(customer_account: PortalAccount) -> APIClient:
    return session_client(customer_account.user)


def _order(seller: User, customer: Customer, **data: Any) -> SalesOrder:
    """Onaylı sipariş: 24 ADET (2 KOLI), 10 TL/KOLI."""
    product = finished_product()
    finished_lot(product, "100")
    order = draft_order(seller, [(product, "2", "KOLI")], customer=customer, **data)
    line = order.lines.get()
    line.unit_price = Decimal("10")
    line.currency = "TRY"
    line.note = "iç satır notu"
    line.save(update_fields=["unit_price", "currency", "note"])
    return sales.confirm_order(seller, order)


def _plan(seller: User, order: SalesOrder, quantity: str | None = None) -> Shipment:
    if not Location.objects.filter(location_type=Location.Type.SHIPPING).exists():
        shipping_location(code="SEVK")
    line = order.lines.get()
    items = None if quantity is None else [{"order_line": line, "quantity": Decimal(quantity)}]
    return sales.plan_shipment(
        seller,
        order,
        {
            "planned_date": timezone.localdate(),
            "vehicle_plate": "34 ABC 123",
            "driver_name": "Ali Veli",
            "driver_id_no": DRIVER_ID,
        },
        items,
    )


def _dispatch(seller: User, picker: User, shipment: Shipment) -> Shipment:
    line = shipment.lines.get()
    reservation = line.order_line.reservations.filter(status="ACTIVE").first()
    assert reservation is not None
    sales.pick_lot(picker, shipment, reservation.lot)
    sales.mark_loaded(picker, shipment)
    return sales.dispatch_shipment(seller, shipment)


class PdfText:
    """PDF üreticisine giden metinler (paragraflar ve tablo hücreleri); PDF okuyucu gerekmez."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
        self.parts: list[str] = []
        paragraph, table = module.Paragraph, module.Table

        def spy_paragraph(text: str, *args: Any, **kwargs: Any) -> Any:
            self.parts.append(str(text))
            return paragraph(text, *args, **kwargs)

        def spy_table(rows: Any, *args: Any, **kwargs: Any) -> Any:
            self.parts.extend(str(cell) for row in rows for cell in row if isinstance(cell, str))
            return table(rows, *args, **kwargs)

        monkeypatch.setattr(module, "Paragraph", spy_paragraph)
        monkeypatch.setattr(module, "Table", spy_table)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)


# --- siparişler ---------------------------------------------------------------------------------


def test_orders_only_confirmed_and_own(client: APIClient, seller: User, customer: Customer) -> None:
    mine = _order(seller, customer, notes="iç not")
    draft_order(seller, [(finished_product(), "1", "ADET")], customer=customer)  # taslak
    never = draft_order(seller, [(finished_product(), "1", "ADET")], customer=customer)
    sales.cancel_order(seller, never, "yanlış")
    cancelled = _order(seller, customer)
    sales.cancel_order(seller, cancelled, "vazgeçti")
    other = _order(seller, CustomerFactory.create())

    data = client.get(BASE + "orders/").json()
    numbers = {row["number"] for row in data["results"]}
    assert numbers == {mine.number, cancelled.number}

    detail = client.get(f"{BASE}orders/{mine.pk}/").json()
    assert detail["status_display"] == "Onaylandı"
    assert detail["due_date"] == str(mine.promised_date)
    assert detail["totals"] == [{"currency": "TRY", "amount": "20.00"}]
    [line] = detail["lines"]
    assert (line["quantity"], line["unit_code"], line["remaining_in_unit"]) == (
        "2.0000",
        "KOLI",
        "2.0000",
    )
    for hidden in ("notes", "cancel_reason", "confirmed_by_name", "created_by_name"):
        assert hidden not in detail
    assert "note" not in line and "reserved_quantity" not in line
    assert "shortage_quantity" not in line

    assert client.get(f"{BASE}orders/{other.pk}/").status_code == 404
    assert client.get(BASE + "orders/", {"status": "CANCELLED"}).json()["count"] == 1


# --- sevkiyatlar ve irsaliye --------------------------------------------------------------------


def test_planned_shipment_hides_vehicle_and_waybill(
    client: APIClient, seller: User, customer: Customer
) -> None:
    order = _order(seller, customer)
    shipment = _plan(seller, order, "12")

    [row] = client.get(BASE + "shipments/").json()["results"]
    assert row["status"] == "PLANNED" and row["vehicle_plate"] == "" and not row["has_waybill"]
    assert "driver_name" not in row and "driver_id_no" not in row and "notes" not in row
    [line] = client.get(f"{BASE}shipments/{shipment.pk}/").json()["lines"]
    assert (line["quantity"], line["quantity_in_unit"], line["unit_code"]) == (
        "12.0000",
        "1.0000",
        "KOLI",
    )
    blocked = client.get(f"{BASE}shipments/{shipment.pk}/waybill-pdf/")
    assert blocked.status_code == 400 and blocked.json()["code"] == "waybill_not_ready"


def test_dispatched_waybill_is_customer_copy(
    client: APIClient,
    seller: User,
    picker: User,
    customer: Customer,
    customer_account: PortalAccount,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.sales import waybill

    order = _order(seller, customer)
    with commit():
        shipment = _dispatch(seller, picker, _plan(seller, order))
    pdf = PdfText(monkeypatch, waybill)
    lot_no = shipment.lines.get().picks.get().lot.lot_no

    row = client.get(f"{BASE}shipments/{shipment.pk}/").json()
    assert row["vehicle_plate"] == "34 ABC 123" and row["has_waybill"] is True
    assert row["lines"][0]["quantity"] == "24.0000"

    response = client.get(f"{BASE}shipments/{shipment.pk}/waybill-pdf/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Cache-Control"] == "no-store"
    assert response.content.startswith(b"%PDF")
    text = pdf.text
    assert "SEVK İRSALİYESİ" in text and "Ali Veli" in text
    assert DRIVER_ID not in text and "*******8901" in text
    assert lot_no not in text and "SKT" not in text
    assert AuditLog.objects.filter(
        actor=customer_account.user, note="İrsaliye görüntülendi (portal)"
    ).exists()


def test_other_customers_shipment_is_404(
    client: APIClient, seller: User, picker: User, commit: Commit
) -> None:
    order = _order(seller, CustomerFactory.create())
    with commit():
        shipment = _dispatch(seller, picker, _plan(seller, order))
    assert client.get(f"{BASE}shipments/{shipment.pk}/").status_code == 404
    assert client.get(f"{BASE}shipments/{shipment.pk}/waybill-pdf/").status_code == 404
    assert client.get(BASE + "shipments/").json()["count"] == 0


# --- cari hesabım -------------------------------------------------------------------------------


def test_balance_statement_and_pdf(
    client: APIClient,
    seller: User,
    picker: User,
    customer: Customer,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.ledger import exports

    order = _order(seller, customer)
    with commit():
        _dispatch(seller, picker, _plan(seller, order))
    other = _order(seller, CustomerFactory.create())
    with commit():
        _dispatch(seller, picker, _plan(seller, other))

    [balance] = client.get(BASE + "ledger/").json()
    assert balance["currency"] == "TRY" and Decimal(balance["balance"]) > 0
    assert set(balance["aging"]) == {"not_due", "d1_30", "d31_60", "d61_90", "d90_plus"}

    statement = client.get(BASE + "ledger/statement/").json()
    [currency] = statement["currencies"]
    [row] = currency["rows"]
    assert row["document"].startswith("SV-")
    assert Decimal(row["debit"]) == Decimal(balance["balance"])
    assert "created_by_name" not in row and "exchange_rate" not in row

    bad = client.get(
        BASE + "ledger/statement/", {"date_from": "2026-12-01", "date_to": "2026-11-01"}
    )
    assert bad.status_code == 400

    pdf = PdfText(monkeypatch, exports)
    response = client.get(BASE + "ledger/statement-pdf/")
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert customer.name in pdf.text and other.customer.name not in pdf.text


# --- yetki --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["orders/", "shipments/", "ledger/", "ledger/statement/", "ledger/statement-pdf/"]
)
def test_only_customer_portal_opens_customer_endpoints(
    path: str, supplier_account: PortalAccount, make_user: Callable[..., User]
) -> None:
    supplier = session_client(supplier_account.user).get(BASE + path)
    assert supplier.status_code == 403 and supplier.json()["code"] == "portal_forbidden"
    staff = APIClient()
    staff.force_authenticate(make_user(SEVKIYAT, username="sevk.calisan"))
    assert staff.get(BASE + path).status_code == 403
    assert APIClient().get(BASE + path).status_code in (401, 403)
