"""Şifre değişikliğinin her yoldan (servis, komut) maskelenerek denetim günlüğüne yazılması."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.test import RequestFactory

from apps.core import services
from apps.core.context import _current_request
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db


def password_entries():
    return AuditLog.objects.filter(action=AuditLog.Action.UPDATE, changes__has_key="password")


def test_password_change_via_service_is_masked_with_request_actor(make_user):
    admin, user = make_user("admin"), make_user()
    request = RequestFactory().post("/", REMOTE_ADDR="10.0.0.9")
    request.user = admin
    token = _current_request.set(request)
    try:
        user.set_password("Yeni.Sifre-456")
        services.save_with_audit(user, admin)
    finally:
        _current_request.reset(token)

    entry = password_entries().get()
    assert entry.changes == {"password": ["***", "***"]}
    assert entry.actor == admin
    assert entry.ip_address == "10.0.0.9"
    assert entry.note == "Şifre değiştirildi"


def test_password_change_without_request_has_no_actor(make_user):
    user = make_user()
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    user.set_password("Yeni.Sifre-456")
    user.save()

    assert password_entries().get().actor is None


def test_changepassword_command_is_audited(make_user, monkeypatch):
    user = make_user(username="depo1")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "Yeni.Sifre-456")

    call_command("changepassword", "depo1")

    assert password_entries().get().target == user


def test_saving_without_password_change_writes_nothing(make_user):
    user = make_user()

    user.full_name = "Yeni Ad"
    user.save()
    user.save(update_fields=["last_login"])

    assert not password_entries().exists()


def test_user_creation_does_not_log_password_change(make_user):
    make_user()

    assert not password_entries().exists()
