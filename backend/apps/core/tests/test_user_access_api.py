"""Yetkiler ekranının API'si (docs/plan/kisi-yetkileri.md §5.10, §6.1; critic §4.2-4.3):
`GET|PUT /api/v1/users/{pk}/access/` ve `GET /api/v1/users/{pk}/access/history/`."""

import re
from collections.abc import Callable
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core import access, event_names, events, services
from apps.core.models import AccessOverride, AuditLog, User
from apps.core.roles import ADMIN, ALL_ROLES, DEPO, PLANLAMA, URETIM, YONETIM

pytestmark = pytest.mark.django_db

USERS = "/api/v1/users/"
FORBIDDEN = "Yetkileri yalnızca sistem yöneticisi değiştirir."
PREP_CHANGE = {"key": "production.prep", "level": "change", "effect": "revoke"}
MakeUser = Callable[..., User]


def url(user: User, suffix: str = "") -> str:
    return f"{USERS}{user.pk}/access/{suffix}"


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def admin(make_user: MakeUser) -> User:
    return make_user(ADMIN, username="yonetici", full_name="Sistem Yöneticisi")


@pytest.fixture
def admin_api(admin: User) -> APIClient:
    return api(admin)


@pytest.fixture
def depo(make_user: MakeUser) -> User:
    return make_user(DEPO, username="depo1", full_name="Ali Depo")


@pytest.fixture
def published() -> list[events.Event]:
    received: list[events.Event] = []
    events.subscribe("*")(received.append)
    return received


def matrix(client: APIClient, user: User) -> dict[str, Any]:
    response = client.get(url(user))
    assert response.status_code == 200, response.json()
    return response.json()


def put(
    client: APIClient,
    user: User,
    overrides: list[dict[str, str]],
    *,
    note: str = "Vardiya düzeni değişti",
    **extra: Any,
) -> Any:
    body = {"version": matrix(client, user)["version"], "overrides": overrides, "note": note}
    return client.put(url(user), {**body, **extra}, format="json")


# --- GET ------------------------------------------------------------------------------------


def test_matrix_shows_role_default_for_depo(admin_api: APIClient, depo: User) -> None:
    body = matrix(admin_api, depo)

    assert body["user"] == {
        "id": depo.pk,
        "username": "depo1",
        "full_name": "Ali Depo",
        "is_active": True,
        "is_superuser": False,
        "otp_enabled": False,
    }
    assert body["roles"] == [DEPO]
    assert body["is_admin"] is False
    assert body["is_self"] is False
    assert re.fullmatch(r"[0-9a-f]{32}", body["version"])
    assert body["catalog_hash"] == access.catalog_hash()
    assert body["default"] == body["effective"]
    assert body["default"]["production.prep"] == "rvc"
    assert body["overrides"] == []
    assert body["open_records_effects"] == {
        key: list(texts) for key, texts in access.all_open_records_effects().items()
    }
    assert "inventory" in body["open_records_effects"]


def test_matrix_marks_admin_target_and_self(admin_api: APIClient, admin: User) -> None:
    body = matrix(admin_api, admin)

    assert body["is_admin"] is True
    assert body["is_self"] is True
    assert body["overrides"] == []
    assert body["default"] == body["effective"]
    assert len(body["effective"]) == len(access.sections())


def test_matrix_lists_rows_with_note_known_and_ineffective_flags(
    admin_api: APIClient, admin: User, depo: User
) -> None:
    # Etkisiz satır (rol zaten veriyor) ve katalogdan kaldırılmış bölümün satırı.
    AccessOverride.objects.create(
        user=depo,
        key="production.prep",
        level="view",
        effect="grant",
        note="eski",
        created_by=admin,
    )
    AccessOverride.objects.create(
        user=depo, key="old.section", level="view", effect="grant", note="x"
    )

    rows = {row["key"]: row for row in matrix(admin_api, depo)["overrides"]}

    assert rows["production.prep"]["ineffective"] is True
    assert rows["production.prep"]["known"] is True
    assert rows["production.prep"]["note"] == "eski"
    assert rows["production.prep"]["created_by_name"] == "Sistem Yöneticisi"
    assert rows["old.section"]["known"] is False
    assert rows["old.section"]["ineffective"] is False
    assert rows["old.section"]["created_by_name"] is None


def test_inactive_user_matrix_is_computed_as_if_active(
    admin_api: APIClient, make_user: MakeUser
) -> None:
    user = make_user(DEPO, is_active=False)

    body = matrix(admin_api, user)

    assert body["user"]["is_active"] is False
    assert body["effective"]["production.prep"] == "rvc"


