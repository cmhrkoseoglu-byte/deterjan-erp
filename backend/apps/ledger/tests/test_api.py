"""Cari hesaplar API'si: yetki, tutar gizleme, liste, ekstre, yaşlandırma, elle kayıt ve çıktılar
(docs/plan/cari-hesaplar.md §2.3-§2.5)."""

import io
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.models import User
from apps.core.roles import DEPO, PLANLAMA, SATIN_ALMA, SEVKIYAT, YONETIM
from apps.ledger import services
from apps.ledger.models import LedgerEntry
from apps.ledger.tests.factories import dispatched_shipment, posted_receipt, product, raw_material
from apps.masterdata.models import Customer
from apps.masterdata.tests.factories import CustomerFactory, SupplierFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

D = Decimal
Kind = LedgerEntry.Kind
BASE = "/api/v1/ledger"
TODAY = timezone.localdate


def days_ago(days: int) -> Any:
    return TODAY() - timedelta(days=days)


def opening(actor: User, partner: Any, amount: str, days: int, direction: str = "debit") -> None:
    services.post_manual_entry(
        actor,
        partner=partner,
        kind=Kind.OPENING,
        entry_date=days_ago(days),
        currency="TRY",
        amount=D(amount),
        direction=direction,
    )


@pytest.fixture
def customer(manager: User) -> Customer:
    customer = CustomerFactory.create(name="Ak Market", payment_term_days=30)
    opening(manager, customer, "1000", 100)  # vadesi 70 gün geçmiş
    opening(manager, customer, "500", 45)  # vadesi 15 gün geçmiş
    opening(manager, customer, "200", 5)  # vadesi gelmemiş
    services.post_manual_entry(
        manager,
        partner=customer,
        kind=Kind.COLLECTION,
        entry_date=days_ago(2),
        currency="TRY",
        amount=D("1200"),
        method="TRANSFER",
    )
    return customer


# --- yetki -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "side", "expected"),
    [
        ((YONETIM,), "customers", 200),
        ((YONETIM,), "suppliers", 200),
        ((SATIN_ALMA,), "suppliers", 200),
        ((SATIN_ALMA,), "customers", 403),
        ((SEVKIYAT,), "customers", 200),
        ((SEVKIYAT,), "suppliers", 403),
        ((PLANLAMA,), "customers", 403),
        ((DEPO,), "suppliers", 403),
        ((), "customers", 403),
    ],
)
def test_list_access(
    client_for: Callable[..., APIClient], roles: tuple[str, ...], side: str, expected: int
) -> None:
    assert client_for(*roles).get(f"{BASE}/{side}/").status_code == expected


def test_signed_out_gets_401(api_client: APIClient) -> None:
    assert api_client.get(f"{BASE}/customers/").status_code in (401, 403)


@pytest.mark.parametrize(("roles", "expected"), [((SEVKIYAT,), 403), ((SATIN_ALMA,), 403)])
def test_customer_entries_need_change(
    client_for: Callable[..., APIClient], roles: tuple[str, ...], expected: int
) -> None:
    customer = CustomerFactory.create()
    response = client_for(*roles).post(
        f"{BASE}/customers/{customer.pk}/entries/",
        {"kind": "COLLECTION", "entry_date": TODAY(), "currency": "TRY", "amount": "10"},
        format="json",
    )

    assert response.status_code == expected
    assert not LedgerEntry.objects.exists()


def test_buyer_enters_supplier_payment(client_for: Callable[..., APIClient]) -> None:
    supplier = SupplierFactory.create()
    response = client_for(SATIN_ALMA).post(
        f"{BASE}/suppliers/{supplier.pk}/entries/",
        {
            "kind": "PAYMENT",
            "entry_date": TODAY(),
            "currency": "EUR",
            "amount": "1500.25",
            "method": "TRANSFER",
            "exchange_rate": "36.1",
            "reference": "EFT-1",
        },
        format="json",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["kind"], body["debit"], body["credit"]) == ("PAYMENT", "1500.25", "0.00")
    assert body["number"].startswith("CH-")
    assert body["method_display"] == "Havale / EFT"


