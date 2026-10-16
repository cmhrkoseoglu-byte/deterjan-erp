import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.core.roles import ADMIN, DEPO, YONETIM
from apps.core.tests.factories import DEFAULT_PASSWORD
from apps.core.tests.testapp.models import Widget

pytestmark = pytest.mark.django_db

LOGIN = reverse("core:auth-login")
LOGOUT = reverse("core:auth-logout")
ME = reverse("core:auth-me")
CSRF = reverse("core:auth-csrf")
USERS = reverse("core:user-list")
AUDIT = reverse("core:audit-log-list")


def csrf_client() -> APIClient:
    """Tarayıcı gibi CSRF kontrolü yapan istemci; csrf çerezini alır."""
    client = APIClient(enforce_csrf_checks=True)
    response = client.get(CSRF)
    assert response.status_code == 204
    return client


def post_with_csrf(client: APIClient, url: str, data: dict | None = None):
    token = client.cookies["csrftoken"].value
    return client.post(url, data or {}, format="json", HTTP_X_CSRFTOKEN=token)


# --- auth -------------------------------------------------------------------------------------


def test_csrf_endpoint_sets_cookie():
    response = APIClient().get(CSRF)

    assert response.status_code == 204
    assert "csrftoken" in response.cookies


def test_login_success_returns_me_and_audits(make_user):
    user = make_user(DEPO, username="depo1", full_name="Ayşe Yılmaz")
    client = csrf_client()

    response = post_with_csrf(client, LOGIN, {"username": "depo1", "password": DEFAULT_PASSWORD})

    assert response.status_code == 200
    assert response.json() == {
        "id": user.pk,
        "username": "depo1",
        "full_name": "Ayşe Yılmaz",
        "email": "depo1@example.com",
        "roles": ["depo"],
        "is_superuser": False,
        "otp_enabled": False,
        "otp_setup_required": False,
        "field_device": False,
        "idle_timeout_seconds": 3600,
    }
    entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN)
    assert entry.actor == user
    assert entry.ip_address == "127.0.0.1"
    # Oturum açıldı: me çalışıyor
    assert client.get(ME).status_code == 200


