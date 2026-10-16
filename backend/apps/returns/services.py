"""Müşteri iadesi servisleri (Faz 3, Adım 3.3).

Kurallar:
- İade sevkiyat rolüyle taslak açılır; teslim alınınca (sevkiyat ya da depo) her satır `RETURN`
  hareketiyle karantina lokasyonuna girer. Lot numarası değişmez.
- Lotun tamamı karara kadar bekler: serbest lot bloke edilir ve laboratuvara iade numunesi
  (`stage=RETURN`) açılır; lotta zaten açık numune varsa o kullanılır. Reddedilmiş lot için numune
  açılmaz, satır doğrudan imhaya gider.
- Kalite kararı satırın sonucunu belirler (`returns.handlers`): lot serbest → yeniden sevke uygun
  (karantinadaki iade miktarı kalite kararında seçilen depoya taşınır), yeniden işleme → lot bloke
  kalır ve planlamaya görev düşer, ret → imha. İmha, depo ya da sevkiyatın `scrap_line` ile
  yazdığı `SCRAP` hareketidir.
- Her satır sonuçlanınca iade kapanır (`CLOSED`). Teslim alınan iade iptal edilmez.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
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
from apps.core.roles import DEPO, SEVKIYAT
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockMovement
from apps.inventory.services import format_quantity, lot_payload, quantize
from apps.masterdata import services as masterdata
from apps.masterdata.models import Location, Material
from apps.quality import services as quality
from apps.quality.models import QualityDecision, Sample, SampleStage
from apps.returns.models import CustomerReturn, CustomerReturnLine
from apps.returns.state import customer_return_states
from apps.sales import selectors as sales_selectors
from apps.sales.models import Shipment

EDIT_ROLES = (SEVKIYAT,)
RECEIVE_ROLES = (SEVKIYAT, DEPO)
SCRAP_ROLES = (DEPO, SEVKIYAT)

RETURN_FIELDS = ("customer", "shipment", "return_date", "reason", "quarantine_location", "note")
LINE_FIELDS = ("product", "lot", "quantity", "unit")

Disposition = CustomerReturnLine.Disposition
Decision = QualityDecision.Decision


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def _require_role(actor: User | None, roles: tuple[str, ...], message: str) -> None:
    if not user_has_role(actor, roles):
        raise PermissionDenied(message)


def _pick(data: Mapping[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


def _lock(customer_return: CustomerReturn) -> CustomerReturn:
    return (
        CustomerReturn.objects.select_for_update(of=("self",))
        .select_related("customer", "quarantine_location")
        .get(pk=customer_return.pk)
    )


def return_payload(customer_return: CustomerReturn, **extra: Any) -> dict[str, Any]:
    """İade olaylarının ek alanları: müşteri ve satır lotları."""
    lines = customer_return.lines.select_related("lot__material").order_by("line_no")
    return {
        "customer_code": customer_return.customer.code,
        "customer_name": customer_return.customer.name,
        "lots": [lot_payload(line.lot, disposition=line.disposition) for line in lines],
        **extra,
    }


# --- doğrulama -------------------------------------------------------------------------------


def _validate_header(customer_return: CustomerReturn) -> None:
    if not customer_return.customer.is_active:
        raise BusinessRuleError(
            "inactive_reference", f"Pasif müşteri seçilemez: {customer_return.customer}."
        )
    location = customer_return.quarantine_location
    if not location.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif lokasyon seçilemez: {location}.")
    if location.location_type != Location.Type.QUARANTINE:
        raise BusinessRuleError(
            "invalid_quarantine_location",
            "İade edilen ürün “Karantina” türündeki bir lokasyona alınır.",
        )
    customer_return.reason = (customer_return.reason or "").strip()
    if not customer_return.reason:
        raise BusinessRuleError("reason_required", "İade nedeni girilmelidir.")
    shipment = customer_return.shipment
    if shipment is not None:
        if shipment.status != Shipment.Status.DISPATCHED:
            raise BusinessRuleError(
                "shipment_not_dispatched",
                f"{shipment.number} sevk edilmemiş; iade yalnızca sevk edilmiş sevkiyata bağlanır.",
            )
        if shipment.sales_order.customer_id != customer_return.customer_id:
            raise BusinessRuleError(
                "shipment_customer_mismatch",
                f"{shipment.number} başka bir müşterinin sevkiyatı.",
            )


def _check_against_shipment(
    customer_return: CustomerReturn, lines: Iterable[CustomerReturnLine]
) -> None:
    """Sevkiyata bağlı iadede her lotun iade miktarı, o sevkiyatta o lottan sevk edilenden
    (aynı sevkiyata bağlı diğer iadeler düşülerek) fazla olamaz."""
    shipment = customer_return.shipment
    if shipment is None:
        return
    # Aynı sevkiyata bağlı iadeler sırayla denetlensin: eşzamanlı iki teslim alma birbirinin
    # kaydedilmemiş miktarını görmeden sınırı aşmasın.
    list(Shipment.objects.select_for_update().filter(pk=shipment.pk).values_list("pk"))
    shipped = sales_selectors.shipped_by_shipment_lot(shipment)
    returned = dict(
        CustomerReturnLine.objects.filter(customer_return__shipment=shipment)
        .exclude(customer_return=customer_return)
        .exclude(customer_return__status=CustomerReturn.Status.CANCELLED)
        .values("lot_id")
        .annotate(total=Sum("base_quantity"))
        .values_list("lot_id", "total")
    )
    wanted: dict[int, Decimal] = defaultdict(Decimal)
    for line in lines:
        wanted[line.lot_id] += quantize(
            masterdata.to_base_quantity(line.product, line.quantity, line.unit)
        )
        if line.lot_id not in shipped:
            raise BusinessRuleError(
                "lot_not_in_shipment",
                f"Lot {line.lot.lot_no} {shipment.number} sevkiyatında sevk edilmedi.",
            )
        limit = shipped[line.lot_id] - (returned.get(line.lot_id) or Decimal(0))
        if wanted[line.lot_id] > limit:
            unit = line.product.base_unit.code
            raise BusinessRuleError(
                "return_exceeds_shipped",
                f"Lot {line.lot.lot_no}: {shipment.number} ile {format_quantity(limit)} {unit} "
                "iade edilebilir (sevk edilen, önceki iadeler düşülerek).",
            )


def _validate_line(line: CustomerReturnLine) -> None:
    product = line.product
    if product.material_type != Material.Type.FINISHED:
        raise BusinessRuleError(
            "return_material_type", f"{product.code}: iadede yalnızca mamul ürün alınır."
        )
    if line.lot.material_id != product.pk:
        raise BusinessRuleError(
            "lot_material_mismatch", f"Lot {line.lot.lot_no} {product.code} ürününe ait değil."
        )
    if line.quantity is None or line.quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    if not line.unit.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif birim seçilemez: {line.unit}.")
    # Birim temel birime çevrilebilmeli (yoksa no_conversion).
    masterdata.to_base_quantity(product, line.quantity, line.unit)


def _sync_lines(
    actor: User | None, customer_return: CustomerReturn, items: Iterable[Mapping[str, Any]]
) -> None:
    """Taslağın satırlarını listeyle eşitler: `id`'li satır güncellenir, `id`'siz eklenir,
    listede olmayan kaldırılır (denetim kaydıyla)."""
    manager = customer_return.lines
    existing = {line.pk: line for line in manager.select_for_update().order_by("line_no")}
    next_no = (manager.aggregate(m=Max("line_no"))["m"] or 0) + 1
    keep: set[int] = set()
    pending: list[CustomerReturnLine] = []
    lots: set[int] = set()
    for item in items:
        values = dict(item)
        line_id = values.pop("id", None)
        values = _pick(values, LINE_FIELDS)
        if line_id is not None:
            line = existing.get(line_id)
            if line is None:
                raise BusinessRuleError("line_not_found", f"İadede {line_id} numaralı satır yok.")
            keep.add(line_id)
            for name, value in values.items():
                setattr(line, name, value)
        else:
            line = CustomerReturnLine(customer_return=customer_return, line_no=next_no, **values)
            next_no += 1
        _validate_line(line)
        if line.lot_id in lots:
            raise BusinessRuleError(
                "duplicate_lot", f"Lot {line.lot.lot_no} iadede birden fazla satırda var."
            )
        lots.add(line.lot_id)
        pending.append(line)
    for line_id, line in existing.items():
        if line_id in keep:
            continue
        log_change(
            _actor(actor),
            customer_return,
            AuditLog.Action.UPDATE,
            {"line": [snapshot(line), None]},
            f"Satır {line.line_no} kaldırıldı (taslak)",
        )
        line.delete()
    _check_against_shipment(customer_return, pending)
    for line in pending:
        save_with_audit(line, actor)


def _require_draft(customer_return: CustomerReturn) -> None:
    if customer_return.status != CustomerReturn.Status.DRAFT:
        raise BusinessRuleError(
            "document_locked",
            f"{customer_return.number} "
            f"{customer_return_states.label(customer_return.status).lower()}; değiştirilemez.",
        )


# --- taslak ----------------------------------------------------------------------------------


@transaction.atomic
def create_return(
    actor: User | None, data: Mapping[str, Any], lines: Iterable[Mapping[str, Any]] = ()
) -> CustomerReturn:
    """Taslak iade açar (`IA-`, rol: sevkiyat); satırlar (ürün, lot, miktar, birim) birlikte."""
    _require_role(actor, EDIT_ROLES, "İadeyi yalnızca sevkiyat kaydeder.")
    customer_return = CustomerReturn(**_pick(data, RETURN_FIELDS))
    _validate_header(customer_return)
    create_document(customer_return, actor, prefix="IA", machine=customer_return_states)
    _sync_lines(actor, customer_return, lines)
    return customer_return


@transaction.atomic
def update_return(
    actor: User | None,
    customer_return: CustomerReturn,
    data: Mapping[str, Any],
    lines: Iterable[Mapping[str, Any]] | None = None,
) -> CustomerReturn:
    """Taslak iadeyi günceller; `lines` verilirse satırları onunla eşitler."""
    _require_role(actor, EDIT_ROLES, "İadeyi yalnızca sevkiyat değiştirir.")
    values = _pick(data, RETURN_FIELDS)
    customer_return = _lock(customer_return)
    _require_draft(customer_return)
    for name, value in values.items():
        setattr(customer_return, name, value)
    _validate_header(customer_return)
    save_with_audit(customer_return, actor)
    if lines is not None:
        _sync_lines(actor, customer_return, lines)
    return customer_return


@transaction.atomic
def cancel_return(
    actor: User | None, customer_return: CustomerReturn, reason: str
) -> CustomerReturn:
    """Taslak iadeyi iptal eder (neden zorunlu). Teslim alınmış iade iptal edilmez."""
    _require_role(actor, EDIT_ROLES, "İadeyi yalnızca sevkiyat iptal eder.")
    return cancel_document(customer_return, actor, reason=reason, machine=customer_return_states)


# --- teslim alma -----------------------------------------------------------------------------


def _hold_lot(actor: User | None, lot: Lot, customer_return: CustomerReturn) -> Sample | None:
    """Lotu karara kadar bekletir ve kararı verecek numuneyi döner (reddedilmiş lotta None)."""
    lot = Lot.objects.select_for_update().get(pk=lot.pk)
    if lot.status == Lot.Status.REJECTED:
        return None
    if lot.status == Lot.Status.RELEASED:
        inventory.block_lot(
            actor,
            lot,
            f"İade {customer_return.number}: kalite kararına kadar bekletiliyor.",
            quality_decision=True,
        )
    open_sample = (
        Sample.objects.filter(lot=lot, status__in=quality.OPEN_SAMPLE_STATUSES)
        .order_by("-created_at", "-id")
        .first()
    )
    if open_sample is not None:
        return open_sample
    return quality.open_sample(
        actor,
        lot,
        SampleStage.RETURN,
        origin=Sample.Origin.RETURN,
        note=f"İade {customer_return.number} ({customer_return.customer.name}): "
        f"{customer_return.reason}",
    )


@transaction.atomic
def receive_return(actor: User | None, customer_return: CustomerReturn) -> CustomerReturn:
    """İadeyi teslim alır (rol: sevkiyat, depo).

    Her satır temel birime çevrilir ve `RETURN` hareketiyle karantina lokasyonuna girer. Serbest
    lot bloke edilir ve iade numunesi açılır (lotta açık numune varsa satır ona bağlanır);
    reddedilmiş lotun satırı doğrudan imha bekler. Olay: `customer_return.received`.
    """
    _require_role(actor, RECEIVE_ROLES, "İadeyi yalnızca sevkiyat ya da depo teslim alır.")
    actor = _actor(actor)
    customer_return = _lock(customer_return)
    customer_return_states.assert_can_transition(
        customer_return.status, CustomerReturn.Status.RECEIVED
    )
    _validate_header(customer_return)
    lines = list(
        customer_return.lines.select_for_update(of=("self",))
        .select_related("product__base_unit", "lot", "unit")
        .order_by("line_no")
    )
    if not lines:
        raise BusinessRuleError("document_empty", "Satırı olmayan iade teslim alınamaz.")
    _check_against_shipment(customer_return, lines)
    location = customer_return.quarantine_location
    scrap_needed = False
    for line in lines:
        _validate_line(line)
        base_quantity = quantize(
            masterdata.to_base_quantity(line.product, line.quantity, line.unit)
        )
        if base_quantity <= 0:
            raise BusinessRuleError(
                "quantity_too_small", f"Satır {line.line_no}: miktar temel birimde sıfıra iniyor."
            )
        line.movement = inventory.post_movement(
            actor,
            line.product,
            line.lot,
            location,
            base_quantity,
            StockMovement.Type.RETURN,
            customer_return,
            note=f"Müşteri iadesi: {customer_return.customer.name}",
        )
        line.base_quantity = base_quantity
        line.sample = _hold_lot(actor, line.lot, customer_return)
        fields = ["movement", "base_quantity", "sample", "updated_at"]
        if line.sample is None:
            line.disposition = Disposition.SCRAP
            line.decided_at = timezone.now()
            fields += ["disposition", "decided_at"]
            scrap_needed = True
        line.save(update_fields=fields)
    customer_return.received_at = timezone.now()
    customer_return.received_by = actor
    customer_return.save(update_fields=["received_at", "received_by", "updated_at"])
    transition_status(
        customer_return,
        CustomerReturn.Status.RECEIVED,
        actor,
        machine=customer_return_states,
        event_payload=return_payload(customer_return),
    )
    if scrap_needed:
        _publish_scrap_required(actor, customer_return)
    return customer_return


# --- kalite kararı ve imha -------------------------------------------------------------------


def _publish_scrap_required(actor: User | None, customer_return: CustomerReturn) -> None:
    events.publish(
        ev.CUSTOMER_RETURN_SCRAP_REQUIRED,
        {
            "model": customer_return._meta.label_lower,
            "id": customer_return.pk,
            "number": customer_return.number,
            **return_payload(customer_return),
        },
        _actor(actor),
    )


def _close_if_settled(actor: User | None, customer_return: CustomerReturn) -> None:
    if customer_return.status != CustomerReturn.Status.RECEIVED:
        return
    if not all(line.is_settled for line in customer_return.lines.all()):
        return
    customer_return.closed_at = timezone.now()
    customer_return.save(update_fields=["closed_at", "updated_at"])
    transition_status(
        customer_return,
        CustomerReturn.Status.CLOSED,
        actor,
        machine=customer_return_states,
        event_payload=return_payload(customer_return),
    )


DECISION_DISPOSITIONS: dict[str, str] = {
    Decision.RELEASE: Disposition.RESTOCK,
    Decision.CONDITIONAL_RELEASE: Disposition.RESTOCK,
    Decision.REWORK: Disposition.REWORK,
    Decision.REJECT: Disposition.SCRAP,
}


@transaction.atomic
def apply_lot_outcome(actor: User | None, lot: Lot, disposition: str, note: str = "") -> int:
    """Lotun kalite sonucunu karar bekleyen iade satırlarına uygular (`returns.handlers` çağırır;
    yetkiyi kararı veren kalite servisi denetlemiştir). Satır sayısını döner.

    İmha kararında depoya görev düşer; her satırı sonuçlanan iade kapanır."""
    if disposition not in Disposition.values or disposition == Disposition.PENDING:
        raise ValueError(f"Geçersiz iade sonucu: {disposition}")
    actor = _actor(actor)
    lines = list(
        CustomerReturnLine.objects.select_for_update(of=("self",))
        .select_related("customer_return")
        .filter(
            lot=lot,
            disposition=Disposition.PENDING,
            customer_return__status=CustomerReturn.Status.RECEIVED,
        )
        .order_by("id")
    )
    returns: dict[int, CustomerReturn] = {}
    for line in lines:
        before = line.disposition
        line.disposition = disposition
        line.decided_at = timezone.now()
        line.updated_by = actor
        line.save(update_fields=["disposition", "decided_at", "updated_by", "updated_at"])
        log_change(
            actor,
            line.customer_return,
            AuditLog.Action.UPDATE,
            {f"line_{line.line_no}.disposition": [before, disposition]},
            note,
        )
        returns[line.customer_return_id] = line.customer_return
    for customer_return in returns.values():
        customer_return = _lock(customer_return)
        if disposition == Disposition.SCRAP:
            _publish_scrap_required(actor, customer_return)
        _close_if_settled(actor, customer_return)
    return len(lines)


@transaction.atomic
def scrap_line(actor: User | None, line: CustomerReturnLine, note: str = "") -> CustomerReturnLine:
    """İmha kararı verilen satırın iade miktarını karantinadan `SCRAP` hareketiyle düşer (rol:
    depo, sevkiyat). Her satırı sonuçlanan iade kapanır."""
    _require_role(actor, SCRAP_ROLES, "İmhayı yalnızca depo ya da sevkiyat kaydeder.")
    actor = _actor(actor)
    line = (
        CustomerReturnLine.objects.select_for_update(of=("self",))
        .select_related("customer_return__quarantine_location", "product", "lot")
        .get(pk=line.pk)
    )
    if line.disposition != Disposition.SCRAP:
        raise BusinessRuleError(
            "scrap_not_decided", "Yalnızca imha kararı verilen iade satırı imha edilir."
        )
    if line.scrap_movement_id is not None:
        raise BusinessRuleError("already_scrapped", f"Satır {line.line_no} zaten imha edildi.")
    assert line.base_quantity is not None
    customer_return = line.customer_return
    text = f"İade {customer_return.number} imha"
    if note.strip():
        text = f"{text}: {note.strip()}"
    line.scrap_movement = inventory.post_movement(
        actor,
        line.product,
        line.lot,
        customer_return.quarantine_location,
        -line.base_quantity,
        StockMovement.Type.SCRAP,
        customer_return,
        note=text,
    )
    line.updated_by = actor
    line.save(update_fields=["scrap_movement", "updated_by", "updated_at"])
    log_change(
        actor,
        customer_return,
        AuditLog.Action.UPDATE,
        {f"line_{line.line_no}.scrapped": [False, True]},
        text,
    )
    _close_if_settled(actor, _lock(customer_return))
    return line
