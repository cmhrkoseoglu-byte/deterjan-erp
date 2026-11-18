"""Termin (sözü verilen teslim tarihi): onayda zorunluluk, gerekçeli değişiklik, durum ve yetki
(docs/plan/musteri-siparis-takibi.md §3.1)."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, timedelta
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.services import transition_status
from apps.sales import services
from apps.sales.models import SalesOrder
from apps.sales.state import sales_order_states
from apps.sales.tests.factories import draft_order, finished_lot, finished_product

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

Status = SalesOrder.Status
Commit = Callable[[], AbstractContextManager[Any]]
URL = "/api/v1/sales/orders/"


def today() -> date:
    return timezone.localdate()


def _draft(seller: User, **data: Any) -> SalesOrder:
    product = finished_product()
    finished_lot(product, "100")
    return draft_order(seller, [(product, "10", "ADET")], **data)


def _confirmed(seller: User) -> SalesOrder:
    return services.confirm_order(seller, _draft(seller))


def _audit(order: SalesOrder, action: str) -> AuditLog:
    return AuditLog.objects.filter(object_id=order.pk, action=action).latest("id")


# --- onay ---------------------------------------------------------------------------------------


def test_confirm_requires_promised_date(seller: User) -> None:
    order = _draft(seller, promised_date=None)

    with pytest.raises(BusinessRuleError) as exc:
        services.confirm_order(seller, order)

    assert exc.value.code == "promised_date_required"
    order.refresh_from_db()
    assert order.status == Status.DRAFT


def test_confirm_rejects_past_promised_date(seller: User) -> None:
    order = _draft(seller, order_date=today() - timedelta(days=5))
    with pytest.raises(BusinessRuleError) as exc:
        services.confirm_order(seller, order, promised_date=today() - timedelta(days=1))
    assert exc.value.code == "promised_date_past"


def test_confirm_sets_promised_date_and_audits_change(seller: User) -> None:
    order = _draft(seller, promised_date=None)
    promised = today() + timedelta(days=10)

    services.confirm_order(seller, order, "tamam", promised_date=promised)

    order.refresh_from_db()
    assert order.status == Status.CONFIRMED
    assert order.promised_date == promised
    log = _audit(order, AuditLog.Action.STATUS_CHANGE)
    assert log.changes["promised_date"] == [None, promised.isoformat()]


def test_promised_date_cannot_precede_order_date(seller: User) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        _draft(seller, promised_date=today() - timedelta(days=1))
    assert exc.value.code == "invalid_promised_date"


# --- termin değişikliği -------------------------------------------------------------------------


def test_change_promised_date_audits_and_publishes(
    seller: User, commit: Commit, published: list[events.Event]
) -> None:
    order = _confirmed(seller)
    old = order.promised_date
    assert old is not None
    new = today() + timedelta(days=20)

    with commit():
        services.change_promised_date(seller, order, new, "  Hammadde gecikti ")

    order.refresh_from_db()
    assert order.promised_date == new
    log = _audit(order, AuditLog.Action.UPDATE)
    assert log.changes["promised_date"] == [old.isoformat(), new.isoformat()]
    assert log.note == "Hammadde gecikti"
    [event] = [e for e in published if e.name == ev.SALES_ORDER_PROMISED_DATE_CHANGED]
    assert event.payload["old_promised_date"] == old.isoformat()
    assert event.payload["promised_date"] == new.isoformat()
    assert event.payload["reason"] == "Hammadde gecikti"
    assert event.payload["number"] == order.number


def test_change_promised_date_allowed_when_partially_shipped(seller: User) -> None:
    order = _confirmed(seller)
    transition_status(order, Status.PARTIALLY_SHIPPED, seller, machine=sales_order_states)
    new = today() + timedelta(days=3)

    services.change_promised_date(seller, order, new, "Kalan için yeni söz")

    order.refresh_from_db()
    assert order.promised_date == new


def test_change_promised_date_requires_reason(seller: User) -> None:
    order = _confirmed(seller)
    with pytest.raises(BusinessRuleError) as exc:
        services.change_promised_date(seller, order, today() + timedelta(days=9), "   ")
    assert exc.value.code == "reason_required"


def test_change_promised_date_rejects_past_and_unchanged(seller: User) -> None:
    order = _confirmed(seller)
    with pytest.raises(BusinessRuleError) as exc:
        services.change_promised_date(seller, order, today() - timedelta(days=1), "geç")
    assert exc.value.code == "promised_date_past"
    assert order.promised_date is not None
    with pytest.raises(BusinessRuleError) as exc:
        services.change_promised_date(seller, order, order.promised_date, "aynı")
    assert exc.value.code == "promised_date_unchanged"


@pytest.mark.parametrize("status", [Status.DRAFT, Status.SHIPPED, Status.CLOSED])
def test_change_promised_date_rejected_in_other_states(seller: User, status: str) -> None:
    order = _draft(seller) if status == Status.DRAFT else _confirmed(seller)
    if status != Status.DRAFT:
        transition_status(order, Status.SHIPPED, seller, machine=sales_order_states)
    if status == Status.CLOSED:
        transition_status(order, Status.CLOSED, seller, machine=sales_order_states)

    with pytest.raises(BusinessRuleError) as exc:
        services.change_promised_date(seller, order, today() + timedelta(days=9), "neden")
    assert exc.value.code == "document_locked"


def test_change_promised_date_needs_change_access(seller: User, planner: User) -> None:
    order = _confirmed(seller)
    with pytest.raises(PermissionDenied):
        services.change_promised_date(planner, order, today() + timedelta(days=9), "neden")


# --- API ----------------------------------------------------------------------------------------


def test_api_confirm_with_promised_date_and_change(
    client_for: Callable[..., APIClient], seller: User
) -> None:
    order = _draft(seller, promised_date=None)
    client = client_for("sevkiyat")
    promised = today() + timedelta(days=4)

    missing = client.post(f"{URL}{order.pk}/confirm/", {}, format="json")
    assert missing.status_code == 400
    assert missing.json()["code"] == "promised_date_required"

    confirmed = client.post(
        f"{URL}{order.pk}/confirm/", {"promised_date": str(promised)}, format="json"
    )
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()["promised_date"] == str(promised)

    later = today() + timedelta(days=8)
    changed = client.post(
        f"{URL}{order.pk}/promised-date/",
        {"promised_date": str(later), "reason": "Müşteri istedi"},
        format="json",
    )
    assert changed.status_code == 200, changed.json()
    assert changed.json()["promised_date"] == str(later)

    listed = client.get(URL, {"ordering": "promised_date"})
    assert listed.json()["results"][0]["promised_date"] == str(later)


def test_api_change_promised_date_validates_body(
    client_for: Callable[..., APIClient], seller: User
) -> None:
    order = _confirmed(seller)
    response = client_for("sevkiyat").post(
        f"{URL}{order.pk}/promised-date/", {"promised_date": ""}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.parametrize("role", ["planlama", "depo"])
def test_api_change_promised_date_forbidden_for_readers(
    client_for: Callable[..., APIClient], seller: User, role: str
) -> None:
    order = _confirmed(seller)
    response = client_for(role).post(
        f"{URL}{order.pk}/promised-date/",
        {"promised_date": str(today() + timedelta(days=9)), "reason": "neden"},
        format="json",
    )
    assert response.status_code == 403
