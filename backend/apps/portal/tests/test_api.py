"""Portal hesapları API'si: yalnız admin; geçici şifre, liste, sıfırlama, açma/kapama;
çalışan kullanıcı listesinde portal hesabı görünmez."""

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.core.models import User
from apps.masterdata.models import Customer, Supplier
from apps.portal.models import PortalAccount

pytestmark = pytest.mark.django_db

URL = "/api/v1/portal/accounts/"
Client = Callable[..., APIClient]


@pytest.fixture
def admin_api(sysadmin: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(sysadmin)
    return client


def test_admin_creates_and_lists_accounts(
    admin_api: APIClient, customer: Customer, supplier: Supplier
) -> None:
    created = admin_api.post(
        URL,
        {
            "username": "ayse.m",
            "full_name": "Ayşe M",
            "email": "a@example.com",
            "customer": customer.pk,
        },
        format="json",
    )
    assert created.status_code == 201
    assert created["Cache-Control"] == "no-store"
    body = created.json()
    assert body["temporary_password"]
    assert body["account"]["kind"] == "customer"
    assert body["account"]["firm_code"] == customer.code
    assert body["account"]["password_change_required"] is True
    admin_api.post(
        URL,
        {"username": "can.t", "full_name": "Can T", "supplier": supplier.pk},
        format="json",
    )

    assert admin_api.get(URL).json()["count"] == 2
    suppliers = admin_api.get(URL, {"kind": "supplier"}).json()["results"]
    assert [row["username"] for row in suppliers] == ["can.t"]
    assert admin_api.get(URL, {"search": customer.code}).json()["count"] == 1


def test_create_errors(admin_api: APIClient, customer: Customer, supplier: Supplier) -> None:
    both = admin_api.post(
        URL,
        {
            "username": "x",
            "full_name": "X",
            "customer": customer.pk,
            "supplier": supplier.pk,
        },
        format="json",
    )
    assert both.status_code == 400 and both.json()["code"] == "portal_firm_required"


def test_reset_toggle_and_unlock(admin_api: APIClient, customer_account: PortalAccount) -> None:
    base = f"{URL}{customer_account.pk}/"
    reset = admin_api.post(base + "reset-password/")
    assert reset.status_code == 200 and reset.json()["temporary_password"]
    assert reset["Cache-Control"] == "no-store"
    assert admin_api.post(base + "deactivate/").json()["is_active"] is False
    assert admin_api.post(base + "activate/").json()["is_active"] is True
    unlock = admin_api.post(base + "unlock/")
    assert unlock.status_code == 400 and unlock.json()["code"] == "not_locked"


@pytest.mark.parametrize("role", ["yonetim", "sevkiyat", "satin_alma"])
def test_staff_without_admin_is_forbidden(
    client_for: Client, role: str, customer_account: PortalAccount
) -> None:
    client = client_for(role)
    assert client.get(URL).status_code == 403
    assert client.post(f"{URL}{customer_account.pk}/reset-password/").status_code == 403


def test_core_user_list_hides_portal_accounts(
    admin_api: APIClient, customer_account: PortalAccount
) -> None:
    usernames = [row["username"] for row in admin_api.get("/api/v1/users/").json()["results"]]
    assert customer_account.user.username not in usernames
    portal_user = customer_account.user.pk
    assert admin_api.get(f"/api/v1/users/{portal_user}/").status_code == 404
    assert admin_api.get(f"/api/v1/users/{portal_user}/access/").status_code == 404
