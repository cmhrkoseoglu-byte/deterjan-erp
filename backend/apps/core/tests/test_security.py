"""Giriş güvenliği (Faz 5, Adım 5.5): kilitleme, 2FA, şifre politikası, hareketsizlik süresi."""

import time
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import security
from apps.core.exceptions import BusinessRuleError
from apps.core.middleware import LAST_ACTIVITY_KEY
from apps.core.models import AuditLog, LoginLockout, RecoveryCode, TOTPDevice
from apps.core.roles import ADMIN, DEPO, YONETIM
from apps.core.tests.factories import DEFAULT_PASSWORD
from apps.core.validators import LetterAndDigitValidator
from apps.workflow.models import Notification

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"


def csrf_client() -> APIClient:
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/v1/auth/csrf/")
    return client


def post(client: APIClient, url: str, data: dict | None = None, **extra):
    token = client.cookies["csrftoken"].value
    return client.post(url, data or {}, format="json", HTTP_X_CSRFTOKEN=token, **extra)


def login(client: APIClient, username: str, password: str = DEFAULT_PASSWORD, **data):
    return post(client, LOGIN, {"username": username, "password": password, **data})


def code_for(device: TOTPDevice, offset: int = 0) -> str:
    return security.totp_code(device.secret, security.current_step() + offset)


def enable_otp(user) -> TOTPDevice:
    security.start_otp_setup(user)
    device = TOTPDevice.objects.get(user=user)
    security.confirm_otp_setup(user, code_for(device))
    device.refresh_from_db()
    return device


# --- hesap kilitleme ----------------------------------------------------------------------------


def test_five_failures_lock_account_and_notify_admin(
    make_user, settings, django_capture_on_commit_callbacks
):
    user = make_user(DEPO, username="depo1")
    admin = make_user(ADMIN, username="sysadmin")
    client = csrf_client()

    with django_capture_on_commit_callbacks(execute=True):
        codes = [login(client, "depo1", "yanlis").json()["code"] for _ in range(5)]

    assert codes == ["invalid_credentials"] * 4 + ["account_locked"]
    # Kilitliyken doğru şifre de reddedilir.
    response = login(client, "depo1")
    assert response.status_code == 400
    assert response.json()["code"] == "account_locked"
    lock = AuditLog.objects.get(action=AuditLog.Action.CUSTOM, note__startswith="Hesap kilitlendi")
    assert lock.target == user
    note = Notification.objects.get(rule_code="user_locked", recipient=admin)
    assert "depo1" in note.title


def test_unknown_username_gets_same_lock_message(make_user):
    client = csrf_client()
    codes = [login(client, "olmayan", "yanlis").json()["code"] for _ in range(6)]
    assert codes[-1] == "account_locked"
    assert not Notification.objects.filter(rule_code="user_locked").exists()


def test_lock_expires_and_success_resets_counter(make_user):
    make_user(DEPO, username="depo1")
    client = csrf_client()
    for _ in range(5):
        login(client, "depo1", "yanlis")
    LoginLockout.objects.filter(username="depo1").update(
        locked_until=timezone.now() - timedelta(seconds=1)
    )

    assert login(client, "depo1").status_code == 200
    assert not LoginLockout.objects.filter(username="depo1").exists()


def test_failures_outside_window_do_not_accumulate(make_user):
    make_user(DEPO, username="depo1")
    for _ in range(4):
        security.register_failed_login("depo1")
    LoginLockout.objects.filter(username="depo1").update(
        window_started_at=timezone.now() - timedelta(minutes=16)
    )
    security.register_failed_login("depo1")
    assert not security.is_locked("depo1")
    assert LoginLockout.objects.get(username="depo1").failed_count == 1


