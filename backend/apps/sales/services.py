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
"""

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
from apps.core.roles import SEVKIYAT, YONETIM
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockReservation
from apps.inventory.services import format_quantity, quantize
from apps.masterdata import services as masterdata
from apps.masterdata.models import Customer, Location, Material
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.sales.state import sales_order_states

ORDER_ROLES = (SEVKIYAT, YONETIM)

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
    _release_all(actor, order, f"Sipariş kapandı {order.number}")
    order.closed_at = timezone.now()
    order.save(update_fields=["closed_at"])
    return transition_status(order, Status.CLOSED, actor, machine=sales_order_states, note=note)


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
        location__location_type=Location.Type.QUARANTINE
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
