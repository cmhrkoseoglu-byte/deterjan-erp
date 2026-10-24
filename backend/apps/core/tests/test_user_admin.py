"""Kullanıcı yönetimi (Sistem > Kullanıcılar): yeni kullanıcı ve geçici şifre, bilgi ve rol
güncelleme, pasife alma, şifre sıfırlama ve geçici şifreyle girende şifre değiştirme zorunluluğu."""

import re

import pytest
from django.contrib.auth import password_validation
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from rest_framework.test import APIClient

from apps.core import security, services
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.roles import ADMIN, DEPO, SEVKIYAT, YONETIM
from apps.core.tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.django_db

USERS = "/api/v1/users/"
LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"
PASSWORD = "/api/v1/auth/password/"
# Dörtlü gruplar, birbirine karışan karakterler (0/O, 1/l/I) olmadan.
TEMP_RE = re.compile(r"^[a-hj-km-np-zA-HJ-NP-Z2-9]{4}(-[a-hj-km-np-zA-HJ-NP-Z2-9]{4}){2,}$")
NEW_PASSWORD = "Yeni.Sifre-2026"


def csrf_client() -> APIClient:
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf/")
    return client


def post(client: APIClient, url: str, data: dict | None = None):
    token = client.cookies["csrftoken"].value
    return client.post(url, data or {}, format="json", HTTP_X_CSRFTOKEN=token)


def login(client: APIClient, username: str, password: str = DEFAULT_PASSWORD):
    return post(client, LOGIN, {"username": username, "password": password})


def user_entries(user: User):
    return AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(User), object_id=user.pk
    )


def assert_no_password_in_audit(user: User, password: str) -> None:
    for entry in user_entries(user):
        assert password not in f"{entry.changes} {entry.note}"
        assert entry.changes.get("password") in (None, ["***", "***"])


@pytest.fixture
def admin(make_user):
    return make_user(ADMIN, username="sysadmin", full_name="Sistem Yöneticisi")


@pytest.fixture
def admin_client(admin):
    client = APIClient()
    client.force_login(admin)
    return client


def create(client: APIClient, **data):
    body = {"username": "ahmet.yilmaz", "full_name": "Ahmet Yılmaz", "roles": [DEPO], **data}
    return client.post(USERS, body, format="json")


# --- yeni kullanıcı -----------------------------------------------------------------------------


def test_admin_creates_user_and_sees_temporary_password_once(admin_client):
    response = create(admin_client, phone="0532 000 00 00", roles=[SEVKIYAT, DEPO])

    assert response.status_code == 201
    assert response["Cache-Control"] == "no-store"
    body = response.json()
    temporary = body["temporary_password"]
    assert TEMP_RE.match(temporary)
    assert body["user"]["username"] == "ahmet.yilmaz"
    assert body["user"]["full_name"] == "Ahmet Yılmaz"
    assert body["user"]["roles"] == [DEPO, SEVKIYAT]
    assert body["user"]["must_change_password"] is True
    assert body["user"]["is_active"] is True

    user = User.objects.get(username="ahmet.yilmaz")
    assert user.check_password(temporary)
    assert user.phone == "0532 000 00 00"
    # Geçici şifre yalnızca oluşturma yanıtındadır: liste ve ayrıntı göstermez.
    detail = admin_client.get(f"{USERS}{user.pk}/").json()
    assert "temporary_password" not in detail
    assert temporary not in admin_client.get(USERS).content.decode()
    # Denetim: oluşturma ve roller yazılır; şifre hiçbir kayıtta yok.
    entries = user_entries(user)
    assert entries.filter(action=AuditLog.Action.CREATE, note="Kullanıcı açıldı").exists()
    assert entries.filter(changes__roles=[[], [DEPO, SEVKIYAT]]).exists()
    assert_no_password_in_audit(user, temporary)


def test_temporary_password_follows_policy(roles):
    user = User(username="deneme", full_name="Deneme Kullanıcı")
    for _ in range(25):
        password = services.generate_temporary_password(user)
        password_validation.validate_password(password, user)
        assert TEMP_RE.match(password)


def test_temporary_password_grows_with_minimum_length(roles, settings):
    settings.AUTH_PASSWORD_VALIDATORS = [
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 16},
        },
    ]
    password = services.generate_temporary_password(User(username="deneme"))
    assert len(password) >= 16
    assert TEMP_RE.match(password)


@pytest.mark.parametrize(
    "username",
    ["Ahmet", "şule", "a", "ali veli", ".ali", "ali@firma"],
    ids=["buyuk-harf", "turkce", "tek-harf", "bosluk", "nokta-ile-baslar", "at-isareti"],
)
def test_username_rule(admin_client, username):
    response = create(admin_client, username=username)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_username"
    assert not User.objects.exclude(username="sysadmin").exists()


