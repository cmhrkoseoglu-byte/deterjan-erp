"""Satış okuma sorguları: satır miktarları (rezerve, sevk, eksik), sipariş toplamı, müşteri
sipariş geçmişi, SKT'si yaklaşan rezerve lotlar; sevkiyat satırları, toplama önerisi, irsaliye
verisi ve müşteriye sevk edilen lotlar (Adım 3.2)."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
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

from apps.core.audit import mask_identifier
from apps.inventory import selectors as inventory_selectors
from apps.inventory.models import StockReservation
from apps.inventory.services import format_quantity
from apps.masterdata import services as masterdata
from apps.masterdata.models import Customer, Material, UnitOfMeasure
from apps.sales.models import SalesOrder, SalesOrderLine, Shipment, ShipmentLine, ShipmentPick

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


OPEN_SHIPMENT_STATUSES = (
    Shipment.Status.PLANNED,
    Shipment.Status.PICKING,
    Shipment.Status.LOADED,
)


def _planned_sum() -> Coalesce:
    total = (
        ShipmentLine.objects.filter(
            order_line=OuterRef("pk"), shipment__status__in=OPEN_SHIPMENT_STATUSES
        )
        .values("order_line")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return Coalesce(Subquery(total, output_field=_DECIMAL), ZERO)


def lines_with_quantities() -> QuerySet[SalesOrderLine]:
    """Satırlar; `planned_quantity` açık sevkiyatlarda planlanan, `plannable_quantity` sevkiyata
    planlanabilecek kalan miktardır (Adım 3.2)."""
    return (
        SalesOrderLine.objects.select_related("product__base_unit", "unit")
        .annotate(
            reserved_quantity=_reservation_sum(StockReservation.Status.ACTIVE),
            shipped_quantity=_reservation_sum(StockReservation.Status.CONSUMED),
            planned_quantity=_planned_sum(),
        )
        .annotate(
            shortage_quantity=Greatest(
                F("base_quantity") - F("shipped_quantity") - F("reserved_quantity"), ZERO
            ),
            plannable_quantity=Greatest(
                F("base_quantity") - F("shipped_quantity") - F("planned_quantity"), ZERO
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


# --- sevkiyat (Adım 3.2) ---------------------------------------------------------------------

CASE_UNIT = "KOLI"


def masked_driver_id(shipment: Shipment) -> str:
    """Şoför TC kimlik no, KVKK gereği maskeli (`*******8901`)."""
    return mask_identifier(shipment.driver_id_no)


def _active_picks(shipment: Shipment) -> QuerySet[ShipmentPick]:
    return ShipmentPick.objects.filter(line__shipment=shipment, returned_at__isnull=True)


def shipment_lines(shipment: Shipment) -> QuerySet[ShipmentLine]:
    """Sevkiyat satırları; `picked_quantity` (geri alınmamış toplama) açıklamasıyla."""
    picked = (
        ShipmentPick.objects.filter(line=OuterRef("pk"), returned_at__isnull=True)
        .values("line")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return (
        ShipmentLine.objects.filter(shipment=shipment)
        .select_related("order_line__product__base_unit")
        .annotate(picked_quantity=Coalesce(Subquery(picked, output_field=_DECIMAL), ZERO))
        .order_by("order_line__line_no")
    )


def shipment_picks(shipment: Shipment) -> QuerySet[ShipmentPick]:
    """Sevkiyatın bütün toplama kayıtları (geri alınanlar dahil), okutma sırasıyla."""
    return (
        ShipmentPick.objects.filter(line__shipment=shipment)
        .select_related(
            "lot", "from_location", "to_location", "picked_by", "line__order_line__product"
        )
        .order_by("picked_at", "id")
    )


def pick_suggestions(shipment: Shipment) -> list[dict[str, Any]]:
    """Toplama tableti için satır başına öneri: önce satırın rezerve lotları (SKT sırasıyla),
    sonra rezervesiz stok (FEFO). Her lot ve lokasyon bir kez listelenir: `quantity` toplanabilir
    miktar (satırın rezervasyonu + rezervesiz stok), `reserved_quantity` bu satıra rezerve kısım.
    Karantina ve sevk alanlarındaki stok önerilmez. SKT'si geçmiş
    ya da müşterinin asgari raf ömrünü karşılamayan lot `meets_shelf_life=false` ile işaretlenir
    (okutulamaz)."""
    from apps.sales import services  # döngüsel import olmasın (services selectors'ı kullanır)

    order = shipment.sales_order
    limit = services.min_expiry_date(order.customer, services.shelf_life_reference_date(order))
    today = timezone.localdate()
    staging = services.UNRESERVABLE_LOCATION_TYPES
    result = []
    for line in shipment_lines(shipment):
        order_line = line.order_line
        remaining = max(line.quantity - line.picked_quantity, Decimal(0))  # type: ignore[attr-defined]
        reserved = (
            StockReservation.objects.filter(
                sales_order_line=order_line, status=StockReservation.Status.ACTIVE
            )
            .exclude(location__location_type__in=staging)
            .select_related("lot", "location")
            .order_by("lot__expiry_date", "lot__lot_no")
        )
        # Lot ve lokasyon başına tek satır: satırın rezervasyonları ile aynı yerdeki rezervesiz
        # stok birleşir (önce aynı lot iki kez, "rezerve" ve "serbest" olarak listeleniyordu).
        by_key: dict[tuple[int, int], dict[str, Any]] = {}
        for r in reserved:
            row = by_key.setdefault(
                (r.lot_id, r.location_id),
                {
                    "lot": r.lot_id,
                    "lot_no": r.lot.lot_no,
                    "expiry_date": r.lot.expiry_date,
                    "location": r.location_id,
                    "location_code": r.location.code,
                    "quantity": Decimal(0),
                    "reserved_quantity": Decimal(0),
                    "reserved": True,
                },
            )
            row["quantity"] += r.quantity
            row["reserved_quantity"] += r.quantity
        free = inventory_selectors.available_lots(order_line.product).exclude(
            location__location_type__in=staging
        )
        for b in free:
            available = b.available_quantity  # type: ignore[attr-defined]
            key = (b.lot_id, b.location_id)
            if key in by_key:
                by_key[key]["quantity"] += available
                continue
            by_key[key] = {
                "lot": b.lot_id,
                "lot_no": b.lot.lot_no,
                "expiry_date": b.lot.expiry_date,
                "location": b.location_id,
                "location_code": b.location.code,
                "quantity": available,
                "reserved_quantity": Decimal(0),
                "reserved": False,
            }
        rows = list(by_key.values())  # rezerve satırlar önce, sonra FEFO (ekleme sırası)
        for row in rows:
            expiry = row["expiry_date"]
            row["meets_shelf_life"] = expiry is None or (
                expiry >= today and (limit is None or expiry >= limit)
            )
        result.append(
            {
                "line": line.pk,
                "line_no": order_line.line_no,
                "product": order_line.product_id,
                "product_code": order_line.product.code,
                "product_name": order_line.product.name,
                "unit": order_line.product.base_unit.code,
                "quantity": line.quantity,
                "picked_quantity": line.picked_quantity,  # type: ignore[attr-defined]
                "remaining_quantity": remaining,
                "suggestions": rows,
            }
        )
    return result


def case_breakdown(material: Material, quantity: Decimal) -> tuple[int | None, Decimal]:
    """Miktarın tam koli sayısı ve koliye girmeyen kalan (temel birimde). Mamulün koli dönüşümü
    yoksa (None, miktar)."""
    case = UnitOfMeasure.objects.filter(code=CASE_UNIT).first()
    factor = masterdata.unit_factor_to_base(material, case) if case is not None else None
    if not factor or factor <= 0:
        return None, quantity
    cases = int(quantity // factor)
    return cases, quantity - cases * factor


def waybill_data(shipment: Shipment) -> dict[str, Any]:
    """İrsaliye verisi (PDF ve dışa aktarım; e-İrsaliye Faz 5): firma, müşteri ve teslim adresi,
    araç / şoför, satırlar (ürün, lot, SKT, miktar, koli). Satırlar sevk edildiyse sevk
    hareketlerinden, değilse geri alınmamış toplama kayıtlarından okunur."""
    order = shipment.sales_order
    customer = order.customer
    lines: list[dict[str, Any]] = []
    picks = (
        _active_picks(shipment)
        .select_related("lot", "line__order_line__product__base_unit")
        .order_by("line__order_line__line_no", "lot__expiry_date", "lot__lot_no")
    )
    for pick in picks:
        product = pick.line.order_line.product
        cases, rest = case_breakdown(product, pick.quantity)
        lines.append(
            {
                "line_no": pick.line.order_line.line_no,
                "product_code": product.code,
                "product_name": product.name,
                "gtin": getattr(product, "gtin", "") or "",
                "lot_no": pick.lot.lot_no,
                "expiry_date": pick.lot.expiry_date,
                "quantity": pick.quantity,
                "unit": product.base_unit.code,
                "cases": cases,
                "loose_units": rest,
            }
        )
    # Farklı birimler toplanmaz: satırlar tek birimdeyse toplam o birimle, değilse boş.
    units = {line["unit"] for line in lines}
    total_unit = units.pop() if len(units) == 1 else None
    total = (
        sum((line["quantity"] for line in lines), Decimal(0)) if total_unit or not lines else None
    )
    return {
        "number": shipment.number,
        "status": shipment.status,
        "date": (
            timezone.localtime(shipment.dispatched_at).date() if shipment.dispatched_at else None
        )
        or shipment.planned_date,
        "dispatched_at": shipment.dispatched_at,
        "company": {
            "name": settings.COMPANY_NAME,
            "address": settings.COMPANY_ADDRESS,
            "tax_office": settings.COMPANY_TAX_OFFICE,
            "tax_no": settings.COMPANY_TAX_NO,
        },
        "customer": {
            "code": customer.code,
            "name": customer.name,
            "address": customer.address,
            "tax_office": customer.tax_office,
            "tax_no": customer.tax_number,
        },
        "delivery_address": order.delivery_address or customer.address,
        "order_number": order.number,
        "customer_po_no": order.customer_po_no,
        "vehicle_plate": shipment.vehicle_plate,
        "driver_name": shipment.driver_name,
        "driver_id_no": shipment.driver_id_no,
        "carrier": shipment.carrier,
        "lines": lines,
        "total_quantity": total,
        "total_unit": total_unit or "",
        "total_cases": sum(line["cases"] or 0 for line in lines),
    }


def customer_shipped_lots(customer: Customer | int) -> QuerySet[ShipmentPick]:
    """Müşteriye sevk edilen lotlar (sevk edilmiş toplama kayıtları), yeniden eskiye. Sevk
    hareketi ters kayıtla geri alınmış toplama sayılmaz."""
    return (
        ShipmentPick.objects.filter(
            line__shipment__sales_order__customer=customer,
            line__shipment__status=Shipment.Status.DISPATCHED,
            movement__isnull=False,
            movement__reversed_by__isnull=True,
        )
        .select_related(
            "lot", "line__shipment", "line__order_line__order", "line__order_line__product"
        )
        .order_by("-line__shipment__dispatched_at", "-id")
    )


def shipped_by_shipment_lot(shipment: Shipment) -> dict[int, Decimal]:
    """Sevkiyatta lot bazında net sevk edilen miktar (iade kontrolü için). Ters kayıtla geri
    alınan sevk hareketi sayılmaz (izlenebilirlikteki net sevk ile aynı)."""
    rows = (
        ShipmentPick.objects.filter(
            line__shipment=shipment, movement__isnull=False, movement__reversed_by__isnull=True
        )
        .values("lot_id")
        .annotate(total=Sum("quantity"))
    )
    return {row["lot_id"]: row["total"] for row in rows}
