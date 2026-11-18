"""Yetkiler ekranının servisi `core.services.set_user_access` (docs/plan/kisi-yetkileri.md §5.2,
§5.10, §5.11, §6.1; kurallar ve sıra: adım 9 tasarımı §4.1).

Her kural için mutlu yol ve ihlal; deneme hesabı (`dry_run`), satırların bitiş nedenleri, rol
kancası, uyarılar, denetim kaydı ve olaylar.
"""

from collections.abc import Callable, Iterable

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core import access, coverage, events, services, user_access
from apps.core.effective_access import active_overrides, compute_access, effective_access
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AccessOverride, AuditLog, TOTPDevice, User
from apps.core.roles import ADMIN, DEPO, LABORATUVAR, PLANLAMA, YONETIM
from apps.core.user_access import GRANT, REVOKE, OverrideSpec

pytestmark = pytest.mark.django_db

NOTE = "Hazırlığı vardiya amiri yapacak"
PREP_CHANGE = OverrideSpec("production.prep", "change", REVOKE)
Reason = AccessOverride.EndReason


def version(user: User) -> str:
    return user_access.access_version(user, list(active_overrides().filter(user=user)))


def save(
    actor: User, user: User, overrides: Iterable[OverrideSpec] = (), **kwargs: object
) -> user_access.AccessPlan:
    options: dict = {"note": NOTE, "version": version(user), **kwargs}
    return services.set_user_access(actor, user, overrides=list(overrides), **options)


def error_code(call: Callable[[], object]) -> str:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value.code


def row(user: User, key: str, level: str, effect: str = REVOKE) -> AccessOverride:
    item = AccessOverride.objects.create(
        user=user, key=key, level=level, effect=effect, note="önceki kayıt"
    )
    user.refresh_access()
    return item


def specs(user: User) -> set[OverrideSpec]:
    return {OverrideSpec.of(item) for item in active_overrides().filter(user=user)}


def codes(plan: user_access.AccessPlan) -> list[str]:
    return [item.code for item in plan.warnings]


def user_logs(user: User):
    return AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(User), object_id=user.pk
    ).order_by("pk")


@pytest.fixture
def admin(make_user) -> User:
    return make_user(ADMIN, username="yonetici")


@pytest.fixture
def published() -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for name in ("access.changed", "access.updated"):
        events.subscribe(name)(lambda event: found.append((event.name, dict(event.payload))))
    return found


# --- mutlu yol ----------------------------------------------------------------------------------


def test_admin_revokes_section_and_access_drops(admin, make_user):
    depo = make_user(DEPO)
    assert depo.access.allows("production.prep", "change")

    plan = save(admin, depo, [PREP_CHANGE])

    assert plan.changed and plan.create == (PREP_CHANGE,)
    stored = AccessOverride.objects.get(user=depo)
    assert stored.is_active and stored.note == NOTE and stored.created_by == admin
    depo = User.objects.get(pk=depo.pk)
    assert not effective_access(depo).allows("production.prep", "change")
    assert effective_access(depo).allows("production.prep", "view")
    assert plan.access_before.letters()["production.prep"] == "rvc"
    assert plan.access_after.letters()["production.prep"] == "rv"


def test_non_admin_cannot_change_access(make_user):
    manager, depo = make_user(YONETIM), make_user(DEPO)

    with pytest.raises(PermissionDenied, match="Yetkileri yalnızca sistem yöneticisi değiştirir"):
        save(manager, depo, [PREP_CHANGE])
    with pytest.raises(PermissionDenied):
        save(make_user(ADMIN, is_active=False), depo, [PREP_CHANGE])
    assert not AccessOverride.objects.exists()


def test_note_required_min_five_chars(admin, make_user):
    depo = make_user(DEPO)

    assert error_code(lambda: save(admin, depo, [PREP_CHANGE], note=" abc ")) == (
        "access_note_required"
    )
    plan = save(admin, depo, [PREP_CHANGE], note="", dry_run=True)
    assert plan.changed and not AccessOverride.objects.exists()
    save(admin, depo, [PREP_CHANGE], note="  Gerekçe  ")
    assert AccessOverride.objects.get(user=depo).note == "Gerekçe"


