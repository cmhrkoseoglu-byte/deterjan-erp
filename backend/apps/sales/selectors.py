"""Satış okuma sorguları: satır miktarları (rezerve, sevk, eksik), sipariş toplamı, müşteri
sipariş geçmişi, SKT'si yaklaşan rezerve lotlar; sevkiyat satırları, toplama önerisi, irsaliye
verisi ve müşteriye sevk edilen lotlar (Adım 3.2)."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    Case,
    Count,
    DateField,
    DateTimeField,
    DecimalField,
    F,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from apps.core.audit import mask_identifier
from apps.core.coding.selectors import code_as_of
from apps.inventory import selectors as inventory_selectors
from apps.inventory.models import StockReservation
from apps.inventory.services import format_quantity
from apps.masterdata import services as masterdata
from apps.masterdata.models import Customer
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


def case_breakdown(quantity: Decimal, factor: Decimal | None) -> tuple[int | None, Decimal]:
    """Miktarın tam koli sayısı ve koliye girmeyen kalan (temel birimde), 1 koli = `factor`. Koli
    içi miktar yoksa ya da sıfırdan büyük değilse (None, miktar). İrsaliye lotun koli düzenini
    kullanır (`Lot.case_factor`, lotun açıldığı günkü koli içi miktar; CUMHUR, 2026-11-05): eski
    lotun kolileri eski adetle sayılır, sevk edilmiş irsaliyenin yeniden basımı koli düzeni sonra
    değişse de (miktar, pasife alınan dönüşüm, Excel'den içe aktarma) değişmez."""
    if factor is None or factor <= 0:
        return None, quantity
    cases = int(quantity // factor)
    return cases, quantity - cases * factor


def _company() -> dict[str, str]:
    """İrsaliyede satıcı: Ana veriler > Firma bilgileri."""
    profile = masterdata.get_company_profile()
    return {
        "name": profile.legal_name,
        "address": profile.address,
        "tax_office": profile.tax_office,
        "tax_no": profile.tax_number,
        "registry": masterdata.company_registry_line(profile),
    }


def waybill_data(shipment: Shipment) -> dict[str, Any]:
    """İrsaliye verisi (PDF ve dışa aktarım; e-İrsaliye Faz 5): firma, müşteri ve teslim adresi,
    araç / şoför, satırlar (ürün, lot, SKT, miktar, koli). Satırlar sevk edildiyse sevk
    hareketlerinden, değilse geri alınmamış toplama kayıtlarından okunur."""
    order = shipment.sales_order
    customer = order.customer
    # Yeniden basımda kodlar sevk anındaki haliyle basılır (sonradan değişse de; core.coding).
    when = shipment.dispatched_at or timezone.now()
    lines: list[dict[str, Any]] = []
    picks = (
        _active_picks(shipment)
        .select_related("lot", "line__order_line__product__base_unit")
        .order_by("line__order_line__line_no", "lot__expiry_date", "lot__lot_no")
    )
    for pick in picks:
        product = pick.line.order_line.product
        cases, rest = case_breakdown(pick.quantity, pick.lot.case_factor)
        lines.append(
            {
                "line_no": pick.line.order_line.line_no,
                "product_code": code_as_of(product, when),
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
        "company": _company(),
        "customer": {
            "code": code_as_of(customer, when),
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


# --- müşteri sipariş takibi (docs/plan/musteri-siparis-takibi.md §3.2) ------------------------

OPEN_ORDER_STATUSES = (SalesOrder.Status.CONFIRMED, SalesOrder.Status.PARTIALLY_SHIPPED)
FINISHED_ORDER_STATUSES = (
    SalesOrder.Status.SHIPPED,
    SalesOrder.Status.CLOSED,
    SalesOrder.Status.CANCELLED,
)
# "Biten siparişleri de göster": son bu kadar günde biten siparişler.
FINISHED_WINDOW_DAYS = 90
# Müşteri özetinde "yakında vadesi gelen": bugünden itibaren bu kadar gün.
DUE_SOON_DAYS = 7


def due_date_expression() -> Coalesce:
    """Vade: termin, yoksa istenen teslim tarihi (ikisi de boşsa boş)."""
    return Coalesce(F("promised_date"), F("requested_delivery_date"), output_field=DateField())


def due_date(order: SalesOrder) -> date | None:
    """Siparişin vadesi: termin, yoksa istenen teslim tarihi."""
    return order.promised_date or order.requested_delivery_date


def _last_dispatch() -> Subquery:
    rows = (
        Shipment.objects.filter(sales_order=OuterRef("pk"), status=Shipment.Status.DISPATCHED)
        .values("sales_order")
        .annotate(last=Max("dispatched_at"))
        .values("last")
    )
    return Subquery(rows, output_field=DateTimeField())


def tracked_orders(
    *, include_finished: bool = False, today: date | None = None
) -> QuerySet[SalesOrder]:
    """Takipteki siparişler: açıklar (Onaylandı, Kısmen sevk edildi); `include_finished` ile son
    `FINISHED_WINDOW_DAYS` günde biten (sevk edilen, kapanan, onaydan sonra iptal edilen)
    siparişler de. Açıklamalar: `due_date`, `last_dispatched_at`, `finished_on` (bitiş günü).
    Satırlar miktarlarıyla (`lines_with_quantities`), sevkiyatlar iptaller hariç önceden
    yüklenir. Sıra: vade (boşlar sonda), sipariş no."""
    today = today or timezone.localdate()
    since = today - timedelta(days=FINISHED_WINDOW_DAYS)
    orders = SalesOrder.objects.annotate(
        due_date=due_date_expression(),
        last_dispatched_at=_last_dispatch(),
    ).annotate(
        finished_at=Case(
            When(status=SalesOrder.Status.CLOSED, then=F("closed_at")),
            When(status=SalesOrder.Status.CANCELLED, then=F("cancelled_at")),
            When(status=SalesOrder.Status.SHIPPED, then=F("last_dispatched_at")),
            default=None,
            output_field=DateTimeField(),
        )
    )
    scope = Q(status__in=OPEN_ORDER_STATUSES)
    if include_finished:
        start = timezone.make_aware(datetime.combine(since, time.min))
        scope |= Q(
            status__in=FINISHED_ORDER_STATUSES,
            confirmed_at__isnull=False,
            finished_at__gte=start,
        )
    return (
        orders.filter(scope)
        .select_related("customer")
        .prefetch_related(
            Prefetch("lines", queryset=lines_with_quantities().order_by("line_no")),
            Prefetch(
                "shipments",
                queryset=Shipment.objects.exclude(status=Shipment.Status.CANCELLED).order_by(
                    "planned_date", "id"
                ),
            ),
        )
        .order_by(F("due_date").asc(nulls_last=True), "number")
    )


def late_filter(today: date | None = None) -> Q:
    """Geciken sipariş: açık ve vadesi bugünden önce."""
    today = today or timezone.localdate()
    return Q(status__in=OPEN_ORDER_STATUSES, due_date__lt=today)


def newly_overdue_orders(today: date | None = None) -> QuerySet[SalesOrder]:
    """Geciken ve bu vade için henüz bildirilmemiş açık siparişler (§3.4). Sıra: vade, no."""
    today = today or timezone.localdate()
    return (
        SalesOrder.objects.annotate(due_date=due_date_expression())
        .filter(late_filter(today))
        .exclude(overdue_notified_due_date=F("due_date"))
        .select_related("customer")
        .order_by("due_date", "number")
    )


def days_late(order: SalesOrder, today: date | None = None) -> int | None:
    """Açık siparişin gecikme günü (vade geçmişse > 0, değilse 0); vadesiz siparişte boş.
    Biten siparişte gecikme son sevk gününe göre (zamanında = 0); sevki olmayanda boş."""
    due = due_date(order)
    if due is None:
        return None
    if order.status in OPEN_ORDER_STATUSES:
        reference = today or timezone.localdate()
    else:
        dispatched = getattr(order, "last_dispatched_at", None)
        if dispatched is None:
            return None
        reference = timezone.localtime(dispatched).date()
    return max((reference - due).days, 0)


def line_remaining(line: SalesOrderLine) -> Decimal:
    """Satırın kalan (sevk edilmemiş) miktarı, temel birimde; en az 0. Kapanan ya da iptal
    edilen siparişte kalan sevk edilmeyecektir (çağıran durumla birlikte gösterir)."""
    shipped = getattr(line, "shipped_quantity", Decimal(0))
    return max(line.base_quantity - shipped, Decimal(0))


def in_order_unit(line: SalesOrderLine, base_quantity: Decimal) -> Decimal:
    """Temel birimdeki miktarı satırın sipariş birimine çevirir (satırın kendi oranıyla)."""
    if not line.base_quantity:
        return Decimal(0)
    return (base_quantity * line.quantity / line.base_quantity).quantize(Decimal("0.0001"))


def customer_tracking_summary(*, today: date | None = None) -> QuerySet[Customer]:
    """Açık siparişi olan müşteriler: `open_orders`, `late_orders`, `oldest_due_date` (geciken
    siparişlerin en eski vadesi), `due_soon` (vadesi bugünden `DUE_SOON_DAYS` gün içinde).
    Sıra: geciken sayısı (çoktan aza), en eski gecikme, müşteri kodu."""
    today = today or timezone.localdate()
    soon = today + timedelta(days=DUE_SOON_DAYS)
    open_q = Q(sales_orders__status__in=OPEN_ORDER_STATUSES)
    due = Coalesce(
        F("sales_orders__promised_date"),
        F("sales_orders__requested_delivery_date"),
        output_field=DateField(),
    )
    customers = Customer.objects.alias(order_due=due).annotate(
        open_orders=Count("sales_orders", filter=open_q, distinct=True),
        late_orders=Count("sales_orders", filter=open_q & Q(order_due__lt=today), distinct=True),
        oldest_due_date=Min("order_due", filter=open_q & Q(order_due__lt=today)),
        due_soon=Count(
            "sales_orders",
            filter=open_q & Q(order_due__gte=today, order_due__lte=soon),
            distinct=True,
        ),
    )
    return customers.filter(open_orders__gt=0).order_by(
        "-late_orders", F("oldest_due_date").asc(nulls_last=True), "code"
    )
