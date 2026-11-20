"""Portal hesabı servisleri (docs/plan/musteri-siparis-takibi.md §4.2).

Hesabı yalnız sistem yöneticisi açar, şifresini sıfırlar, kilidini açar ve pasife alır
(CUMHUR, 2026-11-19). Kullanıcının kendisi `core.services` ile açılır; burada firmaya bağlanır.
"""

import logging
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events, security
from apps.core import services as core
from apps.core.access import CHANGE
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import require_access, require_admin
from apps.core.services import create_document, save_with_audit, transition_status
from apps.masterdata.models import Customer, Material, Supplier, UnitOfMeasure
from apps.portal import email as portal_email
from apps.portal import selectors
from apps.portal.models import OrderRequest, OrderRequestLine, OutboundEmail, PortalAccount
from apps.portal.state import order_request_states
from apps.sales import services as sales
from apps.sales.access import ORDERS
from apps.sales.models import SalesOrder, Shipment

ADMIN_MESSAGE = "Portal hesaplarını yalnız sistem yöneticisi yönetir."
logger = logging.getLogger(__name__)


def _check_firm(customer: Customer | None, supplier: Supplier | None) -> Customer | Supplier:
    if (customer is None) == (supplier is None):
        raise BusinessRuleError(
            "portal_firm_required",
            "Hesap tek bir müşteriye ya da tek bir tedarikçiye bağlanır.",
        )
    firm: Customer | Supplier = customer if customer is not None else supplier  # type: ignore[assignment]
    if not firm.is_active:
        raise BusinessRuleError(
            "portal_firm_inactive",
            "Pasif müşteri ya da tedarikçiye portal hesabı açılamaz.",
        )
    return firm


def create_account(
    actor: User,
    *,
    username: str,
    full_name: str,
    customer: Customer | None = None,
    supplier: Supplier | None = None,
    email: str = "",
    phone: str = "",
) -> tuple[PortalAccount, str]:
    """Müşteri ya da tedarikçi yetkilisine portal hesabı açar; sistemin ürettiği geçici şifreyi
    döner (yalnız bu dönüş değerinde görünür, ilk girişte değiştirilir).

    Hata kodları: `portal_firm_required` (ikisi birden ya da hiçbiri), `portal_firm_inactive`;
    kullanıcı adı ve ad soyad kuralları `core.services.create_user`'daki gibidir.
    """
    require_admin(actor, ADMIN_MESSAGE)
    _check_firm(customer, supplier)
    kinds = User.AccountType
    account_type = kinds.CUSTOMER_PORTAL if customer is not None else kinds.SUPPLIER_PORTAL
    with transaction.atomic():
        user, password = core.create_user(
            actor,
            username=username,
            full_name=full_name,
            email=email,
            phone=phone,
            account_type=account_type,
        )
        account = PortalAccount(user=user, customer=customer, supplier=supplier)
        save_with_audit(account, actor, note="Portal hesabı açıldı")
    return account, password


def reset_password(actor: User, account: PortalAccount) -> str:
    """Yeni geçici şifre üretir (pasif hesapta `user_inactive`)."""
    require_admin(actor, ADMIN_MESSAGE)
    return core.reset_user_password(actor, account.user)


def unlock(actor: User, account: PortalAccount) -> None:
    """Hatalı denemelerden kilitlenen hesabın kilidini açar (`not_locked`)."""
    require_admin(actor, ADMIN_MESSAGE)
    security.unlock_user(actor, account.user)


def set_active(actor: User, account: PortalAccount, active: bool) -> PortalAccount:
    """Hesabı kapatır ya da yeniden açar. Bağlı firma pasifse yeniden açılamaz
    (`portal_firm_inactive`)."""
    require_admin(actor, ADMIN_MESSAGE)
    if active:
        _check_firm(account.customer, account.supplier)
    core.set_user_active(actor, account.user, active)
    account.user.refresh_from_db(fields=["is_active"])
    return account


def record_waybill_view(actor: User, shipment: Shipment) -> None:
    """Müşteri portalından irsaliye açılışı sevkiyatın geçmişine ve denetim günlüğüne yazılır
    (docs/plan/musteri-siparis-takibi.md §4.3); müşteri nüshasında şoför TC'si maskelidir."""
    log_change(actor, shipment, AuditLog.Action.CUSTOM, note="İrsaliye görüntülendi (portal)")


