import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.core.permissions import HasRole
from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA

pytestmark = pytest.mark.django_db


class DepoView(APIView):
    permission_classes = [HasRole(DEPO, PLANLAMA)]

    def get(self, request):
        return Response({"ok": True})


def call(user=None):
    request = APIRequestFactory().get("/x/")
    if user is not None:
        force_authenticate(request, user)
    return DepoView.as_view()(request)


@pytest.mark.parametrize("role", [DEPO, PLANLAMA])
def test_allowed_roles_pass(make_user, role):
    assert call(make_user(role)).status_code == 200


def test_other_role_gets_403(make_user):
    response = call(make_user(LABORATUVAR))

    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


def test_anonymous_gets_401():
    response = call()

    assert response.status_code == 401
    assert response.data["code"] == "not_authenticated"


def test_admin_role_and_superuser_pass(make_user):
    assert call(make_user("admin")).status_code == 200
    assert call(make_user(is_superuser=True)).status_code == 200


def test_inactive_user_rejected(make_user):
    assert call(make_user(DEPO, is_active=False)).status_code == 403


def test_unknown_role_rejected_at_definition():
    with pytest.raises(ValueError):
        HasRole("muhasebe")
    with pytest.raises(ValueError):
        HasRole()