def test_cannot_edit_own_overrides_but_can_change_own_roles(admin):
    assert error_code(lambda: save(admin, admin, [PREP_CHANGE])) == "cannot_edit_own_access"

    save(admin, admin, roles=[ADMIN, PLANLAMA])

    admin.refresh_roles()
    assert admin.role_names == {ADMIN, PLANLAMA}


def test_admin_target_rejects_overrides(admin, make_user):
    other_admin = make_user(ADMIN)
    root = make_user(DEPO, is_superuser=True)
    depo = make_user(DEPO)

    assert error_code(lambda: save(admin, other_admin, [PREP_CHANGE])) == "admin_has_all_access"
    assert error_code(lambda: save(admin, root, [PREP_CHANGE])) == "admin_has_all_access"
    assert error_code(lambda: save(admin, depo, [PREP_CHANGE], roles=[DEPO, ADMIN])) == (
        "admin_has_all_access"
    )
    assert not AccessOverride.objects.exists()


def test_unknown_roles_rejected(admin, make_user):
    depo = make_user(DEPO)
    assert error_code(lambda: save(admin, depo, roles=["muhasebe"])) == "unknown_role"


@pytest.mark.parametrize(
    "spec",
    [
        OverrideSpec("yok.boyle", "view", REVOKE),
        OverrideSpec("production.prep", "read", REVOKE),
        OverrideSpec("production.prep", "approve", GRANT),
        OverrideSpec("production.prep", "view", "remove"),
    ],
)
def test_unknown_section_or_level(admin, make_user, spec):
    with pytest.raises(BusinessRuleError) as exc:
        save(admin, make_user(DEPO), [spec])
    assert exc.value.code == "unknown_access"
    assert exc.value.message == f"Tanımsız yetki: {spec.key} ({spec.level})."


@pytest.mark.parametrize("effect", [GRANT, REVOKE])
def test_admin_only_level_not_grantable(admin, make_user, effect):
    spec = OverrideSpec("inventory.manual_release", "approve", effect)
    assert error_code(lambda: save(admin, make_user(DEPO), [spec])) == "access_not_grantable"


def test_locked_level_cannot_be_revoked(admin, make_user):
    spec = OverrideSpec("inventory.lots", "view", REVOKE)
    assert error_code(lambda: save(admin, make_user(DEPO), [spec])) == "access_locked"
    # Kilitli olmayan düzey kaldırılabilir.
    save(admin, make_user(DEPO), [OverrideSpec("inventory.stock", "change", REVOKE)])


def test_kvkk_grant_requires_yonetim_role(admin, make_user):
    planlama = make_user(PLANLAMA)
    cards = OverrideSpec("personnel.cards", "view", GRANT)

    assert error_code(lambda: save(admin, planlama, [cards])) == "access_requires_role"

    plan = save(admin, planlama, [cards], roles=[PLANLAMA, YONETIM])
    assert plan.create == (cards,)


def test_prerequisite_missing(admin, make_user):
    depo = make_user(DEPO)
    costs = OverrideSpec("sensitive.costs", "view", GRANT)
    prices = OverrideSpec("sensitive.prices", "view", GRANT)

    with pytest.raises(BusinessRuleError) as exc:
        save(admin, depo, [costs])
    assert exc.value.code == "access_requires"
    assert exc.value.message == "Bu yetki için önce “Fiyatları görür” yetkisi gerekir."

    save(admin, depo, [costs, prices])
    assert effective_access(User.objects.get(pk=depo.pk)).allows("sensitive.costs")


def test_prerequisite_label_names_module_and_level(admin, make_user):
    spec = OverrideSpec("maintenance.any_unit", "change", GRANT)
    with pytest.raises(BusinessRuleError) as exc:
        save(admin, make_user(DEPO), [spec])
    assert (
        exc.value.message
        == "Bu yetki için önce “Bakım › Bakım iş emirleri: Değiştirir” yetkisi gerekir."
    )