# --- PUT ------------------------------------------------------------------------------------


def test_put_revoke_saves_and_returns_fresh_matrix(
    admin_api: APIClient, depo: User, django_capture_on_commit_callbacks: Any, published: list
) -> None:
    before = matrix(admin_api, depo)["version"]

    with django_capture_on_commit_callbacks(execute=True):
        response = put(admin_api, depo, [PREP_CHANGE], note="Hazırlık geçici olarak kapandı")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["dry_run"] is False
    assert body["changed"] is True
    assert body["saved"] is True
    assert body["roles"] == {"before": [DEPO], "after": [DEPO]}
    assert body["overrides"]["created"] == [PREP_CHANGE]
    assert body["overrides"]["ended"] == []
    assert body["access"]["before"]["production.prep"] == "rvc"
    assert body["access"]["after"]["production.prep"] == "rv"
    assert body["access"]["removed"] == [{"key": "production.prep", "level": "change"}]
    assert body["access"]["granted"] == []
    fresh = body["matrix"]
    assert fresh["version"] != before
    assert fresh["effective"]["production.prep"] == "rv"
    [row] = fresh["overrides"]
    assert {key: row[key] for key in ("key", "level", "effect")} == PREP_CHANGE
    assert row["note"] == "Hazırlık geçici olarak kapandı"
    row_obj = AccessOverride.objects.get(pk=row["id"])
    assert row_obj.is_active and row_obj.created_by is not None
    # Açık oturum yenilenir ve kişiye bildirim olayı gider (her biri bir kez).
    names = [event.name for event in published]
    assert names.count(event_names.ACCESS_CHANGED) == 1
    assert names.count(event_names.ACCESS_UPDATED) == 1


def test_put_dry_run_writes_nothing_and_publishes_nothing(
    admin_api: APIClient, depo: User, django_capture_on_commit_callbacks: Any, published: list
) -> None:
    logs = AuditLog.objects.count()

    with django_capture_on_commit_callbacks(execute=True):
        response = put(
            admin_api, depo, [PREP_CHANGE], note="", dry_run=True, roles=[DEPO, PLANLAMA]
        )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["dry_run"] is True
    assert body["changed"] is True
    assert body["saved"] is False
    assert body["matrix"] is None
    assert body["roles"] == {"before": [DEPO], "after": [DEPO, PLANLAMA]}
    assert {"key": "production.prep", "level": "change"} in body["access"]["removed"]
    assert body["access"]["after"]["production.orders"] == "rvca"
    assert all(set(item) == {"code", "text"} for item in body["warnings"])
    assert not AccessOverride.objects.filter(user=depo).exists()
    assert AuditLog.objects.count() == logs
    depo.refresh_roles()
    assert depo.roles == [DEPO]
    assert published == []


def test_put_without_changes_saves_nothing(admin_api: APIClient, depo: User) -> None:
    response = put(admin_api, depo, [], note="")

    assert response.status_code == 200, response.json()
    body = response.json()
    assert (body["changed"], body["saved"], body["matrix"]) == (False, False, None)
    assert body["overrides"] == {"created": [], "ended": []}


def test_put_needs_a_note_for_a_real_save(admin_api: APIClient, depo: User) -> None:
    refused = put(admin_api, depo, [PREP_CHANGE], note=" abcd ")

    assert refused.status_code == 400
    assert refused.json() == {
        "code": "access_note_required",
        "detail": "Değişikliğin gerekçesini yazın.",
    }
    assert put(admin_api, depo, [PREP_CHANGE], note="abcde").status_code == 200


