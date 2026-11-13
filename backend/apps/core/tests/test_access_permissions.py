"""Bölüm denetimi ilkelleri: HasAccess, ReadRule, SignedIn, AdminOnly, AccessMixin, require_access
ve 403 yanıtındaki `required` listesi (docs/plan/kisi-yetkileri.md §5.4)."""

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from rest_framework import exceptions
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.core.access import APPROVE, CHANGE, READ, VIEW
from apps.core.authentication import CsrfFailed
from apps.core.exceptions import api_exception_handler
from apps.core.models import AccessOverride, User
from apps.core.permissions import (
    DEFAULT_MESSAGE,
    REQUIRED_ATTR,
    AccessMixin,
    AdminOnly,
    DenyUnknownAction,
    HasAccess,
    HasRole,
    MissingAccess,
    ReadRule,
    SignedIn,
    can_read,
    has_access,
    require_access,
)
from apps.core.roles import DEPO, PLANLAMA
from apps.production.access import BATCHES, ORDERS, PREP

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
VIEW_STUB = APIView()


def noted(request: Request) -> object:
    """İsteğe yazılan eksik yetki (yoksa None)."""
    return getattr(request, REQUIRED_ATTR, None)


def drf_request(user: Any, method: str = "get") -> Request:
    raw = getattr(factory, method)("/api/v1/x/")
    if user is not None:
        force_authenticate(raw, user=user)
    request = Request(raw)
    if user is None:
        request.user = AnonymousUser()
    return request


def test_has_access_and_can_read(make_user: Callable[..., User]) -> None:
    depo = make_user(DEPO)
    nobody = make_user()
    inactive = make_user(PLANLAMA, is_active=False)

    assert has_access(depo, PREP, CHANGE)
    assert not has_access(depo, ORDERS, CHANGE)
    assert can_read(nobody, ORDERS)
    assert not has_access(nobody, ORDERS)
    assert not has_access(inactive, ORDERS, CHANGE)
    assert not has_access(None, ORDERS)
    assert not can_read(AnonymousUser(), ORDERS)


def test_has_access_permission_notes_missing_access(make_user: Callable[..., User]) -> None:
    permission = HasAccess(ORDERS, APPROVE)()
    allowed = drf_request(make_user(PLANLAMA))
    denied = drf_request(make_user(DEPO))
    anonymous = drf_request(None)

    assert permission.has_permission(allowed, VIEW_STUB)
    assert not permission.has_permission(denied, VIEW_STUB)
    assert noted(denied) == [("production.orders", APPROVE)]
    assert not permission.has_permission(anonymous, VIEW_STUB)
    assert noted(anonymous) is None


def test_has_access_rejects_undeclared_level() -> None:
    with pytest.raises(ValueError, match="düzey bölümde yok"):
        HasAccess(PREP, APPROVE)


def test_read_rule_is_any_of(make_user: Callable[..., User]) -> None:
    permission = ReadRule(PREP, BATCHES)()
    nobody = make_user()

    assert permission.has_permission(drf_request(nobody), VIEW_STUB)
    assert ReadRule("sales.orders")().has_permission(drf_request(make_user(DEPO)), VIEW_STUB)
    denied = drf_request(nobody)
    assert not ReadRule("sales.orders")().has_permission(denied, VIEW_STUB)
    assert noted(denied) == [("sales.orders", VIEW)]
    with pytest.raises(ValueError, match="En az bir bölüm"):
        ReadRule()


def test_read_rule_hint_names_view_and_open_records(make_user: Callable[..., User]) -> None:
    user = make_user()
    AccessOverride.objects.create(
        user=user, key="production.open_records", level=READ, effect="revoke", note="x"
    )
    request = drf_request(user)

    assert not ReadRule(ORDERS, BATCHES)().has_permission(request, VIEW_STUB)
    assert noted(request) == [
        ("production.orders", VIEW),
        ("production.open_records", READ),
        ("production.batches", VIEW),
    ]


def test_signed_in_matches_is_authenticated(make_user: Callable[..., User]) -> None:
    permission = SignedIn("kişinin kendi hesabı")()
    nobody = drf_request(make_user())

    assert permission.has_permission(nobody, VIEW_STUB)
    assert IsAuthenticated().has_permission(nobody, VIEW_STUB)
    assert not permission.has_permission(drf_request(None), VIEW_STUB)
    with pytest.raises(ValueError, match="nedeni"):
        SignedIn(" ")


