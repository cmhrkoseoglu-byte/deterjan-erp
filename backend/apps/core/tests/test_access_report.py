""" "Kim neyi görür" raporu (docs/plan/kisi-yetkileri.md §5.10, §5.11, §6.2; critic §4.7):
`access/report/`, `access/report/holders/` ve Excel çıktısı `access/report/export/`."""

import io
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core import access
from apps.core.models import AccessOverride, User
from apps.core.roles import ADMIN, ALL_ROLES, DEPO, LABORATUVAR, PLANLAMA, URETIM

pytestmark = pytest.mark.django_db

REPORT = "/api/v1/access/report/"
HOLDERS = "/api/v1/access/report/holders/"
EXPORT = "/api/v1/access/report/export/"
FORBIDDEN = "Yetkileri yalnızca sistem yöneticisi değiştirir."
MakeUser = Callable[..., User]


def override(
    user: User, key: str, level: str, effect: str = "revoke", note: str = "deneme"
) -> None:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note=note)


@pytest.fixture
def admin(make_user: MakeUser) -> User:
    return make_user(ADMIN, username="yonetici", full_name="Zeynep Yönetici")


@pytest.fixture
def admin_api(admin: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(admin)
    return client


def users_by_name(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["username"]: row for row in body["users"]}


# --- rapor ----------------------------------------------------------------------------------


def test_report_lists_active_users_with_letters_and_personal_rows(
    admin_api: APIClient, make_user: MakeUser
) -> None:
    depo = make_user(DEPO, username="ali.depo")
    make_user(DEPO, username="pasif.depo", is_active=False)
    override(depo, "production.prep", "change")
    override(depo, "production.prep", "view", effect="grant")

    response = admin_api.get(REPORT)

    assert response.status_code == 200
    body = response.json()
    assert body["catalog_hash"] == access.catalog_hash()
    rows = users_by_name(body)
    assert set(rows) == {"yonetici", "ali.depo"}
    row = rows["ali.depo"]
    assert row["roles"] == [DEPO]
    assert row["is_admin"] is False
    assert row["access"]["production.prep"] == "rv"
    assert sorted(row["personal"], key=lambda item: item["level"]) == [
        {"key": "production.prep", "level": "change", "effect": "revoke", "ineffective": False},
        {"key": "production.prep", "level": "view", "effect": "grant", "ineffective": True},
    ]
    assert row["risky_pairs"] == []
    assert rows["yonetici"]["is_admin"] is True
    assert rows["yonetici"]["access"] == {}


def test_report_for_one_user(admin_api: APIClient, make_user: MakeUser) -> None:
    depo = make_user(DEPO)

    body = admin_api.get(REPORT, {"user": depo.pk}).json()

    assert [row["id"] for row in body["users"]] == [depo.pk]


def test_report_flags_risky_pair_from_different_sources(
    admin_api: APIClient, make_user: MakeUser
) -> None:
    operator = make_user(URETIM, username="usta")
    override(operator, "quality.samples", "approve", effect="grant")
    make_user(LABORATUVAR, username="lab")

    rows = users_by_name(admin_api.get(REPORT).json())

    [flag] = rows["usta"]["risky_pairs"]
    assert flag["a"] == {"key": "production.batches", "level": "change"}
    assert flag["b"] == {"key": "quality.samples", "level": "approve"}
    assert flag["sources"] == "role+granted"
    assert flag["text"].startswith("Görev ayrılığı:")
    # Rol paketinin kendisi riskli çift içermez.
    assert rows["lab"]["risky_pairs"] == []


def test_report_query_count_does_not_grow_with_users(
    admin_api: APIClient, make_user: MakeUser
) -> None:
    first = make_user(DEPO)
    override(first, "production.prep", "change")
    assert admin_api.get(REPORT).status_code == 200  # isteği yapanın rolleri önbelleğe alınır
    with CaptureQueriesContext(connection) as small:
        assert admin_api.get(REPORT).status_code == 200
    for role in (DEPO, PLANLAMA, URETIM, LABORATUVAR):
        user = make_user(role)
        override(user, "production.prep", "view", effect="grant")
    with CaptureQueriesContext(connection) as large:
        assert admin_api.get(REPORT).status_code == 200

    assert len(large.captured_queries) == len(small.captured_queries)


# --- kimde var ------------------------------------------------------------------------------


def test_holders_lists_sources_in_order(admin_api: APIClient, make_user: MakeUser) -> None:
    make_user(DEPO, username="b.depo", full_name="Bora Depo")
    make_user(DEPO, username="a.depo", full_name="Ayşe Depo")
    revoked = make_user(DEPO, username="c.depo", full_name="Cem Depo")
    override(revoked, "production.prep", "change")
    granted = make_user(URETIM, username="usta", full_name="Usta Üretim")
    override(granted, "production.prep", "change", effect="grant")
    make_user(PLANLAMA, username="plan")

    response = admin_api.get(HOLDERS, {"key": "production.prep", "level": "change"})

    assert response.status_code == 200
    body = response.json()
    assert (body["key"], body["level"]) == ("production.prep", "change")
    assert [(row["user"]["username"], row["source"], row["roles"]) for row in body["holders"]] == [
        ("a.depo", "role", [DEPO]),
        ("b.depo", "role", [DEPO]),
        ("usta", "granted", []),
        ("yonetici", "admin", []),
        ("c.depo", "revoked", [DEPO]),
    ]
    assert body["holders"][0]["user"]["roles"] == [DEPO]
    assert all(row["segregation"] == [] for row in body["holders"])


def test_holders_everyone_implied_and_segregation(
    admin_api: APIClient, make_user: MakeUser
) -> None:
    make_user(username="rolsuz")
    viewer = make_user(PLANLAMA, username="izleyen")
    override(viewer, "quality.samples", "approve", effect="grant")
    operator = make_user(URETIM, username="usta")
    override(operator, "quality.samples", "approve", effect="grant")

    lots = admin_api.get(HOLDERS, {"key": "inventory.lots", "level": "view"}).json()
    samples = admin_api.get(HOLDERS, {"key": "quality.samples", "level": "view"}).json()
    approve = admin_api.get(HOLDERS, {"key": "quality.samples", "level": "approve"}).json()

    assert {row["source"] for row in lots["holders"]} == {"everyone", "admin"}
    assert {row["user"]["username"] for row in lots["holders"]} >= {"rolsuz", "izleyen", "usta"}
    implied = {row["user"]["username"]: row["source"] for row in samples["holders"]}
    assert implied["usta"] == "implied"
    flags = {row["user"]["username"]: row["segregation"] for row in approve["holders"]}
    assert flags["izleyen"] == []
    assert len(flags["usta"]) == 1 and "Görev ayrılığı" in flags["usta"][0]


def test_holders_leave_out_a_kvkk_grant_without_management_role(
    admin_api: APIClient, make_user: MakeUser
) -> None:
    depo = make_user(DEPO, username="depo")
    override(depo, "personnel.cards", "view", effect="grant")

    body = admin_api.get(HOLDERS, {"key": "personnel.cards", "level": "view"}).json()

    assert "depo" not in {row["user"]["username"] for row in body["holders"]}


@pytest.mark.parametrize(
    "query",
    [
        {"key": "nope.section", "level": "view"},
        {"key": "production.prep", "level": "approve"},
        {"key": "production.prep", "level": "read"},
    ],
)
def test_holders_unknown_cell_is_400(admin_api: APIClient, query: dict[str, str]) -> None:
    response = admin_api.get(HOLDERS, query)

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_access"


# --- Excel ----------------------------------------------------------------------------------


def test_export_has_four_sheets_and_no_cache(admin_api: APIClient, make_user: MakeUser) -> None:
    depo = make_user(DEPO, username="ali.depo")
    override(depo, "production.prep", "change", note="Hazırlık kapatıldı")
    operator = make_user(URETIM, username="usta")
    override(operator, "quality.samples", "approve", effect="grant")

    response = admin_api.get(EXPORT)

    assert response.status_code == 200
    assert response["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response["Cache-Control"] == "no-store"
    assert "yetki-raporu-" in response["Content-Disposition"]
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == [
        "Rol paketleri",
        "Kişilerin yetkileri",
        "Kişiye özel ayarlar",
        "Görev ayrılığı",
    ]
    packages = book["Rol paketleri"]
    header = [cell.value for cell in packages[1]]
    assert header[:4] == ["Modül", "Bölüm", "Herkes", "Rolü olan herkes"]
    first = access.sections()[0]
    assert packages.cell(row=2, column=2).value == first.label
    people = [[cell.value for cell in row] for row in book["Kişilerin yetkileri"].iter_rows()]
    assert any(row[0] == "yonetici" and row[6] == "Sistem yöneticisi" for row in people)
    assert any(row[0] == "ali.depo" and row[6] == "Rolden (Depo)" for row in people)
    assert not any(
        row[0] == "ali.depo" and row[4] == "Malzeme hazırlama" and row[5] == "Değiştirir"
        for row in people
    )
    personal = [[cell.value for cell in row] for row in book["Kişiye özel ayarlar"].iter_rows()]
    assert any(row[0] == "ali.depo" and row[4] == "Hazırlık kapatıldı" for row in personal)
    pairs = [[cell.value for cell in row] for row in book["Görev ayrılığı"].iter_rows()]
    assert pairs[1][0] == "usta" and pairs[1][3] == "Rol + Kişiye özel"


def test_export_writes_formula_like_text_as_text(admin_api: APIClient, make_user: MakeUser) -> None:
    depo = make_user(DEPO, username="ali.depo", full_name="@x")
    override(depo, "production.prep", "change", note="=1+1")
    plain = make_user(DEPO, username="veli.depo", full_name="Veli Depo")
    override(plain, "production.prep", "change", note="Hazırlık kapatıldı")

    book = load_workbook(io.BytesIO(admin_api.get(EXPORT).content))

    people = {row[0].value: row for row in book["Kişilerin yetkileri"].iter_rows(min_row=2)}
    name = people["ali.depo"][1]
    assert (name.value, name.data_type, name.quotePrefix) == ("@x", "s", True)
    personal = {row[0].value: row for row in book["Kişiye özel ayarlar"].iter_rows(min_row=2)}
    note = personal["ali.depo"][4]
    assert (note.value, note.data_type, note.quotePrefix) == ("=1+1", "s", True)
    # Sıradan metin bugünkü gibi yazılır (tırnak öneki yok).
    other = personal["veli.depo"][4]
    assert (other.value, other.data_type, other.quotePrefix) == ("Hazırlık kapatıldı", "s", False)
    assert people["veli.depo"][1].quotePrefix is False


# --- yetki ----------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [*(role for role in ALL_ROLES if role != ADMIN), None])
def test_report_endpoints_are_admin_only(
    client_for: Callable[..., APIClient], role: str | None
) -> None:
    client = client_for(*([role] if role else []))

    for path, query in [
        (REPORT, {}),
        (HOLDERS, {"key": "production.prep", "level": "view"}),
        (EXPORT, {}),
    ]:
        response = client.get(path, query)
        assert response.status_code == 403, path
        assert response.json()["detail"] == FORBIDDEN


def test_report_endpoints_need_sign_in(api_client: APIClient) -> None:
    for path in (REPORT, HOLDERS, EXPORT):
        assert api_client.get(path).status_code == 401
