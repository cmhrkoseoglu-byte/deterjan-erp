"""Cari hesaplar: okuma sorguları (docs/plan/cari-hesaplar.md §2.3).

Bakiye = borç − alacak (para birimi başına). Carinin "doğal yönü" müşteride borç (bize borçlu),
tedarikçide alacaktır (biz borçluyuz). Yaşlandırma doğal yöndeki kayıtları açık kalem sayar; ters
yöndeki kayıtlar (tahsilat, ödeme, alacak dekontu) en eski açık kalemden başlayarak kapatır (FIFO).
Birbirini götüren kayıt ve iptali yaşlandırmaya girmez. Vade = kayıt tarihi + carinin vade günü.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Exists, OuterRef, Q, QuerySet, Sum
from django.utils import timezone

from apps.inventory.models import GoodsReceipt, GoodsReceiptLine
from apps.ledger.amounts import ZERO, money, shipped_quantities, vat_of
from apps.ledger.models import LedgerEntry, Side
from apps.masterdata.models import Customer, Supplier
from apps.returns.models import CustomerReturn
from apps.sales.models import Shipment, ShipmentLine

Partner = Customer | Supplier
AGING_BUCKETS = ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus")


def partner_model(side: str) -> type[Customer] | type[Supplier]:
    return Customer if side == Side.CUSTOMER else Supplier


def find_partner(side: str, pk: int) -> Partner | None:
    if side == Side.CUSTOMER:
        return Customer.objects.filter(pk=pk).first()
    return Supplier.objects.filter(pk=pk).first()


def side_of(partner: Partner) -> str:
    return Side.CUSTOMER if isinstance(partner, Customer) else Side.SUPPLIER


def entries_of(partner: Partner) -> QuerySet[LedgerEntry]:
    return LedgerEntry.objects.filter(**{side_of(partner): partner})


def _natural_sign(side: str) -> int:
    """Müşteride borç, tedarikçide alacak açık kalemdir."""
    return 1 if side == Side.CUSTOMER else -1


def bucket_of(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "not_due"
    if days_overdue <= 30:
        return "d1_30"
    if days_overdue <= 60:
        return "d31_60"
    if days_overdue <= 90:
        return "d61_90"
    return "d90_plus"


@dataclass
class CurrencyBalance:
    currency: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    last_date: date | None = None
    aging: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(AGING_BUCKETS, ZERO))

    @property
    def balance(self) -> Decimal:
        return self.debit - self.credit

    @property
    def overdue(self) -> Decimal:
        return sum((self.aging[key] for key in AGING_BUCKETS[1:]), ZERO)


def _cancelled_pairs(entries: Iterable[LedgerEntry]) -> set[int]:
    """İptal edilmiş kayıtlar ve iptal kayıtları (yaşlandırmada birbirini götürür)."""
    ids: set[int] = set()
    for entry in entries:
        if entry.reversal_of_id is not None:
            ids.add(entry.pk)
            ids.add(entry.reversal_of_id)
    return ids


def _age(
    entries: list[LedgerEntry], side: str, term_days: int | None, today: date
) -> dict[str, Decimal]:
    """Açık kalemlerin vadesine göre dağılımı (tek para birimi). Doğal yönde bakiye yoksa boş."""
    sign = _natural_sign(side)
    cancelled = _cancelled_pairs(entries)
    open_items: list[list[Any]] = []  # [vade, kalan]
    settle = ZERO
    for entry in sorted(entries, key=lambda e: (e.entry_date, e.pk)):
        if entry.pk in cancelled:
            continue
        amount = (entry.debit - entry.credit) * sign
        if amount > 0:
            open_items.append([entry.entry_date + timedelta(days=term_days or 0), amount])
        else:
            settle += -amount
    aging = dict.fromkeys(AGING_BUCKETS, ZERO)
    for item in open_items:
        used = min(item[1], settle)
        item[1] -= used
        settle -= used
        if item[1] > 0:
            aging[bucket_of((today - item[0]).days)] += item[1]
    return aging


def balances_of(partner: Partner, *, today: date | None = None) -> list[CurrencyBalance]:
    """Carinin para birimi başına borç, alacak, bakiye, son hareket ve yaşlandırması."""
    today = today or timezone.localdate()
    side = side_of(partner)
    by_currency: dict[str, list[LedgerEntry]] = defaultdict(list)
    for entry in entries_of(partner).order_by("entry_date", "id"):
        by_currency[entry.currency].append(entry)
    result = []
    for currency in sorted(by_currency):
        entries = by_currency[currency]
        balance = CurrencyBalance(currency=currency)
        for entry in entries:
            balance.debit += entry.debit
            balance.credit += entry.credit
        balance.last_date = max(entry.entry_date for entry in entries)
        balance.aging = _age(entries, side, partner.payment_term_days, today)
        result.append(balance)
    return result


def partner_rows(
    side: str,
    *,
    search: str = "",
    with_balance: bool = False,
    overdue: bool = False,
    currency: str = "",
    include_inactive: bool = False,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Cari listesi: aktif cariler ve hareketi olan pasif cariler, bakiyeleri ve yaşlandırmayla.
    `with_balance`: bakiyesi sıfır olmayanlar; `overdue`: vadesi geçen tutarı olanlar."""
    model = partner_model(side)
    has_entries = Exists(LedgerEntry.objects.filter(**{side: OuterRef("pk")}))
    queryset = model.objects.annotate(has_entries=has_entries).order_by("name")
    if not include_inactive:
        queryset = queryset.filter(Q(is_active=True) | Q(has_entries=True))
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
    missing = missing_price_counts(side)
    rows = []
    for partner in queryset:
        balances = balances_of(partner, today=today) if partner.has_entries else []
        if currency:
            balances = [b for b in balances if b.currency == currency]
        if with_balance and not any(b.balance != 0 for b in balances):
            continue
        if overdue and not any(b.overdue > 0 for b in balances):
            continue
        rows.append({"partner": partner, "balances": balances, "missing": missing[partner.pk]})
    return rows