def test_admin_only(make_user: Callable[..., User]) -> None:
    assert AdminOnly().has_permission(drf_request(make_user("admin")), VIEW_STUB)
    assert AdminOnly().has_permission(drf_request(make_user(is_superuser=True)), VIEW_STUB)
    assert not AdminOnly().has_permission(drf_request(make_user(PLANLAMA)), VIEW_STUB)


class _DemoViewSet(AccessMixin):
    read_access = ReadRule(ORDERS)
    action_access = {"approve": HasAccess(ORDERS, APPROVE)}

    def __init__(self, action: str | None, method: str) -> None:
        self.action = action
        self.action_map = {method.lower(): action}
        self.request = factory.generic(method, "/x/")


def test_access_mixin_maps_actions_and_denies_unknown_writes() -> None:
    (approve,) = _DemoViewSet("approve", "POST").get_permissions()
    (listing,) = _DemoViewSet("list", "GET").get_permissions()
    (custom,) = _DemoViewSet("close", "POST").get_permissions()

    assert type(approve).__name__ == "HasAccess(production.orders, approve)"
    assert type(listing).__name__ == "ReadRule(production.orders)"
    assert isinstance(custom, DenyUnknownAction)
    assert not custom.has_permission(drf_request(None), VIEW_STUB)


def test_access_mixin_reads_head_and_options_by_default() -> None:
    (head,) = _DemoViewSet("list", "HEAD").get_permissions()
    (options,) = _DemoViewSet("metadata", "OPTIONS").get_permissions()

    assert type(head).__name__ == "ReadRule(production.orders)"
    assert type(options).__name__ == "ReadRule(production.orders)"


WRITE = HasRole(DEPO)


class _MethodViewSet(AccessMixin):
    """Bugünkü kararları birebir çeviren bir görünüm: GET ile POST ayrı; HEAD ve OPTIONS okuma
    sayılmaz, yazma rolüyle denetlenir."""

    read_access = ReadRule(ORDERS)
    read_methods = frozenset({"GET"})
    other_safe_access = WRITE
    action_access = {
        "picks:post": HasAccess(PREP, CHANGE),
        "picks": ReadRule(PREP),
        "approve": HasAccess(ORDERS, APPROVE) | HasAccess(PREP, CHANGE),
        "put": HasAccess(ORDERS, CHANGE),
    }

    def __init__(self, action: str | None, method: str) -> None:
        self.action = action
        self.action_map = {method.lower(): action}
        self.request = factory.generic(method, "/x/")


class _MethodView(AccessMixin):
    """Eylemi olmayan görünüm (APIView): anahtar metodun adıdır; işleyicisi olmayan metotta
    `unhandled_access` (verilmezse yalnız oturum) aranır, DRF 405 döner."""

    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options", "trace"]
    read_access = ReadRule(ORDERS)
    action_access = {"put": HasAccess(ORDERS, CHANGE)}

    def __init__(self, method: str) -> None:
        self.request = factory.generic(method, "/x/")

    def get(self) -> None: ...

    def put(self) -> None: ...

    def post(self) -> None: ...


def test_access_mixin_method_keys_read_methods_and_other_safe_access(
    make_user: Callable[..., User],
) -> None:
    def name(action: str | None, method: str) -> str:
        (permission,) = _MethodViewSet(action, method).get_permissions()
        return type(permission).__name__

    assert name("picks", "POST") == "HasAccess(production.prep, change)"
    assert name("picks", "GET") == "ReadRule(production.prep)"
    assert name("list", "GET") == "ReadRule(production.orders)"
    (head,) = _MethodViewSet("list", "HEAD").get_permissions()
    (options,) = _MethodViewSet("metadata", "OPTIONS").get_permissions()
    assert isinstance(head, WRITE)
    assert isinstance(options, WRITE)
    # Listede olmayan yazma eylemi, güvenli metotların izni verilmiş olsa da reddedilir.
    (close,) = _MethodViewSet("close", "POST").get_permissions()
    (delete,) = _MethodViewSet("destroy", "DELETE").get_permissions()
    assert isinstance(close, DenyUnknownAction)
    assert isinstance(delete, DenyUnknownAction)

    # Eylemi olmayan görünümde (APIView) anahtar metodun adıdır; HEAD, GET'i izler.
    (put,) = _MethodView("PUT").get_permissions()
    (head_view,) = _MethodView("HEAD").get_permissions()
    (post,) = _MethodView("POST").get_permissions()
    assert type(put).__name__ == "HasAccess(production.orders, change)"
    assert type(head_view).__name__ == "ReadRule(production.orders)"
    assert isinstance(post, DenyUnknownAction)

    (either,) = _MethodViewSet("approve", "POST").get_permissions()
    assert either.has_permission(drf_request(make_user(PLANLAMA)), VIEW_STUB)
    assert either.has_permission(drf_request(make_user(DEPO)), VIEW_STUB)
    assert not either.has_permission(drf_request(make_user()), VIEW_STUB)


