"""Görevi alacak kimse kalmıyor denetimi ve iş akışı kural kaydı (docs/plan/kisi-yetkileri.md
§5.1, §5.7, §5.10, §8 madde 9).

Kuralı alabilecek kişi kuralın alıcısıyla aynıdır: rollerinden birinin etkin üyesi ve kuralın
gerektirdiği yetkiye sahip. Admin grubunda olmayan süper kullanıcı kimseyi kapsamaz.
"""

from collections.abc import Iterator

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.core import access, coverage
from apps.core.access import NOTIFY, TASK, VIEW
from apps.core.effective_access import compute_access
from apps.core.models import AccessOverride, AuditLog, User
from apps.core.roles import ADMIN, ALL_ROLES, DEPO, PLANLAMA, URETIM

pytestmark = pytest.mark.django_db

READINESS = ("golive.readiness", VIEW)  # Planlama, Depo ve Yönetim paketinde
USERS = "/api/v1/users/"


@pytest.fixture
def only_test_rules() -> Iterator[None]:
    """Kayıtlı iş akışı kuralları yerine yalnız testin kaydettikleri sayılır."""
    with access.temporary_catalog():
        access._RULES.clear()
        yield


def override(user: User, key: str, level: str, effect: str) -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


# --- kayıt defteri ----------------------------------------------------------------------------


def test_register_rule_validates_input(only_test_rules):
    access.register_rule("deneme_gorev", TASK, (DEPO,), READINESS)
    with pytest.raises(ValueError, match="iki kez"):
        access.register_rule("deneme_gorev", TASK, (DEPO,), READINESS)
    with pytest.raises(ValueError, match="tür"):
        access.register_rule("deneme_x", "task_rule", (DEPO,), READINESS)
    with pytest.raises(ValueError, match="rol"):
        access.register_rule("deneme_y", NOTIFY, ("muhasebe",), READINESS)
    with pytest.raises(ValueError, match="çift"):
        access.register_rule("deneme_z", NOTIFY, (DEPO,), ("golive.readiness", ""))
    assert [rule.code for rule in access.rules()] == ["deneme_gorev"]


def test_validate_reports_unknown_rule_section_and_level(only_test_rules):
    access.register_rule("deneme_bolum", TASK, (DEPO,), ("yok.boyle", VIEW))
    access.register_rule("deneme_duzey", TASK, (DEPO,), ("golive.readiness", "approve"))
    errors = access.validate()
    assert any("deneme_bolum" in error and "yok.boyle" in error for error in errors)
    assert any("deneme_duzey" in error and "approve" in error for error in errors)


def test_rules_are_not_part_of_catalog_hash():
    before = access.catalog_hash()
    with access.temporary_catalog():
        access.register_rule("deneme_ozet", TASK, (DEPO,), READINESS)
        assert access.catalog_hash() == before
    assert "deneme_ozet" not in {rule.code for rule in access.rules()}


def test_workflow_registers_every_rule_with_valid_requirement():
    from apps.workflow import rules

    registered = {rule.code: rule for rule in access.rules()}
    assert set(registered) == {rule.code for rule in rules.RULES}
    assert not [error for error in access.validate() if "iş akışı kuralı" in error]
    exempt = {code for code, rule in registered.items() if rule.requires is None}
    # Yalnız raporu isteyene giden bildirimler muaf (plan §5.7); onların rolü de yoktur.
    assert exempt == {"report_ready", "report_failed"}
    assert all(not registered[code].roles for code in exempt)


def test_every_rule_role_holds_the_rule_requirement_without_overrides():
    """Kişiye özel ayar yokken alıcılar bugünküyle aynı: kuralın her rolünün paketi kuralın
    yetkisini taşır (plan §5.7)."""
    missing = [
        (rule.code, role)
        for rule in access.rules()
        if rule.requires is not None
        for role in rule.roles
        if not compute_access({role}, is_admin=role == ADMIN).allows(*rule.requires)
    ]
    assert missing == []


def test_one_active_member_per_role_covers_every_rule(make_user):
    for role in ALL_ROLES:
        make_user(role)
    assert coverage.current_gaps() == []


# --- kapsama ----------------------------------------------------------------------------------