def test_view_revoked_with_change_granted_conflicts(admin, make_user):
    overrides = [
        OverrideSpec("production.orders", "view", REVOKE),
        OverrideSpec("production.orders", "change", GRANT),
    ]
    assert error_code(lambda: save(admin, make_user(DEPO), overrides)) == "access_conflict"


def test_open_records_grant_rejected(admin, make_user):
    spec = OverrideSpec("quality.open_records", "read", GRANT)
    assert error_code(lambda: save(admin, make_user(DEPO), [spec])) == "open_records_revoke_only"


def test_open_records_revoke_closes_reads(admin, make_user):
    depo = make_user(DEPO)
    assert depo.access.can_read("quality.samples")

    plan = save(admin, depo, [OverrideSpec("quality.open_records", "read", REVOKE)])

    assert not effective_access(User.objects.get(pk=depo.pk)).can_read("quality.samples")
    (warning,) = [item for item in plan.warnings if item.code == "open_records_closed"]
    assert warning.text.startswith("Kalite kontrol kayıtları bu kişi için kapanıyor.")
    assert "Okumaya devam ettiği bölümler: yok." in warning.text
    assert "Etkilenebilecek başka ekranlar: Lot sayfasının kalite bölümü" in warning.text


def test_duplicate_rows_rejected(admin, make_user):
    overrides = [PREP_CHANGE, OverrideSpec("production.prep", "change", GRANT)]
    with pytest.raises(BusinessRuleError) as exc:
        save(admin, make_user(DEPO), overrides)
    assert exc.value.code == "access_duplicate"
    assert exc.value.message == "Aynı yetki iki kez seçilmiş: production.prep (change)."


@pytest.mark.parametrize("dry_run", [False, True])
def test_stale_version_rejected(admin, make_user, dry_run):
    depo = make_user(DEPO)
    stale = version(depo)
    row(depo, "masterdata.cards", "view", GRANT)

    with pytest.raises(BusinessRuleError) as exc:
        services.set_user_access(
            admin, depo, version=stale, overrides=[PREP_CHANGE], note=NOTE, dry_run=dry_run
        )
    assert exc.value.code == "access_changed"
    assert exc.value.message == "Yetkiler siz düzenlerken değişti; sayfayı yenileyin."


def test_access_version_changes_on_role_or_override_change(make_user):
    depo = make_user(DEPO)
    first = version(depo)
    assert len(first) == 32 and first == version(User.objects.get(pk=depo.pk))

    item = row(depo, "masterdata.cards", "view", GRANT)
    second = version(depo)
    assert second != first

    services.set_user_roles(depo, [DEPO, PLANLAMA], None)
    third = version(User.objects.get(pk=depo.pk))
    assert third != second

    item.ended_at, item.end_reason = timezone.now(), Reason.RESET
    item.save(update_fields=["ended_at", "end_reason"])
    assert version(User.objects.get(pk=depo.pk)) != third

    fresh = User.objects.get(pk=depo.pk)
    active = user_access.access_version(fresh, [])
    fresh.is_active = False
    assert user_access.access_version(fresh, []) != active
    fresh.is_active, fresh.is_superuser = True, True
    assert user_access.access_version(fresh, []) != active


def test_dry_run_writes_nothing_and_returns_summary_and_warnings(
    admin, make_user, published, django_capture_on_commit_callbacks
):
    depo = make_user(DEPO, is_active=False)
    logs = AuditLog.objects.count()

    with django_capture_on_commit_callbacks(execute=True):
        plan = save(admin, depo, [PREP_CHANGE], roles=[DEPO, PLANLAMA], note="", dry_run=True)

    assert plan.changed and plan.create == (PREP_CHANGE,)
    assert plan.roles_before == (DEPO,) and plan.roles_after == (DEPO, PLANLAMA)
    assert "user_inactive" in codes(plan)
    assert ("production.prep", "change") in plan.access_before.entries  # etkinmiş gibi
    assert ("planning.plans", "view") not in plan.access_after.entries
    assert not AccessOverride.objects.exists()
    assert AuditLog.objects.count() == logs
    depo.refresh_roles()
    assert depo.role_names == {DEPO}
    assert published == []