def test_username_must_be_unique_ignoring_case(admin_client, make_user):
    make_user(DEPO, username="Mehmet")  # yönetim panelinden açılmış eski bir hesap

    response = create(admin_client, username="mehmet")

    assert response.status_code == 400
    assert response.json()["code"] == "username_taken"


def test_full_name_and_known_roles_are_required(admin_client, admin):
    assert create(admin_client, full_name="").json()["code"] == "validation_error"
    unknown = create(admin_client, roles=["muhasebe"])
    assert unknown.status_code == 400
    assert "roles" in unknown.json()["errors"]
    with pytest.raises(BusinessRuleError) as exc:
        services.create_user(admin, username="ayse", full_name="   ")
    assert exc.value.code == "full_name_required"
    assert not User.objects.filter(username__in=["ahmet.yilmaz", "ayse"]).exists()


def test_user_without_roles_can_be_created(admin_client):
    response = create(admin_client, roles=[])

    assert response.status_code == 201
    assert response.json()["user"]["roles"] == []


# --- yetki --------------------------------------------------------------------------------------


def test_only_admin_manages_users(client_for, make_user):
    target = make_user(DEPO)
    client = client_for(YONETIM)

    assert create(client, username="yeni").status_code == 403
    patch = client.patch(f"{USERS}{target.pk}/", {"full_name": "X"}, format="json")
    assert patch.status_code == 403
    for action in ("deactivate", "activate", "reset-password"):
        assert client.post(f"{USERS}{target.pk}/{action}/").status_code == 403
    assert create(APIClient(), username="yeni").status_code == 401
    assert not User.objects.filter(username="yeni").exists()
    target.refresh_from_db()
    assert target.full_name != "X" and target.is_active


def test_users_are_never_deleted_or_replaced(admin_client, make_user):
    target = make_user(DEPO)

    assert admin_client.delete(f"{USERS}{target.pk}/").status_code == 405
    assert admin_client.put(f"{USERS}{target.pk}/", {}, format="json").status_code == 405
    assert User.objects.filter(pk=target.pk).exists()


# --- güncelleme ---------------------------------------------------------------------------------