def test_locked_user_cannot_log_into_admin_site(make_user):
    make_user(ADMIN, username="yonetici", is_staff=True, is_superuser=True)
    for _ in range(5):
        security.register_failed_login("yonetici")

    response = Client().post(
        "/admin/login/", {"username": "yonetici", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200  # form hatasıyla geri döner
    assert "_auth_user_id" not in Client().session


def test_admin_unlocks_user(make_user, client_for):
    user = make_user(DEPO, username="depo1")
    for _ in range(5):
        security.register_failed_login("depo1")
    admin = client_for(ADMIN)

    listed = admin.get("/api/v1/users/", {"search": "depo1"}).json()["results"][0]
    assert listed["is_locked"] is True
    response = admin.post(f"/api/v1/users/{user.pk}/unlock/")

    assert response.status_code == 200
    assert response.json()["is_locked"] is False
    assert not security.is_locked("depo1")
    assert admin.post(f"/api/v1/users/{user.pk}/unlock/").json()["code"] == "not_locked"


def test_non_admin_cannot_unlock(make_user, client_for):
    user = make_user(DEPO)
    assert client_for(YONETIM).post(f"/api/v1/users/{user.pk}/unlock/").status_code == 403


# --- iki aşamalı doğrulama ----------------------------------------------------------------------


def test_totp_matches_rfc6238_vector():
    # RFC 6238 Ek B: anahtar "12345678901234567890", T=59 → 94287082 (8 hane); son 6 hane.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert security.totp_code(secret, 59 // 30) == "287082"


def test_otp_setup_and_login_flow(make_user):
    user = make_user(YONETIM, username="mudur")
    setup = security.start_otp_setup(user)
    assert setup.uri.startswith("otpauth://totp/")
    assert "<svg" in setup.qr_svg
    device = TOTPDevice.objects.get(user=user)

    with pytest.raises(BusinessRuleError) as wrong:
        security.confirm_otp_setup(user, "000000")
    assert wrong.value.code == "invalid_otp"
    codes = security.confirm_otp_setup(user, code_for(device))
    assert len(codes) == 10
    assert RecoveryCode.objects.filter(user=user).count() == 10

    client = csrf_client()
    assert login(client, "mudur").json()["code"] == "otp_required"
    assert login(client, "mudur", otp_code="123456").json()["code"] == "invalid_otp"
    response = login(client, "mudur", otp_code=code_for(device, 1))
    assert response.status_code == 200
    assert response.json()["otp_enabled"] is True
    # Aynı kod ikinci kez kullanılamaz.
    other = csrf_client()
    assert login(other, "mudur", otp_code=code_for(device, 1)).json()["code"] == "invalid_otp"


def test_recovery_code_works_once(make_user):
    user = make_user(YONETIM, username="mudur")
    security.start_otp_setup(user)
    codes = security.confirm_otp_setup(user, code_for(TOTPDevice.objects.get(user=user)))

    assert login(csrf_client(), "mudur", otp_code=codes[0].upper()).status_code == 200
    assert login(csrf_client(), "mudur", otp_code=codes[0]).json()["code"] == "invalid_otp"
    assert security.remaining_recovery_codes(user) == 9


def test_wrong_otp_counts_towards_lockout(make_user):
    user = make_user(YONETIM, username="mudur")
    enable_otp(user)
    client = csrf_client()
    codes = [login(client, "mudur", otp_code="000000").json()["code"] for _ in range(5)]
    assert codes[-1] == "account_locked"
    assert (
        AuditLog.objects.filter(
            action=AuditLog.Action.LOGIN_FAILED, note__contains="doğrulama kodu"
        ).count()
        == 5
    )


def test_required_role_must_set_up_otp_before_using_api(make_user, settings):
    settings.OTP_REQUIRED_ROLES = ["yonetim"]
    user = make_user(YONETIM, username="mudur")
    client = APIClient()
    client.force_login(user)

    me = client.get(ME).json()
    assert me["otp_setup_required"] is True
    blocked = client.get("/api/v1/audit-log/")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "otp_setup_required"

    setup = client.post("/api/v1/auth/otp/setup/").json()
    device = TOTPDevice.objects.get(user=user)
    assert setup["secret"] == device.secret
    confirm = client.post("/api/v1/auth/otp/confirm/", {"code": code_for(device)}, format="json")
    assert confirm.status_code == 200
    assert len(confirm.json()["recovery_codes"]) == 10
    assert client.get("/api/v1/audit-log/").status_code == 200


def test_required_role_cannot_disable_otp(make_user, settings):
    settings.OTP_REQUIRED_ROLES = ["yonetim"]
    user = make_user(YONETIM)
    enable_otp(user)
    with pytest.raises(BusinessRuleError) as exc:
        security.disable_otp(user, DEFAULT_PASSWORD)
    assert exc.value.code == "otp_required"


def test_optional_otp_can_be_disabled_with_password(make_user):
    user = make_user(DEPO)
    enable_otp(user)
    client = APIClient()
    client.force_login(user)

    wrong = client.post("/api/v1/auth/otp/disable/", {"password": "yanlis"}, format="json")
    assert wrong.json()["code"] == "wrong_password"
    ok = client.post("/api/v1/auth/otp/disable/", {"password": DEFAULT_PASSWORD}, format="json")
    assert ok.status_code == 204
    assert not security.otp_enabled(user)


def test_admin_resets_otp(make_user, client_for):
    user = make_user(YONETIM)
    enable_otp(user)
    admin = client_for(ADMIN)

    response = admin.post(f"/api/v1/users/{user.pk}/reset-otp/")
    assert response.status_code == 200
    assert response.json()["otp_enabled"] is False
    assert not RecoveryCode.objects.filter(user=user).exists()
    assert client_for(YONETIM).post(f"/api/v1/users/{user.pk}/reset-otp/").status_code == 403


def test_regenerate_recovery_codes_requires_totp(make_user):
    user = make_user(DEPO)
    device = enable_otp(user)
    old = set(RecoveryCode.objects.filter(user=user).values_list("code_hash", flat=True))
    codes = security.regenerate_recovery_codes(user, code_for(device, 1))
    assert len(codes) == 10
    assert old.isdisjoint(
        RecoveryCode.objects.filter(user=user).values_list("code_hash", flat=True)
    )


def test_admin_site_requires_otp_code(make_user, settings):
    settings.OTP_REQUIRED_ROLES = ["admin"]
    user = make_user(ADMIN, username="yonetici", is_staff=True, is_superuser=True)

    no_device = Client()
    no_device.post("/admin/login/", {"username": "yonetici", "password": DEFAULT_PASSWORD})
    assert "_auth_user_id" not in no_device.session

    device = enable_otp(user)
    client = Client()
    client.post(
        "/admin/login/",
        {"username": "yonetici", "password": DEFAULT_PASSWORD, "otp_code": "000000"},
    )
    assert "_auth_user_id" not in client.session
    client.post(
        "/admin/login/",
        {"username": "yonetici", "password": DEFAULT_PASSWORD, "otp_code": code_for(device, 1)},
    )
    assert client.session["_auth_user_id"] == str(user.pk)
    assert client.get("/admin/").status_code == 200


def test_admin_site_blocks_session_without_required_otp(make_user, settings):
    settings.OTP_REQUIRED_ROLES = ["admin"]
    user = make_user(ADMIN, is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    assert client.get("/admin/").status_code == 302  # giriş sayfasına


# --- şifre politikası ve değiştirme -------------------------------------------------------------


def test_letter_and_digit_validator():
    validator = LetterAndDigitValidator()
    validator.validate("abc123def0")
    for weak in ("sadeceharfler", "1234567890"):
        with pytest.raises(ValidationError):
            validator.validate(weak)


def test_password_change(make_user):
    user = make_user(DEPO, username="depo1")
    client = APIClient()
    client.force_login(user)
    url = "/api/v1/auth/password/"

    wrong = client.post(url, {"old_password": "x", "new_password": "Yeni.Sifre42"}, format="json")
    assert wrong.json()["code"] == "wrong_password"
    weak = client.post(
        url, {"old_password": DEFAULT_PASSWORD, "new_password": "kisa"}, format="json"
    )
    assert weak.json()["code"] == "weak_password"
    ok = client.post(
        url, {"old_password": DEFAULT_PASSWORD, "new_password": "Yeni.Sifre42"}, format="json"
    )
    assert ok.status_code == 204
    assert client.get(ME).status_code == 200  # oturum açık kaldı
    user.refresh_from_db()
    assert user.check_password("Yeni.Sifre42")
    assert AuditLog.objects.filter(note="Şifre değiştirildi", object_id=user.pk).exists()


# --- hareketsizlik süresi ve saha tableti -------------------------------------------------------


def _age_session(client: APIClient, seconds: int) -> None:
    session = client.session
    session[LAST_ACTIVITY_KEY] = time.time() - seconds
    session.save()


def test_idle_session_expires(make_user):
    user = make_user(DEPO)
    client = APIClient()
    client.force_login(user)
    assert client.get(ME).status_code == 200

    _age_session(client, 61 * 60)
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["code"] == "session_expired"
    assert client.get(ME).status_code == 401
    entry = AuditLog.objects.get(action=AuditLog.Action.LOGOUT)
    assert entry.note == "Hareketsizlik nedeniyle oturum kapandı"


def test_activity_keeps_session_but_background_polls_do_not(make_user):
    user = make_user(DEPO)
    client = APIClient()
    client.force_login(user)
    _age_session(client, 50 * 60)

    # Arka plan isteği: kullanıcı 50 dakikadır dokunmadı → etkinlik yenilenmez.
    assert client.get(ME, HTTP_X_ERP_IDLE_SECONDS="3000").status_code == 200
    _age_session(client, 61 * 60)
    assert client.get(ME, HTTP_X_ERP_IDLE_SECONDS="3660").status_code == 401

    client.force_login(user)
    _age_session(client, 50 * 60)
    assert client.get(ME, HTTP_X_ERP_IDLE_SECONDS="2").status_code == 200  # kullanıcı dokundu
    assert time.time() - client.session[LAST_ACTIVITY_KEY] < 10


def test_field_device_has_short_timeout(make_user, client_for):
    admin = make_user(ADMIN)
    client = APIClient()
    client.force_login(admin)

    response = client.post("/api/v1/auth/field-device/", {"enabled": True}, format="json")
    assert response.status_code == 200
    assert client.get(ME).json()["field_device"] is True
    assert client.get(ME).json()["idle_timeout_seconds"] == 600

    _age_session(client, 11 * 60)
    assert client.get(ME).status_code == 401

    client.force_login(admin)
    client.post("/api/v1/auth/field-device/", {"enabled": False}, format="json")
    assert client.get(ME).json()["field_device"] is False


def test_tampered_field_device_cookie_is_ignored(make_user):
    client = APIClient()
    client.force_login(make_user(DEPO))
    client.cookies["erp_field_device"] = "1"
    assert client.get(ME).json()["field_device"] is False


def test_only_admin_marks_field_device(make_user):
    client = APIClient()
    client.force_login(make_user(DEPO))
    response = client.post("/api/v1/auth/field-device/", {"enabled": True}, format="json")
    assert response.status_code == 403


def test_security_status(make_user):
    user = make_user(DEPO)
    enable_otp(user)
    client = APIClient()
    client.force_login(user)
    body = client.get("/api/v1/auth/security/").json()
    assert body["otp_enabled"] is True
    assert body["otp_required"] is False
    assert body["recovery_codes_remaining"] == 10
    assert any("10" in text for text in body["password_help"])
