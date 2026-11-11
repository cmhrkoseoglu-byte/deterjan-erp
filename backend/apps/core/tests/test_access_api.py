"""Yetki API'si: `me` yanıtındaki `access` ve `is_admin`, yetki kataloğu uç noktası."""

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.core import access
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