# --- sipariş talebi (docs/plan/musteri-siparis-takibi.md §4.4) ------------------------------

REQUEST_FIELDS = ("requested_delivery_date", "customer_po_no", "delivery_address", "note")
TEXT_FIELDS = ("customer_po_no", "delivery_address", "note")


def _customer_of(actor: User) -> Customer:
    """Talep açan müşteri portalı kullanıcısının bağlı (etkin) müşterisi."""
    account = selectors.account_of(actor)
    if account is None or account.customer is None or not selectors.is_usable(account):
        raise PermissionDenied("Sipariş talebini yalnız müşteri portalı hesabı gönderir.")
    return account.customer


def _request_payload(request: OrderRequest) -> dict[str, Any]:
    return {"customer_code": request.customer.code, "customer_name": request.customer.name}


def _lock_request(request: OrderRequest) -> OrderRequest:
    return OrderRequest.objects.select_for_update().select_related("customer").get(pk=request.pk)


def _require_submitted(request: OrderRequest, what: str) -> None:
    if request.status != OrderRequest.Status.SUBMITTED:
        raise BusinessRuleError(
            "request_not_open", f"Yalnız gönderilmiş (karar bekleyen) talep {what}."
        )


def _clean_lines(lines: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Satırları doğrular: aktif mamul, sıfırdan büyük miktar, mamulün tanımlı birimi."""
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(lines, start=1):
        product: Material = item["product"]
        quantity = Decimal(item["quantity"])
        unit: UnitOfMeasure = item["unit"]
        if not product.is_active or product.material_type != Material.Type.FINISHED:
            raise BusinessRuleError(
                "product_not_orderable", f"{index}. satırdaki ürün sipariş edilemez."
            )
        if quantity <= 0:
            raise BusinessRuleError(
                "invalid_quantity", f"{index}. satırda miktar sıfırdan büyük olmalı."
            )
        defined = (
            unit.pk == product.base_unit_id
            or product.conversions.filter(unit=unit, is_active=True).exists()
        )
        if not defined:
            raise BusinessRuleError(
                "invalid_unit", f"{index}. satırdaki birim bu ürün için tanımlı değil."
            )
        cleaned.append({"product": product, "quantity": quantity, "unit": unit})
    if not cleaned:
        raise BusinessRuleError("request_empty", "Talepte en az bir satır olmalı.")
    return cleaned


def submit_request(
    actor: User, data: Mapping[str, Any], lines: Iterable[Mapping[str, Any]]
) -> OrderRequest:
    """Müşteri portalından sipariş talebi gönderir (`MT-`, durum Gönderildi). Teslim adresi
    boşsa müşterinin adresi alınır; geçmiş istenen teslim tarihi kabul edilmez. Fiyat yoktur.
    `order_request.created` olayı sevkiyata "Portal talebi incele" görevi açar."""
    customer = _customer_of(actor)
    values: dict[str, Any] = {name: data.get(name) for name in REQUEST_FIELDS if name in data}
    for name in TEXT_FIELDS:
        values[name] = (values.get(name) or "").strip()
    wanted = values.get("requested_delivery_date")
    if wanted is not None and wanted < timezone.localdate():
        raise BusinessRuleError(
            "requested_date_past", "İstenen teslim tarihi bugünden önce olamaz."
        )
    cleaned = _clean_lines(lines)
    with transaction.atomic():
        request = OrderRequest(customer=customer, **values)
        if not request.delivery_address:
            request.delivery_address = customer.address
        create_document(
            request,
            actor,
            prefix="MT",
            machine=order_request_states,
            note="Portaldan sipariş talebi",
            event_payload={
                "customer_code": customer.code,
                "customer_name": customer.name,
                "line_count": len(cleaned),
            },
        )
        for line_no, item in enumerate(cleaned, start=1):
            save_with_audit(OrderRequestLine(request=request, line_no=line_no, **item), actor)
    return request


def withdraw_request(actor: User, request: OrderRequest) -> OrderRequest:
    """Müşteri, karar verilmemiş talebini geri çeker (yalnız kendi firmasının talebi)."""
    customer = _customer_of(actor)
    with transaction.atomic():
        request = _lock_request(request)
        if request.customer_id != customer.pk:
            raise PermissionDenied("Bu talep sizin firmanıza ait değil.")
        _require_submitted(request, "geri çekilebilir")
        return transition_status(
            request,
            OrderRequest.Status.WITHDRAWN,
            actor,
            machine=order_request_states,
            note="Müşteri talebi geri çekti",
            event_payload=_request_payload(request),
        )


def _decide(request: OrderRequest, actor: User, **fields: Any) -> dict[str, Any]:
    """Karar alanlarını yazar; denetim kaydı için eski → yeni değerleri döner."""
    changes = {
        name: [str(getattr(request, name) or ""), str(value)] for name, value in fields.items()
    }
    request.decided_at = timezone.now()
    request.decided_by = actor
    for name, value in fields.items():
        setattr(request, name, value)
    request.save(update_fields=[*fields, "decided_at", "decided_by", "updated_at"])
    return changes


def convert_request(actor: User, request: OrderRequest) -> SalesOrder:
    """Talepten taslak satış siparişi açar (Satış siparişleri: Değiştirir). Satırlar, istenen
    teslim tarihi, müşteri sipariş no'su ve adres taşınır; talebin notu sipariş notuna
    "Portal talebi MT-…" diye yazılır. Fiyat ve termin taslakta girilir, onay bugünkü gibidir."""
    require_access(actor, ORDERS, CHANGE, "Portal talebini siparişe çevirme yetkiniz yok.")
    with transaction.atomic():
        request = _lock_request(request)
        _require_submitted(request, "siparişe çevrilebilir")
        note = f"Portal talebi {request.number}"
        if request.note:
            note = f"{note}: {request.note}"
        order = sales.create_order(
            actor,
            {
                "customer": request.customer,
                "order_date": timezone.localdate(),
                "requested_delivery_date": request.requested_delivery_date,
                "delivery_address": request.delivery_address,
                "customer_po_no": request.customer_po_no,
                "notes": note,
            },
            [
                {"product": line.product, "quantity": line.quantity, "unit": line.unit}
                for line in request.lines.select_related("product", "unit").order_by("line_no")
            ],
        )
        changes = _decide(request, actor, sales_order=order)
        transition_status(
            request,
            OrderRequest.Status.CONVERTED,
            actor,
            machine=order_request_states,
            note=f"Siparişe çevrildi: {order.number}",
            event_payload={
                **_request_payload(request),
                "order": {"model": "sales.salesorder", "id": order.pk, "number": order.number},
            },
            changes=changes,
        )
    return order


def reject_request(actor: User, request: OrderRequest, reason: str) -> OrderRequest:
    """Talebi gerekçeyle reddeder (Satış siparişleri: Değiştirir); müşteri gerekçeyi portalda
    görür."""
    require_access(actor, ORDERS, CHANGE, "Portal talebini reddetme yetkiniz yok.")
    reason = (reason or "").strip()
    if not reason:
        raise BusinessRuleError("reason_required", "Ret gerekçesi yazılmalı.")
    with transaction.atomic():
        request = _lock_request(request)
        _require_submitted(request, "reddedilebilir")
        changes = _decide(request, actor, reject_reason=reason)
        return transition_status(
            request,
            OrderRequest.Status.REJECTED,
            actor,
            machine=order_request_states,
            note="Talep reddedildi",
            event_payload={**_request_payload(request), "reason": reason},
            changes=changes,
        )


# --- müşteriye e-posta (docs/plan/musteri-siparis-takibi.md §4.5) ------------------------------

# Gönderim en çok bu kadar denenir (arada bekleme: deneme × EMAIL_RETRY_SECONDS).
EMAIL_MAX_ATTEMPTS = 3
EMAIL_RETRY_SECONDS = 300


def set_email_preference(actor: User, enabled: bool) -> PortalAccount:
    """Müşteri yetkilisi sipariş ve sevk e-postalarını açar ya da kapatır (denetim kaydıyla)."""
    customer = _customer_of(actor)
    account = PortalAccount.objects.select_for_update().get(user=actor, customer=customer)
    account.email_opt_out = not enabled
    return save_with_audit(account, actor)


def email_recipients(customer: Customer) -> list[User]:
    """E-posta alacak portal kullanıcıları: müşterinin etkin, e-postası dolu ve e-postayı
    kapatmamış hesapları."""
    accounts = (
        PortalAccount.objects.filter(customer=customer, email_opt_out=False, user__is_active=True)
        .exclude(user__email="")
        .select_related("user")
        .order_by("user__username")
    )
    return [account.user for account in accounts]


def _queue(
    kind: str, customer: Customer, model: str, record_id: int, number: str, subject: str
) -> list[OutboundEmail]:
    if not customer.is_active:
        return []
    queued = []
    for user in email_recipients(customer):
        email, created = OutboundEmail.objects.get_or_create(
            kind=kind,
            related_model=model,
            related_id=record_id,
            user=user,
            defaults={
                "customer": customer,
                "to_address": user.email,
                "subject": subject,
                "related_number": number,
            },
        )
        if created:
            queued.append(email)
    if queued:
        from apps.portal.tasks import send_portal_email

        ids = [email.pk for email in queued]
        transaction.on_commit(lambda: [send_portal_email.delay(pk) for pk in ids])
    return queued


@transaction.atomic
def queue_order_confirmed(order: SalesOrder) -> list[OutboundEmail]:
    """Onaylanan sipariş için müşterinin portal kullanıcılarına e-posta sıraya alınır."""
    content = portal_email.order_confirmed(order)
    return _queue(
        OutboundEmail.Kind.ORDER_CONFIRMED,
        order.customer,
        "sales.salesorder",
        order.pk,
        order.number,
        content.subject,
    )


@transaction.atomic
def queue_shipment_dispatched(shipment: Shipment) -> list[OutboundEmail]:
    """Sevk edilen sevkiyat için müşterinin portal kullanıcılarına e-posta sıraya alınır."""
    order = shipment.sales_order
    return _queue(
        OutboundEmail.Kind.SHIPMENT_DISPATCHED,
        order.customer,
        "sales.shipment",
        shipment.pk,
        shipment.number,
        f"Siparişiniz sevk edildi: {shipment.number}",
    )


def _content(email: OutboundEmail) -> portal_email.Content | None:
    if email.related_model == "sales.salesorder":
        order = SalesOrder.objects.filter(pk=email.related_id).select_related("customer").first()
        return portal_email.order_confirmed(order) if order else None
    shipment = (
        Shipment.objects.filter(pk=email.related_id).select_related("sales_order__customer").first()
    )
    return portal_email.shipment_dispatched(shipment) if shipment else None


def deliver_email(email_id: int) -> bool:
    """Sıradaki e-postayı gönderir. SMTP tanımlı değilse "gönderilmedi" olur. Hata olursa deneme
    sayısı artar; son denemede "gönderilemedi" olur ve `portal_email.failed` yayınlanır (admin'e
    bildirim). Yeniden denenmesi gerekiyorsa True döner."""
    with transaction.atomic():
        email = OutboundEmail.objects.select_for_update().filter(pk=email_id).first()
        if email is None or email.status != OutboundEmail.Status.QUEUED:
            return False
        if not settings.EMAIL_CONFIGURED:
            email.status = OutboundEmail.Status.SKIPPED
            email.save(update_fields=["status"])
            return False
        content = _content(email)
        if content is None:
            email.status = OutboundEmail.Status.FAILED
            email.last_error = "İlgili kayıt bulunamadı."
            email.save(update_fields=["status", "last_error"])
            return False
        email.attempts += 1
        message = EmailMultiAlternatives(
            subject=content.subject, body=content.text, to=[email.to_address]
        )
        message.attach_alternative(content.html, "text/html")
        try:
            message.send(fail_silently=False)
        except Exception as exc:
            logger.exception("Portal e-postası gönderilemedi: %s", email.pk)
            email.last_error = exc.__class__.__name__
            if email.attempts < EMAIL_MAX_ATTEMPTS:
                email.save(update_fields=["attempts", "last_error"])
                return True
            email.status = OutboundEmail.Status.FAILED
            email.save(update_fields=["attempts", "last_error", "status"])
            events.publish(
                ev.PORTAL_EMAIL_FAILED,
                {
                    "model": email.related_model,
                    "id": email.related_id,
                    "number": email.related_number,
                    "customer_name": email.customer.name,
                    "kind_label": email.get_kind_display(),
                    "error": email.last_error,
                },
            )
            return False
        email.status = OutboundEmail.Status.SENT
        email.sent_at = timezone.now()
        email.save(update_fields=["attempts", "status", "sent_at", "last_error"])
        return False
