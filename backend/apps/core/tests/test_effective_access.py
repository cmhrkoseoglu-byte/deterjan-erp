"""Geçerli yetki hesabı (docs/plan/kisi-yetkileri.md §5.3)."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.db.models import Prefetch

from apps.core.access import (
    ALL,
    ANY_ROLE,
    APPROVE,
    CHANGE,
    EVERYONE,
    READ,
    VIEW,
    Kind,
    ReadScope,
    Section,
    grant,
    register_field_openers,
    register_module,
    register_open_records,
    register_section,
    temporary_catalog,
)
from apps.core.effective_access import (
    ADMIN_ACCESS,
    NO_ACCESS,
    active_overrides,
    compute_access,
    effective_access,
)
from apps.core.models import AccessOverride, User
from apps.core.roles import DEPO, PLANLAMA, SEVKIYAT, YONETIM
from apps.production.access import BATCHES, ORDERS, PREP


@pytest.fixture
def demo() -> Iterator[dict[str, Section]]:
    """Deneme modülü: kurallar gerçek katalogdan bağımsız sınanır."""
    with temporary_catalog():
        register_module("demo", "Deneme", order=999)
        sections = {
            "orders": register_section(
                "demo.orders", "Emirler", levels=(VIEW, CHANGE, APPROVE), read=ReadScope.OPEN
            ),
            "shared": register_section(
                "demo.shared", "Ortak", levels=(VIEW,), read=ReadScope.SHARED
            ),
            "roles": register_section(
                "demo.roles", "Rolü olan", levels=(VIEW,), read=ReadScope.ANY_ROLE
            ),
            "plain": register_section("demo.plain", "Düz", levels=(VIEW, CHANGE)),
            "locked": register_section("demo.locked", "Kilitli", levels=(VIEW,), locked=(VIEW,)),
            "admin": register_section(
                "demo.admin", "Yalnız admin", levels=(VIEW, APPROVE), admin_only=(APPROVE,)
            ),
            "kvkk": register_section(
                "demo.kvkk", "KVKK", levels=(VIEW,), restricted_to_role=YONETIM
            ),
            "base": register_section("demo.base", "Temel", levels=(VIEW,), kind=Kind.SENSITIVE),
            "records": register_open_records("demo"),
        }
        sections["mid"] = register_section(
            "demo.mid", "Orta", levels=(VIEW, CHANGE), requires={ALL: [(sections["base"], VIEW)]}
        )
        sections["top"] = register_section(
            "demo.top",
            "Üst",
            levels=(VIEW, CHANGE),
            requires={CHANGE: [(sections["mid"], VIEW)]},
        )
        grant(DEPO, sections["orders"], VIEW)
        grant(PLANLAMA, sections["orders"], CHANGE)
        grant(EVERYONE, sections["locked"], VIEW)
        grant(YONETIM, sections["kvkk"], VIEW)
        grant(ANY_ROLE, sections["plain"], VIEW)
        for key in ("base", "mid", "top"):
            grant(SEVKIYAT, sections[key], VIEW)
        grant(SEVKIYAT, sections["top"], CHANGE)
        yield sections


def test_change_implies_view_but_approve_and_change_are_separate(demo: object) -> None:
    planner = compute_access([PLANLAMA])
    approver = compute_access([], grants=[("demo.orders", APPROVE)])

    assert planner.allows("demo.orders", VIEW)
    assert planner.allows("demo.orders", CHANGE)
    assert not planner.allows("demo.orders", APPROVE)
    assert approver.allows("demo.orders", VIEW)
    assert not approver.allows("demo.orders", CHANGE)


def test_revoking_view_drops_change_and_approve(demo: object) -> None:
    result = compute_access(
        [PLANLAMA], grants=[("demo.orders", APPROVE)], revokes=[("demo.orders", VIEW)]
    )

    assert not result.allows("demo.orders", VIEW)
    assert not result.allows("demo.orders", CHANGE)
    assert not result.allows("demo.orders", APPROVE)


def test_locked_and_admin_only_levels_cannot_be_changed(demo: object) -> None:
    result = compute_access([], grants=[("demo.admin", APPROVE)], revokes=[("demo.locked", VIEW)])

    assert result.allows("demo.locked", VIEW)
    assert not result.allows("demo.admin", APPROVE)


def test_unknown_overrides_are_ignored(demo: object) -> None:
    result = compute_access([], grants=[("demo.gone", VIEW), ("demo.plain", APPROVE)])

    assert not result.allows("demo.plain", VIEW)


def test_kvkk_section_needs_the_role(demo: object) -> None:
    assert compute_access([YONETIM]).allows("demo.kvkk", VIEW)
    assert not compute_access([PLANLAMA], grants=[("demo.kvkk", VIEW)]).allows("demo.kvkk")


def test_requirements_cascade_to_a_fixpoint(demo: object) -> None:
    full = compute_access([SEVKIYAT])
    without_base = compute_access([SEVKIYAT], revokes=[("demo.base", VIEW)])

    assert full.allows("demo.top", CHANGE)
    # base düşünce mid'in bütün düzeyleri, mid'in Görür'ü düşünce top'un Değiştirir'i düşer.
    assert not without_base.allows("demo.mid", VIEW)
    assert not without_base.allows("demo.top", CHANGE)
    assert without_base.allows("demo.top", VIEW)


def test_read_scopes(demo: object) -> None:
    nobody = compute_access([])
    member = compute_access([DEPO])

    assert nobody.can_read("demo.shared")
    assert nobody.can_read("demo.orders")
    assert not nobody.can_read("demo.roles")
    assert member.can_read("demo.roles")
    assert not nobody.can_read("demo.plain")
    assert member.can_read("demo.plain")


def test_closing_open_records_keeps_reads_through_view(demo: object) -> None:
    closed = compute_access([], revokes=[("demo.open_records", READ)])
    depo_closed = compute_access([DEPO], revokes=[("demo.open_records", READ)])

    assert not closed.can_read("demo.orders")
    assert depo_closed.can_read("demo.orders")
    assert depo_closed.allows("demo.orders", VIEW)


def test_sees_fields(demo: dict[str, Section]) -> None:
    register_field_openers("demo.customer.contact", demo["plain"])
    closed = ("demo.open_records", READ)
    group = "demo.customer.contact"

    assert compute_access([]).sees_fields(group)
    assert not compute_access([], revokes=[closed]).sees_fields(group)
    assert compute_access([DEPO], revokes=[closed]).sees_fields(group)
    assert not compute_access([DEPO], revokes=[closed, ("demo.plain", VIEW)]).sees_fields(group)
    assert compute_access([], revokes=[closed], is_admin=True).sees_fields(group)
    with pytest.raises(KeyError, match="Tanımsız alan grubu"):
        compute_access([], is_admin=True).sees_fields("demo.customer.kontak")


def test_admin_and_inactive(demo: object) -> None:
    admin = compute_access([DEPO], is_admin=True)
    inactive = compute_access([DEPO], is_active=False)

    assert admin is ADMIN_ACCESS
    assert admin.allows("demo.admin", APPROVE)
    assert admin.can_read("demo.orders", "demo.open_records")
    assert inactive is NO_ACCESS
    assert not inactive.allows("demo.locked", VIEW)


def test_allows_rejects_unknown_section_and_level(demo: object) -> None:
    result = compute_access([DEPO])

    with pytest.raises(KeyError):
        result.allows("demo.nothing")
    with pytest.raises(ValueError, match="düzey bölümde yok"):
        result.allows("demo.locked", CHANGE)


def test_letters(demo: object) -> None:
    letters = compute_access([PLANLAMA]).letters()

    assert letters["demo.orders"] == "rvc"
    assert letters["demo.open_records"] == "r"
    assert letters["demo.plain"] == "rv"
    assert "demo.kvkk" not in letters
    assert ADMIN_ACCESS.letters()["demo.admin"] == "rva"


# --- gerçek katalog -------------------------------------------------------------------------------


def test_role_packages_follow_the_plan() -> None:
    depo = compute_access([DEPO])
    planner = compute_access([PLANLAMA])
    nobody = compute_access([])

    assert depo.allows(PREP, CHANGE)
    assert depo.allows(ORDERS, VIEW)
    assert not depo.allows(ORDERS, CHANGE)
    assert planner.allows(ORDERS, APPROVE)
    assert not planner.allows(PREP, VIEW)
    assert planner.can_read(PREP)  # açık okuma
    assert nobody.can_read(ORDERS, BATCHES)
    assert not nobody.allows(ORDERS, VIEW)
    assert nobody.letters()["inventory.stock"] == "rv"


def test_multi_role_union() -> None:
    both = compute_access([DEPO, SEVKIYAT])

    assert both.allows("sales.picking", CHANGE)
    assert both.allows("sales.shipments", APPROVE)
    assert both.allows("production.prep", CHANGE)


# --- veritabanı -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_effective_access_reads_active_overrides(make_user: Callable[..., User]) -> None:
    user = make_user(DEPO)
    admin = make_user("admin")
    AccessOverride.objects.create(
        user=user,
        key="production.prep",
        level=CHANGE,
        effect="revoke",
        note="izin",
        created_by=admin,
    )
    ended = AccessOverride.objects.create(
        user=user,
        key="sales.orders",
        level=CHANGE,
        effect="grant",
        note="vekâlet",
        created_by=admin,
    )
    ended.ended_at = ended.created_at
    ended.end_reason = AccessOverride.EndReason.RESET
    ended.save(update_fields=["ended_at", "end_reason"])
    AccessOverride.objects.create(
        user=user,
        key="sales.orders",
        level=APPROVE,
        effect="grant",
        note="vekâlet",
        created_by=admin,
    )

    result = effective_access(user)

    assert not result.allows("production.prep", CHANGE)
    assert result.allows("production.prep", VIEW)
    assert not result.allows("sales.orders", CHANGE)
    assert result.allows("sales.orders", APPROVE)


@pytest.mark.django_db
def test_effective_access_uses_prefetched_roles_and_overrides(
    make_user: Callable[..., User], django_assert_num_queries: Any
) -> None:
    user = make_user(DEPO)
    AccessOverride.objects.create(
        user=user, key="production.prep", level=CHANGE, effect="revoke", note="x"
    )
    loaded = User.objects.prefetch_related(
        "groups", Prefetch("access_overrides", queryset=active_overrides())
    ).get(pk=user.pk)

    with django_assert_num_queries(0):
        result = effective_access(loaded)

    assert loaded.role_names == frozenset({DEPO})
    assert not result.allows("production.prep", CHANGE)


@pytest.mark.django_db
def test_refresh_access_drops_prefetched_roles_and_overrides(
    make_user: Callable[..., User],
) -> None:
    user = make_user(DEPO)
    loaded = User.objects.prefetch_related(
        "groups", Prefetch("access_overrides", queryset=active_overrides())
    ).get(pk=user.pk)
    assert loaded.access.allows("production.prep", CHANGE)

    AccessOverride.objects.create(
        user=user, key="production.prep", level=CHANGE, effect="revoke", note="x"
    )
    user.groups.add(Group.objects.get(name=PLANLAMA))
    assert loaded.access.allows("production.prep", CHANGE)

    loaded.refresh_access()

    assert loaded.role_names == frozenset({DEPO, PLANLAMA})
    assert not loaded.access.allows("production.prep", CHANGE)


@pytest.mark.django_db
def test_user_access_is_cached_until_refreshed(make_user: Callable[..., User]) -> None:
    user = make_user(DEPO)
    assert user.access.allows("production.prep", CHANGE)

    AccessOverride.objects.create(
        user=user, key="production.prep", level=CHANGE, effect="revoke", note="x"
    )
    assert user.access.allows("production.prep", CHANGE)

    user.refresh_access()
    assert not user.access.allows("production.prep", CHANGE)


@pytest.mark.django_db
def test_inactive_anonymous_and_admin_users(make_user: Callable[..., User]) -> None:
    from django.contrib.auth.models import AnonymousUser

    inactive = make_user(DEPO, is_active=False)
    admin = make_user("admin")
    superuser = make_user(is_superuser=True)

    assert effective_access(None) is NO_ACCESS
    assert effective_access(AnonymousUser()) is NO_ACCESS
    assert effective_access(inactive) is NO_ACCESS
    assert effective_access(admin) is ADMIN_ACCESS
    assert effective_access(superuser) is ADMIN_ACCESS