def test_rule_without_members_is_a_gap(only_test_rules, make_user):
    access.register_rule("deneme_gorev", TASK, (DEPO,), READINESS)
    access.register_rule("deneme_bildirim", NOTIFY, (DEPO,), READINESS)
    access.register_rule("rapor_hazir", NOTIFY, (), None)  # raporu isteyene: sayılmaz
    make_user(PLANLAMA)
    make_user(DEPO, is_active=False)

    (gap,) = coverage.current_gaps()
    assert gap.tasks == ("deneme_gorev",) and gap.notifications == ("deneme_bildirim",)
    assert gap.text.startswith("Depo rolünde “")
    assert "Hazırlık listesi: Görür" in gap.text
    assert "1 görev kimseye düşmez, 1 bildirim kimseye gitmez" in gap.text

    make_user(DEPO)
    assert coverage.current_gaps() == []


def test_revoked_requirement_leaves_rule_uncovered(only_test_rules, make_user):
    access.register_rule("deneme_gorev", TASK, (DEPO,), READINESS)
    depo = make_user(DEPO)
    assert coverage.current_gaps() == []

    override(depo, *READINESS, AccessOverride.Effect.REVOKE)
    assert [gap.tasks for gap in coverage.current_gaps()] == [("deneme_gorev",)]


def test_granted_requirement_covers_rule(only_test_rules, make_user):
    access.register_rule("deneme_gorev", TASK, (URETIM,), READINESS)
    uretim = make_user(URETIM)
    assert len(coverage.current_gaps()) == 1

    override(uretim, *READINESS, AccessOverride.Effect.GRANT)
    assert coverage.current_gaps() == []


def test_admin_rules_need_an_admin_group_member(only_test_rules, make_user):
    access.register_rule("deneme_sorun", TASK, (ADMIN,), READINESS)
    make_user(username="kok", is_superuser=True, is_staff=True)
    assert len(coverage.current_gaps()) == 1  # süper kullanıcı rol alıcısı değil

    make_user(ADMIN)
    assert coverage.current_gaps() == []


# --- rol değişikliği uyarısı ------------------------------------------------------------------


def test_role_change_warns_only_about_newly_uncovered_rules(only_test_rules, make_user):
    access.register_rule("deneme_depo", TASK, (DEPO,), READINESS)
    access.register_rule("deneme_uretim", TASK, (URETIM,), None)  # zaten kimsesiz
    depo = make_user(DEPO)

    (warning,) = coverage.role_change_warnings(depo, [DEPO], [PLANLAMA])
    assert warning.startswith("Depo rolünde")
    assert coverage.role_change_warnings(depo, [DEPO], [DEPO]) == []
    assert coverage.role_change_warnings(depo, [DEPO], [DEPO, PLANLAMA]) == []

    make_user(DEPO)
    assert coverage.role_change_warnings(depo, [DEPO], [PLANLAMA]) == []


def test_role_change_of_inactive_user_does_not_warn(only_test_rules, make_user):
    access.register_rule("deneme_depo", TASK, (DEPO,), READINESS)
    depo = make_user(DEPO, is_active=False)
    assert coverage.role_change_warnings(depo, [DEPO], []) == []


def test_giving_role_to_roleless_user_never_warns(only_test_rules, make_user):
    access.register_rule("deneme_depo", TASK, (DEPO,), READINESS)
    nobody = make_user()
    assert coverage.role_change_warnings(nobody, [], [DEPO]) == []


def test_user_patch_returns_non_blocking_warning(only_test_rules, client_for, make_user):
    access.register_rule("deneme_depo", TASK, (DEPO,), READINESS)
    depo = make_user(DEPO)
    admin = client_for(ADMIN)

    response = admin.patch(f"{USERS}{depo.pk}/", {"roles": [PLANLAMA]}, format="json")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["roles"] == [PLANLAMA]
    assert len(body["coverage_warnings"]) == 1
    assert "Depo rolünde" in body["coverage_warnings"][0]
    depo.refresh_from_db()
    assert depo.role_names == {PLANLAMA}

    other = make_user(DEPO)
    response = admin.patch(f"{USERS}{other.pk}/", {"full_name": "Ali Veli"}, format="json")
    assert response.json()["coverage_warnings"] == []