def totals(rows: Iterable[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    """Listenin para birimi başına toplamı: doğal yöndeki toplam (alacağımız / borcumuz), ters
    yöndeki toplam (avans) ve vadesi geçen."""
    sign = _natural_sign(side)
    sums: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"open": ZERO, "advance": ZERO, "overdue": ZERO}
    )
    for row in rows:
        for balance in row["balances"]:
            natural = balance.balance * sign
            bucket = sums[balance.currency]
            if natural > 0:
                bucket["open"] += natural
            else:
                bucket["advance"] += -natural
            bucket["overdue"] += balance.overdue
    return [{"currency": currency, **values} for currency, values in sorted(sums.items())]


# --- ekstre ----------------------------------------------------------------------------------


def statement(
    partner: Partner, date_from: date | None = None, date_to: date | None = None
) -> list[dict[str, Any]]:
    """Ekstre: para birimi başına devreden bakiye, satırlar (yürüyen bakiyeyle) ve dönem
    toplamları. Satırın vadesi doğal yöndeki kayıtta kayıt tarihi + vade günüdür."""
    side = side_of(partner)
    sign = _natural_sign(side)
    term = partner.payment_term_days or 0
    entries = entries_of(partner).select_related(
        "shipment", "goods_receipt", "customer_return", "reversal_of", "created_by"
    )
    reversed_ids = set(
        LedgerEntry.objects.filter(reversal_of__in=entries.values("pk")).values_list(
            "reversal_of_id", flat=True
        )
    )
    result = []
    currencies = sorted(set(entries.values_list("currency", flat=True)))
    for currency in currencies:
        in_currency = entries.filter(currency=currency)
        opening = ZERO
        if date_from is not None:
            before = in_currency.filter(entry_date__lt=date_from).aggregate(
                debit=Sum("debit"), credit=Sum("credit")
            )
            opening = (before["debit"] or ZERO) - (before["credit"] or ZERO)
        period = in_currency
        if date_from is not None:
            period = period.filter(entry_date__gte=date_from)
        if date_to is not None:
            period = period.filter(entry_date__lte=date_to)
        running = opening
        rows = []
        total_debit = total_credit = ZERO
        for entry in period.order_by("entry_date", "id"):
            running += entry.debit - entry.credit
            total_debit += entry.debit
            total_credit += entry.credit
            natural = (entry.debit - entry.credit) * sign > 0
            rows.append(
                {
                    "entry": entry,
                    "balance": running,
                    "due_date": entry.entry_date + timedelta(days=term) if natural else None,
                    "is_reversed": entry.pk in reversed_ids,
                }
            )
        result.append(
            {
                "currency": currency,
                "opening": opening,
                "rows": rows,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "closing": running,
            }
        )
    return result


