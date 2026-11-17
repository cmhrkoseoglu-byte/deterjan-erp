"""Açık işaretlerin API'deki davranışı: `AdminOnly` (yalnız sistem yöneticisi), `SignedIn` (giriş
yapan herkes) ve `Public` (giriş gerektirmez). Oturumsuza 401, yetkisize 403 döner."""

import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.core.permissions import AdminOnly, Public, SignedIn
from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA

pytestmark = pytest.mark.django_db


class AdminView(APIView):
    permission_classes = [AdminOnly]

    def get(self, request):
        return Response({"ok": True})


class SignedInView(APIView):
    permission_classes = [SignedIn("deneme")]

    def get(self, request):
        return Response({"ok": True})


class PublicView(APIView):
    permission_classes = [Public("deneme")]

    def get(self, request):
        return Response({"ok": True})


def call(view, user=None, method="get"):
    request = getattr(APIRequestFactory(), method)("/x/")
    if user is not None:
        force_authenticate(request, user)
    return view.as_view()(request)


@pytest.mark.parametrize("role", [DEPO, PLANLAMA, LABORATUVAR])
def test_admin_only_refuses_other_roles(make_user, role):
    response = call(AdminView, make_user(role))

    assert response.status_code == 403
    assert response.data == {"code": "permission_denied", "detail": "Bu işlem için yetkiniz yok."}


def test_admin_only_anonymous_gets_401():
    response = call(AdminView)

    assert response.status_code == 401
    assert response.data["code"] == "not_authenticated"


def test_admin_role_and_superuser_pass(make_user):
    assert call(AdminView, make_user("admin")).status_code == 200
    assert call(AdminView, make_user(is_superuser=True)).status_code == 200


def test_admin_only_rejects_inactive_admin(make_user):
    assert call(AdminView, make_user("admin", is_active=False)).status_code == 403


def test_admin_only_checks_permission_before_405(make_user):
    """Görünümün karşılamadığı metotta önce yetki denetlenir: yetkisize 403, admine 405."""
    assert call(AdminView, make_user(DEPO), "post").status_code == 403
    assert call(AdminView, make_user("admin"), "post").status_code == 405


def test_signed_in_allows_every_user_and_refuses_anonymous(make_user):
    assert call(SignedInView, make_user()).status_code == 200
    assert call(SignedInView, make_user(DEPO)).status_code == 200
    assert call(SignedInView).status_code == 401


def test_public_allows_anonymous(make_user):
    assert call(PublicView).status_code == 200
    assert call(PublicView, make_user()).status_code == 200
    assert call(PublicView, None, "post").status_code == 405
