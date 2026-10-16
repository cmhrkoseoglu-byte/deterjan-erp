"""Satış servisleri: müşteri siparişi ve stok rezervasyonu (Faz 3, Adım 3.1).

Kurallar:
- Sipariş satırı yalnızca mamul (FINISHED) içerir; miktar ADET / KOLI / PALET gibi bir birimle
  girilir ve `masterdata.services.to_base_quantity` ile temel birime çevrilir. Satırlar yalnızca
  taslakta değişir.
- Onayda (`CONFIRMED`) her satır için FEFO sırasıyla otomatik rezervasyon yapılır: serbest, SKT'si
  geçmemiş, karantina dışı stok; müşterinin asgari kalan raf ömrü varsa (Karar D-11) onu
  karşılamayan lot atlanır. Yetmeyen miktar için `sales_order.shortage` yayınlanır (planlamaya
  görev). `reserve_shortages` yeni stoğu ekler; eksik kapanınca `sales_order.fully_reserved`.
- Rezervasyon `inventory.StockReservation` kaydıdır (kaynak: sipariş satırı); yalnızca
  `inventory.services` ile yazılır. Rezervasyon stok hareketi değildir.
- İptal ve kapanışta aktif rezervasyonlar bırakılır. Rezerve lot serbest durumdan çıkarsa
  (bloke, red, karantina) rezervasyonları bırakılır ve eksik yeniden yayınlanır (`handlers`).

Sevkiyat (Adım 3.2, `SV-`, Karar D-10: tek sipariş):
- Planlamada sipariş satırlarının kalan miktarı (sipariş − sevk edilen − açık sevkiyatlarda
  planlanan) satırlara gelir. Depo lotu okutur: lot serbest, SKT'si geçmemiş ve müşterinin asgari
  raf ömrünü karşılamalıdır (D-11). Okutulan miktar depodan sevk alanına (`SHIPPING`) transfer
  edilir; rezervasyon da taşınır (bırak → transfer → sevk alanında yeniden rezerve et).
  Rezervasyondan farklı lot okutmak gerekçe ister; satırın fazladan rezervasyonu bırakılır.
- "Yükleme tamam" (depo) → `LOADED`; "Sevki onayla" (sevkiyat) → rezervasyonlar `CONSUMED`,
  `SHIPMENT` hareketi sevk alanından çıkar, sipariş kısmen sevk edildi / sevk edildi olur.
- İptalde (sevkten önce) toplanan lotlar geldikleri yere döner ve orada yeniden rezerve edilir.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.audit import log_change, snapshot
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import DEPO, SEVKIYAT, YONETIM
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockReservation
from apps.inventory.picking import picked_total
from apps.inventory.services import format_quantity, quantize
from apps.masterdata import services as masterdata
from apps.masterdata.models import Customer, Location, Material
from apps.sales.models import SalesOrder, SalesOrderLine, Shipment, ShipmentLine, ShipmentPick
from apps.sales.state import sales_order_states, shipment_states

ORDER_ROLES = (SEVKIYAT, YONETIM)
# Sevkiyat planlama, iptal ve sevk onayı; toplama ve yükleme (Adım 3.2).
SHIPMENT_ROLES = (SEVKIYAT,)
PICK_ROLES = (DEPO,)

Status = SalesOrder.Status
ReservationStatus = StockReservation.Status
ZERO = Decimal(0)

ORDER_FIELDS = (
    "customer",
    "order_date",
    "requested_delivery_date",
    "delivery_address",
    "customer_po_no",
    "notes",
)
LINE_FIELDS = ("product", "quantity", "unit", "unit_price", "currency", "note")
TEXT_FIELDS = frozenset({"delivery_address", "customer_po_no", "notes", "currency", "note"})
# Rezervasyon yapılabilen (stoğu sevk edilecek) sipariş durumları.
RESERVABLE_STATUSES = (Status.CONFIRMED, Status.PARTIALLY_SHIPPED)
ShipmentStatus = Shipment.Status
OPEN_SHIPMENT_STATUSES = (ShipmentStatus.PLANNED, ShipmentStatus.PICKING, ShipmentStatus.LOADED)
# Karantina stoğu kullanılamaz; sevk alanındaki stok başka bir sevkiyata okutulmuş maldır.
# Bu lokasyonlardaki stok siparişe rezerve edilmez ve toplamada kaynak olarak seçilmez.
UNRESERVABLE_LOCATION_TYPES = (Location.Type.QUARANTINE, Location.Type.SHIPPING)
SHIPMENT_FIELDS = (
    "planned_date",
    "loading_location",
    "vehicle_plate",
    "driver_name",
    "driver_id_no",
    "carrier",
    "notes",
)
SHIPMENT_TEXT_FIELDS = frozenset(
    {"vehicle_plate", "driver_name", "driver_id_no", "carrier", "notes"}
)
DRIVER_ID_RE = re.compile(r"^\d{11}$")


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def _require_role(actor: User | None, message: str) -> None:
    if not user_has_role(actor, ORDER_ROLES):
        raise PermissionDenied(message)


def _pick_fields(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return {name: ("" if name in TEXT_FIELDS and v is None else v) for name, v in data.items()}


def _lock_order(order: SalesOrder) -> SalesOrder:
    return (
        SalesOrder.objects.select_for_update(of=("self",))
        .select_related("customer")
        .get(pk=order.pk)
    )


def _require_status(order: SalesOrder, allowed: Sequence[str], code: str, what: str) -> None:
    if order.status not in allowed:
        raise BusinessRuleError(
            code,
            f"{order.number} {sales_order_states.label(order.status).lower()} durumda; {what}.",
        )


# --- sipariş ---------------------------------------------------------------------------------


def _validate_order(order: SalesOrder) -> None:
    if not order.customer.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif müşteri seçilemez: {order.customer}.")
    if order.requested_delivery_date and order.requested_delivery_date < order.order_date:
        raise BusinessRuleError(
            "invalid_delivery_date", "İstenen teslim tarihi sipariş tarihinden önce olamaz."
        )


def _prepare_line(line: SalesOrderLine) -> None:
    product = line.product
    if not product.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif malzeme seçilemez: {product}.")
    if product.material_type != Material.Type.FINISHED:
        raise BusinessRuleError(
            "sales_material_type", f"{product.code}: siparişe yalnızca mamul girilir."
        )
    if line.quantity is None or line.quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    if not line.unit.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif birim seçilemez: {line.unit}.")
    base = quantize(masterdata.to_base_quantity(product, line.quantity, line.unit))
    if base <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar temel birimde sıfıra iniyor.")
    line.base_quantity = base
    if line.unit_price is not None:
        if line.unit_price < 0:
            raise BusinessRuleError("invalid_price", "Birim fiyat negatif olamaz.")
        if not line.currency:
            raise BusinessRuleError("currency_required", "Fiyat girilen satırda para birimi seçin.")
    else:
        line.currency = ""


def _sync_lines(actor: User | None, order: SalesOrder, items: Iterable[Mapping[str, Any]]) -> None:
    """Taslak siparişin satırlarını verilen listeyle eşitler: `id`'li satır güncellenir, `id`'siz
    eklenir, listede olmayan kaldırılır (denetim kaydıyla)."""
    existing = {line.pk: line for line in order.lines.select_for_update().order_by("line_no")}
    keep: set[int] = set()
    next_no = (order.lines.aggregate(m=Max("line_no"))["m"] or 0) + 1
    pending: list[SalesOrderLine] = []
    for item in items:
        values = dict(item)
        line_id = values.pop("id", None)
        values = _pick_fields(values, LINE_FIELDS)
        if line_id is not None:
            line = existing.get(line_id)
            if line is None:
                raise BusinessRuleError(
                    "line_not_found", f"Siparişte {line_id} numaralı satır yok."
                )
            keep.add(line_id)
            for name, value in values.items():
                setattr(line, name, value)
        else:
            line = SalesOrderLine(order=order, line_no=next_no, **values)
            next_no += 1
        pending.append(line)
    for line_id, line in existing.items():
        if line_id in keep:
            continue
        log_change(
            _actor(actor),
            order,
            AuditLog.Action.UPDATE,
            {"line": [snapshot(line), None]},
            f"Satır {line.line_no} kaldırıldı (taslak)",
        )
        line.delete()
    for line in pending:
        _prepare_line(line)
        save_with_audit(line, actor)


@transaction.atomic
def create_order(
    actor: User | None, data: Mapping[str, Any], lines: Iterable[Mapping[str, Any]] = ()
) -> SalesOrder:
    """Taslak satış siparişi açar (`SS-`, rol: sevkiyat ya da yonetim); satırlar birlikte
    verilebilir. Teslim adresi boşsa müşterinin adresi alınır."""
    _require_role(actor, "Satış siparişini yalnızca sevkiyat ve yönetim açar.")
    order = SalesOrder(**_pick_fields(data, ORDER_FIELDS))
    if not order.delivery_address:
        order.delivery_address = order.customer.address
    _validate_order(order)
    create_document(order, actor, prefix="SS", machine=sales_order_states)
    _sync_lines(actor, order, lines)
    return order


@transaction.atomic
def update_order(
    actor: User | None,
    order: SalesOrder,
    data: Mapping[str, Any],
    lines: Iterable[Mapping[str, Any]] | None = None,
) -> SalesOrder:
    """Taslak siparişin başlığını günceller; `lines` verilirse satırları onunla eşitler.
    Onaylanan sipariş değiştirilmez."""
    _require_role(actor, "Satış siparişini yalnızca sevkiyat ve yönetim değiştirir.")
    values = _pick_fields(data, ORDER_FIELDS)
    order = _lock_order(order)
    _require_status(order, (Status.DRAFT,), "document_locked", "değiştirilemez")
    for name, value in values.items():
        setattr(order, name, value)
    _validate_order(order)
    save_with_audit(order, actor)
    if lines is not None:
        _sync_lines(actor, order, lines)
    return order


@transaction.atomic
def confirm_order(actor: User | None, order: SalesOrder, note: str = "") -> SalesOrder:
    """Siparişi onaylar ve FEFO ile rezervasyon yapar. Olay `sales_order.confirmed` sevkiyata
    "Sevkiyat planla" görevi açar; eksik varsa `sales_order.shortage` planlamaya görev açar."""
    _require_role(actor, "Satış siparişini yalnızca sevkiyat ve yönetim onaylar.")
    actor = _actor(actor)
    order = _lock_order(order)
    sales_order_states.assert_can_transition(order.status, Status.CONFIRMED)
    _validate_order(order)
    lines = list(order.lines.select_related("product__base_unit", "unit").order_by("line_no"))
    if not lines:
        raise BusinessRuleError("document_empty", "Satırı olmayan sipariş onaylanamaz.")
    for line in lines:
        _prepare_line(line)
    order.confirmed_by = actor
    order.confirmed_at = timezone.now()
    order.save(update_fields=["confirmed_by", "confirmed_at"])
    transition_status(
        order,
        Status.CONFIRMED,
        actor,
        machine=sales_order_states,
        note=note,
        event_payload=_order_payload(order),
    )
    _reserve_order(actor, order, publish_complete=False)
    return order


@transaction.atomic
def cancel_order(actor: User | None, order: SalesOrder, reason: str) -> SalesOrder:
    """Taslak ya da onaylı (henüz sevk edilmemiş) siparişi iptal eder; aktif rezervasyonlar
    bırakılır. Olay `sales_order.cancelled` siparişe bağlı açık görevleri iptal eder."""
    _require_role(actor, "Satış siparişini yalnızca sevkiyat ve yönetim iptal eder.")
    order = _lock_order(order)
    sales_order_states.assert_can_transition(order.status, Status.CANCELLED)
    _require_no_open_shipments(order)
    if not reason.strip():
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    _release_all(actor, order, f"Sipariş iptali {order.number}")
    return cancel_document(order, actor, reason=reason, machine=sales_order_states)


@transaction.atomic
def close_order(actor: User | None, order: SalesOrder, note: str = "") -> SalesOrder:
    """Sevk edilmiş ya da kısmen sevk edilmiş siparişi kapatır; kalan aktif rezervasyonlar
    bırakılır (kalan miktar sevk edilmeyecek)."""
    _require_role(actor, "Satış siparişini yalnızca sevkiyat ve yönetim kapatır.")
    order = _lock_order(order)
    sales_order_states.assert_can_transition(order.status, Status.CLOSED)
    _require_no_open_shipments(order)
    _release_all(actor, order, f"Sipariş kapandı {order.number}")
    order.closed_at = timezone.now()
    order.save(update_fields=["closed_at"])
    return transition_status(order, Status.CLOSED, actor, machine=sales_order_states, note=note)


def _require_no_open_shipments(order: SalesOrder) -> None:
    numbers = list(
        order.shipments.filter(status__in=OPEN_SHIPMENT_STATUSES)
        .order_by("id")
        .values_list("number", flat=True)
    )
    if numbers:
        raise BusinessRuleError(
            "open_shipments",
            f"{order.number} siparişinin açık sevkiyatı var ({', '.join(numbers)}); önce "
            "sevkiyatı sevk edin ya da iptal edin.",
        )


def _release_all(actor: User | None, order: SalesOrder, note: str) -> None:
    for reservation in active_reservations(order):
        inventory.release_reservation(actor, reservation, note)


# --- miktarlar -------------------------------------------------------------------------------


def _reservations_of(line: SalesOrderLine) -> Any:
    return inventory.reservations_for(line)


def reserved_quantity(line: SalesOrderLine) -> Decimal:
    """Satırın aktif rezervasyonları (temel birimde)."""
    total = (
        _reservations_of(line)
        .filter(status=ReservationStatus.ACTIVE)
        .aggregate(t=Sum("quantity"))["t"]
    )
    return total or ZERO


def shipped_quantity(line: SalesOrderLine) -> Decimal:
    """Satırdan sevk edilen miktar: kullanılmış (`CONSUMED`) rezervasyonlar. Sevkiyat her çıkışta
    rezervasyonu kullanır (DECISIONS.md, rezervasyon sözleşmesi)."""
    total = (
        _reservations_of(line)
        .filter(status=ReservationStatus.CONSUMED)
        .aggregate(t=Sum("quantity"))["t"]
    )
    return total or ZERO


def shortage_quantity(line: SalesOrderLine) -> Decimal:
    """Rezerve edilmemiş ve sevk edilmemiş kalan miktar (temel birimde, en az 0)."""
    return max(line.base_quantity - shipped_quantity(line) - reserved_quantity(line), ZERO)


def active_reservations(order: SalesOrder) -> list[StockReservation]:
    """Siparişin bütün satırlarındaki aktif rezervasyonlar."""
    return list(
        StockReservation.objects.filter(
            sales_order_line__order=order, status=ReservationStatus.ACTIVE
        ).select_related("lot", "location", "material")
    )


# --- raf ömrü (Karar D-11) -------------------------------------------------------------------


def shelf_life_reference_date(order: SalesOrder, today: date | None = None) -> date:
    """Kalan raf ömrünün ölçüldüğü gün: istenen teslim tarihi (bugünden sonraysa) ya da bugün."""
    today = today or timezone.localdate()
    requested = order.requested_delivery_date
    return requested if requested and requested > today else today


def min_expiry_date(customer: Customer, reference: date) -> date | None:
    """Müşterinin asgari kalan raf ömrü şartını karşılayan en erken SKT; şart yoksa None."""
    days = customer.min_remaining_shelf_life_days
    if days is None:
        return None
    return reference + timedelta(days=days)


def shelf_life_error(lot: Lot, order: SalesOrder) -> BusinessRuleError | None:
    """Lot müşterinin asgari kalan raf ömrünü karşılamıyorsa hata; karşılıyorsa None. SKT'siz lot
    şartı karşılar. Sevkiyat toplamada da bu kontrolü kullanır."""
    limit = min_expiry_date(order.customer, shelf_life_reference_date(order))
    if limit is None or lot.expiry_date is None or lot.expiry_date >= limit:
        return None
    days = order.customer.min_remaining_shelf_life_days
    return BusinessRuleError(
        "shelf_life_too_short",
        f"Lot {lot.lot_no} SKT'si {lot.expiry_date:%d.%m.%Y}; {order.customer.name} en az {days} "
        f"gün kalan raf ömrü istiyor ({limit:%d.%m.%Y} ve sonrası).",
    )


# --- rezervasyon -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LineShortage:
    line: SalesOrderLine
    quantity: Decimal


def _reserve_line_fefo(actor: User | None, order: SalesOrder, line: SalesOrderLine) -> Decimal:
    """Satırın eksik miktarını FEFO ile rezerve eder; kalan eksik miktarı döner."""
    need = shortage_quantity(line)
    if need <= 0:
        return ZERO
    limit = min_expiry_date(order.customer, shelf_life_reference_date(order))
    candidates = inventory_selectors.available_lots(line.product).exclude(
        location__location_type__in=UNRESERVABLE_LOCATION_TYPES
    )
    if limit is not None:
        candidates = candidates.exclude(lot__expiry_date__lt=limit)
    for balance in candidates:
        if need <= 0:
            break
        quantity = min(need, balance.available_quantity)  # type: ignore[attr-defined]
        inventory.reserve(
            actor,
            lot=balance.lot,
            location=balance.location,
            quantity=quantity,
            source=line,
            document_number=order.number,
            note=f"FEFO rezervasyonu {order.number}",
        )
        need -= quantity
    return need


def _reserve_order(
    actor: User | None, order: SalesOrder, *, publish_complete: bool
) -> list[LineShortage]:
    shortages = []
    lines = order.lines.select_related("product__base_unit").order_by("line_no")
    for line in lines:
        missing = _reserve_line_fefo(actor, order, line)
        if missing > 0:
            shortages.append(LineShortage(line, missing))
    if shortages:
        publish_shortage(order, shortages, actor)
    elif publish_complete:
        events.publish(ev.SALES_ORDER_FULLY_RESERVED, _order_payload(order), actor)
    return shortages


@transaction.atomic
def reserve_shortages(actor: User | None, order: SalesOrder) -> list[LineShortage]:
    """Onaylı siparişin eksik miktarlarını yeni serbest stoktan FEFO ile rezerve eder. Eksik
    kalmazsa `sales_order.fully_reserved` (planlama görevi kapanır), kalırsa
    `sales_order.shortage` yeniden yayınlanır (açık görev varsa yenisi açılmaz)."""
    _require_role(actor, "Rezervasyonu yalnızca sevkiyat ve yönetim yapar.")
    order = _lock_order(order)
    _require_status(order, RESERVABLE_STATUSES, "order_not_reservable", "rezervasyon yapılamaz")
    return _reserve_order(_actor(actor), order, publish_complete=True)


@transaction.atomic
def reserve_lot(
    actor: User | None,
    line: SalesOrderLine,
    *,
    lot: Lot,
    location: Location,
    quantity: Decimal,
    note: str = "",
) -> StockReservation:
    """Satıra elle lot rezerve eder (ör. FEFO önerisi yerine başka lot). Miktar satırın eksik
    miktarını aşamaz; lot müşterinin raf ömrü şartını karşılamalıdır."""
    _require_role(actor, "Rezervasyonu yalnızca sevkiyat ve yönetim yapar.")
    order = _lock_order(line.order)
    _require_status(order, RESERVABLE_STATUSES, "order_not_reservable", "rezervasyon yapılamaz")
    line = SalesOrderLine.objects.select_related("product__base_unit").get(pk=line.pk)
    if lot.material_id != line.product_id:
        raise BusinessRuleError(
            "lot_material_mismatch",
            f"Lot {lot.lot_no} bu satırın ürünü ({line.product.code}) değil.",
        )
    error = shelf_life_error(lot, order)
    if error is not None:
        raise error
    if location.location_type in UNRESERVABLE_LOCATION_TYPES:
        raise BusinessRuleError(
            "invalid_reservation_location",
            f"{location.code} lokasyonundaki stok rezerve edilemez (karantina ya da sevk alanı).",
        )
    quantity = quantize(quantity)
    missing = shortage_quantity(line)
    if quantity > missing:
        unit = line.product.base_unit.code
        raise BusinessRuleError(
            "reservation_exceeds_line",
            f"Satır {line.line_no} için en çok {format_quantity(missing)} {unit} daha rezerve "
            "edilebilir.",
        )
    reservation = inventory.reserve(
        actor,
        lot=lot,
        location=location,
        quantity=quantity,
        source=line,
        document_number=order.number,
        note=note,
    )
    if all(shortage_quantity(other) == 0 for other in order.lines.all()):
        events.publish(ev.SALES_ORDER_FULLY_RESERVED, _order_payload(order), _actor(actor))
    return reservation


@transaction.atomic
def release_line_reservation(
    actor: User | None, reservation: StockReservation, note: str = ""
) -> StockReservation:
    """Satırdaki rezervasyonu elle bırakır (ör. başka lot seçmek için). Eksik olay olarak
    yayınlanmaz; gerekirse "Eksikleri rezerve et" ile tamamlanır."""
    _require_role(actor, "Rezervasyonu yalnızca sevkiyat ve yönetim bırakır.")
    line = order_line_of(reservation)
    if line is None:
        raise BusinessRuleError(
            "not_sales_reservation", "Rezervasyon bir satış siparişine ait değil."
        )
    order = _lock_order(line.order)
    _require_status(order, RESERVABLE_STATUSES, "order_not_reservable", "rezervasyon bırakılamaz")
    if reservation.location.location_type == Location.Type.SHIPPING:
        raise BusinessRuleError(
            "reservation_on_loading",
            "Sevk alanındaki rezervasyon okutulmuş mala aittir; sevkiyatta okutmayı geri alın.",
        )
    return inventory.release_reservation(actor, reservation, note)


def order_line_of(reservation: StockReservation) -> SalesOrderLine | None:
    """Rezervasyonun bağlı olduğu sipariş satırı (satışa ait değilse None)."""
    return (
        SalesOrderLine.objects.select_related("order__customer")
        .filter(reservations=reservation)
        .first()
    )


@transaction.atomic
def release_unusable_lot(actor: User | None, lot: Lot, reason: str) -> list[SalesOrder]:
    """Lot serbest durumdan çıktığında (bloke, red, karantina) siparişlerdeki aktif
    rezervasyonlarını bırakır ve etkilenen siparişler için eksik yeniden yayınlanır. Etkilenen
    siparişleri döner."""
    reservations = StockReservation.objects.filter(
        lot=lot, status=ReservationStatus.ACTIVE, sales_order_line__isnull=False
    ).distinct()
    orders: dict[int, SalesOrder] = {}
    for reservation in reservations:
        line = order_line_of(reservation)
        if line is None:
            continue
        inventory.release_reservation(actor, reservation, reason)
        orders.setdefault(line.order_id, line.order)
    for order in orders.values():
        shortages = [
            LineShortage(line, missing)
            for line in order.lines.select_related("product__base_unit").order_by("line_no")
            if (missing := shortage_quantity(line)) > 0
        ]
        if shortages:
            publish_shortage(order, shortages, actor, reason=reason)
    return list(orders.values())


# --- olaylar ---------------------------------------------------------------------------------


def _order_payload(order: SalesOrder) -> dict[str, Any]:
    return {
        "model": "sales.salesorder",
        "id": order.pk,
        "number": order.number,
        "customer_code": order.customer.code,
        "customer_name": order.customer.name,
    }


def publish_shortage(
    order: SalesOrder,
    shortages: Sequence[LineShortage],
    actor: User | None,
    *,
    reason: str = "",
) -> None:
    """`sales_order.shortage`: rezerve edilemeyen ürün ve miktarlar (planlamaya görev)."""
    events.publish(
        ev.SALES_ORDER_SHORTAGE,
        {
            **_order_payload(order),
            "reason": reason,
            "lines": [
                {
                    "line_no": s.line.line_no,
                    "product_code": s.line.product.code,
                    "product_name": s.line.product.name,
                    "quantity": format_quantity(s.quantity),
                    "unit": s.line.product.base_unit.code,
                }
                for s in shortages
            ],
        },
        _actor(actor),
    )


# --- sevkiyat (Adım 3.2) ---------------------------------------------------------------------


def _require_roles(actor: User | None, roles: tuple[str, ...], message: str) -> None:
    if not user_has_role(actor, roles):
        raise PermissionDenied(message)


def _shipment_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(data) - set(SHIPMENT_FIELDS)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return {
        name: ("" if name in SHIPMENT_TEXT_FIELDS and v is None else v) for name, v in data.items()
    }


def _lock_shipment(shipment: Shipment) -> Shipment:
    return (
        Shipment.objects.select_for_update(of=("self",))
        .select_related("sales_order__customer", "loading_location")
        .get(pk=shipment.pk)
    )


def _require_shipment_status(
    shipment: Shipment, allowed: Sequence[str], code: str, what: str
) -> None:
    if shipment.status not in allowed:
        raise BusinessRuleError(
            code,
            f"{shipment.number} {shipment_states.label(shipment.status).lower()} durumda; {what}.",
        )


def default_loading_location() -> Location:
    """Varsayılan sevk alanı: koduna göre ilk aktif `SHIPPING` türü lokasyon."""
    location = (
        Location.objects.filter(location_type=Location.Type.SHIPPING, is_active=True)
        .order_by("code")
        .first()
    )
    if location is None:
        raise BusinessRuleError(
            "no_loading_location", "Sevkiyat türünde (sevk alanı) aktif lokasyon tanımlı değil."
        )
    return location


def _clean_shipment(shipment: Shipment) -> None:
    location = shipment.loading_location
    if location.location_type != Location.Type.SHIPPING or not location.is_active:
        raise BusinessRuleError(
            "invalid_loading_location", "Sevk alanı aktif ve “Sevkiyat” türünde olmalıdır."
        )
    shipment.vehicle_plate = " ".join(shipment.vehicle_plate.upper().split())
    shipment.driver_name = shipment.driver_name.strip()
    shipment.driver_id_no = shipment.driver_id_no.strip()
    shipment.carrier = shipment.carrier.strip()
    if shipment.driver_id_no and not DRIVER_ID_RE.match(shipment.driver_id_no):
        raise BusinessRuleError(
            "invalid_driver_id", "Şoför TC kimlik numarası 11 haneli olmalıdır."
        )


def planned_quantity(line: SalesOrderLine) -> Decimal:
    """Satırın açık (sevk edilmemiş, iptal edilmemiş) sevkiyatlarda planlanan miktarı."""
    total = ShipmentLine.objects.filter(
        order_line=line, shipment__status__in=OPEN_SHIPMENT_STATUSES
    ).aggregate(t=Sum("quantity"))["t"]
    return total or ZERO


def plannable_quantity(line: SalesOrderLine) -> Decimal:
    """Sevkiyata planlanabilecek kalan miktar: sipariş − sevk edilen − açık sevkiyatlarda."""
    return max(line.base_quantity - shipped_quantity(line) - planned_quantity(line), ZERO)


def picked_quantity(line: ShipmentLine) -> Decimal:
    """Sevkiyat satırında toplanmış (geri alınmamış) miktar."""
    return picked_total(line.picks.all())


def remaining_to_pick(line: ShipmentLine) -> Decimal:
    return max(line.quantity - picked_quantity(line), ZERO)


def shipment_payload(shipment: Shipment, **extra: Any) -> dict[str, Any]:
    order = shipment.sales_order
    return {
        "model": "sales.shipment",
        "id": shipment.pk,
        "number": shipment.number,
        "order": {"model": "sales.salesorder", "id": order.pk, "number": order.number},
        "order_number": order.number,
        "customer_code": order.customer.code,
        "customer_name": order.customer.name,
        "vehicle_plate": shipment.vehicle_plate,
        **extra,
    }


def _plan_items(
    order: SalesOrder, lines: Iterable[Mapping[str, Any]] | None
) -> list[tuple[SalesOrderLine, Decimal]]:
    order_lines = {
        line.pk: line
        for line in order.lines.select_related("product__base_unit").order_by("line_no")
    }
    if lines is None:
        defaults = [(line, plannable_quantity(line)) for line in order_lines.values()]
        return [(line, quantity) for line, quantity in defaults if quantity > 0]
    items: list[tuple[SalesOrderLine, Decimal]] = []
    seen: set[int] = set()
    for item in lines:
        ref = item["order_line"]
        line_id = ref.pk if isinstance(ref, SalesOrderLine) else int(ref)
        line = order_lines.get(line_id)
        if line is None:
            raise BusinessRuleError("line_not_found", f"Siparişte {line_id} numaralı satır yok.")
        if line_id in seen:
            raise BusinessRuleError(
                "duplicate_line", f"Satır {line.line_no} sevkiyatta birden fazla kez var."
            )
        seen.add(line_id)
        quantity = quantize(Decimal(item["quantity"]))
        if quantity <= 0:
            continue
        limit = plannable_quantity(line)
        if quantity > limit:
            raise BusinessRuleError(
                "shipment_exceeds_order",
                f"Satır {line.line_no} ({line.product.code}) için en çok "
                f"{format_quantity(limit)} {line.product.base_unit.code} planlanabilir.",
            )
        items.append((line, quantity))
    return items


@transaction.atomic
def plan_shipment(
    actor: User | None,
    order: SalesOrder,
    data: Mapping[str, Any],
    lines: Iterable[Mapping[str, Any]] | None = None,
) -> Shipment:
    """Onaylı (ya da kısmen sevk edilmiş) sipariş için sevkiyat planlar (`SV-`, rol: sevkiyat).

    `lines` verilmezse her sipariş satırının kalan miktarı gelir; verilirse
    `[{"order_line", "quantity"}]` (temel birimde, kalanı aşamaz). Sevk alanı verilmezse
    varsayılan `SHIPPING` lokasyonu. Olay `shipment.planned` depoya "Toplama yap" görevi açar;
    siparişin tamamı planlandıysa "Sevkiyat planla" görevi kapanır."""
    _require_roles(actor, SHIPMENT_ROLES, "Sevkiyatı yalnızca sevkiyat planlar.")
    order = _lock_order(order)
    _require_status(order, RESERVABLE_STATUSES, "order_not_shippable", "sevkiyat planlanamaz")
    shipment = Shipment(sales_order=order, **_shipment_fields(data))
    if shipment.loading_location_id is None:
        shipment.loading_location = default_loading_location()
    _clean_shipment(shipment)
    items = _plan_items(order, lines)
    if not items:
        raise BusinessRuleError(
            "nothing_to_ship", f"{order.number} siparişinde planlanacak kalan miktar yok."
        )
    create_document(shipment, actor, prefix="SV", machine=shipment_states)
    for line, quantity in items:
        save_with_audit(ShipmentLine(shipment=shipment, order_line=line, quantity=quantity), actor)
    fully_planned = all(plannable_quantity(line) == 0 for line in order.lines.all())
    events.publish(
        ev.SHIPMENT_PLANNED,
        shipment_payload(shipment, order_fully_planned=fully_planned),
        _actor(actor),
    )
    return shipment


@transaction.atomic
def update_shipment(actor: User | None, shipment: Shipment, data: Mapping[str, Any]) -> Shipment:
    """Sevk edilmemiş sevkiyatın başlığını (tarih, araç, şoför, taşıyıcı, not) günceller. Sevk
    alanı yalnızca toplama başlamadan değişir."""
    _require_roles(actor, SHIPMENT_ROLES, "Sevkiyatı yalnızca sevkiyat değiştirir.")
    values = _shipment_fields(data)
    shipment = _lock_shipment(shipment)
    _require_shipment_status(shipment, OPEN_SHIPMENT_STATUSES, "document_locked", "değiştirilemez")
    location = values.get("loading_location")
    if location is not None and location.pk != shipment.loading_location_id:
        _require_shipment_status(
            shipment, (ShipmentStatus.PLANNED,), "picking_started", "sevk alanı değiştirilemez"
        )
    for name, value in values.items():
        setattr(shipment, name, value)
    _clean_shipment(shipment)
    return save_with_audit(shipment, actor)


def _line_reservations(
    line: SalesOrderLine, *, lot: Lot | None = None, location: Location | None = None
) -> list[StockReservation]:
    queryset = inventory.reservations_for(line).filter(status=ReservationStatus.ACTIVE)
    if lot is not None:
        queryset = queryset.filter(lot=lot)
    if location is not None:
        queryset = queryset.filter(location=location)
    return list(queryset.select_related("lot", "location").order_by("created_at", "id"))


def _take(
    actor: User | None,
    reservations: Iterable[StockReservation],
    quantity: Decimal,
    note: str,
    *,
    consume: bool,
) -> list[tuple[StockReservation, Decimal]]:
    """Rezervasyonlardan sırayla `quantity` kadarını bırakır ya da kullanır; (rezervasyon,
    miktar) listesi döner. Rezervasyonlar yetmezse kalan miktar sessizce kalır."""
    taken: list[tuple[StockReservation, Decimal]] = []
    for reservation in reservations:
        if quantity <= 0:
            break
        part = min(quantity, reservation.quantity)
        if consume:
            inventory.consume_reservation(actor, reservation, part, note)
        else:
            inventory.release_reservation(actor, reservation, note, quantity=part)
        taken.append((reservation, part))
        quantity -= part
    return taken


def _move_to_loading(
    actor: User | None,
    shipment: Shipment,
    line: ShipmentLine,
    lot: Lot,
    from_location: Location,
    quantity: Decimal,
    reason: str,
) -> ShipmentPick:
    """Lotu sevk alanına transfer eder, orada sipariş satırına rezerve eder ve toplama kaydını
    yazar."""
    loading = shipment.loading_location
    note = f"Toplama {shipment.number}"
    out, _into = inventory.transfer(
        actor, lot, from_location, loading, quantity, source=shipment, note=note
    )
    inventory.reserve(
        actor,
        lot=lot,
        location=loading,
        quantity=quantity,
        source=line.order_line,
        document_number=shipment.sales_order.number,
        note=note,
    )
    assert out.transfer_group is not None
    pick = ShipmentPick(
        line=line,
        lot=lot,
        quantity=quantity,
        from_location=from_location,
        to_location=loading,
        picked_by=_actor(actor),
        picked_at=timezone.now(),
        transfer_group=out.transfer_group,
        deviation_reason=reason,
    )
    return save_with_audit(pick, actor)


def _free_stock_location(lot: Lot, quantity: Decimal) -> Location:
    """Lotun rezervesiz stoğunun yettiği depo lokasyonu (en çok stoklu önce). Karantina ve sevk
    alanları (okutulmuş, başka sevkiyata ayrılmış mal) hariç."""
    rows = (
        inventory_selectors.available_lots(lot.material)
        .filter(lot=lot)
        .exclude(location__location_type__in=UNRESERVABLE_LOCATION_TYPES)
    )
    best = max(rows, key=lambda r: r.available_quantity, default=None)  # type: ignore[attr-defined]
    available = best.available_quantity if best is not None else ZERO  # type: ignore[attr-defined]
    if best is None or available < quantity:
        unit = lot.material.base_unit.code
        raise BusinessRuleError(
            "insufficient_available",
            f"Lot {lot.lot_no} için depoda rezervesiz {format_quantity(available)} {unit} var, "
            f"{format_quantity(quantity)} {unit} toplanamaz.",
        )
    return best.location


def _pick_line(shipment: Shipment, lot: Lot) -> ShipmentLine:
    lines = [
        line
        for line in shipment.lines.select_related("order_line__product__base_unit").order_by(
            "order_line__line_no"
        )
        if line.order_line.product_id == lot.material_id
    ]
    if not lines:
        raise BusinessRuleError(
            "lot_not_in_shipment",
            f"Lot {lot.lot_no} ({lot.material.code}) bu sevkiyatın ürünlerinden değil.",
        )
    for line in lines:
        if remaining_to_pick(line) > 0:
            return line
    raise BusinessRuleError("line_already_picked", f"{lot.material.code} satırı tamamen toplandı.")


@transaction.atomic
def pick_lot(
    actor: User | None,
    shipment: Shipment,
    lot: Lot,
    quantity: Decimal | None = None,
    reason: str = "",
) -> list[ShipmentPick]:
    """Okutulan lotu sevkiyata toplar (rol: depo) ve sevk alanına taşır.

    Lot serbest, SKT'si geçmemiş ve müşterinin asgari kalan raf ömrünü karşılamalıdır.
    `quantity` verilmezse satırın kalan miktarı (satıra bu lottan rezervasyon varsa en çok o
    kadar) toplanır; kalanı aşamaz. Önce satırın bu lottaki rezervasyonu kullanılır; fazlası
    rezervesiz stoktan gelir. Satırın başka lotlarda rezervasyonu varken rezervesiz lot okutmak
    gerekçe ister (`lot_not_reserved`); satır taahhüdünü aşan rezervasyon bırakılır. İlk okutma
    sevkiyatı "Toplanıyor" yapar. Kaynak lokasyon başına bir toplama kaydı döner."""
    _require_roles(actor, PICK_ROLES, "Toplamayı yalnızca depo yapar.")
    actor = _actor(actor)
    shipment = _lock_shipment(shipment)
    _require_shipment_status(
        shipment,
        (ShipmentStatus.PLANNED, ShipmentStatus.PICKING),
        "shipment_not_picking",
        "lot okutulamaz",
    )
    # Kilit sırası: sevkiyat → sipariş → lot → bakiye (rezervasyon ve stok hareketiyle aynı).
    order = _lock_order(shipment.sales_order)
    lot = (
        Lot.objects.select_for_update(of=("self",))
        .select_related("material__base_unit")
        .get(pk=lot.pk)
    )
    line = _pick_line(shipment, lot)
    inventory.assert_lot_usable(lot)
    error = shelf_life_error(lot, order)
    if error is not None:
        raise error
    had_shortage = any(shortage_quantity(other) > 0 for other in order.lines.all())
    # Sevk alanlarındaki rezervasyonlar okutulmuş maldır (bu ya da başka sevkiyat); dokunulmaz.
    reservations = [
        r
        for r in _line_reservations(line.order_line)
        if r.location.location_type != Location.Type.SHIPPING
    ]
    own = [r for r in reservations if r.lot_id == lot.pk]
    others = [r for r in reservations if r.lot_id != lot.pk]
    own_total = sum((r.quantity for r in own), ZERO)
    remaining = remaining_to_pick(line)
    if quantity is None:
        quantity = min(remaining, own_total) if own_total > 0 else remaining
    quantity = quantize(quantity)
    unit = line.order_line.product.base_unit.code
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    if quantity > remaining:
        raise BusinessRuleError(
            "pick_exceeds_line",
            f"Satır {line.order_line.line_no} için en çok {format_quantity(remaining)} {unit} "
            "daha toplanabilir.",
        )
    reason = reason.strip()
    extra = quantity - min(quantity, own_total)
    if extra > 0 and others and not reason:
        lots = ", ".join(sorted({r.lot.lot_no for r in others}))
        raise BusinessRuleError(
            "lot_not_reserved",
            f"Lot {lot.lot_no} bu sipariş için rezerve edilmemiş (rezerve lot: {lots}). Farklı "
            "lot okutmak için gerekçe girin.",
        )
    note = f"Toplama {shipment.number}"
    picks: list[ShipmentPick] = []
    for reservation, part in _take(actor, own, quantity - extra, note, consume=False):
        picks.append(_move_to_loading(actor, shipment, line, lot, reservation.location, part, ""))
    if extra > 0:
        # Satır taahhüdü (sevk edilen + aktif rezervasyon) sipariş miktarını aşmasın: fazlası
        # en geç SKT'li diğer rezervasyondan bırakılır.
        committed = shipped_quantity(line.order_line) + reserved_quantity(line.order_line)
        overflow = committed + extra - line.order_line.base_quantity
        if overflow > 0:
            by_expiry = sorted(
                others,
                key=lambda r: (r.lot.expiry_date is not None, r.lot.expiry_date, r.pk),
                reverse=True,
            )
            _take(
                actor, by_expiry, overflow, f"Farklı lot okutuldu {shipment.number}", consume=False
            )
        source = _free_stock_location(lot, extra)
        picks.append(_move_to_loading(actor, shipment, line, lot, source, extra, reason))
        if had_shortage and all(shortage_quantity(other) == 0 for other in order.lines.all()):
            events.publish(ev.SALES_ORDER_FULLY_RESERVED, _order_payload(order), actor)
    if shipment.status == ShipmentStatus.PLANNED:
        transition_status(
            shipment,
            ShipmentStatus.PICKING,
            actor,
            machine=shipment_states,
            event_payload=shipment_payload(shipment),
        )
    return picks


def _return_pick(actor: User | None, shipment: Shipment, pick: ShipmentPick, note: str) -> None:
    """Toplanan lotu geldiği yere geri transfer eder; sevk alanındaki rezervasyonu bırakır ve
    lot hâlâ kullanılabilirse geldiği yerde satıra yeniden rezerve eder."""
    order_line = pick.line.order_line
    loading = shipment.loading_location
    _take(
        actor,
        _line_reservations(order_line, lot=pick.lot, location=loading),
        pick.quantity,
        note,
        consume=False,
    )
    inventory.transfer(
        actor, pick.lot, loading, pick.from_location, pick.quantity, source=shipment, note=note
    )
    pick.returned_at = timezone.now()
    save_with_audit(pick, actor, note=note)
    order = shipment.sales_order
    room = order_line.base_quantity - shipped_quantity(order_line) - reserved_quantity(order_line)
    usable = (
        inventory.lot_usable_error(pick.lot) is None
        and shelf_life_error(pick.lot, order) is None
        and pick.from_location.location_type != Location.Type.QUARANTINE
        and order.status in RESERVABLE_STATUSES
    )
    if usable and room > 0:
        inventory.reserve(
            actor,
            lot=pick.lot,
            location=pick.from_location,
            quantity=min(room, pick.quantity),
            source=order_line,
            document_number=order.number,
            note=note,
        )


def _lock_lots(lot_ids: Iterable[int]) -> None:
    """Lot satırlarını kimlik sırasıyla kilitler; bakiye ve rezervasyon kilitlerinden önce
    (rezervasyon ve stok hareketi de lot → bakiye sırasıyla kilitler)."""
    list(
        Lot.objects.select_for_update(of=("self",))
        .filter(pk__in=set(lot_ids))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


@transaction.atomic
def undo_pick(actor: User | None, pick: ShipmentPick, note: str = "") -> ShipmentPick:
    """Yanlış okutmayı geri alır (rol: depo; toplama sürerken ya da yüklemeden sonra, sevkten
    önce): lot geldiği yere döner. Yüklenmiş sevkiyatta durum Yüklendi kalır."""
    _require_roles(actor, PICK_ROLES, "Toplamayı yalnızca depo geri alır.")
    shipment = _lock_shipment(pick.line.shipment)
    _require_shipment_status(
        shipment,
        (ShipmentStatus.PICKING, ShipmentStatus.LOADED),
        "shipment_not_picking",
        "okutma geri alınamaz",
    )
    _lock_order(shipment.sales_order)
    _lock_lots([pick.lot_id])
    pick = ShipmentPick.objects.select_related(
        "lot__material__base_unit", "from_location", "line__order_line"
    ).get(pk=pick.pk)
    if pick.returned_at is not None:
        raise BusinessRuleError("pick_already_returned", "Bu okutma zaten geri alınmış.")
    _return_pick(actor, shipment, pick, note or f"Okutma geri alındı {shipment.number}")
    return pick


def active_picks(shipment: Shipment) -> list[ShipmentPick]:
    """Sevkiyatın geri alınmamış toplama kayıtları."""
    return list(
        ShipmentPick.objects.filter(line__shipment=shipment, returned_at__isnull=True)
        .select_related("lot__material__base_unit", "from_location", "line__order_line__product")
        .order_by("line__order_line__line_no", "picked_at", "id")
    )


def _assert_picks_shippable(shipment: Shipment, picks: Sequence[ShipmentPick], hint: str) -> None:
    """Her okutulan lot kullanılabilir olmalı ve satır + lot başına okutulan toplam, sevk
    alanında o satıra ayrılmış rezervasyonla karşılanmalı. `hint` hatada ne yapılacağını söyler."""
    needed: dict[tuple[int, int], tuple[ShipmentPick, Decimal]] = {}
    for pick in picks:
        error = inventory.lot_usable_error(pick.lot)
        if error is not None:
            raise BusinessRuleError(
                "picked_lot_unusable",
                f"{error.message} {hint}",
            )
        key = (pick.line.order_line_id, pick.lot_id)
        first, total = needed.get(key, (pick, ZERO))
        needed[key] = (first, total + pick.quantity)
    for pick, total in needed.values():
        reserved = sum(
            (
                r.quantity
                for r in _line_reservations(
                    pick.line.order_line, lot=pick.lot, location=shipment.loading_location
                )
            ),
            ZERO,
        )
        if reserved < total:
            raise BusinessRuleError(
                "picked_lot_unreserved",
                f"Lot {pick.lot.lot_no} sevk alanında bu siparişe rezerve değil. {hint}",
            )


@transaction.atomic
def mark_loaded(actor: User | None, shipment: Shipment, note: str = "") -> Shipment:
    """Toplama bitti, araç yüklendi (rol: depo): `LOADED`. Olay `shipment.loaded` sevkiyata
    "Sevki onayla / irsaliye kes" görevi açar. Planlanandan az toplanan satır eksik sevk edilir."""
    _require_roles(actor, PICK_ROLES, "Yüklemeyi yalnızca depo onaylar.")
    actor = _actor(actor)
    shipment = _lock_shipment(shipment)
    shipment_states.assert_can_transition(shipment.status, ShipmentStatus.LOADED)
    picks = active_picks(shipment)
    if not picks:
        raise BusinessRuleError("nothing_picked", "Hiç lot okutulmadan yükleme onaylanamaz.")
    _assert_picks_shippable(shipment, picks, "Okutmayı geri alıp yeniden toplayın.")
    shipment.loaded_at = timezone.now()
    shipment.loaded_by = actor
    shipment.save(update_fields=["loaded_at", "loaded_by"])
    return transition_status(
        shipment,
        ShipmentStatus.LOADED,
        actor,
        machine=shipment_states,
        note=note,
        event_payload=shipment_payload(shipment),
    )


def _update_order_shipping_status(actor: User | None, order: SalesOrder) -> None:
    complete = all(shipped_quantity(line) >= line.base_quantity for line in order.lines.all())
    target = Status.SHIPPED if complete else Status.PARTIALLY_SHIPPED
    if order.status != target:
        transition_status(
            order,
            target,
            actor,
            machine=sales_order_states,
            event_payload=_order_payload(order),
        )


@transaction.atomic
def dispatch_shipment(actor: User | None, shipment: Shipment, note: str = "") -> Shipment:
    """Sevki onaylar (rol: sevkiyat): plaka ve şoför adı zorunlu; her toplanan lot için sevk
    alanındaki rezervasyon kullanılır (`CONSUMED`) ve `SHIPMENT` hareketi yazılır. Sipariş
    kısmen sevk edildi / sevk edildi olur. Olay `shipment.dispatched`."""
    _require_roles(actor, SHIPMENT_ROLES, "Sevki yalnızca sevkiyat onaylar.")
    actor = _actor(actor)
    shipment = _lock_shipment(shipment)
    shipment_states.assert_can_transition(shipment.status, ShipmentStatus.DISPATCHED)
    if not shipment.vehicle_plate or not shipment.driver_name:
        raise BusinessRuleError(
            "vehicle_required", "Sevk için araç plakası ve şoför adı girilmelidir."
        )
    order = _lock_order(shipment.sales_order)
    picks = active_picks(shipment)
    if not picks:
        raise BusinessRuleError("nothing_picked", "Okutulmuş lot kalmadı; sevk onaylanamaz.")
    _lock_lots(pick.lot_id for pick in picks)
    picks = active_picks(shipment)  # kilitten sonra güncel lot durumuyla
    hint = "Depo okutmayı geri alsın; eksik kalan miktar yeni sevkiyatla gönderilir."
    _assert_picks_shippable(shipment, picks, hint)
    loading = shipment.loading_location
    message = f"Sevkiyat {shipment.number}"
    lots: list[dict[str, Any]] = []
    for pick in picks:
        taken = _take(
            actor,
            _line_reservations(pick.line.order_line, lot=pick.lot, location=loading),
            pick.quantity,
            message,
            consume=True,
        )
        if sum((part for _, part in taken), ZERO) != pick.quantity:
            raise BusinessRuleError(
                "picked_lot_unreserved",
                f"Lot {pick.lot.lot_no} sevk alanında bu siparişe rezerve değil. {hint}",
            )
        pick.movement = inventory.post_movement(
            actor,
            pick.lot.material,
            pick.lot,
            loading,
            -pick.quantity,
            inventory.MovementType.SHIPMENT,
            shipment,
            message,
        )
        save_with_audit(pick, actor, note=message)
        lots.append(inventory.lot_payload(pick.lot, quantity=format_quantity(pick.quantity)))
    shipment.dispatched_at = timezone.now()
    shipment.dispatched_by = actor
    shipment.save(update_fields=["dispatched_at", "dispatched_by"])
    shipment.sales_order = order
    transition_status(
        shipment,
        ShipmentStatus.DISPATCHED,
        actor,
        machine=shipment_states,
        note=note,
        event_payload=shipment_payload(
            shipment, order_created_by_id=order.created_by_id, lots=lots
        ),
    )
    _update_order_shipping_status(actor, order)
    return shipment


@transaction.atomic
def cancel_shipment(actor: User | None, shipment: Shipment, reason: str) -> Shipment:
    """Sevk edilmemiş sevkiyatı iptal eder (rol: sevkiyat, gerekçe zorunlu); toplanan lotlar
    geldikleri yere döner ve satıra yeniden rezerve edilir."""
    _require_roles(actor, SHIPMENT_ROLES, "Sevkiyatı yalnızca sevkiyat iptal eder.")
    shipment = _lock_shipment(shipment)
    shipment_states.assert_can_transition(shipment.status, ShipmentStatus.CANCELLED)
    if not reason.strip():
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    _lock_order(shipment.sales_order)
    _lock_lots(pick.lot_id for pick in active_picks(shipment))
    for pick in active_picks(shipment):  # kilitten sonra güncel lot durumuyla
        _return_pick(actor, shipment, pick, f"Sevkiyat iptali {shipment.number}")
    return cancel_document(shipment, actor, reason=reason, machine=shipment_states)