@pytest.mark.parametrize("dry_run", [False, True])
def test_put_with_a_stale_version_is_refused(
    admin_api: APIClient, depo: User, dry_run: bool
) -> None:
    version = matrix(admin_api, depo)["version"]
    services.set_user_access(
        User.objects.get(username="yonetici"),
        depo,
        version=version,
        overrides=[],
        roles=[DEPO, PLANLAMA],
        note="Başka sekmede değişti",
    )

    response = admin_api.put(
        url(depo),
        {
            "version": version,
            "overrides": [PREP_CHANGE],
            "note": "Geç kalan kayıt",
            "dry_run": dry_run,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "access_changed",
        "detail": "Yetkiler siz düzenlerken değişti; sayfayı yenileyin.",
    }
    assert not AccessOverride.objects.filter(user=depo).exists()


def grant(key: str, level: str) -> dict[str, str]:
    return {"key": key, "level": level, "effect": "grant"}


def revoke(key: str, level: str) -> dict[str, str]:
    return {"key": key, "level": level, "effect": "revoke"}


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ([grant("nope.section", "view")], "unknown_access"),
        ([grant("production.prep", "approve")], "unknown_access"),
        (
            [revoke("production.open_records", "read") | {"effect": "grant"}],
            "open_records_revoke_only",
        ),
        ([grant("inventory.manual_release", "approve")], "access_not_grantable"),
        ([revoke("inventory.stock", "view")], "access_locked"),
        ([grant("personnel.cards", "view")], "access_requires_role"),
        (
            [revoke("production.batches", "view"), grant("production.batches", "change")],
            "access_conflict",
        ),
        ([grant("costing.lot_costs", "view")], "access_requires"),
        ([PREP_CHANGE, revoke("production.prep", "change")], "access_duplicate"),
    ],
)
def test_put_business_rules_are_400_with_code(
    admin_api: APIClient, depo: User, overrides: list[dict[str, str]], code: str
) -> None:
    response = put(admin_api, depo, overrides)

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == code
    assert body["detail"]
    assert not AccessOverride.objects.filter(user=depo).exists()


def test_put_rejects_a_malformed_body(admin_api: APIClient, depo: User) -> None:
    version = matrix(admin_api, depo)["version"]

    bad_effect = admin_api.put(
        url(depo),
        {"version": version, "overrides": [{**PREP_CHANGE, "effect": "drop"}]},
        format="json",
    )
    missing = admin_api.put(url(depo), {"version": version}, format="json")
    bad_role = admin_api.put(
        url(depo), {"version": version, "overrides": [], "roles": ["patron"]}, format="json"
    )

    for response in (bad_effect, missing, bad_role):
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"


def test_admin_edits_own_roles_but_not_own_access(admin_api: APIClient, admin: User) -> None:
    own = put(admin_api, admin, [PREP_CHANGE])
    assert own.status_code == 400
    assert own.json()["code"] == "cannot_edit_own_access"

    removed = put(admin_api, admin, [], roles=[YONETIM])
    assert removed.status_code == 400
    assert removed.json() == {
        "code": "cannot_remove_own_admin",
        "detail": "Kendi sistem yöneticisi rolünüzü kaldıramazsınız.",
    }

    added = put(admin_api, admin, [], roles=[ADMIN, YONETIM], note="Yönetim rolü de verildi")
    assert added.status_code == 200, added.json()
    admin.refresh_roles()
    assert admin.roles == [ADMIN, YONETIM]


def test_admin_target_gets_no_personal_rows(admin_api: APIClient, make_user: MakeUser) -> None:
    other = make_user(ADMIN)

    response = put(admin_api, other, [PREP_CHANGE])

    assert response.status_code == 400
    assert response.json()["code"] == "admin_has_all_access"