def test_noop_save_writes_nothing(admin, make_user, published, django_capture_on_commit_callbacks):
    depo = make_user(DEPO)
    kept = row(depo, "masterdata.cards", "view", GRANT)
    logs = AuditLog.objects.count()

    with django_capture_on_commit_callbacks(execute=True):
        plan = save(admin, depo, [OverrideSpec.of(kept)], roles=[DEPO], note="")

    assert not plan.changed and plan.warnings == ()
    assert plan.keep == (kept,)
    assert AuditLog.objects.count() == logs
    assert published == []


# --- satırların dönemleri -----------------------------------------------------------------------


def _ended(item: AccessOverride) -> AccessOverride:
    item.refresh_from_db()
    assert item.ended_at is not None
    return item


def test_return_to_default_ends_row_reset(admin, make_user):
    depo = make_user(DEPO)
    item = row(depo, "production.prep", "change")

    plan = save(admin, depo, [])

    assert plan.end == ((item, Reason.RESET.value),)
    ended = _ended(item)
    assert ended.end_reason == Reason.RESET and ended.ended_by == admin and ended.end_note == NOTE
    assert specs(depo) == set()


def test_effect_flip_replaces_row(admin, make_user):
    depo = make_user(DEPO)
    item = row(depo, "masterdata.cards", "view", GRANT)
    flipped = OverrideSpec("masterdata.cards", "view", REVOKE)

    save(admin, depo, [flipped])

    assert _ended(item).end_reason == Reason.REPLACED
    assert specs(depo) == {flipped}


def test_removing_ineffective_row_ends_ineffective(admin, make_user):
    """ "Etkisiz ayarları temizle": rolün zaten verdiği ekleme ve rolün vermediği kaldırma."""
    depo = make_user(DEPO)
    redundant = row(depo, "production.prep", "change", GRANT)
    empty = row(depo, "quality.samples", "approve", REVOKE)
    real = row(depo, "production.orders", "view", REVOKE)

    save(admin, depo, [OverrideSpec.of(real)])

    assert _ended(redundant).end_reason == Reason.INEFFECTIVE
    assert _ended(empty).end_reason == Reason.INEFFECTIVE
    assert specs(depo) == {OverrideSpec.of(real)}


def test_unknown_key_row_ends_retired(admin, make_user):
    depo = make_user(DEPO)
    gone = row(depo, "eski.bolum", "view", GRANT)
    assert not user_access.is_ineffective(OverrideSpec.of(gone), [DEPO])

    save(admin, depo, [PREP_CHANGE])

    assert _ended(gone).end_reason == Reason.RETIRED


def test_unknown_key_row_sent_back_is_kept(admin, make_user):
    """Kalan satırlar yeniden denetlenmez; ekran tanımsız satırı göndermezse `retired` biter."""
    depo = make_user(DEPO)
    gone = row(depo, "eski.bolum", "view", GRANT)

    plan = save(admin, depo, [OverrideSpec.of(gone), PREP_CHANGE])

    assert plan.keep == (gone,)


def test_redundant_row_is_stored_and_flagged(admin, make_user):
    depo = make_user(DEPO)
    redundant = OverrideSpec("production.prep", "change", GRANT)
    view = OverrideSpec("masterdata.cards", "view", GRANT)
    change = OverrideSpec("masterdata.cards", "change", GRANT)

    plan = save(admin, depo, [redundant, view, change])

    assert specs(depo) == {redundant, view, change}
    assert user_access.is_ineffective(redundant, [DEPO])
    # Değiştirir'in yanındaki açık Görür etkisiz değildir: Değiştirir kalkınca Görür kalır.
    assert not user_access.is_ineffective(view, [DEPO])
    assert "override_ineffective" in codes(plan)
    (warning,) = [item for item in plan.warnings if item.code == "override_ineffective"]
    assert warning.text.startswith("1 kişiye özel ayar etkisiz kalıyor")


