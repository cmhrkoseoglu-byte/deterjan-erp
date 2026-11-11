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
from apps.core.models import User
from apps.core.permissions import (
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
    assert noted(denied) == [("sales.orders", READ)]
    with pytest.raises(ValueError, match="En az bir bölüm"):
        ReadRule()


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
        self.request = factory.generic(method, "/x/")


def test_access_mixin_maps_actions_and_denies_unknown_writes() -> None:
    (approve,) = _DemoViewSet("approve", "POST").get_permissions()
    (listing,) = _DemoViewSet("list", "GET").get_permissions()
    (custom,) = _DemoViewSet("close", "POST").get_permissions()

    assert type(approve).__name__ == "HasAccess(production.orders, approve)"
    assert type(listing).__name__ == "ReadRule(production.orders)"
    assert isinstance(custom, DenyUnknownAction)
    assert not custom.has_permission(drf_request(None), VIEW_STUB)


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