def test_giving_admin_ends_rows_with_admin_reason(admin_api: APIClient, depo: User) -> None:
    assert put(admin_api, depo, [PREP_CHANGE]).status_code == 200

    response = put(
        admin_api, depo, [PREP_CHANGE], roles=[ADMIN, DEPO], note="Sistem yöneticisi oldu"
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert [(row["key"], row["reason"]) for row in body["overrides"]["ended"]] == [
        ("production.prep", "admin")
    ]
    assert body["matrix"]["is_admin"] is True
    assert body["matrix"]["overrides"] == []
    assert "admin_granted" in {item["code"] for item in body["warnings"]}


def test_omitted_row_returns_to_role_default(admin_api: APIClient, depo: User) -> None:
    assert put(admin_api, depo, [PREP_CHANGE]).status_code == 200

    response = put(admin_api, depo, [], note="Rol varsayılanına dönüldü")

    assert response.status_code == 200, response.json()
    [ended] = response.json()["overrides"]["ended"]
    assert ended["reason"] == "reset"
    assert response.json()["matrix"]["effective"]["production.prep"] == "rvc"
    row = AccessOverride.objects.get(pk=ended["id"])
    assert row.ended_at is not None and row.end_reason == "reset"


# --- PATCH users/{pk}/ artık rol almaz (§8 madde 13) ------------------------------------------


def test_patch_with_roles_points_to_the_access_page(admin_api: APIClient, depo: User) -> None:
    response = admin_api.patch(
        f"{USERS}{depo.pk}/", {"full_name": "Ali Veli", "roles": [PLANLAMA]}, format="json"
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "roles_on_access_page",
        "detail": "Roller Sistem › Kullanıcılar › Yetkiler ekranında, gerekçe yazılarak "
        "değiştirilir.",
    }
    depo.refresh_from_db()
    depo.refresh_roles()
    assert depo.roles == [DEPO]
    assert depo.full_name == "Ali Depo"


def test_patch_without_roles_returns_the_plain_user(admin_api: APIClient, depo: User) -> None:
    response = admin_api.patch(f"{USERS}{depo.pk}/", {"full_name": "Ali Veli"}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Ali Veli"
    assert "coverage_warnings" not in body
    assert body["personal_counts"] == {"granted": 0, "revoked": 0}


# --- geçmiş ----------------------------------------------------------------------------------


def test_history_lists_role_and_access_saves_newest_first(
    admin_api: APIClient, admin: User
) -> None:
    user, _password = services.create_user(
        admin, username="yeni.depo", full_name="Yeni Depo", roles=[DEPO]
    )
    assert put(admin_api, user, [PREP_CHANGE], note="Hazırlık kapatıldı").status_code == 200
    saved = put(
        admin_api,
        user,
        [grant("production.orders", "change")],
        roles=[DEPO, URETIM],
        note="Rol varsayılanına döndü, şarj verildi",
    )
    assert saved.status_code == 200, saved.json()

    response = admin_api.get(url(user, "history/"))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    latest, revoke_entry, created = body["results"]
    assert latest["note"] == "Rol varsayılanına döndü, şarj verildi"
    assert latest["actor_name"] == "Sistem Yöneticisi"
    assert latest["roles"] == {"before": [DEPO], "after": [DEPO, URETIM]}
    assert {line["kind"] for line in latest["lines"]} == {"granted", "ended"}
    ended = next(line for line in latest["lines"] if line["kind"] == "ended")
    assert ended == {
        "kind": "ended",
        "key": "production.prep",
        "level": "change",
        "effect": "revoke",
        "reason": "reset",
        "reason_label": "Rol varsayılanına döndü",
    }
    assert revoke_entry["roles"] is None
    assert revoke_entry["lines"] == [
        {"kind": "revoked", "key": "production.prep", "level": "change"}
    ]
    assert created["roles"] == {"before": [], "after": [DEPO]}
    assert created["note"] == "Kullanıcı açıldı"


def test_history_shows_automatic_end_reason(admin_api: APIClient, make_user: MakeUser) -> None:
    manager = make_user(YONETIM)
    assert put(admin_api, manager, [revoke("personnel.cards", "change")]).status_code == 200
    assert (
        put(admin_api, manager, [revoke("personnel.cards", "change")], roles=[ADMIN]).status_code
        == 200
    )

    lines = admin_api.get(url(manager, "history/")).json()["results"][0]["lines"]

    assert [(line["kind"], line["reason"], line["reason_label"]) for line in lines] == [
        ("ended", "admin", "Sistem yöneticisi oldu")
    ]


def test_history_is_paginated_and_skips_other_changes(
    admin_api: APIClient, depo: User, admin: User
) -> None:
    services.update_user(admin, depo, phone="0532 000 00 00")

    body = admin_api.get(url(depo, "history/")).json()

    assert set(body) >= {"count", "next", "previous", "results"}
    assert body["results"] == []


# --- yetki ----------------------------------------------------------------------------------


NON_ADMIN = [role for role in ALL_ROLES if role != ADMIN]


@pytest.mark.parametrize("role", [*NON_ADMIN, None])
def test_access_endpoints_are_admin_only(
    client_for: Callable[..., APIClient], depo: User, role: str | None
) -> None:
    client = client_for(*([role] if role else []))
    calls = [
        client.get(url(depo)),
        client.put(url(depo), {"version": "x", "overrides": []}, format="json"),
        client.get(url(depo, "history/")),
    ]

    for response in calls:
        assert response.status_code == 403
        assert response.json()["detail"] == FORBIDDEN
    assert not AccessOverride.objects.exists()


def test_access_endpoints_need_sign_in(api_client: APIClient, depo: User) -> None:
    assert api_client.get(url(depo)).status_code == 401
    assert api_client.put(url(depo), {}, format="json").status_code == 401
    assert api_client.get(url(depo, "history/")).status_code == 401


def test_service_also_refuses_a_non_admin(make_user: MakeUser, depo: User) -> None:
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.set_user_access(make_user(YONETIM), depo, version="x", overrides=[])