def test_kvkk_revoke_kept_outside_role(admin, make_user):
    planlama = make_user(PLANLAMA)
    cards = OverrideSpec("personnel.cards", "view", REVOKE)

    save(admin, planlama, [cards])
    assert not user_access.is_ineffective(cards, [PLANLAMA])

    save(admin, User.objects.get(pk=planlama.pk), [cards], roles=[PLANLAMA, YONETIM])
    planlama = User.objects.get(pk=planlama.pk)
    assert specs(planlama) == {cards}
    assert not effective_access(planlama).allows("personnel.cards")
    assert effective_access(planlama).allows("personnel.wages")


def test_inactive_user_rows_are_not_ineffective(admin, make_user):
    depo = make_user(DEPO, is_active=False)
    item = row(depo, "production.prep", "change")
    assert not user_access.is_ineffective(OverrideSpec.of(item), depo.roles)

    plan = save(admin, depo, [])

    assert plan.end == ((item, Reason.RESET.value),)
    assert codes(plan) == ["user_inactive"]


def test_roles_saved_in_same_transaction(admin, make_user):
    depo = make_user(DEPO)

    plan = save(admin, depo, [PREP_CHANGE], roles=[DEPO, PLANLAMA])
    depo = User.objects.get(pk=depo.pk)
    assert depo.role_names == {DEPO, PLANLAMA} and specs(depo) == {PREP_CHANGE}
    assert plan.roles_after == (DEPO, PLANLAMA)

    bad = OverrideSpec("inventory.lots", "view", REVOKE)
    assert error_code(lambda: save(admin, depo, [PREP_CHANGE, bad], roles=[DEPO])) == (
        "access_locked"
    )
    depo = User.objects.get(pk=depo.pk)
    assert depo.role_names == {DEPO, PLANLAMA} and specs(depo) == {PREP_CHANGE}


def test_own_admin_role_cannot_be_removed(admin, make_user):
    make_user(ADMIN)
    assert error_code(lambda: save(admin, admin, roles=[PLANLAMA])) == "cannot_remove_own_admin"


def test_last_admin_rule(admin, make_user):
    """Kaydı yapan her zaman aktif bir yöneticidir; son admin kuralı yine de aynı denetimden
    geçer (`_admin_removal_guard`)."""
    other = make_user(ADMIN, username="ikinci")
    save(admin, other, roles=[DEPO])
    other = User.objects.get(pk=other.pk)
    assert not other.is_admin

    only = User.objects.get(pk=admin.pk)
    with pytest.raises(BusinessRuleError) as exc:
        services._admin_removal_guard(make_user(YONETIM), only, [DEPO])
    assert exc.value.code == "last_admin"
    assert exc.value.message == "Başka aktif sistem yöneticisi olmadığı için bu rol kaldırılamaz."
    # Süper kullanıcı da aktif yöneticidir.
    make_user(is_superuser=True, username="kok")
    services._admin_removal_guard(make_user(YONETIM), only, [DEPO])


def test_last_admin_check_locks_admin_rows(admin, make_user):
    other = make_user(ADMIN, username="ikinci")

    with CaptureQueriesContext(connection) as queries:
        save(admin, other, roles=[DEPO])

    sql = [query["sql"] for query in queries.captured_queries]
    locks = [
        index
        for index, text in enumerate(sql)
        if "FOR UPDATE" in text and '"core_user"' in text and " IN (SELECT" in text
    ]
    target = [
        index
        for index, text in enumerate(sql)
        if "FOR UPDATE" in text and '"core_user"' in text and " IN (SELECT" not in text
    ]
    assert locks and target and locks[0] < target[0]


def test_admin_rows_are_not_locked_without_admin_removal(admin, make_user):
    depo = make_user(DEPO)
    with CaptureQueriesContext(connection) as queries:
        save(admin, depo, roles=[DEPO, PLANLAMA])
    assert not [
        query
        for query in queries.captured_queries
        if "FOR UPDATE" in query["sql"] and " IN (SELECT" in query["sql"]
    ]