def test_login_records_ip_from_nginx_header(make_user):
    make_user(username="depo1")
    client = csrf_client()

    token = client.cookies["csrftoken"].value
    client.post(
        LOGIN,
        {"username": "depo1", "password": DEFAULT_PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_X_REAL_IP="192.168.1.20",
    )

    assert AuditLog.objects.get(action=AuditLog.Action.LOGIN).ip_address == "192.168.1.20"


def test_login_without_csrf_token_rejected_with_json(make_user):
    make_user(username="depo1")
    client = APIClient(enforce_csrf_checks=True)

    response = client.post(
        LOGIN, {"username": "depo1", "password": DEFAULT_PASSWORD}, format="json"
    )

    assert response.status_code == 403
    assert response["Content-Type"] == "application/json"
    assert response.json()["code"] == "csrf_failed"
    assert not AuditLog.objects.filter(action=AuditLog.Action.LOGIN).exists()


def test_write_with_stale_csrf_token_after_login_is_csrf_failed(make_user):
    make_user(username="depo1")
    client = csrf_client()
    old_token = client.cookies["csrftoken"].value
    post_with_csrf(client, LOGIN, {"username": "depo1", "password": DEFAULT_PASSWORD})

    response = client.post(LOGOUT, {}, format="json", HTTP_X_CSRFTOKEN=old_token)

    assert response.status_code == 403
    assert response.json() == {
        "code": "csrf_failed",
        "detail": "Güvenlik doğrulaması başarısız. Sayfayı yenileyip tekrar deneyin.",
    }


def test_login_wrong_password_is_400_and_audited(make_user):
    user = make_user(username="depo1")

    response = post_with_csrf(csrf_client(), LOGIN, {"username": "depo1", "password": "yanlis"})

    assert response.status_code == 400
    assert response.json() == {
        "code": "invalid_credentials",
        "detail": "Kullanıcı adı veya şifre hatalı.",
    }
    entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
    assert entry.actor is None
    assert entry.target == user
    assert entry.changes == {}
    assert "depo1" in entry.note
    assert entry.ip_address == "127.0.0.1"
    assert not AuditLog.objects.filter(action=AuditLog.Action.LOGIN).exists()


def test_login_unknown_user_audited_without_target():
    response = post_with_csrf(csrf_client(), LOGIN, {"username": "yok", "password": "x"})

    assert response.status_code == 400
    entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
    assert entry.content_type is None
    assert "yok" in entry.note


def test_login_inactive_user_rejected(make_user):
    make_user(username="depo1", is_active=False)

    response = post_with_csrf(
        csrf_client(), LOGIN, {"username": "depo1", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_credentials"


def test_login_missing_fields_is_validation_error():
    response = post_with_csrf(csrf_client(), LOGIN, {"username": "depo1"})

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_error"
    assert "password" in body["errors"]


@pytest.fixture
def login_limit_3(settings):
    from django.core.cache import cache

    cache.clear()
    settings.LOGIN_RATE_LIMIT = "3/minute"
    yield
    cache.clear()


def test_login_is_throttled(login_limit_3):
    client = csrf_client()

    responses = [
        post_with_csrf(client, LOGIN, {"username": "x", "password": "y"}) for _ in range(4)
    ]

    assert [r.status_code for r in responses] == [400, 400, 400, 429]
    assert responses[-1].json()["code"] == "throttled"
    assert responses[-1].json()["detail"]


def test_login_throttle_ignores_spoofed_forwarded_for(login_limit_3):
    """İstemcinin gönderdiği X-Forwarded-For her istekte değişse de sınır nginx'in yazdığı
    X-Real-IP'ye göre uygulanır."""
    client = csrf_client()
    token = client.cookies["csrftoken"].value

    codes = [
        client.post(
            LOGIN,
            {"username": "x", "password": "y"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_X_FORWARDED_FOR=f"10.9.9.{n}, 192.168.1.20",
            HTTP_X_REAL_IP="192.168.1.20",
        ).status_code
        for n in range(5)
    ]

    assert codes == [400, 400, 400, 429, 429]


def test_login_throttle_is_per_client_ip(login_limit_3):
    client = csrf_client()
    token = client.cookies["csrftoken"].value

    def attempt(ip: str) -> int:
        return client.post(
            LOGIN,
            {"username": "x", "password": "y"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_X_REAL_IP=ip,
        ).status_code

    assert [attempt("192.168.1.20") for _ in range(4)][-1] == 429
    assert attempt("192.168.1.21") == 400


def test_logout_ends_session_and_audits(make_user):
    user = make_user(username="depo1")
    client = csrf_client()
    post_with_csrf(client, LOGIN, {"username": "depo1", "password": DEFAULT_PASSWORD})

    response = post_with_csrf(client, LOGOUT)

    assert response.status_code == 204
    assert AuditLog.objects.get(action=AuditLog.Action.LOGOUT).actor == user
    assert client.get(ME).status_code == 401


def test_logout_requires_csrf_when_logged_in(make_user):
    make_user(username="depo1")
    client = csrf_client()
    post_with_csrf(client, LOGIN, {"username": "depo1", "password": DEFAULT_PASSWORD})

    response = client.post(LOGOUT)

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert client.get(ME).status_code == 200


def test_logout_when_anonymous_is_noop():
    response = post_with_csrf(csrf_client(), LOGOUT)

    assert response.status_code == 204
    assert not AuditLog.objects.exists()


def test_me_requires_login():
    response = APIClient().get(ME)

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_me_lists_roles_sorted(client_for):
    response = client_for(YONETIM, DEPO).get(ME)

    assert response.status_code == 200
    assert response.json()["roles"] == ["depo", "yonetim"]


def test_malformed_json_is_turkish_parse_error():
    client = csrf_client()
    token = client.cookies["csrftoken"].value

    response = client.post(
        LOGIN, data="{bozuk", content_type="application/json", HTTP_X_CSRFTOKEN=token
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "parse_error",
        "detail": "İstek gövdesi okunamadı (geçersiz JSON).",
    }


def test_unknown_api_url_is_json_404(client_for):
    response = client_for(DEPO).get("/api/v1/olmayan/")

    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "detail": "Bulunamadı."}


def test_unknown_non_api_url_is_html_404(client):
    response = client.get("/olmayan-sayfa/")

    assert response.status_code == 404
    assert "application/json" not in response["Content-Type"]


# --- users ------------------------------------------------------------------------------------


def test_users_list_for_admin(client_for, make_user):
    make_user(DEPO, username="depo1")

    response = client_for(ADMIN).get(USERS, {"role": "depo"})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["username"] == "depo1"
    assert body["results"][0]["roles"] == ["depo"]
    assert "password" not in body["results"][0]


@pytest.mark.parametrize("role", [DEPO, YONETIM])
def test_users_list_forbidden_for_other_roles(client_for, role):
    response = client_for(role).get(USERS)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_users_list_requires_login():
    assert APIClient().get(USERS).status_code == 401


def test_users_api_is_read_only(client_for):
    client = client_for(ADMIN)

    assert client.post(USERS, {"username": "x"}).status_code == 405


def test_users_list_is_paginated_by_50(client_for, make_user):
    for _ in range(55):
        make_user()

    body = client_for(ADMIN).get(USERS).json()

    assert body["count"] == 56
    assert len(body["results"]) == 50
    assert body["next"] is not None


# --- audit log --------------------------------------------------------------------------------


@pytest.fixture
def widget_history(make_user):
    from apps.core.services import save_with_audit

    actor = make_user(username="editor")
    widget = save_with_audit(Widget(name="Tank"), actor)
    widget.name = "Tank 2"
    save_with_audit(widget, actor)
    save_with_audit(Widget(name="Başka"), actor)
    return widget


@pytest.mark.parametrize("role", [ADMIN, YONETIM])
def test_audit_log_filtered_by_object(client_for, widget_history, role):
    response = client_for(role).get(
        AUDIT, {"content_type": "core_testapp.widget", "object_id": widget_history.pk}
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["action"] for r in results] == ["update", "create"]  # en yeni önce
    assert results[0]["changes"] == {"name": ["Tank", "Tank 2"]}
    assert results[0]["content_type"] == "core_testapp.widget"
    assert results[0]["actor_name"] == str(widget_history.created_by)


def test_audit_log_unknown_content_type_returns_empty(client_for, widget_history):
    response = client_for(ADMIN).get(AUDIT, {"content_type": "yok.model"})

    assert response.json()["count"] == 0


def test_audit_log_forbidden_for_other_roles(client_for):
    assert client_for(DEPO).get(AUDIT).status_code == 403


def test_audit_log_is_read_only(client_for, widget_history):
    client = client_for(ADMIN)
    entry = AuditLog.objects.first()
    url = reverse("core:audit-log-detail", args=[entry.pk])

    assert client.get(url).status_code == 200
    assert client.post(AUDIT, {}).status_code == 405
    assert client.patch(url, {"note": "x"}).status_code == 405
    assert client.delete(url).status_code == 405


# --- schema -----------------------------------------------------------------------------------


def test_openapi_schema_requires_login_outside_dev():
    assert APIClient().get("/api/schema/").status_code == 401


def test_openapi_schema_and_docs(client_for):
    client = client_for(DEPO)

    schema = client.get("/api/schema/")
    assert schema.status_code == 200
    assert b"/api/v1/auth/login/" in schema.content
    assert client.get("/api/docs/").status_code == 200


def test_openapi_schema_generates_without_warnings(tmp_path):
    from django.core.management import call_command

    call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "s.yml"))