def returns_of(
    customer: Customer, date_from: date | None = None, date_to: date | None = None
) -> QuerySet[CustomerReturn]:
    """Ekstrenin bilgi satırları: teslim alınmış iadeler, dekontu girilmiş mi bilgisiyle."""
    queryset = CustomerReturn.objects.filter(
        customer=customer,
        status__in=(CustomerReturn.Status.RECEIVED, CustomerReturn.Status.CLOSED),
    )
    if date_from is not None:
        queryset = queryset.filter(return_date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(return_date__lte=date_to)
    credited = LedgerEntry.objects.filter(
        customer_return=OuterRef("pk"), kind=LedgerEntry.Kind.RETURN_CREDIT
    ).exclude(Exists(LedgerEntry.objects.filter(reversal_of=OuterRef("pk"))))
    return (
        queryset.select_related("shipment")
        .annotate(has_credit=Exists(credited))
        .order_by("return_date", "id")
    )


# --- fiyatı eksik belgeler -------------------------------------------------------------------


def _unpriced_shipment_lines() -> QuerySet[ShipmentLine]:
    return (
        ShipmentLine.objects.filter(
            shipment__status=Shipment.Status.DISPATCHED,
            order_line__unit_price__isnull=True,
            ledger_price__isnull=True,
            picks__movement__isnull=False,
        )
        .distinct()
        .select_related(
            "shipment__sales_order__customer", "order_line__product", "order_line__unit"
        )
        .order_by("shipment__dispatched_at", "id")
    )


def _unpriced_receipt_lines() -> QuerySet[GoodsReceiptLine]:
    return (
        GoodsReceiptLine.objects.filter(
            receipt__status=GoodsReceipt.Status.POSTED, unit_price__isnull=True
        )
        .select_related("receipt__supplier", "material", "unit")
        .order_by("receipt__receipt_date", "id")
    )


def missing_price_counts(side: str) -> dict[int, int]:
    """Cari başına tutarı eksik belge sayısı."""
    counts: dict[int, int] = defaultdict(int)
    pairs: set[tuple[int, int]]
    if side == Side.CUSTOMER:
        pairs = set(
            _unpriced_shipment_lines().values_list(
                "shipment__sales_order__customer_id", "shipment_id"
            )
        )
    else:
        pairs = set(_unpriced_receipt_lines().values_list("receipt__supplier_id", "receipt_id"))
    for partner_id, _ in pairs:
        counts[partner_id] += 1
    return counts


def missing_prices(side: str, partner: Partner | None = None) -> list[dict[str, Any]]:
    """Fiyatı olmadığı için cariye yazılmamış satırlar (belge, cari, malzeme, miktar)."""
    rows: list[dict[str, Any]] = []
    if side == Side.CUSTOMER:
        lines = _unpriced_shipment_lines()
        if partner is not None:
            lines = lines.filter(shipment__sales_order__customer_id=partner.pk)
        shipped: dict[int, dict[int, Decimal]] = {}
        for line in lines:
            shipment = line.shipment
            if shipment.pk not in shipped:
                shipped[shipment.pk] = shipped_quantities(shipment)
            order_line = line.order_line
            base = shipped[shipment.pk].get(line.pk, ZERO)
            rows.append(
                {
                    "kind": "shipment",
                    "line_id": line.pk,
                    "document_id": shipment.pk,
                    "document_number": shipment.number,
                    "document_date": timezone.localtime(shipment.dispatched_at).date()
                    if shipment.dispatched_at
                    else None,
                    "partner": shipment.sales_order.customer,
                    "material_code": order_line.product.code,
                    "material_name": order_line.product.name,
                    "quantity": base * order_line.quantity / order_line.base_quantity,
                    "unit_code": order_line.unit.code,
                }
            )
        return rows
    receipt_lines = _unpriced_receipt_lines()
    if partner is not None:
        receipt_lines = receipt_lines.filter(receipt__supplier_id=partner.pk)
    for receipt_line in receipt_lines:
        rows.append(
            {
                "kind": "goods_receipt",
                "line_id": receipt_line.pk,
                "document_id": receipt_line.receipt_id,
                "document_number": receipt_line.receipt.number,
                "document_date": receipt_line.receipt.receipt_date,
                "partner": receipt_line.receipt.supplier,
                "material_code": receipt_line.material.code,
                "material_name": receipt_line.material.name,
                "quantity": receipt_line.quantity,
                "unit_code": receipt_line.unit.code,
            }
        )
    return rows


def return_credit_suggestion(customer_return: CustomerReturn) -> list[dict[str, Any]]:
    """İade dekontu için önerilen tutar (para birimi başına, KDV dahil): iade miktarı × iadenin
    sevkiyatındaki aynı mamulün sipariş fiyatı (yoksa cari için girilen fiyat). Sevkiyatı ya da
    fiyatı bilinmeyen satır öneriye girmez."""
    shipment = customer_return.shipment
    if shipment is None:
        return []
    exempt = customer_return.customer.vat_exempt
    lines = ShipmentLine.objects.filter(shipment=shipment).select_related(
        "order_line__product", "ledger_price"
    )
    by_product = {line.order_line.product_id: line for line in lines}
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for item in customer_return.lines.select_related("product"):
        line = by_product.get(item.product_id)
        if line is None or item.base_quantity is None:
            continue
        order_line = line.order_line
        price, currency = order_line.unit_price, order_line.currency
        if price is None:
            override = getattr(line, "ledger_price", None)
            if override is None:
                continue
            price, currency = override.unit_price, override.currency
        quantity = item.base_quantity * order_line.quantity / order_line.base_quantity
        net = money(quantity * price)
        sums[currency] += net + vat_of(net, order_line.product, exempt)
    return [{"currency": c, "amount": amount} for c, amount in sorted(sums.items())]