def test_admin_role_ends_overrides(admin, make_user):
    depo = make_user(DEPO)
    item = row(depo, "production.prep", "change")

    plan = save(admin, depo, [OverrideSpec.of(item)], roles=[DEPO, ADMIN])

    assert _ended(item).end_reason == Reason.ADMIN
    assert codes(plan) == ["admin_granted"]
    assert plan.warnings[0].text == (
        "Sistem yöneticisi rolü veriliyor: kişi her ekranı görür ve her işlemi yapar; kişiye "
        "özel 1 ayar biter."
    )
    assert specs(depo) == set()


def test_admin_given_ends_rows_even_if_client_omits_them(admin, make_user):
    depo = make_user(DEPO)
    item = row(depo, "masterdata.cards", "view", GRANT)

    plan = save(admin, depo, [], roles=[DEPO, ADMIN])

    assert plan.end == ((item, Reason.ADMIN.value),)


def test_yonetim_removed_ends_kvkk_grants_keeps_revokes(admin, make_user):
    manager = make_user(YONETIM, PLANLAMA)
    grant = row(manager, "personnel.cards", "view", GRANT)
    revoke = row(manager, "hse.incidents", "change", REVOKE)

    plan = save(admin, manager, [OverrideSpec.of(grant), OverrideSpec.of(revoke)], roles=[PLANLAMA])

    assert _ended(grant).end_reason == Reason.ROLE_REMOVED
    assert specs(manager) == {OverrideSpec.of(revoke)}
    (warning,) = [item for item in plan.warnings if item.code == "kvkk_role_removed"]
    assert warning.text.startswith("Yönetim rolü kaldırılıyor: ")
    assert access.section("personnel.cards").label in warning.text
    assert warning.text.endswith("; kişiye özel 1 ekleme biter.")


def test_set_user_roles_admin_ends_rows_and_logs_access(make_user):
    depo = make_user(DEPO)
    item = row(depo, "production.prep", "change")

    services.set_user_roles(depo, [DEPO, ADMIN], None)

    ended = _ended(item)
    assert ended.end_reason == Reason.ADMIN and ended.end_note == "Sistem yöneticisi oldu"
    log = user_logs(depo).last()
    assert log.changes == {
        "roles": [[DEPO], [ADMIN, DEPO]],
        "access": [
            [{"id": item.pk, "key": "production.prep", "level": "change", "effect": REVOKE}],
            [],
        ],
    }


def test_set_user_roles_role_removed_ends_kvkk_grants(make_user):
    manager = make_user(YONETIM)
    grant = row(manager, "personnel.cards", "view", GRANT)
    revoke = row(manager, "personnel.wages", "view", REVOKE)

    services.set_user_roles(manager, [PLANLAMA], None, note="Görev değişti")

    assert _ended(grant).end_note == "Görev değişti"
    assert specs(manager) == {OverrideSpec.of(revoke)}
    services.set_user_roles(manager, [PLANLAMA, DEPO], None)
    assert set(user_logs(manager).last().changes) == {"roles"}


# --- uyarılar -----------------------------------------------------------------------------------


def test_warning_task_not_routed(admin, make_user):
    lab = make_user(LABORATUVAR)
    spec = OverrideSpec("quality.conditional", "approve", GRANT)

    plan = save(admin, lab, [spec], dry_run=True)

    (warning,) = [item for item in plan.warnings if item.code == "task_not_routed"]
    assert warning.text == (
        "“Kalite kontrol › Şartlı kabul onayı: Onaylar” yetkisinin görevleri Yönetim rolüne "
        "gider; bu kişiye görev düşmez."
    )


def test_warning_no_role_no_tasks(admin, make_user):
    nobody = make_user()
    plan = save(admin, nobody, [OverrideSpec("production.orders", "view", GRANT)], dry_run=True)
    assert "no_role_no_tasks" in codes(plan) and "task_not_routed" not in codes(plan)


