"""Yetki API'si: `me` yanıtındaki `access` ve `is_admin`, yetki kataloğu uç noktası ve Yetkilerim
(`auth/me/access/`)."""

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.core import access
from apps.core.models import AccessOverride, User
from apps.core.roles import DEPO

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"
CATALOG = "/api/v1/access/catalog/"


def test_me_lists_access_letters(client_for: Callable[..., APIClient]) -> None:
    body = client_for(DEPO).get(ME).json()

    assert body["is_admin"] is False
    assert body["access"]["production.prep"] == "rvc"
    assert body["access"]["production.orders"] == "rv"
    assert body["access"]["inventory.stock"] == "rvc"
    assert "sales.orders" in body["access"]
    assert "personnel.cards" not in body["access"]


def test_me_for_admin_and_user_without_role(client_for: Callable[..., APIClient]) -> None:
    admin = client_for("admin").get(ME).json()
    nobody = client_for().get(ME).json()

    assert admin["is_admin"] is True
    assert admin["access"]["personnel.payroll"] == "rvca"
    assert admin["access"]["inventory.manual_release"] == "a"
    assert len(admin["access"]) == len(access.sections())
    assert nobody["is_admin"] is False
    assert nobody["access"]["production.orders"] == "r"
    assert nobody["access"]["inventory.lots"] == "rv"
    assert "maintenance.breakdowns" not in nobody["access"]


def test_catalog_requires_sign_in(api_client: APIClient) -> None:
    assert api_client.get(CATALOG).status_code == 401


def test_catalog_for_any_signed_in_user(client_for: Callable[..., APIClient]) -> None:
    response = client_for().get(CATALOG)

    assert response.status_code == 200
    body = response.json()
    assert body["hash"] == access.catalog_hash()
    assert body["levels"]["approve"] == "Onaylar"
    assert body["holders"]["*"] == "Herkes"
    assert body["holders"]["depo"] == "Depo"
    production = next(item for item in body["modules"] if item["key"] == "production")
    assert [item["key"] for item in production["sections"]] == [
        "production.orders",
        "production.prep",
        "production.batches",
        "production.open_records",
    ]
    assert body["packages"]["depo"]["production.prep"] == "vc"


# --- Yetkilerim (plan §6.4; critic §4.5) -------------------------------------------------------

MY_ACCESS = "/api/v1/auth/me/access/"


def _find(body: dict, key: str, level: str) -> dict | None:
    return next(
        (item for item in body["entries"] if (item["key"], item["level"]) == (key, level)), None
    )


def _entry(body: dict, key: str, level: str) -> dict:
    found = _find(body, key, level)
    assert found is not None, (key, level)
    return found


def _keys(value: object) -> set[str]:
    """JSON'daki bütün sözlük anahtarları (iç içe)."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_my_access_names_the_source_of_each_right(make_user: Callable[..., User]) -> None:
    user = make_user(DEPO)
    client = APIClient()
    client.force_authenticate(user)

    body = client.get(MY_ACCESS).json()

    assert body["roles"] == [DEPO]
    assert body["is_admin"] is False
    assert _entry(body, "inventory.stock", "view") == {
        "key": "inventory.stock",
        "level": "view",
        "source": "everyone",
        "roles": [],
        "implied": False,
    }
    assert _entry(body, "inventory.stock", "change")["source"] == "role"
    assert _entry(body, "production.prep", "view")["roles"] == [DEPO]
    assert _entry(body, "maintenance.breakdowns", "change")["source"] == "any_role"
    assert _find(body, "personnel.cards", "view") is None
    assert all(item["level"] != "read" for item in body["entries"])
    assert body["revoked"] == []


def test_my_access_shows_granted_and_revoked_without_reason(
    make_user: Callable[..., User],
) -> None:
    user = make_user(DEPO)
    for key, level, effect in [
        ("production.orders", "change", "grant"),
        ("quality.samples", "change", "grant"),
        ("production.prep", "change", "revoke"),
        ("quality.open_records", "read", "revoke"),
    ]:
        AccessOverride.objects.create(
            user=user, key=key, level=level, effect=effect, note="Gizli gerekçe"
        )
    client = APIClient()
    client.force_authenticate(user)

    response = client.get(MY_ACCESS)

    body = response.json()
    assert _entry(body, "production.orders", "change")["source"] == "granted"
    assert _entry(body, "production.orders", "view")["source"] == "role"
    assert _entry(body, "quality.samples", "view") == {
        "key": "quality.samples",
        "level": "view",
        "source": "granted",
        "roles": [],
        "implied": True,
    }
    assert _find(body, "production.prep", "change") is None
    assert body["revoked"] == [
        {"key": "production.prep", "level": "change", "roles": [DEPO]},
        {"key": "quality.open_records", "level": "read", "roles": []},
    ]
    assert "Gizli gerekçe" not in response.content.decode()
    assert not _keys(body) & {"note", "created_by", "created_by_name", "created_at", "ended_at"}


def test_my_access_lists_levels_lost_with_view(make_user: Callable[..., User]) -> None:
    user = make_user(DEPO)
    AccessOverride.objects.create(
        user=user, key="production.prep", level="view", effect="revoke", note="Görmesin"
    )
    client = APIClient()
    client.force_authenticate(user)

    body = client.get(MY_ACCESS).json()

    assert _find(body, "production.prep", "change") is None
    assert body["revoked"] == [
        {"key": "production.prep", "level": "view", "roles": [DEPO]},
        {"key": "production.prep", "level": "change", "roles": [DEPO]},
    ]


def test_my_access_for_admin_and_roleless(client_for: Callable[..., APIClient]) -> None:
    admin = client_for("admin").get(MY_ACCESS).json()
    nobody = client_for().get(MY_ACCESS).json()

    assert admin == {"roles": ["admin"], "is_admin": True, "entries": [], "revoked": []}
    assert nobody["roles"] == []
    assert _entry(nobody, "inventory.lots", "view")["source"] == "everyone"
    assert _find(nobody, "maintenance.breakdowns", "change") is None


def test_my_access_requires_sign_in(api_client: APIClient, make_user: Callable[..., User]) -> None:
    assert api_client.get(MY_ACCESS).status_code == 401
    inactive = APIClient()
    inactive.force_login(make_user(DEPO, is_active=False))
    assert inactive.get(MY_ACCESS).status_code == 401
