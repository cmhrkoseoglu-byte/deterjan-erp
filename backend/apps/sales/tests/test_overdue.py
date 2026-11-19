"""Geciken teslim bildirimi: günlük kontrolde yeni gecikenler, aynı vade için bir kez, termin
değişince yeniden; yalnız yetkili sevkiyat ve yönetim (docs/plan/musteri-siparis-takibi.md §3.4)."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from django.db import transaction
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.access import VIEW
from apps.core.models import AccessOverride, User
from apps.core.roles import SEVKIYAT, YONETIM
from apps.masterdata.models import Customer
from apps.masterdata.tests.factories import CustomerFactory
from apps.sales import services
from apps.sales.models import SalesOrder
from apps.sales.tests.factories import draft_order, finished_lot, finished_product
from apps.workflow.models import Notification

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

Commit = Callable[..., Any]
RULE = "sales_orders_overdue"


def today() -> date:
    return timezone.localdate()


def _order(seller: User, customer: Customer | None = None) -> SalesOrder:
    product = finished_product()
    finished_lot(product, "100")
    order = draft_order(
        seller, [(product, "2", "KOLI")], customer=customer or CustomerFactory.create()
    )
    return services.confirm_order(seller, order)


def _due(order: SalesOrder, days_ago: int) -> None:
    """Vadeyi geçmişe çeker (zaman geçmiş gibi; onaydan sonra termin geçmişe girilemez)."""
    SalesOrder.objects.filter(pk=order.pk).update(promised_date=today() - timedelta(days=days_ago))


def _daily_check(commit: Commit) -> None:
    with commit():
        events.publish(ev.DAILY_CHECK, {})


def _notes() -> list[Notification]:
    return list(Notification.objects.filter(rule_code=RULE).order_by("id"))


@pytest.fixture
def boss(make_user: Callable[..., User]) -> User:
    return make_user(YONETIM, username="yonetici")


def test_first_morning_notifies_once(seller: User, boss: User, commit: Commit) -> None:
    late = _order(seller, CustomerFactory.create(name="Zincir Market"))
    _due(late, 2)
    _order(seller)  # vadesi gelmedi

    _daily_check(commit)

    note = boss.notifications.get(rule_code=RULE)
    assert note.level == "WARNING"
    assert note.title == "Teslimi geciken siparişler: 1 yeni"
    assert late.number in note.body and "Zincir Market" in note.body
    assert "2 gün gecikti" in note.body
    assert seller.notifications.filter(rule_code=RULE).exists()  # sevkiyat
    late.refresh_from_db()
    assert late.overdue_notified_due_date == today() - timedelta(days=2)

    count = len(_notes())
    _daily_check(commit)
    assert len(_notes()) == count  # ertesi sabah tekrar yok


def test_new_late_order_next_day_lists_only_new(seller: User, boss: User, commit: Commit) -> None:
    first = _order(seller)
    _due(first, 3)
    _daily_check(commit)
    second = _order(seller)
    _due(second, 1)

    _daily_check(commit)

    latest = boss.notifications.filter(rule_code=RULE).latest("id")
    assert second.number in latest.body and first.number not in latest.body
    assert "Geciken sipariş toplamı: 2" in latest.body


def test_changed_promise_notifies_again_when_new_due_passes(
    seller: User, boss: User, commit: Commit
) -> None:
    order = _order(seller)
    _due(order, 1)
    _daily_check(commit)
    services.change_promised_date(seller, order, today() + timedelta(days=3), "Müşteri onayladı")
    _daily_check(commit)
    assert boss.notifications.filter(rule_code=RULE).count() == 1  # yeni vade gelmedi

    _due(order, 4)  # yeni vade de geçti (ilkinden farklı gün)
    _daily_check(commit)

    assert boss.notifications.filter(rule_code=RULE).count() == 2


def test_finished_and_undated_orders_are_not_notified(seller: User, commit: Commit) -> None:
    cancelled = _order(seller)
    _due(cancelled, 2)
    services.cancel_order(seller, cancelled, "müşteri vazgeçti")
    undated = _order(seller)
    SalesOrder.objects.filter(pk=undated.pk).update(
        promised_date=None, requested_delivery_date=None
    )

    _daily_check(commit)

    assert _notes() == []
    assert services.publish_overdue_orders() == []


def test_not_sent_to_unrelated_or_unauthorized(
    seller: User, commit: Commit, make_user: Callable[..., User]
) -> None:
    planner = make_user("planlama", username="planci")
    no_view = make_user(SEVKIYAT, username="sevk-yetkisiz")
    AccessOverride.objects.create(
        user=no_view, key="sales.orders", level=VIEW, effect="revoke", note="deneme"
    )
    no_view.refresh_access()
    order = _order(seller)
    _due(order, 1)

    _daily_check(commit)

    assert not planner.notifications.filter(rule_code=RULE).exists()
    assert not no_view.notifications.filter(rule_code=RULE).exists()
    assert seller.notifications.filter(rule_code=RULE).exists()


def test_rolled_back_check_leaves_no_mark(seller: User, commit: Commit) -> None:
    order = _order(seller)
    _due(order, 1)

    with commit(), pytest.raises(RuntimeError), transaction.atomic():
        services.publish_overdue_orders()
        raise RuntimeError("geri al")

    order.refresh_from_db()
    assert order.overdue_notified_due_date is None
    assert _notes() == []