def test_warning_segregation_mixed_sources_only(admin, make_user):
    depo = make_user(DEPO)
    plan = save(admin, depo, [OverrideSpec("quality.samples", "approve", GRANT)], dry_run=True)
    (warning,) = [item for item in plan.warnings if item.code == "segregation"]
    assert warning.text == (
        "Görev ayrılığı: “Mal kabul (Değiştirir)” ve “Numuneler ve kalite kararı (Onaylar)” "
        "aynı kişide. Kaydedenle onaylayanın ayrı olması önerilir."
    )

    # Yönetim paketi satın alma ayarlarını ve sipariş onayını birlikte verir: uyarı yok.
    manager = make_user(YONETIM)
    plan = save(admin, manager, [OverrideSpec("reporting.lab", "view", REVOKE)], dry_run=True)
    assert "segregation" not in codes(plan)
    # İki rolden gelince uyarı çıkar.
    plan = save(admin, depo, [], roles=[DEPO, LABORATUVAR], dry_run=True)
    assert "segregation" in codes(plan)


def test_warning_user_inactive(admin, make_user):
    plan = save(admin, make_user(DEPO, is_active=False), [PREP_CHANGE], dry_run=True)
    (warning,) = [item for item in plan.warnings if item.code == "user_inactive"]
    assert warning.text == "Kullanıcı pasif; değişiklik etkinleştirilince geçerli olur."


def test_warning_sensitive_without_otp(admin, make_user):
    depo = make_user(DEPO)
    prices = OverrideSpec("sensitive.prices", "view", GRANT)

    assert "sensitive_without_otp" in codes(save(admin, depo, [prices], dry_run=True))

    TOTPDevice.objects.create(user=depo, secret="x", confirmed_at=timezone.now())
    assert "sensitive_without_otp" not in codes(save(admin, depo, [prices], dry_run=True))


def test_warning_sensitive_without_otp_covers_kvkk_sections(admin, make_user):
    planlama = make_user(PLANLAMA)
    spec = OverrideSpec("personnel.cards", "view", GRANT)
    plan = save(admin, planlama, [spec], roles=[PLANLAMA, YONETIM], dry_run=True)
    assert "sensitive_without_otp" in codes(plan)


def test_warning_open_records_closed_lists_effects(admin, make_user):
    depo = make_user(DEPO)
    plan = save(admin, depo, [OverrideSpec("inventory.open_records", "read", REVOKE)], dry_run=True)
    (warning,) = [item for item in plan.warnings if item.code == "open_records_closed"]
    module = access.module("inventory").label
    assert warning.text == (
        f"{module} kayıtları bu kişi için kapanıyor. Okumaya devam ettiği bölümler: Mal kabul, "
        "Sayım düzeltme. Etkilenebilecek başka ekranlar: Lot sayfasındaki, satın alma sipariş "
        "sayfasındaki, izlenebilirlikteki ve cari ekstresindeki mal kabul bağlantıları düz metin "
        "olur."
    )


def test_warning_dependent_dropped(admin, make_user):
    manager = make_user(YONETIM)
    plan = save(admin, manager, [OverrideSpec("sensitive.prices", "view", REVOKE)], dry_run=True)
    (warning,) = [item for item in plan.warnings if item.code == "dependent_dropped"]
    assert warning.text.startswith("“Fiyatları görür” kaldırıldığı için şunlar da düşer: ")
    assert "Maliyetleri görür" in warning.text
    assert coverage.requirement_label(("costing.lot_costs", "view")) in warning.text
    assert "Fiyatları görür:" not in warning.text


def test_warning_override_ineffective(admin, make_user):
    depo = make_user(DEPO)
    item = row(depo, "masterdata.cards", "view", GRANT)

    plan = save(admin, depo, [OverrideSpec.of(item)], roles=[DEPO, PLANLAMA], dry_run=True)

    assert "override_ineffective" in codes(plan)
    assert plan.keep == (item,)


