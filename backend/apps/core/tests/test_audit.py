from decimal import Decimal

import pytest

from apps.core import audit
from apps.core.context import _current_request
from apps.core.models import AuditLog
from apps.core.tests.testapp.models import Widget

pytestmark = pytest.mark.django_db


def test_diff_for_new_instance_lists_filled_fields():
    widget = Widget(name="Tank", quantity=Decimal("1.5"))

    assert audit.diff(None, widget) == {
        "name": [None, "Tank"],
        "quantity": [None, "1.5000"],
        "is_active": [None, True],
    }


def test_diff_compares_normalized_values():
    before = Widget(name="Tank", code="01", quantity=Decimal("1.5"))
    after = Widget(name="Tank", code="1", quantity="1.50")

    # Metin alanında "01" ≠ "1"; ondalık alanda 1.5 = 1.50
    assert audit.diff(before, after) == {"code": ["01", "1"]}


def test_diff_excludes_password_and_automatic_fields(make_user):
    # Şifre özeti farka girmez; şifre değişikliği core.signals ile maskelenerek yazılır
    # (bkz. test_signals.py).
    user = make_user()
    before = type(user).objects.get(pk=user.pk)
    user.set_password("yeni-sifre-123")

    assert audit.diff(before, user) == {}
    assert "password" in audit.diff(before, user, exclude=frozenset())


def test_diff_rounds_decimals_like_the_database():
    before = Widget(name="Tank", quantity=Decimal("1.2346"))
    after = Widget(name="Tank", quantity=Decimal("1.23456"))

    assert audit.diff(before, after) == {}
    assert audit.diff(None, after)["quantity"] == [None, "1.2346"]


def test_log_change_uses_request_ip_and_ignores_anonymous():
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    widget = Widget.objects.create(name="Tank")
    token = _current_request.set(RequestFactory().get("/", REMOTE_ADDR="10.0.0.5"))
    try:
        entry = audit.log_change(AnonymousUser(), widget, AuditLog.Action.CUSTOM, note="not")
    finally:
        _current_request.reset(token)

    assert entry.actor is None
    assert entry.ip_address == "10.0.0.5"
    assert entry.object_id == widget.pk
    assert entry.note == "not"


def test_log_change_rejects_unknown_action():
    with pytest.raises(ValueError):
        audit.log_change(None, None, "silme")