def test_admin_updates_details_and_roles_but_not_username(admin_client, make_user):
    user = make_user(DEPO, username="ayse", full_name="Ayşe")

    response = admin_client.patch(
        f"{USERS}{user.pk}/",
        {
            "full_name": "Ayşe Yılmaz",
            "phone": "0532 111 22 33",
            "roles": [SEVKIYAT, DEPO],
            "username": "baska",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "ayse"
    assert body["full_name"] == "Ayşe Yılmaz"
    assert body["roles"] == [DEPO, SEVKIYAT]
    entries = user_entries(user)
    assert entries.filter(changes__full_name=["Ayşe", "Ayşe Yılmaz"]).exists()
    assert entries.filter(changes__roles=[[DEPO], [DEPO, SEVKIYAT]]).exists()


def test_partial_update_changes_only_given_fields(admin_client, make_user):
    user = make_user(DEPO, username="ayse", full_name="Ayşe", phone="123")

    admin_client.patch(f"{USERS}{user.pk}/", {"phone": ""}, format="json")

    user.refresh_from_db()
    user.refresh_roles()
    assert user.phone == ""
    assert user.full_name == "Ayşe"
    assert user.roles == [DEPO]


def test_admin_cannot_remove_own_admin_role(admin_client, admin):
    response = admin_client.patch(f"{USERS}{admin.pk}/", {"roles": [YONETIM]}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "cannot_remove_own_admin"
    admin.refresh_roles()
    assert admin.has_role(ADMIN)


def test_last_active_admin_keeps_admin_role(make_user):
    only = make_user(ADMIN, username="tek.yonetici")
    actor = make_user(YONETIM)

    with pytest.raises(BusinessRuleError) as exc:
        services.update_user(actor, only, roles=[DEPO])
    assert exc.value.code == "last_admin"

    make_user(ADMIN, username="ikinci.yonetici")
    services.update_user(actor, only, roles=[DEPO])
    only.refresh_roles()
    assert only.roles == [DEPO]


# --- pasife alma --------------------------------------------------------------------------------


def test_deactivate_ends_session_and_blocks_login_until_reactivated(admin_client, make_user):
    user = make_user(DEPO, username="depo1")
    session = APIClient()
    session.force_login(user)
    assert session.get(ME).status_code == 200

    response = admin_client.post(f"{USERS}{user.pk}/deactivate/")

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert session.get(ME).status_code == 401
    assert login(csrf_client(), "depo1").json()["code"] == "invalid_credentials"
    assert (
        user_entries(user)
        .filter(note="Kullanıcı pasife alındı", changes__is_active=[True, False])
        .exists()
    )

    response = admin_client.post(f"{USERS}{user.pk}/activate/")

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert login(csrf_client(), "depo1").status_code == 200
    assert user_entries(user).filter(note="Kullanıcı yeniden etkinleştirildi").exists()


def test_admin_cannot_deactivate_self(admin_client, admin):
    response = admin_client.post(f"{USERS}{admin.pk}/deactivate/")

    assert response.status_code == 400
    assert response.json()["code"] == "cannot_deactivate_self"
    admin.refresh_from_db()
    assert admin.is_active


def test_last_active_admin_cannot_be_deactivated(make_user):
    only = make_user(DEPO, username="tek", is_superuser=True)
    actor = make_user(YONETIM)

    with pytest.raises(BusinessRuleError) as exc:
        services.set_user_active(actor, only, False)
    assert exc.value.code == "last_admin"


def test_deactivating_twice_changes_nothing(admin_client, make_user):
    user = make_user(DEPO, is_active=False)
    before = user_entries(user).count()

    response = admin_client.post(f"{USERS}{user.pk}/deactivate/")

    assert response.status_code == 200
    assert user_entries(user).count() == before


# --- şifre sıfırlama ----------------------------------------------------------------------------


def test_reset_password_issues_new_temporary_password_and_ends_sessions(admin_client, make_user):
    user = make_user(DEPO, username="depo1")
    session = APIClient()
    session.force_login(user)  # girişte hatalı deneme sayacı sıfırlanır: kilit ondan sonra
    for _ in range(5):
        security.register_failed_login("depo1")
    assert security.is_locked("depo1")

    response = admin_client.post(f"{USERS}{user.pk}/reset-password/")

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    temporary = response.json()["temporary_password"]
    assert TEMP_RE.match(temporary)
    assert response.json()["user"]["must_change_password"] is True
    user.refresh_from_db()
    assert user.check_password(temporary)
    assert not user.check_password(DEFAULT_PASSWORD)
    assert session.get(ME).status_code == 401  # şifre değişti: açık oturum kapandı
    assert not security.is_locked("depo1")
    assert (
        user_entries(user)
        .filter(action=AuditLog.Action.CUSTOM, note__startswith="Şifre sıfırlandı")
        .filter(note__endswith="(hesap kilidi açıldı)")
        .exists()
    )
    assert_no_password_in_audit(user, temporary)


def test_reset_password_rules(admin_client, admin, make_user):
    own = admin_client.post(f"{USERS}{admin.pk}/reset-password/")
    assert own.status_code == 400
    assert own.json()["code"] == "use_security_page"

    inactive = make_user(DEPO, is_active=False)
    response = admin_client.post(f"{USERS}{inactive.pk}/reset-password/")
    assert response.status_code == 400
    assert response.json()["code"] == "user_inactive"


# --- geçici şifreyle ilk giriş ------------------------------------------------------------------


def test_temporary_password_must_be_changed_before_using_the_system(admin_client):
    created = create(admin_client, username="yeni.mudur", roles=[YONETIM]).json()
    temporary = created["temporary_password"]
    client = csrf_client()

    me = login(client, "yeni.mudur", temporary)
    assert me.status_code == 200
    assert me.json()["password_change_required"] is True
    blocked = client.get("/api/v1/audit-log/")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "password_change_required"
    # Oturum uçları açık kalır; geçici şifre yeni şifre olarak kullanılamaz.
    same = post(client, PASSWORD, {"old_password": temporary, "new_password": temporary})
    assert same.status_code == 400
    assert same.json()["code"] == "same_password"

    changed = post(client, PASSWORD, {"old_password": temporary, "new_password": NEW_PASSWORD})

    assert changed.status_code == 204
    assert client.get(ME).json()["password_change_required"] is False
    assert client.get("/api/v1/audit-log/").status_code == 200
    user = User.objects.get(username="yeni.mudur")
    assert not user.must_change_password
    assert user.check_password(NEW_PASSWORD)


def test_password_change_comes_before_otp_setup(admin_client, settings):
    settings.OTP_REQUIRED_ROLES = [YONETIM]
    temporary = create(admin_client, username="yeni.mudur", roles=[YONETIM]).json()[
        "temporary_password"
    ]
    client = csrf_client()
    login(client, "yeni.mudur", temporary)

    assert client.get("/api/v1/audit-log/").json()["code"] == "password_change_required"
    post(client, PASSWORD, {"old_password": temporary, "new_password": NEW_PASSWORD})
    assert client.get("/api/v1/audit-log/").json()["code"] == "otp_setup_required"


def test_admin_panel_is_closed_until_password_changed(make_user):
    make_user(ADMIN, username="yeni.yonetici", is_staff=True, must_change_password=True)

    response = Client().post(
        "/admin/login/", {"username": "yeni.yonetici", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200  # form hatayla tekrar gösterilir
    assert "Geçici şifreyle girdiniz" in response.content.decode()