def test_business_rule_error_shape(client_for: Callable[..., APIClient]) -> None:
    customer = CustomerFactory.create()
    response = client_for(YONETIM).post(
        f"{BASE}/customers/{customer.pk}/entries/",
        {"kind": "PAYMENT", "entry_date": TODAY(), "currency": "TRY", "amount": "10"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_entry_kind"


# --- liste, özet ve tutar gizleme ----------------------------------------------------------


def test_list_shows_balances_aging_and_totals(
    client_for: Callable[..., APIClient], customer: Customer
) -> None:
    CustomerFactory.create(name="Boş Cari")

    body = client_for(YONETIM).get(f"{BASE}/customers/").json()

    assert body["count"] == 2
    row = next(r for r in body["results"] if r["partner"]["id"] == customer.pk)
    [balance] = row["balances"]
    assert (balance["debit"], balance["credit"], balance["balance"]) == (
        "1700.00",
        "1200.00",
        "500.00",
    )
    # 1.200 tahsilat en eski 1.000'i ve 500'ün 200'ünü kapatır: 300 (15 gün geçmiş) + 200 vadesiz.
    assert balance["aging"] == {
        "not_due": "200.00",
        "d1_30": "300.00",
        "d31_60": "0.00",
        "d61_90": "0.00",
        "d90_plus": "0.00",
    }
    assert balance["overdue"] == "300.00"
    assert body["totals"] == [
        {"currency": "TRY", "open": "500.00", "advance": "0.00", "overdue": "300.00"}
    ]


def test_list_filters(client_for: Callable[..., APIClient], customer: Customer) -> None:
    CustomerFactory.create(name="Boş Cari")
    client = client_for(YONETIM)

    def names(**params: Any) -> list[str]:
        rows = client.get(f"{BASE}/customers/", params).json()["results"]
        return [row["partner"]["name"] for row in rows]

    assert names(with_balance=True) == ["Ak Market"]
    assert names(overdue=True) == ["Ak Market"]
    assert names(currency="EUR", with_balance=True) == []
    assert names(search="boş") == ["Boş Cari"]


def test_shipper_sees_no_amounts(client_for: Callable[..., APIClient], customer: Customer) -> None:
    client = client_for(SEVKIYAT)

    listing = client.get(f"{BASE}/customers/").json()
    summary = client.get(f"{BASE}/customers/{customer.pk}/").json()
    statement = client.get(f"{BASE}/customers/{customer.pk}/statement/").json()

    assert "totals" not in listing
    assert listing["results"][0]["balances"] == [{"currency": "TRY", "last_date": str(days_ago(2))}]
    assert summary["balances"] == [{"currency": "TRY", "last_date": str(days_ago(2))}]
    block = statement["currencies"][0]
    assert set(block) == {"currency", "rows"}
    row = block["rows"][0]
    assert set(row) == {"entry", "due_date", "is_reversed"}
    assert not {"debit", "credit", "net_amount", "vat_amount", "exchange_rate"} & set(row["entry"])


def test_summary_and_404(client_for: Callable[..., APIClient], customer: Customer) -> None:
    client = client_for(YONETIM)

    summary = client.get(f"{BASE}/customers/{customer.pk}/").json()

    assert summary["partner"] == {
        "id": customer.pk,
        "code": customer.code,
        "name": "Ak Market",
        "payment_term_days": 30,
        "vat_exempt": False,
        "is_active": True,
    }
    assert summary["balances"][0]["balance"] == "500.00"
    assert client.get(f"{BASE}/suppliers/{customer.pk + 1000}/").status_code == 404


# --- ekstre ----------------------------------------------------------------------------------


def test_statement_with_opening_balance_and_running_balance(
    client_for: Callable[..., APIClient], customer: Customer
) -> None:
    response = client_for(YONETIM).get(
        f"{BASE}/customers/{customer.pk}/statement/", {"date_from": str(days_ago(50))}
    )

    assert response.status_code == 200, response.json()
    [block] = response.json()["currencies"]
    assert block["opening"] == "1000.00"
    assert [(r["entry"]["kind"], r["balance"]) for r in block["rows"]] == [
        ("OPENING", "1500.00"),
        ("OPENING", "1700.00"),
        ("COLLECTION", "500.00"),
    ]
    assert block["rows"][0]["due_date"] == str(days_ago(15))
    assert block["rows"][2]["due_date"] is None
    assert (block["total_debit"], block["total_credit"], block["closing"]) == (
        "700.00",
        "1200.00",
        "500.00",
    )


def test_statement_rejects_reversed_dates(
    client_for: Callable[..., APIClient], customer: Customer
) -> None:
    response = client_for(YONETIM).get(
        f"{BASE}/customers/{customer.pk}/statement/",
        {"date_from": str(TODAY()), "date_to": str(days_ago(1))},
    )

    assert response.status_code == 400


def test_reverse_via_api(client_for: Callable[..., APIClient], customer: Customer) -> None:
    client = client_for(YONETIM)
    collection = LedgerEntry.objects.get(kind=Kind.COLLECTION)
    other = CustomerFactory.create()

    wrong = client.post(
        f"{BASE}/customers/{other.pk}/reverse/",
        {"entry": collection.pk, "reason": "Hata"},
        format="json",
    )
    response = client.post(
        f"{BASE}/customers/{customer.pk}/reverse/",
        {"entry": collection.pk, "reason": "Yanlış tutar"},
        format="json",
    )
    statement = client.get(f"{BASE}/customers/{customer.pk}/statement/").json()

    assert wrong.status_code == 404
    assert response.status_code == 201, response.json()
    assert response.json()["reversal_of_number"] == collection.number
    rows = statement["currencies"][0]["rows"]
    assert [r["is_reversed"] for r in rows if r["entry"]["kind"] == "COLLECTION"] == [True]
    assert statement["currencies"][0]["closing"] == "1700.00"
    # Birbirini götüren kayıtlar yaşlandırmaya girmez: 1.000 + 500 vadesi geçmiş.
    summary = client.get(f"{BASE}/customers/{customer.pk}/").json()
    assert summary["balances"][0]["aging"]["d61_90"] == "1000.00"
    assert summary["balances"][0]["overdue"] == "1500.00"


def test_supplier_aging_counts_our_debt(
    client_for: Callable[..., APIClient], buyer: User, manager: User
) -> None:
    supplier = SupplierFactory.create(payment_term_days=60)
    posted_receipt(
        buyer,
        [(raw_material(), "100", "10", "TRY", None)],
        supplier=supplier,
        receipt_date=days_ago(90),
    )
    services.sync_all()
    services.post_manual_entry(
        manager,
        partner=supplier,
        kind=Kind.PAYMENT,
        entry_date=days_ago(1),
        currency="TRY",
        amount=D("200"),
        method="CASH",
    )

    [balance] = client_for(YONETIM).get(f"{BASE}/suppliers/{supplier.pk}/").json()["balances"]

    assert (balance["credit"], balance["debit"], balance["balance"]) == (
        "1200.00",
        "200.00",
        "-1000.00",
    )
    assert balance["aging"]["d1_30"] == "1000.00"


# --- eksik fiyat ve iade önerisi -------------------------------------------------------------


def test_missing_prices_and_ledger_price(
    client_for: Callable[..., APIClient], shipper: User, picker: User
) -> None:
    item = product()
    shipment = dispatched_shipment(shipper, picker, [(item, "3", "KOLI", None, "")])
    customer = shipment.sales_order.customer
    client = client_for(YONETIM)

    missing = client.get(f"{BASE}/customers/missing-prices/", {"partner": customer.pk}).json()
    listing = client.get(f"{BASE}/customers/").json()["results"]
    assert [(m["document_number"], m["quantity"], m["unit_code"]) for m in missing] == [
        (shipment.number, "3.0000", "KOLI")
    ]
    assert listing[0]["missing"] == 1

    denied = client_for(SEVKIYAT).post(
        f"{BASE}/customers/shipment-line-prices/",
        {"line": missing[0]["line_id"], "unit_price": "100", "currency": "TRY"},
        format="json",
    )
    response = client.post(
        f"{BASE}/customers/shipment-line-prices/",
        {"line": missing[0]["line_id"], "unit_price": "100", "currency": "TRY"},
        format="json",
    )

    assert denied.status_code == 403
    assert response.status_code == 200, response.json()
    assert [e["debit"] for e in response.json()] == ["360.00"]
    assert client.get(f"{BASE}/customers/missing-prices/").json() == []


def test_supplier_missing_prices(client_for: Callable[..., APIClient], buyer: User) -> None:
    receipt = posted_receipt(buyer, [(raw_material(), "5", None, "TRY", None)])

    rows = client_for(SATIN_ALMA).get(f"{BASE}/suppliers/missing-prices/").json()

    assert [(r["kind"], r["document_number"]) for r in rows] == [("goods_receipt", receipt.number)]


def test_return_suggestion(
    client_for: Callable[..., APIClient], shipper: User, picker: User
) -> None:
    from apps.ledger.tests.test_services import _received_return

    shipment = dispatched_shipment(shipper, picker, [(product(), "10", "ADET", "50", "TRY")])
    document = _received_return(shipper, shipment)
    customer = shipment.sales_order.customer

    response = client_for(YONETIM).get(
        f"{BASE}/customers/{customer.pk}/return-suggestion/", {"customer_return": document.pk}
    )

    assert response.status_code == 200, response.json()
    # 2 adet × 50 = 100 + %20 KDV.
    assert response.json()["suggestion"] == [{"currency": "TRY", "amount": "120.00"}]
    assert (
        client_for(SEVKIYAT)
        .get(f"{BASE}/customers/{customer.pk}/return-suggestion/", {"customer_return": document.pk})
        .status_code
        == 403
    )


# --- çıktılar --------------------------------------------------------------------------------


def _sheet_values(content: bytes) -> list[list[Any]]:
    workbook = load_workbook(io.BytesIO(content))
    return [list(row) for sheet in workbook.worksheets for row in sheet.iter_rows(values_only=True)]


def test_statement_xlsx_hides_amounts_without_prices(
    client_for: Callable[..., APIClient], customer: Customer
) -> None:
    url = f"{BASE}/customers/{customer.pk}/statement-xlsx/"

    full = client_for(YONETIM).get(url)
    plain = client_for(SEVKIYAT).get(url)

    assert full.status_code == plain.status_code == 200
    assert full["Content-Disposition"].startswith('attachment; filename="ekstre-')
    full_rows, plain_rows = _sheet_values(full.content), _sheet_values(plain.content)
    assert [*full_rows[4][:9]] == [
        "Tarih",
        "Kayıt no",
        "Tür",
        "Belge",
        "Açıklama",
        "Vade",
        "Matrah",
        "KDV",
        "Borç",
    ]
    assert "Borç" not in plain_rows[4]
    assert any(row[2] == "Tahsilat" and row[9] == 1200 for row in full_rows)


def test_partners_xlsx(client_for: Callable[..., APIClient], customer: Customer) -> None:
    response = client_for(YONETIM).get(f"{BASE}/customers/export-xlsx/", {"with_balance": True})

    assert response.status_code == 200
    rows = _sheet_values(response.content)
    assert rows[0][0] == "Müşteri carileri"
    assert rows[4][:4] == [customer.code, "Ak Market", 30, "TRY"]


def test_statement_pdf_needs_prices(
    client_for: Callable[..., APIClient], customer: Customer
) -> None:
    url = f"{BASE}/customers/{customer.pk}/statement-pdf/"

    response = client_for(YONETIM).get(url)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert client_for(SEVKIYAT).get(url).status_code == 403


def test_supplier_outputs_carry_balance_notice(
    client_for: Callable[..., APIClient],
    manager: User,
    customer: Customer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.ledger import exports
    from apps.ledger.notices import SUPPLIER_NOTICE

    supplier = SupplierFactory.create()
    services.post_manual_entry(
        manager,
        partner=supplier,
        kind=Kind.PAYMENT,
        entry_date=days_ago(1),
        currency="TRY",
        amount=D("10"),
        method="CASH",
    )
    client = client_for(YONETIM)

    listing = _sheet_values(client.get(f"{BASE}/suppliers/export-xlsx/").content)
    statement = _sheet_values(client.get(f"{BASE}/suppliers/{supplier.pk}/statement-xlsx/").content)
    assert ["Not", SUPPLIER_NOTICE] in [row[:2] for row in listing[:4]]
    assert ["Not", SUPPLIER_NOTICE] in [row[:2] for row in statement[:5]]
    assert listing[4][0] == "Kod"  # başlık notun altında

    texts: list[str] = []
    real = exports.Paragraph

    def spy(text: str, *args: Any, **kwargs: Any) -> Any:
        texts.append(text)
        return real(text, *args, **kwargs)

    monkeypatch.setattr(exports, "Paragraph", spy)
    assert client.get(f"{BASE}/suppliers/{supplier.pk}/statement-pdf/").status_code == 200
    assert SUPPLIER_NOTICE in texts
    texts.clear()
    assert client.get(f"{BASE}/customers/{customer.pk}/statement-pdf/").status_code == 200
    assert SUPPLIER_NOTICE not in texts
    customers = _sheet_values(client.get(f"{BASE}/customers/export-xlsx/").content)
    assert all(row[0] != "Not" for row in customers)
