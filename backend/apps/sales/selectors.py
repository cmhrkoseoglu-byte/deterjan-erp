"""Satış okuma sorguları: satır miktarları (rezerve, sevk, eksik), sipariş toplamı, müşteri
sipariş geçmişi, SKT'si yaklaşan rezerve lotlar."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    Case,
    DecimalField,
    F,
    OuterRef,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from apps.inventory.models import StockReservation
from apps.inventory.services import format_quantity
from apps.masterdata.models import Customer
from apps.sales.models import SalesOrder, SalesOrderLine

EXPIRY_WARNING_DAYS = 30
MONEY_STEP = Decimal("0.01")
_DECIMAL = DecimalField(max_digits=18, decimal_places=4)
ZERO = Value(Decimal(0), output_field=_DECIMAL)


def _reservation_sum(status: str) -> Coalesce:
    total = (
        StockReservation.objects.filter(
            source_content_type=ContentType.objects.get_for_model(SalesOrderLine),
            source_object_id=OuterRef("pk"),
            status=status,
        )
        .values("source_object_id")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return Coalesce(Subquery(total, output_field=_DECIMAL), ZERO)


def order_lines(order: SalesOrder) -> QuerySet[SalesOrderLine]:
    """Siparişin satırları; açıklamalar (temel birimde): `reserved_quantity` (aktif rezervasyon),
    `shipped_quantity` (kullanılmış rezervasyon), `shortage_quantity` (kalan eksik, en az 0),
    `line_total` (fiyat girilmişse miktar × birim fiyat)."""
    return lines_with_quantities().filter(order=order).order_by("line_no")


def lines_with_quantities() -> QuerySet[SalesOrderLine]:
    return (
        SalesOrderLine.objects.select_related("product__base_unit", "unit")
        .annotate(
            reserved_quantity=_reservation_sum(StockReservation.Status.ACTIVE),
            shipped_quantity=_reservation_sum(StockReservation.Status.CONSUMED),
        )
        .annotate(
            shortage_quantity=Greatest(
                F("base_quantity") - F("shipped_quantity") - F("reserved_quantity"), ZERO
            ),
            line_total=Case(
                When(unit_price__isnull=False, then=F("quantity") * F("unit_price")),
                default=None,
                output_field=_DECIMAL,
            ),
        )
    )


def order_totals(order: SalesOrder) -> list[dict[str, str]]:
    """Fiyatlı satırların para birimi bazında toplamı (Karar D-9), 2 ondalık."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for line in order.lines.filter(unit_price__isnull=False):
        assert line.unit_price is not None
        totals[line.currency] += line.quantity * line.unit_price
    return [
        {"currency": currency, "amount": str(amount.quantize(MONEY_STEP, ROUND_HALF_UP))}
        for currency, amount in sorted(totals.items())
    ]


def order_reservations(order: SalesOrder) -> QuerySet[StockReservation]:
    """Siparişin bütün rezervasyonları (satır, lot ve lokasyonla), satır ve oluşturma sırasıyla."""
    return (
        StockReservation.objects.filter(sales_order_line__order=order)
        .select_related("lot", "location", "material__base_unit", "created_by")
        .annotate(line_no=F("sales_order_line__line_no"), line_id=F("sales_order_line__id"))
        .order_by("line_no", "created_at", "id")
    )


def orders_with_shortage() -> QuerySet[SalesOrder]:
    """Eksiği (rezerve edilmemiş, sevk edilmemiş miktarı) olan açık siparişler."""
    lines = lines_with_quantities().filter(
        order=OuterRef("pk"),
        shortage_quantity__gt=0,  # type: ignore[misc]
    )
    return SalesOrder.objects.filter(
        status__in=(SalesOrder.Status.CONFIRMED, SalesOrder.Status.PARTIALLY_SHIPPED)
    ).filter(pk__in=Subquery(lines.values("order_id")))


def customer_orders(customer: Customer) -> QuerySet[SalesOrder]:
    """Müşterinin siparişleri (yeniden eskiye)."""
    return SalesOrder.objects.filter(customer=customer).order_by("-order_date", "-id")


def expiring_reserved_lots(
    days: int = EXPIRY_WARNING_DAYS, *, today: date | None = None
) -> list[dict[str, Any]]:
    """Aktif rezervasyonu olan ve SKT'si `days` gün içinde dolacak lotlar; olay payload'ı için
    sözlükler (lot ve rezerve edildiği sipariş numaralarıyla)."""
    today = today or timezone.localdate()
    reservations = (
        StockReservation.objects.filter(
            status=StockReservation.Status.ACTIVE,
            sales_order_line__isnull=False,
            lot__expiry_date__isnull=False,
            lot__expiry_date__lte=today + timedelta(days=days),
        )
        .select_related("lot__material", "material__base_unit")
        .order_by("lot__expiry_date", "lot__lot_no")
    )
    lots: dict[int, dict[str, Any]] = {}
    quantities: dict[int, Decimal] = defaultdict(Decimal)
    for reservation in reservations:
        lot = reservation.lot
        entry = lots.setdefault(
            lot.pk,
            {
                "model": "inventory.lot",
                "id": lot.pk,
                "lot_no": lot.lot_no,
                "material_code": lot.material.code,
                "material_name": lot.material.name,
                "expiry_date": lot.expiry_date.strftime("%d.%m.%Y") if lot.expiry_date else "",
                "unit": reservation.material.base_unit.code,
                "orders": [],
            },
        )
        if reservation.document_number and reservation.document_number not in entry["orders"]:
            entry["orders"].append(reservation.document_number)
        quantities[lot.pk] += reservation.quantity
    for lot_id, entry in lots.items():
        entry["reserved_quantity"] = format_quantity(quantities[lot_id])
    return list(lots.values())
