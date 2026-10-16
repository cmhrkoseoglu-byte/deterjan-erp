"""Satın alma okuma sorguları: teslim alınan / bekleyen miktarlar, talep önerisi (basit MRP),
açık sipariş satırları ve tedarikçi performansı.

Raporlama (Adım 4.3) bu modülün verisini yalnızca buradaki fonksiyonlarla okur:
`open_order_lines`, `supplier_performance`, `purchase_suggestions`, `order_totals`.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db.models import (
    DecimalField,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.filling.models import FillingConsumption, FillingOrder, FillingRequirement
from apps.inventory.models import GoodsReceipt, Lot, StockBalance, StockReservation
from apps.masterdata.models import Material, Supplier
from apps.production.models import BatchConsumption, ProductionOrder, ProductionRequirement
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest

ZERO = Decimal(0)
_Q4 = Decimal("0.0001")
_ZERO_VALUE = Value(ZERO, output_field=DecimalField(max_digits=18, decimal_places=4))

POStatus = PurchaseOrder.Status
# Teslimat beklenen (kalan miktarı açık) sipariş durumları.
RECEIVABLE_STATUSES = (POStatus.APPROVED, POStatus.SENT, POStatus.PARTIALLY_RECEIVED)
# Talep önerisinde "açık sipariş" sayılan durumlar: taslak ve onaydaki sipariş de yolda sayılır,
# yoksa sabah kontrolü aynı ihtiyaç için ikinci talep açar.
OPEN_ORDER_STATUSES = (POStatus.DRAFT, POStatus.PENDING_APPROVAL, *RECEIVABLE_STATUSES)
PURCHASABLE_TYPES = (Material.Type.RAW, Material.Type.PACKAGING)
# İhtiyacı henüz tüketilmemiş emir durumları (ihtiyaç satırları onayda oluşur).
OPEN_PRODUCTION_STATUSES = (
    ProductionOrder.Status.APPROVED,
    ProductionOrder.Status.MATERIAL_PREP,
    ProductionOrder.Status.MATERIAL_READY,
    ProductionOrder.Status.IN_PRODUCTION,
)
OPEN_FILLING_STATUSES = (
    FillingOrder.Status.APPROVED,
    FillingOrder.Status.MATERIAL_PREP,
    FillingOrder.Status.MATERIAL_READY,
    FillingOrder.Status.IN_PROGRESS,
)
# Serbest stok: kullanılabilir (RELEASED) ve giriş kontrolündeki (QUARANTINE, yeni gelen) lotlar;
# reddedilmiş / bloke lot sayılmaz (minimum stok kontrolüyle aynı kural).
STOCK_STATUSES = (Lot.Status.RELEASED, Lot.Status.QUARANTINE)


def q4(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


# --- teslim alınan miktar --------------------------------------------------------------------


def _received_subquery(*, receipt_date_lte: date | None = None) -> Coalesce:
    """Sipariş satırına bağlı, kaydedilmiş mal kabul satırlarının temel birim toplamı."""
    from apps.purchasing.models import ReceiptLineLink

    links = ReceiptLineLink.objects.filter(
        order_line=OuterRef("pk"),
        receipt_line__receipt__status=GoodsReceipt.Status.POSTED,
    )
    if receipt_date_lte is not None:
        links = links.filter(receipt_line__receipt__receipt_date__lte=receipt_date_lte)
    total = (
        links.values("order_line")
        .annotate(total=Sum("receipt_line__base_quantity"))
        .values("total")
    )
    return Coalesce(Subquery(total), _ZERO_VALUE)


def _draft_receipt_subquery() -> Coalesce:
    """Sipariş satırına bağlı taslak mal kabullerdeki miktar (satır biriminde; siparişten mal
    kabulde birim sipariş satırının birimidir)."""
    from apps.purchasing.models import ReceiptLineLink

    total = (
        ReceiptLineLink.objects.filter(
            order_line=OuterRef("pk"),
            receipt_line__receipt__status=GoodsReceipt.Status.DRAFT,
        )
        .values("order_line")
        .annotate(total=Sum("receipt_line__quantity"))
        .values("total")
    )
    return Coalesce(Subquery(total), _ZERO_VALUE)


def order_lines() -> QuerySet[PurchaseOrderLine]:
    """Sipariş satırları; açıklamalar (temel birimde): `received_quantity` (kaydedilmiş mal
    kabuller), `draft_receipt_quantity` (taslak mal kabullerdeki, satır biriminde),
    `pending_quantity` (sipariş − teslim alınan, en az 0; kapanmış/iptal siparişte 0)."""
    return (
        PurchaseOrderLine.objects.select_related("order__supplier", "material__base_unit", "unit")
        .annotate(received_quantity=_received_subquery())
        .annotate(draft_receipt_quantity=_draft_receipt_subquery())
    )


def pending_quantity(line: PurchaseOrderLine) -> Decimal:
    """Satırın bekleyen miktarı (temel birimde). `order_lines()` açıklamalarını kullanır."""
    if line.order.status not in RECEIVABLE_STATUSES:
        return ZERO
    received: Decimal = getattr(line, "received_quantity", None) or received_quantity(line)
    return max(ZERO, line.base_quantity - received)


def received_quantity(line: PurchaseOrderLine) -> Decimal:
    """Satıra bağlı kaydedilmiş mal kabul miktarı (temel birimde)."""
    total = line.receipt_links.filter(
        receipt_line__receipt__status=GoodsReceipt.Status.POSTED
    ).aggregate(total=Sum("receipt_line__base_quantity"))["total"]
    return total or ZERO


def open_order_lines(
    *, supplier: Supplier | None = None, material: Material | None = None
) -> list[PurchaseOrderLine]:
    """Teslimat bekleyen sipariş satırları (onaylı, gönderilmiş, kısmen teslim alınmış), teslim
    tarihine göre. Her satırda `received_quantity` ve `pending_quantity` (temel birim) dolu;
    "Beklenen teslimatlar" listesi ve raporlama bunu kullanır."""
    queryset = order_lines().filter(order__status__in=RECEIVABLE_STATUSES)
    if supplier is not None:
        queryset = queryset.filter(order__supplier=supplier)
    if material is not None:
        queryset = queryset.filter(material=material)
    lines = []
    for line in queryset.order_by("expected_date", "order__number", "line_no"):
        line.pending_quantity = pending_quantity(line)  # type: ignore[attr-defined]
        if line.pending_quantity > 0:  # type: ignore[attr-defined]
            lines.append(line)
    return lines


# --- tutarlar --------------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderTotals:
    total: Decimal  # sipariş para biriminde
    total_try: Decimal  # TL karşılığı (siparişteki kurla)


def order_totals(order: PurchaseOrder) -> OrderTotals:
    """Sipariş tutarı (satır miktarı × birim fiyat) ve TL karşılığı, 2 ondalık."""
    total = sum(
        (line.quantity * line.unit_price for line in order.lines.all()),
        ZERO,
    )
    cents = Decimal("0.01")
    return OrderTotals(
        total=total.quantize(cents, rounding=ROUND_HALF_UP),
        total_try=(total * order.exchange_rate).quantize(cents, rounding=ROUND_HALF_UP),
    )


# --- talep önerisi (basit MRP) ---------------------------------------------------------------


@dataclass
class Suggestion:
    """Malzeme başına öneri (temel birimde).

    `suggested = demand + min_stock − free_stock − open_orders − open_requests` (> 0 ise)."""

    material: Material
    demand: Decimal = ZERO
    min_stock: Decimal = ZERO
    free_stock: Decimal = ZERO
    open_orders: Decimal = ZERO
    open_requests: Decimal = ZERO
    need_date: date | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)

    @property
    def suggested(self) -> Decimal:
        value = (
            self.demand + self.min_stock - self.free_stock - self.open_orders - self.open_requests
        )
        return q4(max(ZERO, value))


def _production_demand() -> list[tuple[int, Decimal, date, str]]:
    consumed = (
        BatchConsumption.objects.filter(requirement=OuterRef("pk"))
        .values("requirement")
        .annotate(total=Sum("actual_quantity"))
        .values("total")
    )
    rows = (
        ProductionRequirement.objects.filter(
            order__status__in=OPEN_PRODUCTION_STATUSES,
            is_water=False,
            lot__isnull=True,
            material__material_type__in=PURCHASABLE_TYPES,
        )
        .annotate(consumed=Coalesce(Subquery(consumed), _ZERO_VALUE))
        .annotate(remaining=F("required_quantity") - F("consumed"))
        .filter(remaining__gt=0)
        .values_list("material_id", "remaining", "order__planned_date", "order__number")
    )
    return list(rows)


def _filling_demand() -> list[tuple[int, Decimal, date, str]]:
    consumed = (
        FillingConsumption.objects.filter(
            run__order=OuterRef("order"),
            spec_line=OuterRef("spec_line"),
            kind="PACKAGING",
        )
        .values("spec_line")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    rows = (
        FillingRequirement.objects.filter(
            order__status__in=OPEN_FILLING_STATUSES,
            material__material_type__in=PURCHASABLE_TYPES,
        )
        .annotate(consumed=Coalesce(Subquery(consumed), _ZERO_VALUE))
        .annotate(remaining=F("required_quantity") - F("consumed"))
        .filter(remaining__gt=0)
        .values_list("material_id", "remaining", "order__planned_date", "order__number")
    )
    return list(rows)


def _free_stock(today: date) -> dict[int, Decimal]:
    reserved = (
        StockReservation.objects.filter(
            lot=OuterRef("lot"),
            location=OuterRef("location"),
            status=StockReservation.Status.ACTIVE,
        )
        .values("lot")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    rows = (
        StockBalance.objects.filter(
            quantity__gt=0,
            lot__status__in=STOCK_STATUSES,
            material__material_type__in=PURCHASABLE_TYPES,
        )
        .filter(Q(lot__expiry_date__isnull=True) | Q(lot__expiry_date__gte=today))
        .annotate(reserved=Coalesce(Subquery(reserved), _ZERO_VALUE))
        .values_list("material_id", "quantity", "reserved")
    )
    free: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for material_id, quantity, reserved_qty in rows:
        free[material_id] += max(ZERO, quantity - reserved_qty)
    return free


def _open_order_quantities() -> dict[int, Decimal]:
    totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    lines = order_lines().filter(order__status__in=OPEN_ORDER_STATUSES)
    for line in lines:
        totals[line.material_id] += max(ZERO, line.base_quantity - line.received_quantity)  # type: ignore[attr-defined]
    return totals


def _open_request_quantities() -> dict[int, Decimal]:
    rows = (
        PurchaseRequest.objects.filter(status=PurchaseRequest.Status.OPEN)
        .values("material")
        .annotate(total=Sum("quantity"))
        .values_list("material", "total")
    )
    return {material_id: total for material_id, total in rows}


def purchase_suggestions(*, today: date | None = None) -> list[Suggestion]:
    """Talep önerisi: açık üretim / dolum emirlerinin henüz tüketilmemiş ihtiyaçları + minimum
    stok − serbest stok − açık sipariş kalanı − açık talepler. Yalnızca hammadde ve ambalaj;
    şebeke suyu (D-1) ve yeniden işleme lotu satırları sayılmaz. Öneri sıfırsa listede yoktur.

    İhtiyaç tarihi: ihtiyacı serbest stok ve açık siparişle karşılanamayan ilk emrin planlanan
    tarihi; yalnızca minimum stok açığıysa bugün."""
    today = today or timezone.localdate()
    by_material: dict[int, Suggestion] = {}
    demand_rows: dict[int, list[tuple[Decimal, date, str]]] = defaultdict(list)
    for material_id, remaining, planned, number in _production_demand() + _filling_demand():
        demand_rows[material_id].append((remaining, planned, number))
    materials = Material.objects.filter(is_active=True, material_type__in=PURCHASABLE_TYPES).filter(
        Q(min_stock__isnull=False) | Q(pk__in=list(demand_rows))
    )
    free = _free_stock(today)
    on_order = _open_order_quantities()
    requested = _open_request_quantities()
    for material in materials.select_related("base_unit").order_by("code"):
        suggestion = Suggestion(
            material=material,
            min_stock=material.min_stock or ZERO,
            free_stock=q4(free.get(material.pk, ZERO)),
            open_orders=q4(on_order.get(material.pk, ZERO)),
            open_requests=q4(requested.get(material.pk, ZERO)),
        )
        covered = suggestion.free_stock + suggestion.open_orders + suggestion.open_requests
        running = ZERO
        for remaining, planned, number in sorted(demand_rows.get(material.pk, []), key=_by_date):
            suggestion.demand += remaining
            suggestion.sources.append(
                {"order_number": number, "planned_date": planned, "quantity": q4(remaining)}
            )
            running += remaining
            if suggestion.need_date is None and running > covered:
                suggestion.need_date = max(planned, today)
        suggestion.demand = q4(suggestion.demand)
        if suggestion.suggested <= 0:
            continue
        if suggestion.need_date is None:
            suggestion.need_date = today
        by_material[material.pk] = suggestion
    return list(by_material.values())


def _by_date(row: tuple[Decimal, date, str]) -> tuple[date, str]:
    return row[1], row[2]


# --- tedarikçi performansı -------------------------------------------------------------------


@dataclass
class SupplierPerformance:
    supplier: Supplier
    due_lines: int = 0
    on_time_lines: int = 0
    received_lots: int = 0
    rejected_lots: int = 0

    @staticmethod
    def _rate(part: int, whole: int) -> Decimal | None:
        if whole == 0:
            return None
        return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), ROUND_HALF_UP)

    @property
    def on_time_rate(self) -> Decimal | None:
        """Zamanında teslim oranı (%); vadesi gelmiş satır yoksa boş."""
        return self._rate(self.on_time_lines, self.due_lines)

    @property
    def reject_rate(self) -> Decimal | None:
        """QC red oranı (%): reddedilen lot / kabul edilen lot; lot yoksa boş."""
        return self._rate(self.rejected_lots, self.received_lots)


def supplier_performance(
    date_from: date,
    date_to: date,
    *,
    supplier: Supplier | None = None,
    today: date | None = None,
) -> list[SupplierPerformance]:
    """Tarih aralığında tedarikçi performansı.

    - Zamanında teslim: teslim tarihi aralıkta ve bugünden önce (ya da tamamı gelmiş) olan,
      iptal edilmemiş sipariş satırlarından, teslim tarihine kadar kaydedilen mal kabullerle
      tamamı gelenlerin oranı. "Kalanı kapat"la kapanan siparişte hedef, teslim alınan miktardır.
    - QC red oranı: aralıkta mal kabulle gelen tedarikçi lotlarından reddedilenlerin oranı
      (Faz 2 kalite kararları lot durumunu `REJECTED` yapar).
    """
    today = today or timezone.localdate()
    lines = (
        order_lines()
        .exclude(order__status__in=(POStatus.CANCELLED, POStatus.DRAFT, POStatus.PENDING_APPROVAL))
        .filter(expected_date__gte=date_from, expected_date__lte=date_to)
        .annotate(
            received_on_time=_received_subquery_by_expected_date(),
        )
    )
    if supplier is not None:
        lines = lines.filter(order__supplier=supplier)
    stats: dict[int, SupplierPerformance] = {}

    def entry(s: Supplier) -> SupplierPerformance:
        if s.pk not in stats:
            stats[s.pk] = SupplierPerformance(supplier=s)
        return stats[s.pk]

    for line in lines:
        received: Decimal = line.received_quantity  # type: ignore[attr-defined]
        target = line.base_quantity
        if line.order.status == POStatus.RECEIVED:
            target = min(target, received)
        fully_received = received >= target
        if line.expected_date >= today and not fully_received:
            continue  # vadesi gelmemiş, henüz değerlendirilmez
        row = entry(line.order.supplier)
        row.due_lines += 1
        if target > 0 and line.received_on_time >= target:  # type: ignore[attr-defined]
            row.on_time_lines += 1
    lots = Lot.objects.filter(
        source=Lot.Source.PURCHASE,
        supplier__isnull=False,
        receipt_line__receipt__receipt_date__gte=date_from,
        receipt_line__receipt__receipt_date__lte=date_to,
    ).select_related("supplier")
    if supplier is not None:
        lots = lots.filter(supplier=supplier)
    for lot in lots:
        assert lot.supplier is not None
        row = entry(lot.supplier)
        row.received_lots += 1
        if lot.status == Lot.Status.REJECTED:
            row.rejected_lots += 1
    return sorted(stats.values(), key=lambda r: (r.supplier.name, r.supplier.pk))


def _received_subquery_by_expected_date() -> Coalesce:
    from apps.purchasing.models import ReceiptLineLink

    total = (
        ReceiptLineLink.objects.filter(
            order_line=OuterRef("pk"),
            receipt_line__receipt__status=GoodsReceipt.Status.POSTED,
            receipt_line__receipt__receipt_date__lte=OuterRef("expected_date"),
        )
        .values("order_line")
        .annotate(total=Sum("receipt_line__base_quantity"))
        .values("total")
    )
    return Coalesce(Subquery(total), _ZERO_VALUE)