def test_warnings_when_target_becomes_admin_are_limited(admin, make_user):
    depo = make_user(DEPO, is_active=False)
    plan = save(admin, depo, [], roles=[ADMIN], dry_run=True)
    assert codes(plan) == ["admin_granted", "user_inactive"]
    assert plan.warnings[0].text.endswith("işlemi yapar.")


# --- denetim kaydı ve olaylar -------------------------------------------------------------------


def test_single_audit_row_with_roles_and_access(admin, make_user):
    depo = make_user(DEPO)
    old = row(depo, "masterdata.cards", "view", GRANT)
    logs = user_logs(depo).count()

    save(admin, depo, [PREP_CHANGE], roles=[DEPO, PLANLAMA])

    assert user_logs(depo).count() == logs + 1
    log = user_logs(depo).last()
    new = AccessOverride.objects.get(user=depo, ended_at__isnull=True)
    assert log.actor == admin and log.note == NOTE and log.action == AuditLog.Action.UPDATE
    assert log.changes == {
        "roles": [[DEPO], [DEPO, PLANLAMA]],
        "access": [
            [{"id": old.pk, "key": "masterdata.cards", "level": "view", "effect": GRANT}],
            [{"id": new.pk, "key": "production.prep", "level": "change", "effect": REVOKE}],
        ],
    }


def test_audit_access_rows_carry_ids(admin, make_user):
    depo = make_user(DEPO)
    kept = row(depo, "masterdata.cards", "view", GRANT)

    save(admin, depo, [OverrideSpec.of(kept), PREP_CHANGE])

    before, after = user_logs(depo).last().changes["access"]
    assert [item["id"] for item in before] == [kept.pk]
    assert {item["id"] for item in after} == set(
        active_overrides().filter(user=depo).values_list("pk", flat=True)
    )


def test_roles_only_save_still_records_access_key(admin, make_user):
    depo = make_user(DEPO)
    save(admin, depo, roles=[DEPO, PLANLAMA])
    assert user_logs(depo).last().changes == {
        "roles": [[DEPO], [DEPO, PLANLAMA]],
        "access": [[], []],
    }


def test_roles_only_save_hides_note_from_yonetim(admin, make_user):
    from apps.core import audit_filter

    depo = make_user(DEPO)
    manager = make_user(YONETIM)
    save(admin, depo, roles=[DEPO, PLANLAMA], note="Gizli gerekçe metni")
    log = user_logs(depo).last()

    view = audit_filter.view_for(manager)
    assert view.note_hidden is not None and view.hidden is not None
    rows = AuditLog.objects.filter(pk=log.pk)
    assert rows.filter(view.note_hidden).exists()  # gerekçe yönetime görünmez
    assert not rows.filter(view.hidden).exists()  # rol değişikliği listelenir
    assert audit_filter.view_for(admin).note_hidden is None


def test_save_publishes_access_changed_and_updated_after_commit(
    admin, make_user, published, django_capture_on_commit_callbacks
):
    depo = make_user(DEPO)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        save(admin, depo, [PREP_CHANGE])
        assert published == []

    for callback in callbacks:
        callback()
    assert published == [
        ("access.changed", {"user_id": depo.pk}),
        ("access.updated", {"user_id": depo.pk}),
    ]


def test_rolled_back_save_publishes_nothing(
    admin, make_user, published, django_capture_on_commit_callbacks
):
    depo = make_user(DEPO)
    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(RuntimeError),
        transaction.atomic(),
    ):
        save(admin, depo, [PREP_CHANGE])
        raise RuntimeError("geri al")
    assert published == []
    assert not AccessOverride.objects.exists()


def test_preview_matches_compute_access():
    specs_ = [PREP_CHANGE, OverrideSpec("masterdata.cards", "view", GRANT)]
    assert user_access.preview_access([DEPO], specs_) == compute_access(
        [DEPO], grants=[("masterdata.cards", "view")], revokes=[("production.prep", "change")]
    )
    assert user_access.default_access([DEPO]) == compute_access([DEPO])