def test_composed_rule_denial_keeps_the_project_message(make_user: Callable[..., User]) -> None:
    """DRF'nin `A | B` birleşiminin mesajı yoktur; reddedince 403 yanıtı öteki denetimlerle aynı
    mesajı ve iki yetkiyi de söyler (DRF'nin varsayılan metni değil)."""
    viewset = _MethodViewSet("approve", "POST")
    (either,) = viewset.get_permissions()
    assert either.message == DEFAULT_MESSAGE
    (single,) = _MethodViewSet("picks", "POST").get_permissions()
    assert single.message == DEFAULT_MESSAGE

    request = drf_request(make_user())
    assert not either.has_permission(request, VIEW_STUB)
    with pytest.raises(exceptions.PermissionDenied) as caught:
        APIView().permission_denied(request, message=either.message)
    response = api_exception_handler(caught.value, {"request": request})

    assert response is not None
    assert response.data == {
        "code": "permission_denied",
        "detail": DEFAULT_MESSAGE,
        "required": [
            {"key": "production.orders", "level": APPROVE},
            {"key": "production.prep", "level": CHANGE},
        ],
    }


class _TraceViewSet(AccessMixin):
    """Eylemi `trace` adını taşıyan görünüm (lotun soy ağacı gibi): DRF HTTP TRACE isteğini de bu
    işleyiciye gönderir."""

    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options", "trace"]
    read_access = ReadRule(ORDERS)
    unhandled_access = HasAccess(ORDERS, CHANGE)

    def __init__(self, method: str) -> None:
        self.action = None
        self.action_map = {"get": "trace"}
        self.request = factory.generic(method, "/x/")

    def trace(self) -> None: ...


def test_access_mixin_unhandled_methods_keep_the_write_rule(
    make_user: Callable[..., User],
) -> None:
    """Görünümün karşılamadığı metotta `unhandled_access` denetlenir, sonra DRF 405 döner;
    verilmezse yalnız oturum aranır (oturumsuza 401)."""
    viewset = _TraceViewSet("PATCH")
    (patch,) = viewset.get_permissions()
    assert type(patch).__name__ == "HasAccess(production.orders, change)"

    (plain,) = _MethodView("PATCH").get_permissions()
    assert plain.has_permission(drf_request(make_user()), VIEW_STUB)
    assert not plain.has_permission(drf_request(None), VIEW_STUB)


class _ActionRouteViewSet(AccessMixin):
    """Yalnız POST'u olan eylem yolu (ör. `approve`) ve bugün her GET'i okuma sayan görünüm
    (üretim, dolum): karşılanmayan GET okuma kuralıyla, diğer metotlar yazma kuralıyla."""

    read_access = ReadRule(ORDERS)
    unhandled_access = HasAccess(ORDERS, CHANGE)
    unhandled_read_methods = frozenset({"GET"})

    def __init__(self, method: str) -> None:
        self.action_map = {"post": "approve"}
        self.action = self.action_map.get(method.lower())
        self.request = factory.generic(method, "/x/")


def test_access_mixin_unhandled_reads_follow_the_read_rule() -> None:
    def name(method: str) -> str:
        (permission,) = _ActionRouteViewSet(method).get_permissions()
        return type(permission).__name__

    assert name("GET") == "ReadRule(production.orders)"
    # HEAD, GET'i karşılamayan yolda karşılanmaz; bugünkü gibi yazma kuralıyla denetlenir.
    assert name("HEAD") == "HasAccess(production.orders, change)"
    assert name("DELETE") == "HasAccess(production.orders, change)"
    # Karşılanan metot `action_access`'te olmalıdır: listede olmayan eylem reddedilir.
    assert name("POST") == "DenyUnknownAction"


