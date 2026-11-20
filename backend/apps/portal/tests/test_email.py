"""Müşteriye portal e-postası (docs/plan/musteri-siparis-takibi.md §4.5, B5)."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core import event_names as ev
from apps.core.models import AuditLog, User
from apps.core.roles import ADMIN
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Customer
from apps.masterdata.tests.factories import CustomerFactory
from apps.portal import services
from apps.portal.models import OutboundEmail, PortalAccount
from apps.portal.tests.conftest import Commit
from apps.portal.tests.helpers import session_client
from apps.portal.tests.test_customer import DRIVER_ID, _dispatch, _order, _plan
from apps.workflow.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def invariants() -> Iterator[None]:
    yield
    assert_stock_invariants()


SMTP = override_settings(
    EMAIL_CONFIGURED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PORTAL_BASE_URL="https://portal.ornek",
)
PREF = "/api/v1/portal/customer/email-preference/"


@pytest.fixture
def account(customer_account: PortalAccount) -> PortalAccount:
    user = customer_account.user
    user.email = "yetkili@musteri.ornek"
    user.save(update_fields=["email"])
    return customer_account


def _second_account(sysadmin: User, customer: Customer, **user: Any) -> PortalAccount:
    acc, _ = services.create_account(
        sysadmin, username="ikinci.yetkili", full_name="İkinci Yetkili", customer=customer
    )
    for field, value in user.items():
        setattr(acc.user, field, value)
    acc.user.save()
    return acc


@SMTP
def test_order_confirmed_email_without_price(
    account: PortalAccount, seller: User, customer: Customer, commit: Commit
) -> None:
    with commit():
        order = _order(seller, customer, customer_po_no="PO-77")
    email = OutboundEmail.objects.get()
    assert email.status == OutboundEmail.Status.SENT
    assert email.kind == OutboundEmail.Kind.ORDER_CONFIRMED
    assert email.related_number == order.number and email.attempts == 1
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["yetkili@musteri.ornek"]
    assert message.subject == f"Siparişiniz onaylandı: {order.number}"
    assert "PO-77" in message.body
    assert f"https://portal.ornek/portal/siparisler/{order.pk}" in message.body
    html = message.alternatives[0][0]  # type: ignore[attr-defined]
    for text in (message.body, html):
        assert "TL" not in text and "10,00" not in text and "Fiyat" not in text


@SMTP
def test_shipment_dispatched_email_hides_driver(
    account: PortalAccount, seller: User, picker: User, customer: Customer, commit: Commit
) -> None:
    with commit():
        order = _order(seller, customer)
        shipment = _dispatch(seller, picker, _plan(seller, order))
    kinds = set(OutboundEmail.objects.values_list("kind", "status"))
    assert kinds == {
        (OutboundEmail.Kind.ORDER_CONFIRMED, OutboundEmail.Status.SENT),
        (OutboundEmail.Kind.SHIPMENT_DISPATCHED, OutboundEmail.Status.SENT),
    }
    message = mail.outbox[-1]
    assert message.subject == f"Siparişiniz sevk edildi: {shipment.number}"
    assert "34 ABC 123" in message.body and "2 KOLI" in message.body
    assert f"/portal/sevkiyatlar/{shipment.pk}" in message.body
    for text in (message.body, message.alternatives[0][0]):  # type: ignore[attr-defined]
        assert DRIVER_ID not in text and "Ali Veli" not in text
    assert message.attachments == []


@SMTP
def test_recipients_skip_opt_out_inactive_and_no_email(
    account: PortalAccount,
    sysadmin: User,
    seller: User,
    customer: Customer,
    commit: Commit,
) -> None:
    _second_account(sysadmin, customer)  # e-postası boş
    other = CustomerFactory.create(code="M-BASKA")
    other_acc, _ = services.create_account(
        sysadmin, username="baska.yetkili", full_name="Başka", customer=other
    )
    other_acc.user.email = "baska@ornek"
    other_acc.user.save()
    with commit():
        _order(seller, customer)
    assert [m.to for m in mail.outbox] == [["yetkili@musteri.ornek"]]

    services.set_email_preference(account.user, False)
    with commit():
        _order(seller, customer)
    assert len(mail.outbox) == 1

    services.set_email_preference(account.user, True)
    services.set_active(sysadmin, account, False)
    with commit():
        _order(seller, customer)
    assert len(mail.outbox) == 1


def test_without_smtp_email_is_skipped(
    account: PortalAccount, seller: User, customer: Customer, commit: Commit
) -> None:
    with override_settings(EMAIL_CONFIGURED=False), commit():
        _order(seller, customer)
    assert OutboundEmail.objects.get().status == OutboundEmail.Status.SKIPPED
    assert mail.outbox == []


@SMTP
def test_failure_retries_then_notifies_admin(
    account: PortalAccount,
    sysadmin: User,
    seller: User,
    customer: Customer,
    commit: Commit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def boom(self: Any, fail_silently: bool = False) -> int:
        calls.append(1)
        raise ConnectionRefusedError("smtp kapalı")

    monkeypatch.setattr("django.core.mail.EmailMultiAlternatives.send", boom)
    with commit():
        order = _order(seller, customer)
    email = OutboundEmail.objects.get()
    assert len(calls) == services.EMAIL_MAX_ATTEMPTS
    assert email.status == OutboundEmail.Status.FAILED
    assert email.attempts == services.EMAIL_MAX_ATTEMPTS
    assert email.last_error == "ConnectionRefusedError"
    note = Notification.objects.get(rule_code="portal_email_failed")
    assert note.recipient == sysadmin
    assert order.number in note.title
    assert ev.PORTAL_EMAIL_FAILED == "portal_email.failed"
    # Sipariş onayı e-posta hatasından etkilenmez.
    order.refresh_from_db()
    assert order.status == order.Status.CONFIRMED


@SMTP
def test_same_email_is_not_sent_twice(
    account: PortalAccount, seller: User, customer: Customer, commit: Commit
) -> None:
    with commit():
        order = _order(seller, customer)
    with commit():
        assert services.queue_order_confirmed(order) == []
    assert len(mail.outbox) == 1


def test_preference_api(account: PortalAccount) -> None:
    client = session_client(account.user)
    response = client.get(PREF)
    assert response.status_code == 200
    assert response.json() == {"email": "yetkili@musteri.ornek", "enabled": True}
    response = client.put(PREF, {"enabled": False}, format="json")
    assert response.status_code == 200 and response.json()["enabled"] is False
    account.refresh_from_db()
    assert account.email_opt_out is True
    assert AuditLog.objects.filter(
        object_id=str(account.pk), action=AuditLog.Action.UPDATE
    ).exists()


def test_preference_api_only_customer_portal(
    supplier_account: PortalAccount, make_user: Callable[..., User]
) -> None:
    assert session_client(supplier_account.user).get(PREF).status_code == 403
    staff = APIClient()
    staff.force_authenticate(make_user(ADMIN, username="yonetici"))
    assert staff.get(PREF).status_code == 403