def test_user_patch_warning_counts_revoked_override(only_test_rules, client_for, make_user):
    """İkinci depo üyesinin Hazırlık listesi yetkisi kaldırılmışsa görevi alamaz: ilk üyenin rolü
    değişince uyarı çıkar."""
    access.register_rule("deneme_depo", TASK, (DEPO,), READINESS)
    depo = make_user(DEPO)
    override(make_user(DEPO), *READINESS, AccessOverride.Effect.REVOKE)

    response = client_for(ADMIN).patch(f"{USERS}{depo.pk}/", {"roles": [PLANLAMA]}, format="json")

    assert response.status_code == 200
    assert len(response.json()["coverage_warnings"]) == 1


# --- access.changed ---------------------------------------------------------------------------


@pytest.fixture
def access_events() -> list[dict]:
    from apps.core import events

    payloads: list[dict] = []
    events.subscribe("access.changed")(lambda event: payloads.append(dict(event.payload)))
    return payloads


def test_role_change_publishes_access_changed_after_commit(
    client_for, make_user, access_events, django_capture_on_commit_callbacks
):
    depo = make_user(DEPO)
    admin = client_for(ADMIN)

    with django_capture_on_commit_callbacks(execute=True):
        admin.patch(f"{USERS}{depo.pk}/", {"roles": [DEPO]}, format="json")
        admin.patch(f"{USERS}{depo.pk}/", {"full_name": "Ali"}, format="json")
    assert access_events == []

    with django_capture_on_commit_callbacks(execute=True):
        admin.patch(f"{USERS}{depo.pk}/", {"roles": [DEPO, PLANLAMA]}, format="json")
    assert access_events == [{"user_id": depo.pk}]


def test_new_user_with_roles_publishes_access_changed(
    client_for, access_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = client_for(ADMIN).post(
            USERS, {"username": "yeni.kisi", "full_name": "Yeni Kişi", "roles": [DEPO]}
        )
    assert response.status_code == 201, response.content
    assert access_events == [{"user_id": response.json()["user"]["id"]}]


def test_rolled_back_role_change_publishes_nothing(make_user, access_events):
    from django.db import transaction

    from apps.core import services

    depo = make_user(DEPO)
    with pytest.raises(RuntimeError), transaction.atomic():
        services.set_user_roles(depo, [PLANLAMA], None)
        raise RuntimeError("geri al")
    assert access_events == []


@pytest.fixture
def panel(make_user):
    from django.test import Client

    superuser = make_user(ADMIN, username="kok", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(superuser)
    return client


def _panel_form(user: User, **changes: object) -> dict:
    from django.contrib.auth.models import Group

    data: dict = {
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "phone": "",
        "groups": [group.pk for group in Group.objects.filter(name__in=user.role_names)],
    }
    if user.is_active:
        data["is_active"] = "on"
    if user.is_superuser:
        data["is_superuser"] = "on"
    data.update(changes)
    return {key: value for key, value in data.items() if value is not None}


@pytest.mark.parametrize("change", ["groups", "is_superuser", "is_active"])
def test_admin_panel_publishes_access_changed(
    panel, make_user, access_events, django_capture_on_commit_callbacks, change
):
    from django.contrib.auth.models import Group

    target = make_user(DEPO, username="depo1", full_name="Ayşe")
    changes: dict[str, object] = {
        "groups": {"groups": [Group.objects.get(name=PLANLAMA).pk]},
        "is_superuser": {"is_superuser": "on"},
        "is_active": {"is_active": None},
    }[change]

    with django_capture_on_commit_callbacks(execute=True):
        response = panel.post(
            f"/admin/core/user/{target.pk}/change/", _panel_form(target, **changes)
        )

    assert response.status_code == 302, response.content[:500]
    assert access_events == [{"user_id": target.pk}]


def test_admin_panel_name_change_does_not_publish(
    panel, make_user, access_events, django_capture_on_commit_callbacks
):
    target = make_user(DEPO, username="depo1", full_name="Ayşe")
    with django_capture_on_commit_callbacks(execute=True):
        response = panel.post(
            f"/admin/core/user/{target.pk}/change/", _panel_form(target, full_name="Ayşe Y")
        )
    assert response.status_code == 302
    assert access_events == []
    assert AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(User), object_id=target.pk
    ).exists()
