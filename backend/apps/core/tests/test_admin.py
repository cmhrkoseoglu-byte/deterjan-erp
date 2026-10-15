"""Yönetim paneli: giriş/çıkış denetimi ve sınırı, şifre ve rol değişikliği denetimi, roller."""

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.core.models import AuditLog, User
from apps.core.tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.django_db

ADMIN_LOGIN = "/admin/login/"


@pytest.fixture
def superuser(make_user):
    return make_user("admin", username="yonetici", is_staff=True, is_superuser=True)


@pytest.fixture
def admin_client(superuser):
    client = Client()
    client.force_login(superuser)
    return client


def test_admin_failed_login_is_audited(superuser):
    response = Client().post(
        ADMIN_LOGIN,
        {"username": "yonetici", "password": "yanlis"},
        REMOTE_ADDR="10.1.1.5",
    )

    assert response.status_code == 200  # form hata ile tekrar gösterilir
    entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
    assert entry.target == superuser
    assert "yonetici" in entry.note
    assert entry.ip_address == "10.1.1.5"


def test_admin_login_and_logout_are_audited(superuser):
    client = Client()

    response = client.post(ADMIN_LOGIN, {"username": "yonetici", "password": DEFAULT_PASSWORD})
    assert response.status_code == 302
    client.post("/admin/logout/")

    actions = list(AuditLog.objects.order_by("id").values_list("action", "actor"))
    assert actions == [
        (AuditLog.Action.LOGIN, superuser.pk),
        (AuditLog.Action.LOGOUT, superuser.pk),
    ]


def test_admin_login_shares_rate_limit(superuser, settings):
    from django.core.cache import cache

    cache.clear()
    settings.LOGIN_RATE_LIMIT = "2/minute"
    client = Client()

    codes = [
        client.post(ADMIN_LOGIN, {"username": "yonetici", "password": "x"}).status_code
        for _ in range(3)
    ]

    assert codes == [200, 200, 429]
    assert AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED).count() == 2
    cache.clear()


def test_admin_password_change_of_other_user_is_audited(admin_client, superuser, make_user):
    target = make_user("depo", username="depo1")

    response = admin_client.post(
        f"/admin/core/user/{target.pk}/password/",
        {"password1": "Yeni.Sifre-456", "password2": "Yeni.Sifre-456", "usable_password": "true"},
    )

    assert response.status_code == 302
    target.refresh_from_db()
    assert target.check_password("Yeni.Sifre-456")
    entry = AuditLog.objects.get(action=AuditLog.Action.UPDATE)
    assert entry.target == target
    assert entry.actor == superuser
    assert entry.changes == {"password": ["***", "***"]}
    assert "pbkdf2" not in str(entry.changes) and "md5" not in str(entry.changes)


def test_admin_user_role_change_is_audited(admin_client, superuser, make_user):
    target = make_user("depo", username="depo1", full_name="Ayşe")
    planlama = Group.objects.get(name="planlama")

    response = admin_client.post(
        f"/admin/core/user/{target.pk}/change/",
        {
            "username": "depo1",
            "full_name": "Ayşe Yılmaz",
            "email": target.email,
            "phone": "",
            "is_active": "on",
            "groups": [planlama.pk],
        },
    )

    assert response.status_code == 302, response.content[:500]
    updates = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=target.pk)
    assert sorted((e.changes for e in updates), key=str) == [
        {"full_name": ["Ayşe", "Ayşe Yılmaz"]},
        {"roles": [["depo"], ["planlama"]]},
    ]
    assert {e.actor for e in updates} == {superuser}


def test_admin_cannot_delete_users(admin_client, make_user):
    target = make_user(username="depo1")

    response = admin_client.post(f"/admin/core/user/{target.pk}/delete/", {"post": "yes"})

    assert response.status_code == 403
    assert User.objects.filter(pk=target.pk).exists()


@pytest.mark.parametrize("action", ["change", "delete"])
def test_roles_cannot_be_renamed_or_deleted_in_admin(admin_client, action):
    depo = Group.objects.get(name="depo")

    response = admin_client.post(
        f"/admin/auth/group/{depo.pk}/{action}/", {"name": "admin", "post": "yes"}
    )

    assert response.status_code == 403
    assert Group.objects.filter(pk=depo.pk, name="depo").exists()


def test_roles_cannot_be_added_in_admin(admin_client):
    response = admin_client.post("/admin/auth/group/add/", {"name": "muhasebe"})

    assert response.status_code == 403
    assert not Group.objects.filter(name="muhasebe").exists()


def test_roles_are_listed_read_only(admin_client):
    response = admin_client.get("/admin/auth/group/")

    assert response.status_code == 200
    assert "Depo" in response.content.decode()


def test_audit_log_is_read_only_in_admin(admin_client, superuser):
    entry = AuditLog.objects.create(action=AuditLog.Action.CUSTOM, note="x")

    assert (
        admin_client.post(f"/admin/core/auditlog/{entry.pk}/delete/", {"post": "yes"}).status_code
        == 403
    )
    assert admin_client.post("/admin/core/auditlog/add/", {}).status_code == 403
    assert AuditLog.objects.filter(pk=entry.pk).exists()
