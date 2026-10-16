"""Satın alma servisleri (Faz 4, Adım 4.2).

Kurallar:
- Talep (`ST-`) hammadde ya da ambalaj içindir; miktar temel birimdedir. Açık talep siparişe
  bağlanınca `ORDERED` olur; sipariş iptal edilir ya da satır kaldırılırsa yeniden `OPEN` olur.
- Sabah kontrolünde (07:00) `selectors.purchase_suggestions` önerileri otomatik talep olarak açılır.
- Sipariş (`SA-`) satırları yalnızca taslakta değişir. Onay (Karar D-13): TL tutar = toplam × kur;
  limit girilmiş ve tutar limit içindeyse satin_alma onaylar, değilse yalnızca yonetim.
  satin_alma "Yönetim onayına gönder" der (`PENDING_APPROVAL`); yonetim onaylar ya da gerekçeyle
  taslağa geri gönderir. Her onay denetim günlüğüne tutar ve limitle yazılır.
- Siparişten mal kabul: satırlar sipariş satırının birimi ve fiyatıyla açılır, bağ
  `ReceiptLineLink` ile tutulur. Mal kabul kaydedilirken (inventory kancası) fazla teslim toleransı
  ve sipariş durumu denetlenir; sipariş kısmen teslim alındı / teslim alındı olur.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.audit import log_change, snapshot
from apps.core.exceptions import BusinessRuleError
from apps.core.formatting import format_money
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import DEPO, PLANLAMA, SATIN_ALMA, URETIM, YONETIM
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceipt, GoodsReceiptLine
from apps.inventory.services import format_quantity, quantize
from apps.masterdata import services as masterdata
from apps.masterdata.models import Material
from apps.purchasing import selectors
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchasingSettings,
    ReceiptLineLink,
)
from apps.purchasing.state import purchase_order_states, purchase_request_states

logger = logging.getLogger(__name__)

ORDER_ROLES = (SATIN_ALMA, YONETIM)
APPROVER_ROLES = (YONETIM,)
REQUEST_ROLES = (PLANLAMA, DEPO, URETIM, SATIN_ALMA, YONETIM)
# Siparişten mal kabulü depo yapar; satın alma da açabilir.
RECEIPT_ROLES = (DEPO, SATIN_ALMA, YONETIM)

Status = PurchaseOrder.Status
RequestStatus = PurchaseRequest.Status
ZERO = Decimal(0)
HUNDRED = Decimal(100)

ORDER_FIELDS = ("supplier", "order_date", "currency", "exchange_rate", "notes")
LINE_FIELDS = ("material", "quantity", "unit", "unit_price", "expected_date", "note", "requests")
REQUEST_FIELDS = ("material", "quantity", "need_date", "reason")
SETTINGS_FIELDS = ("approval_limit_try", "over_receipt_tolerance_pct")
RECEIPT_HEADER_FIELDS = (
    "receipt_date",
    "delivery_note_no",
    "quarantine_location",
    "storage_location",
    "note",
)
RECEIPT_LINE_FIELDS = (
    "order_line",
    "quantity",
    "supplier_lot_no",
    "manufactured_at",
    "expiry_date",
)
TEXT_FIELDS = frozenset({"notes", "note", "reason", "delivery_note_no", "supplier_lot_no"})
CANCELLABLE_STATUSES = (Status.DRAFT, Status.PENDING_APPROVAL, Status.APPROVED, Status.SENT)


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def _require_role(actor: User | None, roles: tuple[str, ...], message: str) -> None:
    if not user_has_role(actor, roles):
        raise PermissionDenied(message)


def _pick(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return {name: ("" if name in TEXT_FIELDS and v is None else v) for name, v in data.items()}


def _require_note(note: str, code: str, message: str) -> str:
    note = (note or "").strip()
    if not note:
        raise BusinessRuleError(code, message)
    return note


def _require_purchasable(material: Material) -> None:
    if not material.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif malzeme seçilemez: {material}.")
    if material.material_type not in selectors.PURCHASABLE_TYPES:
        raise BusinessRuleError(
            "purchase_material_type",
            f"{material.code}: satın almada yalnızca hammadde ve ambalaj alınır.",
        )


def _material_payload(material: Material) -> dict[str, Any]:
    return {
        "material_id": material.pk,
        "material_code": material.code,
        "material_name": material.name,
        "unit": material.base_unit.code,
    }


# --- ayarlar (Karar D-13) --------------------------------------------------------------------


def get_settings() -> PurchasingSettings:
    """Tek satırlık satın alma ayarı (yoksa varsayılanla oluşturulur)."""
    instance = PurchasingSettings.objects.order_by("pk").first()
    if instance is None:
        instance = PurchasingSettings.objects.create()
    return instance


@transaction.atomic
def update_settings(actor: User, data: Mapping[str, Any]) -> PurchasingSettings:
    """Onay limitini ve fazla teslim toleransını günceller. Yalnızca yönetim (denetim kaydıyla)."""
    _require_role(actor, APPROVER_ROLES, "Satın alma ayarlarını yalnızca yönetim değiştirir.")
    instance = PurchasingSettings.objects.select_for_update().get(pk=get_settings().pk)
    for name, value in _pick(data, SETTINGS_FIELDS).items():
        setattr(instance, name, value)
    if instance.approval_limit_try is not None and instance.approval_limit_try < 0:
        raise BusinessRuleError("invalid_limit", "Onay limiti negatif olamaz.")
    if instance.over_receipt_tolerance_pct is None or instance.over_receipt_tolerance_pct < 0:
        raise BusinessRuleError("invalid_tolerance", "Fazla teslim toleransı negatif olamaz.")
    return save_with_audit(instance, actor)


# --- talep -----------------------------------------------------------------------------------


def _request_payload(request: PurchaseRequest) -> dict[str, Any]:
    return {
        **_material_payload(request.material),
        "quantity": str(request.quantity),
        "need_date": request.need_date.isoformat(),
        "source": request.source,
        "reason": request.reason,
    }


def _validate_request(request: PurchaseRequest) -> None:
    _require_purchasable(request.material)
    if request.quantity is None or request.quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    request.quantity = quantize(request.quantity)


@transaction.atomic
def create_request(
    actor: User | None,
    data: Mapping[str, Any],
    *,
    source: str = PurchaseRequest.Source.MANUAL,
) -> PurchaseRequest:
    """Satın alma talebi açar (`ST-`, miktar malzemenin temel biriminde). Manuel talebi planlama,
    depo, üretim, satın alma ve yönetim açar; otomatik talebi sabah kontrolü açar (actor yok).
    Olay: `purchase_request.created` → satin_alma görevi."""
    if source == PurchaseRequest.Source.MANUAL:
        _require_role(actor, REQUEST_ROLES, "Satın alma talebi açma yetkiniz yok.")
    request = PurchaseRequest(**_pick(data, REQUEST_FIELDS), source=source)
    _validate_request(request)
    return create_document(
        request,
        actor,
        prefix="ST",
        machine=purchase_request_states,
        event_payload=_request_payload(request),
    )


def _lock_request(request: PurchaseRequest) -> PurchaseRequest:
    return (
        PurchaseRequest.objects.select_for_update(of=("self",))
        .select_related("material__base_unit")
        .get(pk=request.pk)
    )


def _can_edit_request(actor: User | None, request: PurchaseRequest) -> bool:
    if user_has_role(actor, ORDER_ROLES):
        return True
    return actor is not None and request.created_by_id == actor.pk


@transaction.atomic
def update_request(
    actor: User | None, request: PurchaseRequest, data: Mapping[str, Any]
) -> PurchaseRequest:
    """Açık talebi günceller (talebi açan ya da satın alma / yönetim)."""
    request = _lock_request(request)
    if not _can_edit_request(actor, request):
        raise PermissionDenied("Bu talebi yalnızca açan kişi ya da satın alma değiştirebilir.")
    if request.status != RequestStatus.OPEN:
        raise BusinessRuleError(
            "document_locked",
            f"{request.number} {purchase_request_states.label(request.status).lower()}; "
            "değiştirilemez.",
        )
    for name, value in _pick(data, REQUEST_FIELDS).items():
        setattr(request, name, value)
    _validate_request(request)
    return save_with_audit(request, actor)


@transaction.atomic
def cancel_request(actor: User | None, request: PurchaseRequest, reason: str) -> PurchaseRequest:
    """Açık talebi gerekçeyle iptal eder (talebi açan ya da satın alma / yönetim)."""
    request = _lock_request(request)
    if not _can_edit_request(actor, request):
        raise PermissionDenied("Bu talebi yalnızca açan kişi ya da satın alma iptal edebilir.")
    return cancel_document(request, actor, reason=reason, machine=purchase_request_states)


def create_suggested_requests(
    actor: User | None = None, *, today: date | None = None
) -> list[PurchaseRequest]:
    """Talep önerilerini otomatik talep olarak açar (sabah kontrolü). Açık talepler öneriden
    düşüldüğü için aynı ihtiyaç ikinci kez açılmaz."""
    created = []
    for suggestion in selectors.purchase_suggestions(today=today):
        parts = []
        if suggestion.demand:
            orders = ", ".join(s["order_number"] for s in suggestion.sources[:5])
            parts.append(f"açık emir ihtiyacı {format_quantity(suggestion.demand)} ({orders})")
        if suggestion.min_stock:
            parts.append(f"minimum stok {format_quantity(suggestion.min_stock)}")
        parts.append(f"serbest stok {format_quantity(suggestion.free_stock)}")
        if suggestion.open_orders:
            parts.append(f"açık sipariş {format_quantity(suggestion.open_orders)}")
        if suggestion.open_requests:
            parts.append(f"açık talep {format_quantity(suggestion.open_requests)}")
        with transaction.atomic():
            created.append(
                create_request(
                    actor,
                    {
                        "material": suggestion.material,
                        "quantity": suggestion.suggested,
                        "need_date": suggestion.need_date,
                        "reason": "Otomatik öneri: " + "; ".join(parts) + ".",
                    },
                    source=PurchaseRequest.Source.AUTO,
                )
            )
    return created


# --- sipariş ---------------------------------------------------------------------------------


def _lock_order(order: PurchaseOrder) -> PurchaseOrder:
    return (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .select_related("supplier")
        .get(pk=order.pk)
    )


def _require_status(order: PurchaseOrder, allowed: Sequence[str], code: str, what: str) -> None:
    if order.status not in allowed:
        raise BusinessRuleError(
            code,
            f"{order.number} {purchase_order_states.label(order.status).lower()} durumda; {what}.",
        )


def _validate_order(order: PurchaseOrder) -> None:
    if not order.supplier.is_active:
        raise BusinessRuleError(
            "inactive_reference", f"Pasif tedarikçi seçilemez: {order.supplier}."
        )
    if order.currency == "TRY":
        order.exchange_rate = Decimal(1)
    elif order.exchange_rate is None or order.exchange_rate <= 0:
        raise BusinessRuleError(
            "exchange_rate_required", "Dövizli siparişte TL kuru sıfırdan büyük girilmelidir."
        )


def _prepare_line(line: PurchaseOrderLine) -> None:
    _require_purchasable(line.material)
    if not line.unit.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif birim seçilemez: {line.unit}.")
    if line.quantity is None or line.quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    if line.unit_price is None or line.unit_price < 0:
        raise BusinessRuleError("invalid_price", "Birim fiyat girilmeli ve negatif olmamalıdır.")
    base = quantize(masterdata.to_base_quantity(line.material, line.quantity, line.unit))
    if base <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar temel birimde sıfıra iniyor.")
    line.base_quantity = base
    if line.expected_date < line.order.order_date:
        raise BusinessRuleError(
            "invalid_expected_date", "Teslim tarihi sipariş tarihinden önce olamaz."
        )


def _set_request_status(
    actor: User | None, request: PurchaseRequest, line: PurchaseOrderLine | None
) -> None:
    to_status = RequestStatus.ORDERED if line is not None else RequestStatus.OPEN
    request.order_line = line
    request.save(update_fields=["order_line", "updated_at"])
    transition_status(
        request,
        to_status,
        actor,
        machine=purchase_request_states,
        note=f"Sipariş {line.order.number}" if line is not None else "Siparişten çıkarıldı",
        event_payload={
            **_request_payload(request),
            "order_number": line.order.number if line is not None else "",
        },
    )


def _link_requests(
    actor: User | None, line: PurchaseOrderLine, requests: Iterable[PurchaseRequest]
) -> None:
    """Satırın bağlı taleplerini verilen listeyle eşitler."""
    wanted = {r.pk: r for r in requests}
    for current in list(line.requests.select_for_update()):
        if current.pk not in wanted:
            _set_request_status(actor, current, None)
    for request in wanted.values():
        request = _lock_request(request)
        if request.order_line_id == line.pk:
            continue
        if request.status != RequestStatus.OPEN:
            raise BusinessRuleError(
                "request_not_open", f"{request.number} açık değil; siparişe bağlanamaz."
            )
        if request.material_id != line.material_id:
            raise BusinessRuleError(
                "request_material_mismatch",
                f"{request.number} farklı malzeme için; satırın malzemesiyle aynı olmalı.",
            )
        _set_request_status(actor, request, line)


def _sync_lines(
    actor: User | None, order: PurchaseOrder, items: Iterable[Mapping[str, Any]]
) -> None:
    """Taslak siparişin satırlarını verilen listeyle eşitler: `id`'li satır güncellenir, `id`'siz
    eklenir, listede olmayan kaldırılır (bağlı talepler yeniden açılır, denetim kaydıyla)."""
    existing = {line.pk: line for line in order.lines.select_for_update().order_by("line_no")}
    keep: set[int] = set()
    next_no = (order.lines.aggregate(m=Max("line_no"))["m"] or 0) + 1
    pending: list[tuple[PurchaseOrderLine, list[PurchaseRequest] | None]] = []
    for item in items:
        values = dict(item)
        line_id = values.pop("id", None)
        values = _pick(values, LINE_FIELDS)
        requests = values.pop("requests", None)
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
            line = PurchaseOrderLine(order=order, line_no=next_no, **values)
            next_no += 1
        pending.append((line, list(requests) if requests is not None else None))
    for line_id, line in existing.items():
        if line_id in keep:
            continue
        for request in line.requests.select_for_update():
            _set_request_status(actor, request, None)
        log_change(
            _actor(actor),
            order,
            AuditLog.Action.UPDATE,
            {"line": [snapshot(line), None]},
            f"Satır {line.line_no} kaldırıldı (taslak)",
        )
        line.delete()
    for line, requests in pending:
        _prepare_line(line)
        line.full_clean(exclude=["created_by", "updated_by", "order", "line_no", "base_quantity"])
        save_with_audit(line, actor)
        if requests is not None:
            _link_requests(actor, line, requests)


@transaction.atomic
def create_order(
    actor: User | None, data: Mapping[str, Any], lines: Iterable[Mapping[str, Any]] = ()
) -> PurchaseOrder:
    """Taslak satın alma siparişi açar (`SA-`). Satırlar talep bağlayabilir (`requests`)."""
    _require_role(actor, ORDER_ROLES, "Satın alma siparişi açma yetkiniz yok.")
    order = PurchaseOrder(**_pick(data, ORDER_FIELDS))
    _validate_order(order)
    create_document(order, actor, prefix="SA", machine=purchase_order_states)
    _sync_lines(actor, order, lines)
    return order


@transaction.atomic
def update_order(
    actor: User | None,
    order: PurchaseOrder,
    data: Mapping[str, Any],
    lines: Iterable[Mapping[str, Any]] | None = None,
) -> PurchaseOrder:
    """Taslak siparişi günceller; `lines` verilirse satırları onunla eşitler."""
    _require_role(actor, ORDER_ROLES, "Satın alma siparişini değiştirme yetkiniz yok.")
    order = _lock_order(order)
    _require_status(order, (Status.DRAFT,), "document_locked", "yalnızca taslak değiştirilebilir")
    for name, value in _pick(data, ORDER_FIELDS).items():
        setattr(order, name, value)
    _validate_order(order)
    save_with_audit(order, actor)
    if lines is not None:
        _sync_lines(actor, order, lines)
    elif "order_date" in data:
        for line in order.lines.all():
            _prepare_line(line)
    return order


def can_approve(actor: User | None, order: PurchaseOrder) -> bool:
    """Karar D-13: yönetim her siparişi onaylar; satın alma yalnızca limit girilmiş ve TL tutar
    limit içindeyse."""
    if user_has_role(actor, APPROVER_ROLES):
        return True
    if not user_has_role(actor, (SATIN_ALMA,)):
        return False
    limit = get_settings().approval_limit_try
    return limit is not None and selectors.order_totals(order).total_try <= limit


def _require_lines(order: PurchaseOrder) -> None:
    if not order.lines.exists():
        raise BusinessRuleError("document_empty", "Satırı olmayan sipariş onaylanamaz.")


def _order_payload(order: PurchaseOrder) -> dict[str, Any]:
    totals = selectors.order_totals(order)
    lines = list(order.lines.select_related("material__base_unit", "unit").order_by("line_no"))
    return {
        "supplier_id": order.supplier_id,
        "supplier_name": order.supplier.name,
        "currency": order.currency,
        "total": str(totals.total),
        "total_try": str(totals.total_try),
        "expected_date": min(line.expected_date for line in lines).isoformat() if lines else "",
        "lines": [
            {
                **_material_payload(line.material),
                "quantity": str(line.quantity),
                "line_unit": line.unit.code,
                "expected_date": line.expected_date.isoformat(),
            }
            for line in lines
        ],
    }


@transaction.atomic
def submit_for_approval(actor: User | None, order: PurchaseOrder) -> PurchaseOrder:
    """Taslağı yönetim onayına gönderir (`PENDING_APPROVAL`). Olay: yönetime görev."""
    _require_role(actor, ORDER_ROLES, "Siparişi onaya gönderme yetkiniz yok.")
    order = _lock_order(order)
    _require_lines(order)
    totals = selectors.order_totals(order)
    order.approval_total_try = totals.total_try
    order.approval_limit_try = get_settings().approval_limit_try
    order.save(update_fields=["approval_total_try", "approval_limit_try", "updated_at"])
    return transition_status(
        order,
        Status.PENDING_APPROVAL,
        actor,
        machine=purchase_order_states,
        note=f"Tutar {format_money(totals.total_try)} TL",
        event_payload=_order_payload(order),
    )


@transaction.atomic
def approve_order(actor: User | None, order: PurchaseOrder) -> PurchaseOrder:
    """Siparişi onaylar (taslak ya da yönetim onayındaki). Yetki D-13'e göre `can_approve`.
    Onay notunda TL tutar ve geçerli limit denetim günlüğüne yazılır. Olay:
    `purchase_order.approved` → depoya "beklenen teslimat" bildirimi."""
    _require_role(actor, ORDER_ROLES, "Siparişi onaylama yetkiniz yok.")
    order = _lock_order(order)
    _require_status(
        order, (Status.DRAFT, Status.PENDING_APPROVAL), "invalid_transition", "onaylanamaz"
    )
    _require_lines(order)
    totals = selectors.order_totals(order)
    limit = get_settings().approval_limit_try
    if not can_approve(actor, order):
        if limit is None:
            message = "Onay limiti girilmediği için siparişi yönetim onaylar."
        else:
            message = (
                f"Sipariş tutarı {format_money(totals.total_try)} TL, onay limitiniz "
                f"{format_money(limit)} TL; "
                "siparişi yönetim onaylar."
            )
        raise BusinessRuleError("approval_limit_exceeded", message)
    order.approval_total_try = totals.total_try
    order.approval_limit_try = limit
    order.approved_by = _actor(actor)
    order.approved_at = timezone.now()
    order.save(
        update_fields=[
            "approval_total_try",
            "approval_limit_try",
            "approved_by",
            "approved_at",
            "updated_at",
        ]
    )
    limit_text = f"{format_money(limit)} TL" if limit is not None else "girilmemiş"
    return transition_status(
        order,
        Status.APPROVED,
        actor,
        machine=purchase_order_states,
        note=(
            f"Onay: tutar {format_money(totals.total_try)} TL (kur {order.exchange_rate}), "
            f"limit {limit_text}"
        ),
        event_payload=_order_payload(order),
    )


@transaction.atomic
def return_to_draft(actor: User | None, order: PurchaseOrder, note: str) -> PurchaseOrder:
    """Yönetim onayındaki siparişi gerekçeyle taslağa geri gönderir (yalnızca yönetim)."""
    _require_role(actor, APPROVER_ROLES, "Siparişi taslağa yalnızca yönetim geri gönderir.")
    note = _require_note(note, "note_required", "Geri gönderme gerekçesi girilmelidir.")
    order = _lock_order(order)
    return transition_status(
        order,
        Status.DRAFT,
        actor,
        machine=purchase_order_states,
        note=note,
        event_payload={**_order_payload(order), "note": note},
    )


def _send_email(order: PurchaseOrder, to: str, pdf: bytes) -> None:
    company = settings.COMPANY_NAME or "Firmamız"
    message = EmailMessage(
        subject=f"Satın alma siparişi {order.number}",
        body=(
            f"Sayın {order.supplier.name},\n\n"
            f"{order.number} numaralı satın alma siparişimiz ektedir.\n\n"
            f"Saygılarımızla,\n{company}"
        ),
        to=[to],
    )
    message.attach(f"{order.number}.pdf", pdf, "application/pdf")
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        logger.exception("Sipariş e-postası gönderilemedi: %s", order.number)
        raise BusinessRuleError(
            "email_failed", f"E-posta gönderilemedi ({exc.__class__.__name__})."
        ) from exc


@transaction.atomic
def mark_sent(
    actor: User | None, order: PurchaseOrder, *, email: str | None = None
) -> PurchaseOrder:
    """Onaylı siparişi tedarikçiye gönderildi yapar (`SENT`). `email` verilirse sipariş PDF'i bu
    adrese gönderilir (kullanıcı ekranda adresi görüp onaylar); verilmezse yalnızca işaretlenir."""
    from apps.purchasing.pdf import purchase_order_pdf

    _require_role(actor, ORDER_ROLES, "Siparişi gönderme yetkiniz yok.")
    order = _lock_order(order)
    purchase_order_states.assert_can_transition(order.status, Status.SENT)
    to = (email or "").strip()
    if to:
        try:
            validate_email(to)
        except Exception as exc:
            raise BusinessRuleError("invalid_email", "Geçerli bir e-posta adresi girin.") from exc
    order.sent_at = timezone.now()
    order.sent_by = _actor(actor)
    order.sent_to = to
    order.save(update_fields=["sent_at", "sent_by", "sent_to", "updated_at"])
    result = transition_status(
        order,
        Status.SENT,
        actor,
        machine=purchase_order_states,
        note=f"E-posta: {to}" if to else "E-postasız gönderildi olarak işaretlendi",
        event_payload={"supplier_name": order.supplier.name, "email": to},
    )
    if to:
        # Son adım: e-posta gönderilemezse işlem geri alınır, sipariş onaylı kalır.
        _send_email(order, to, purchase_order_pdf(order))
    return result


@transaction.atomic
def cancel_order(actor: User | None, order: PurchaseOrder, reason: str) -> PurchaseOrder:
    """Mal kabul gelmemiş siparişi iptal eder; bağlı talepler yeniden açılır. Siparişe bağlı
    taslak mal kabul varsa önce o iptal edilmelidir."""
    _require_role(actor, ORDER_ROLES, "Siparişi iptal etme yetkiniz yok.")
    order = _lock_order(order)
    _require_status(order, CANCELLABLE_STATUSES, "invalid_transition", "iptal edilemez")
    links = ReceiptLineLink.objects.filter(order_line__order=order).exclude(
        receipt_line__receipt__status=GoodsReceipt.Status.CANCELLED
    )
    if links.exists():
        numbers = sorted({link.receipt_line.receipt.number for link in links})
        raise BusinessRuleError(
            "order_has_receipts",
            f"Siparişe bağlı mal kabul var ({', '.join(numbers)}); sipariş iptal edilemez.",
        )
    for request in PurchaseRequest.objects.select_for_update().filter(order_line__order=order):
        _set_request_status(actor, request, None)
    return cancel_document(order, actor, reason=reason, machine=purchase_order_states)


@transaction.atomic
def close_order(actor: User | None, order: PurchaseOrder, note: str) -> PurchaseOrder:
    """Kısmen teslim alınmış siparişin kalanını gerekçeyle kapatır (`RECEIVED`)."""
    _require_role(actor, ORDER_ROLES, "Siparişi kapatma yetkiniz yok.")
    note = _require_note(note, "note_required", "Kapanış gerekçesi girilmelidir.")
    order = _lock_order(order)
    _require_status(order, (Status.PARTIALLY_RECEIVED,), "invalid_transition", "kalanı kapatılamaz")
    drafts = ReceiptLineLink.objects.filter(
        order_line__order=order, receipt_line__receipt__status=GoodsReceipt.Status.DRAFT
    )
    if drafts.exists():
        raise BusinessRuleError(
            "order_has_draft_receipts",
            "Siparişe bağlı taslak mal kabul var; önce kaydedin ya da iptal edin.",
        )
    order.closed_note = note
    order.save(update_fields=["closed_note", "updated_at"])
    return transition_status(
        order,
        Status.RECEIVED,
        actor,
        machine=purchase_order_states,
        note=f"Kalan kapatıldı: {note}",
        event_payload={"supplier_name": order.supplier.name, "short_closed": True},
    )


# --- siparişten mal kabul --------------------------------------------------------------------


def _tolerance_limit(line: PurchaseOrderLine, tolerance_pct: Decimal) -> Decimal:
    """Satırdan teslim alınabilecek en çok miktar (temel birimde)."""
    return quantize(line.base_quantity * (HUNDRED + tolerance_pct) / HUNDRED)


def _price_fields(order: PurchaseOrder, line: PurchaseOrderLine) -> dict[str, Any]:
    """Mal kabul satırına siparişten gelen fiyat (Maliyet adımının alanları: birim fiyat satır
    biriminde, para birimi ve kur)."""
    return {
        "unit_price": line.unit_price,
        "currency": order.currency,
        "exchange_rate": order.exchange_rate,
    }


@transaction.atomic
def create_receipt_from_order(
    actor: User | None,
    order: PurchaseOrder,
    data: Mapping[str, Any],
    lines: Iterable[Mapping[str, Any]],
) -> GoodsReceipt:
    """Siparişten taslak mal kabul açar. Satır birimi ve fiyatı sipariş satırından gelir; miktar
    satırın kalanını tolerans kadar aşabilir. Mal kabul inventory ekranında kaydedilir."""
    _require_role(actor, RECEIPT_ROLES, "Siparişten mal kabul açma yetkiniz yok.")
    order = _lock_order(order)
    _require_status(
        order,
        selectors.RECEIVABLE_STATUSES,
        "order_not_receivable",
        "mal kabul yapılamaz (onaylı ya da gönderilmiş olmalı)",
    )
    tolerance = get_settings().over_receipt_tolerance_pct
    order_lines = {line.pk: line for line in selectors.order_lines().filter(order=order)}
    receipt_lines: list[dict[str, Any]] = []
    sources: list[PurchaseOrderLine] = []
    for item in lines:
        values = _pick(item, RECEIPT_LINE_FIELDS)
        order_line_ref = values.pop("order_line")
        order_line_id = getattr(order_line_ref, "pk", order_line_ref)
        order_line = order_lines.get(order_line_id)
        if order_line is None:
            raise BusinessRuleError(
                "line_not_found", f"Siparişte {order_line_id} numaralı satır yok."
            )
        quantity = values.pop("quantity")
        if quantity is None or quantity <= 0:
            raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
        base = quantize(masterdata.to_base_quantity(order_line.material, quantity, order_line.unit))
        draft_base = quantize(
            masterdata.to_base_quantity(
                order_line.material,
                order_line.draft_receipt_quantity,  # type: ignore[attr-defined]
                order_line.unit,
            )
        )
        received = order_line.received_quantity  # type: ignore[attr-defined]
        _check_tolerance(order_line, received + draft_base + base, tolerance)
        receipt_lines.append(
            {
                "material": order_line.material,
                "quantity": quantity,
                "unit": order_line.unit,
                **values,
                **_price_fields(order, order_line),
            }
        )
        sources.append(order_line)
    if not receipt_lines:
        raise BusinessRuleError("document_empty", "En az bir satır seçin.")
    header = _pick(data, RECEIPT_HEADER_FIELDS)
    receipt = inventory.create_goods_receipt(
        actor,
        {**header, "supplier": order.supplier},
        receipt_lines,
    )
    created = list(receipt.lines.order_by("line_no"))
    for receipt_line, order_line in zip(created, sources, strict=True):
        save_with_audit(ReceiptLineLink(receipt_line=receipt_line, order_line=order_line), actor)
    log_change(
        _actor(actor),
        order,
        AuditLog.Action.UPDATE,
        {"receipt": [None, receipt.number]},
        f"Mal kabul açıldı: {receipt.number}",
    )
    return receipt


def _check_tolerance(line: PurchaseOrderLine, total_base: Decimal, tolerance: Decimal) -> None:
    limit = _tolerance_limit(line, tolerance)
    if total_base > limit:
        unit = line.material.base_unit.code
        raise BusinessRuleError(
            "over_receipt",
            f"{line.material.code}: sipariş {format_quantity(line.base_quantity)} {unit}, "
            f"toplam teslim {format_quantity(total_base)} {unit} olur; en fazla "
            f"%{format_quantity(tolerance)} fazlası ({format_quantity(limit)} {unit}) "
            "kabul edilir.",
        )


def _target_status(order: PurchaseOrder, extra: Mapping[int, Decimal]) -> str:
    """Siparişin mal kabul sonrası durumu; `extra` kaydedilmekte olan mal kabulün satır
    miktarları (sipariş satırı → temel birim)."""
    lines = list(selectors.order_lines().filter(order=order))
    if all(
        line.received_quantity + extra.get(line.pk, ZERO) >= line.base_quantity  # type: ignore[attr-defined]
        for line in lines
    ):
        return Status.RECEIVED
    return Status.PARTIALLY_RECEIVED


@inventory.register_receipt_post_hook
def on_receipt_posting(
    actor: User | None, receipt: GoodsReceipt, lines: list[GoodsReceiptLine]
) -> None:
    """Mal kabul kaydedilirken (aynı transaction): siparişe bağlı satırlarda sipariş durumu ve
    fazla teslim toleransı denetlenir, ardından sipariş kısmen teslim alındı / teslim alındı olur.
    Olay: `purchase_order.partially_received` / `purchase_order.received`."""
    links = list(
        ReceiptLineLink.objects.filter(receipt_line__in=lines).select_related(
            "order_line__material__base_unit", "receipt_line"
        )
    )
    if not links:
        return
    tolerance = get_settings().over_receipt_tolerance_pct
    orders: dict[int, PurchaseOrder] = {}
    for link in links:
        order_line = link.order_line
        order = orders.get(order_line.order_id)
        if order is None:
            order = _lock_order(order_line.order)
            _require_status(
                order,
                selectors.RECEIVABLE_STATUSES,
                "order_not_receivable",
                "bu siparişe mal kabul kaydedilemez",
            )
            orders[order.pk] = order
        if link.receipt_line.material_id != order_line.material_id:
            raise BusinessRuleError(
                "receipt_material_mismatch",
                f"Mal kabul satırı {link.receipt_line.line_no}: malzeme sipariş satırıyla aynı "
                "olmalı.",
            )
    # Bu mal kabul henüz `POSTED` değil: satırlarının miktarı kaydedilmişlere eklenir.
    incoming: dict[int, Decimal] = {}
    for link in links:
        base = link.receipt_line.base_quantity or ZERO
        incoming[link.order_line_id] = incoming.get(link.order_line_id, ZERO) + base
    for order_line_id, quantity in incoming.items():
        line = selectors.order_lines().get(pk=order_line_id)
        _check_tolerance(line, line.received_quantity + quantity, tolerance)  # type: ignore[attr-defined]
    for order in orders.values():
        to_status = _target_status(order, incoming)
        if to_status == order.status:
            continue
        transition_status(
            order,
            to_status,
            actor,
            machine=purchase_order_states,
            note=f"Mal kabul {receipt.number}",
            event_payload={
                "supplier_name": order.supplier.name,
                "receipt_id": receipt.pk,
                "receipt_number": receipt.number,
            },
        )
