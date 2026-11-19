"""Cari defter servisleri (docs/plan/cari-hesaplar.md §2.1)."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.inventory import services as inventory
from apps.inventory.tests.factories import quarantine_location
from apps.ledger import services
from apps.ledger.models import LedgerEntry
from apps.ledger.testing import assert_ledger_invariants
from apps.ledger.tests.factories import dispatched_shipment, posted_receipt, product, raw_material
from apps.masterdata.tests.factories import CustomerFactory, SupplierFactory, unit
from apps.returns import services as returns
from apps.returns.models import CustomerReturn
from apps.sales.models import Shipment

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

D = Decimal
Kind = LedgerEntry.Kind
Commit = Callable[[], AbstractContextManager[Any]]


def entries(**filters: Any) -> list[LedgerEntry]:
    return list(LedgerEntry.objects.filter(**filters).order_by("id"))


# --- sevkiyat --------------------------------------------------------------------------------


def test_dispatch_debits_customer_with_vat(shipper: User, picker: User, commit: Commit) -> None:
    item = product()
    with commit():
        shipment = dispatched_shipment(shipper, picker, [(item, "10", "ADET", "50", "TRY")])

    [entry] = entries()
    assert entry.kind == Kind.SALE
    assert entry.customer == shipment.sales_order.customer
    assert entry.shipment == shipment
    assert (entry.net_amount, entry.vat_amount, entry.debit, entry.credit) == (
        D("500.00"),
        D("100.00"),
        D("600.00"),
        D("0.00"),
    )
    assert entry.entry_date == timezone.localtime(shipment.dispatched_at).date()
    assert entry.description == f"Sevkiyat {shipment.number}"
    assert entry.number.startswith("CH-")
    assert entry.created_by == shipper
    assert AuditLog.objects.filter(object_id=str(entry.pk), action=AuditLog.Action.CREATE).exists()


def test_price_in_order_unit_and_vat_rates_per_material(shipper: User, picker: User) -> None:
    case_item = product(vat_rate="10")
    low_vat = product(vat_rate="1")
    shipment = dispatched_shipment(
        shipper,
        picker,
        [(case_item, "2", "KOLI", "120", "TRY"), (low_vat, "3", "ADET", "10.555", "TRY")],
    )

    [entry] = services.sync_shipment(shipper, shipment)

    # 2 koli × 120 = 240 (+%10); 3 × 10,555 = 31,665 → 31,67 (+%1 = 0,32).
    assert entry.net_amount == D("271.67")
    assert entry.vat_amount == D("24.32")
    assert entry.debit == D("295.99")


def test_each_currency_has_its_own_entry(shipper: User, picker: User) -> None:
    shipment = dispatched_shipment(
        shipper,
        picker,
        [(product(), "4", "ADET", "25", "TRY"), (product(), "2", "ADET", "3.50", "EUR")],
    )

    created = services.sync_shipment(shipper, shipment)

    assert [(e.currency, e.debit) for e in created] == [("EUR", D("8.40")), ("TRY", D("120.00"))]
    assert all(e.exchange_rate is None for e in created)


def test_vat_exempt_customer_is_debited_without_vat(shipper: User, picker: User) -> None:
    customer = CustomerFactory.create(vat_exempt=True)
    shipment = dispatched_shipment(
        shipper, picker, [(product(), "10", "ADET", "4", "USD")], customer=customer
    )

    [entry] = services.sync_shipment(shipper, shipment)

    assert (entry.net_amount, entry.vat_amount, entry.debit) == (D("40.00"), D("0"), D("40.00"))


def test_sync_is_idempotent(shipper: User, picker: User) -> None:
    shipment = dispatched_shipment(shipper, picker, [(product(), "10", "ADET", "50", "TRY")])
    services.sync_shipment(shipper, shipment)

    assert services.sync_shipment(shipper, shipment) == []
    assert services.sync_all() == 0
    assert LedgerEntry.objects.count() == 1


def test_unpriced_line_waits_for_ledger_price(shipper: User, picker: User, manager: User) -> None:
    priced, unpriced = product(), product()
    shipment = dispatched_shipment(
        shipper,
        picker,
        [(priced, "1", "ADET", "100", "TRY"), (unpriced, "2", "KOLI", None, "")],
    )
    [first] = services.sync_shipment(shipper, shipment)
    assert first.net_amount == D("100.00")

    line = shipment.lines.get(order_line__product=unpriced)
    [added] = services.set_shipment_line_price(manager, line, D("60"), "TRY", "Fiyat sonradan")

    # İlk kayıt değil: düzeltme bugün tarihli; 2 koli × 60 = 120 (+%20).
    assert added.description == f"Düzeltme: Sevkiyat {shipment.number}"
    assert added.entry_date == timezone.localdate()
    assert (added.net_amount, added.debit) == (D("120.00"), D("144.00"))
    assert line.ledger_price.note == "Fiyat sonradan"


def test_ledger_price_change_writes_correction(shipper: User, picker: User, manager: User) -> None:
    shipment = dispatched_shipment(shipper, picker, [(product(), "10", "ADET", None, "")])
    line = shipment.lines.get()
    [first] = services.set_shipment_line_price(manager, line, D("5"), "TRY")
    assert first.description == f"Sevkiyat {shipment.number}"
    assert first.debit == D("60.00")

    [correction] = services.set_shipment_line_price(manager, line, D("4"), "TRY")

    assert (correction.net_amount, correction.vat_amount) == (D("-10.00"), D("-2.00"))
    assert (correction.debit, correction.credit) == (D("0"), D("12.00"))
    assert AuditLog.objects.filter(
        object_id=str(line.ledger_price.pk), action=AuditLog.Action.UPDATE
    ).exists()


def test_ledger_price_only_for_unpriced_dispatched_lines(
    shipper: User, picker: User, manager: User
) -> None:
    shipment = dispatched_shipment(shipper, picker, [(product(), "1", "ADET", "9", "TRY")])

    with pytest.raises(BusinessRuleError) as exc:
        services.set_shipment_line_price(manager, shipment.lines.get(), D("5"), "TRY")

    assert exc.value.code == "order_line_has_price"


def test_ledger_price_rejects_negative_price(shipper: User, picker: User, manager: User) -> None:
    shipment = dispatched_shipment(shipper, picker, [(product(), "1", "ADET", None, "")])

    with pytest.raises(BusinessRuleError) as exc:
        services.set_shipment_line_price(manager, shipment.lines.get(), D("-1"), "TRY")

    assert exc.value.code == "invalid_price"


def test_undispatched_shipment_writes_nothing(shipper: User, picker: User) -> None:
    shipment = dispatched_shipment(shipper, picker, [(product(), "1", "ADET", "9", "TRY")])
    Shipment.objects.filter(pk=shipment.pk).update(status=Shipment.Status.LOADED)

    assert services.sync_shipment(shipper, shipment) == []


# --- mal kabul -------------------------------------------------------------------------------


def test_posted_receipt_credits_supplier(buyer: User, commit: Commit) -> None:
    yesterday = timezone.localdate() - timedelta(days=1)
    with commit():
        receipt = posted_receipt(
            buyer,
            [
                (raw_material(), "100", "12.5", "TRY", None),
                (raw_material(), "10", "2", "EUR", "35"),
            ],
            receipt_date=yesterday,
        )

    eur, tl = entries(goods_receipt=receipt, currency="EUR"), entries(currency="TRY")
    assert [(e.kind, e.net_amount, e.vat_amount, e.credit, e.debit) for e in tl] == [
        (Kind.PURCHASE, D("1250.00"), D("250.00"), D("1500.00"), D("0"))
    ]
    assert [(e.credit, e.exchange_rate) for e in eur] == [(D("24.00"), D("35.000000"))]
    assert {e.entry_date for e in eur + tl} == {yesterday}
    assert eur[0].supplier == receipt.supplier


def test_receipt_extra_costs_stay_out_of_ledger(buyer: User) -> None:
    receipt = posted_receipt(buyer, [(raw_material(), "10", "10", "TRY", None)])
    inventory.set_receipt_costs(
        buyer,
        receipt,
        extra_costs=[{"kind": "FREIGHT", "description": "Nakliye", "amount": D("500")}],
        note="Nakliye faturası",
    )

    [entry] = services.sync_receipt(buyer, receipt)

    assert entry.credit == D("120.00")


def test_receipt_price_correction_writes_dated_correction(buyer: User, commit: Commit) -> None:
    last_week = timezone.localdate() - timedelta(days=7)
    with commit():
        receipt = posted_receipt(
            buyer, [(raw_material(), "100", "10", "TRY", None)], receipt_date=last_week
        )
    line = receipt.lines.get()

    with commit():
        inventory.set_receipt_costs(
            buyer, receipt, lines=[{"id": line.pk, "unit_price": D("11")}], note="Fatura farkı"
        )

    first, correction = entries(goods_receipt=receipt)
    assert first.entry_date == last_week
    assert correction.entry_date == timezone.localdate()
    assert correction.description.startswith(f"Düzeltme: Mal kabul {receipt.number}")
    assert (correction.net_amount, correction.vat_amount, correction.credit) == (
        D("100.00"),
        D("20.00"),
        D("120.00"),
    )


def test_receipt_priced_later_is_posted_on_receipt_date(buyer: User, commit: Commit) -> None:
    last_week = timezone.localdate() - timedelta(days=7)
    with commit():
        receipt = posted_receipt(
            buyer, [(raw_material(), "5", None, "TRY", None)], receipt_date=last_week
        )
    assert entries() == []

    with commit():
        inventory.set_receipt_costs(
            buyer,
            receipt,
            lines=[{"id": receipt.lines.get().pk, "unit_price": D("8")}],
            note="Fiyat geldi",
        )

    [entry] = entries()
    assert (entry.entry_date, entry.credit) == (last_week, D("48.00"))


def test_vat_exempt_supplier(buyer: User) -> None:
    supplier = SupplierFactory.create(vat_exempt=True)
    receipt = posted_receipt(buyer, [(raw_material(), "10", "3", "USD", "38")], supplier=supplier)

    [entry] = services.sync_receipt(buyer, receipt)

    assert (entry.credit, entry.vat_amount, entry.exchange_rate) == (
        D("30.00"),
        D("0"),
        D("38.000000"),
    )


def test_sync_ledger_command_backfills_once(shipper: User, picker: User, buyer: User) -> None:
    dispatched_shipment(shipper, picker, [(product(), "1", "ADET", "9", "TRY")])
    posted_receipt(buyer, [(raw_material(), "1", "9", "TRY", None)])
    assert entries() == []

    out = StringIO()
    call_command("sync_ledger", stdout=out)
    assert "2 kayıt" in out.getvalue()
    call_command("sync_ledger", stdout=out)

    assert LedgerEntry.objects.count() == 2
    assert all(entry.created_by is None for entry in entries())
    assert_ledger_invariants(all_documents=True)


# --- elle kayıt ------------------------------------------------------------------------------


def manual(actor: User, partner: Any, kind: str, amount: str = "100", **kwargs: Any) -> LedgerEntry:
    values: dict[str, Any] = {
        "partner": partner,
        "kind": kind,
        "entry_date": timezone.localdate(),
        "currency": "TRY",
        "amount": D(amount),
        **kwargs,
    }
    return services.post_manual_entry(actor, **values)


@pytest.mark.parametrize(
    ("kind", "extra", "side"),
    [
        (Kind.COLLECTION, {"method": "TRANSFER"}, "credit"),
        (Kind.DEBIT_NOTE, {"description": "Vade farkı"}, "debit"),
        (Kind.CREDIT_NOTE, {"description": "Fiyat farkı"}, "credit"),
        (Kind.OPENING, {"direction": "debit"}, "debit"),
        (Kind.OPENING, {"direction": "credit"}, "credit"),
    ],
)
def test_customer_manual_entries(manager: User, kind: str, extra: dict, side: str) -> None:
    customer = CustomerFactory.create()

    entry = manual(manager, customer, kind, "250.50", **extra)

    assert entry.customer == customer and entry.supplier is None
    assert getattr(entry, side) == D("250.50")
    assert entry.net_amount is None
    assert AuditLog.objects.filter(object_id=str(entry.pk), action=AuditLog.Action.CREATE).exists()


def test_supplier_payment_debits_supplier(buyer: User) -> None:
    supplier = SupplierFactory.create()

    entry = manual(
        buyer,
        supplier,
        Kind.PAYMENT,
        "1000",
        method="CHECK",
        reference="ÇEK-123",
        currency="EUR",
        exchange_rate=D("36.5"),
    )

    assert (entry.debit, entry.credit, entry.currency) == (D("1000.00"), D("0"), "EUR")
    assert (entry.method, entry.reference, entry.exchange_rate) == ("CHECK", "ÇEK-123", D("36.5"))


@pytest.mark.parametrize(
    ("partner_kind", "kind", "extra", "code"),
    [
        ("supplier", Kind.COLLECTION, {"method": "CASH"}, "invalid_entry_kind"),
        ("customer", Kind.PAYMENT, {"method": "CASH"}, "invalid_entry_kind"),
        ("customer", Kind.SALE, {}, "invalid_entry_kind"),
        ("customer", Kind.REVERSAL, {}, "invalid_entry_kind"),
        ("customer", Kind.OPENING, {}, "direction_required"),
        ("customer", Kind.COLLECTION, {}, "method_required"),
        ("customer", Kind.DEBIT_NOTE, {}, "description_required"),
        ("customer", Kind.RETURN_CREDIT, {}, "return_required"),
        ("customer", Kind.COLLECTION, {"method": "CASH", "currency": "GBP"}, "invalid_currency"),
    ],
)
def test_manual_entry_rules(
    manager: User, partner_kind: str, kind: str, extra: dict, code: str
) -> None:
    partner = CustomerFactory.create() if partner_kind == "customer" else SupplierFactory.create()

    with pytest.raises(BusinessRuleError) as exc:
        manual(manager, partner, kind, **extra)

    assert exc.value.code == code
    assert not LedgerEntry.objects.exists()


@pytest.mark.parametrize("amount", ["0", "-5", "10.555"])
def test_manual_entry_amount_rules(manager: User, amount: str) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        manual(manager, CustomerFactory.create(), Kind.COLLECTION, amount, method="CASH")

    assert exc.value.code == "invalid_amount"


def test_manual_entry_date_cannot_be_in_future(manager: User) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        manual(
            manager,
            CustomerFactory.create(),
            Kind.COLLECTION,
            method="CASH",
            entry_date=timezone.localdate() + timedelta(days=1),
        )

    assert exc.value.code == "entry_date_in_future"


def test_try_entry_drops_exchange_rate(manager: User) -> None:
    entry = manual(
        manager, CustomerFactory.create(), Kind.COLLECTION, method="CASH", exchange_rate=D("2")
    )

    assert entry.exchange_rate is None


def _received_return(shipper: User, shipment: Shipment) -> CustomerReturn:
    pick = shipment.lines.get().picks.get()
    document = returns.create_return(
        shipper,
        {
            "customer": shipment.sales_order.customer,
            "shipment": shipment,
            "return_date": timezone.localdate(),
            "reason": "Hasarlı koli",
            "quarantine_location": quarantine_location(),
        },
        [{"product": pick.lot.material, "lot": pick.lot, "quantity": D("2"), "unit": unit("ADET")}],
    )
    return returns.receive_return(shipper, document)


def test_return_credit_is_linked_to_received_return(
    shipper: User, picker: User, manager: User
) -> None:
    shipment = dispatched_shipment(shipper, picker, [(product(), "10", "ADET", "50", "TRY")])
    document = _received_return(shipper, shipment)

    entry = manual(
        manager,
        shipment.sales_order.customer,
        Kind.RETURN_CREDIT,
        "120",
        customer_return=document,
    )

    assert (entry.credit, entry.customer_return) == (D("120.00"), document)
    assert entry.description == f"İade {document.number}"


def test_return_credit_rejects_other_customer_and_draft(
    shipper: User, picker: User, manager: User
) -> None:
    shipment = dispatched_shipment(shipper, picker, [(product(), "10", "ADET", "50", "TRY")])
    document = _received_return(shipper, shipment)

    with pytest.raises(BusinessRuleError) as other:
        manual(manager, CustomerFactory.create(), Kind.RETURN_CREDIT, customer_return=document)
    CustomerReturn.objects.filter(pk=document.pk).update(status=CustomerReturn.Status.DRAFT)
    document.refresh_from_db()
    with pytest.raises(BusinessRuleError) as draft:
        manual(manager, shipment.sales_order.customer, Kind.RETURN_CREDIT, customer_return=document)

    assert (other.value.code, draft.value.code) == ("return_other_customer", "return_not_received")


# --- iptal -----------------------------------------------------------------------------------


def test_reverse_entry_writes_opposite_entry(manager: User) -> None:
    customer = CustomerFactory.create()
    entry = manual(manager, customer, Kind.COLLECTION, "75", method="CASH", currency="USD")

    reversal = services.reverse_entry(manager, entry, "Yanlış cari")

    assert reversal.kind == Kind.REVERSAL
    assert reversal.reversal_of == entry
    assert (reversal.debit, reversal.credit, reversal.currency) == (D("75.00"), D("0"), "USD")
    assert reversal.entry_date == timezone.localdate()
    assert reversal.description == f"İptal: {entry.number} (Yanlış cari)"
    log = AuditLog.objects.get(object_id=str(reversal.pk), action=AuditLog.Action.CREATE)
    assert log.note == f"{entry.number} iptal edildi: Yanlış cari"


def test_reverse_rules(manager: User, shipper: User, picker: User) -> None:
    entry = manual(manager, CustomerFactory.create(), Kind.COLLECTION, method="CASH")
    shipment = dispatched_shipment(shipper, picker, [(product(), "1", "ADET", "9", "TRY")])
    [sale] = services.sync_shipment(shipper, shipment)

    codes = []
    for target, reason in ((entry, " "), (sale, "Hata")):
        with pytest.raises(BusinessRuleError) as exc:
            services.reverse_entry(manager, target, reason)
        codes.append(exc.value.code)
    reversal = services.reverse_entry(manager, entry, "Hata")
    for target in (entry, reversal):
        with pytest.raises(BusinessRuleError) as exc:
            services.reverse_entry(manager, target, "Yine")
        codes.append(exc.value.code)

    assert codes == [
        "reversal_reason_required",
        "auto_entry_not_reversible",
        "already_reversed",
        "cannot_reverse_reversal",
    ]


def test_entries_cannot_be_changed_or_deleted(manager: User) -> None:
    entry = manual(manager, CustomerFactory.create(), Kind.COLLECTION, method="CASH")

    entry.description = "Değişti"
    with pytest.raises(TypeError):
        entry.save()
    with pytest.raises(TypeError):
        entry.delete()


# --- devir sıfırlama (DECISIONS 2026-11-20) ----------------------------------------------------


def _supplier_balance(supplier: Any, currency: str, **filters: Any) -> Decimal:
    rows = entries(supplier=supplier, currency=currency, **filters)
    return sum((e.debit - e.credit for e in rows), D(0))


def test_close_supplier_balances_zeroes_each_currency(buyer: User, manager: User) -> None:
    today = timezone.localdate()
    as_of = today - timedelta(days=1)
    owed, advance = SupplierFactory.create(), SupplierFactory.create()
    posted_receipt(
        buyer,
        [(raw_material(), "100", "12.5", "TRY", None), (raw_material(), "10", "2", "USD", "34")],
        supplier=owed,
        receipt_date=today - timedelta(days=3),
    )
    manual(manager, advance, Kind.PAYMENT, "300", method="TRANSFER", entry_date=as_of)
    manual(manager, owed, Kind.PAYMENT, "50", method="CASH")  # kapanıştan sonra: kalır
    customer = CustomerFactory.create()
    manual(manager, customer, Kind.DEBIT_NOTE, "70", description="Fark")
    services.sync_all()

    written = services.close_supplier_balances(manager, as_of=as_of, description="Devir")

    assert {(e.supplier_id, e.currency, e.debit, e.credit) for e in written} == {
        (owed.pk, "TRY", D("1500.00"), D("0")),
        (owed.pk, "USD", D("24.00"), D("0")),
        (advance.pk, "TRY", D("0"), D("300.00")),
    }
    assert len(written) == 3
    assert {(e.kind, e.entry_date, e.description, e.created_by) for e in written} == {
        (Kind.OPENING, as_of, "Devir", manager)
    }
    assert _supplier_balance(owed, "TRY", entry_date__lte=as_of) == 0
    assert _supplier_balance(owed, "USD") == 0
    assert _supplier_balance(advance, "TRY") == 0
    assert _supplier_balance(owed, "TRY") == D("50.00")  # kapanış sonrası ödeme
    assert entries(customer=customer)[0].debit == D("70.00")  # müşteriye dokunulmaz
    assert services.close_supplier_balances(manager, as_of=as_of) == []  # tekrar: yazmaz
    assert_ledger_invariants(all_documents=True)


def test_close_supplier_balances_rejects_future_date(buyer: User, manager: User) -> None:
    posted_receipt(buyer, [(raw_material(), "1", "9", "TRY", None)])
    services.sync_all()

    with pytest.raises(BusinessRuleError) as error:
        services.close_supplier_balances(manager, as_of=timezone.localdate() + timedelta(days=1))

    assert error.value.code == "entry_date_in_future"
    assert LedgerEntry.objects.filter(kind=Kind.OPENING).count() == 0


def test_close_supplier_balances_command_is_dry_run_by_default(buyer: User, manager: User) -> None:
    as_of = timezone.localdate() - timedelta(days=1)
    posted_receipt(buyer, [(raw_material(), "1", "9", "TRY", None)], receipt_date=as_of)
    services.sync_all()
    args = ["close_supplier_balances", "--user", manager.username, "--as-of", as_of.isoformat()]

    out = StringIO()
    call_command(*args, stdout=out)
    assert "Kuru çalıştırma: 1 kayıt" in out.getvalue()
    assert LedgerEntry.objects.filter(kind=Kind.OPENING).count() == 0

    call_command(*args, "--apply", stdout=out)
    assert "1 kayıt yazıldı" in out.getvalue()
    closing = LedgerEntry.objects.get(kind=Kind.OPENING)
    assert (closing.debit, closing.created_by) == (D("10.80"), manager)