def test_access_mixin_checks_methods_drf_dispatches_by_name() -> None:
    """HTTP TRACE, aynı adlı eylemi çalıştırır: işleyicidir ve denetlenir (açık kalmaz)."""
    (trace,) = _TraceViewSet("TRACE").get_permissions()

    assert isinstance(trace, DenyUnknownAction)


def test_access_mixin_metadata_checks_follow_options(make_user: Callable[..., User]) -> None:
    """OPTIONS yanıtının yazma alanları için DRF izni POST ve PUT kopyasıyla dener (eylem
    `metadata`); karar OPTIONS'ınkiyle aynıdır."""
    viewset = _MethodViewSet("metadata", "OPTIONS")
    viewset.request = factory.generic("POST", "/x/")

    (permission,) = viewset.get_permissions()
    assert isinstance(permission, WRITE)
    (demo,) = _DemoViewSet("metadata", "POST").get_permissions()
    assert type(demo).__name__ == "ReadRule(production.orders)"


def test_require_access(make_user: Callable[..., User]) -> None:
    require_access(make_user(PLANLAMA), ORDERS, APPROVE)

    with pytest.raises(MissingAccess) as caught:
        require_access(make_user(DEPO), ORDERS, APPROVE, "Üretim emrini onaylama yetkiniz yok.")

    assert isinstance(caught.value, PermissionDenied)
    assert str(caught.value) == "Üretim emrini onaylama yetkiniz yok."
    assert caught.value.required == (("production.orders", APPROVE),)


def test_403_response_lists_required_access_from_service() -> None:
    error = MissingAccess("Üretim emrini onaylama yetkiniz yok.", (("production.orders", APPROVE),))

    response = api_exception_handler(error, {"request": None})

    assert response is not None
    assert response.status_code == 403
    assert response.data == {
        "code": "permission_denied",
        "detail": "Üretim emrini onaylama yetkiniz yok.",
        "required": [{"key": "production.orders", "level": APPROVE}],
    }


def test_403_response_lists_required_access_from_permission(
    make_user: Callable[..., User],
) -> None:
    request = drf_request(make_user(DEPO))
    HasAccess(ORDERS, CHANGE)().has_permission(request, VIEW_STUB)

    response = api_exception_handler(exceptions.PermissionDenied(), {"request": request})

    assert response is not None
    assert response.data["required"] == [{"key": "production.orders", "level": CHANGE}]


def test_passing_alternative_clears_noted_access(make_user: Callable[..., User]) -> None:
    request = drf_request(make_user(DEPO))

    assert (HasAccess(ORDERS, APPROVE) | HasAccess(PREP, CHANGE))().has_permission(
        request, VIEW_STUB
    )
    service_error = PermissionDenied("Rol yetkisi yok.")
    response = api_exception_handler(service_error, {"request": request})

    assert noted(request) == []
    assert response is not None and "required" not in response.data


def test_service_role_denial_ignores_noted_access(make_user: Callable[..., User]) -> None:
    request = drf_request(make_user(DEPO))
    HasAccess(ORDERS, APPROVE)().has_permission(request, VIEW_STUB)

    response = api_exception_handler(PermissionDenied("Rol yetkisi yok."), {"request": request})

    assert response is not None and "required" not in response.data


def test_403_without_access_check_has_no_required_and_csrf_is_untouched() -> None:
    plain = api_exception_handler(exceptions.PermissionDenied(), {"request": None})
    csrf = api_exception_handler(CsrfFailed(), {"request": None})
    role = api_exception_handler(PermissionDenied("Rol yetkisi yok."), {"request": None})

    assert plain is not None and "required" not in plain.data
    assert csrf is not None and csrf.data["code"] == "csrf_failed"
    assert "required" not in csrf.data
    assert role is not None and role.data == {
        "code": "permission_denied",
        "detail": "Rol yetkisi yok.",
    }


def test_has_role_is_unchanged(make_user: Callable[..., User]) -> None:
    permission = HasRole(DEPO)()

    assert permission.has_permission(drf_request(make_user(DEPO)), VIEW_STUB)
    assert not permission.has_permission(drf_request(make_user(PLANLAMA)), VIEW_STUB)
    assert VIEW == "view"
