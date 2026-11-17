"""Hazırlık listesinde "Her görevi alabilecek biri var" maddesi (docs/plan/kisi-yetkileri.md
§8 madde 9): her iş akışı kuralının rolünde kuralın yetkisi olan etkin biri. Kapsanmayan görev
MISSING, yalnız bildirim kapsanmıyorsa WARNING; liste bilgi amaçlıdır, hiçbir işlemi engellemez."""

import pytest

from apps.core import access
from apps.core.access import NOTIFY, TASK, VIEW
from apps.core.models import AccessOverride
from apps.core.roles import ALL_ROLES, DEPO, PLANLAMA
from apps.golive import selectors

pytestmark = pytest.mark.django_db

READINESS = ("golive.readiness", VIEW)


def coverage_check() -> dict:
    return {check["code"]: check for check in selectors.readiness()}["task_coverage"]


def test_every_role_filled_covers_every_rule(make_user):
    for role in ALL_ROLES:
        make_user(role)
    check = coverage_check()
    assert check["status"] == "OK"
    assert check["group"] == "Kullanıcılar"
    assert check["title"] == "Her görevi alabilecek biri var"
    assert check["items"] == [] and check["count"] == 0


def test_empty_role_with_tasks_is_missing(make_user):
    make_user(DEPO)
    check = coverage_check()
    assert check["status"] == "MISSING"
    assert any(item.startswith("Planlama rolünde") for item in check["items"])
    assert not any(item.startswith("Depo rolünde") for item in check["items"])


def test_uncovered_notification_only_is_warning_and_override_counts(make_user):
    with access.temporary_catalog():
        access._RULES.clear()
        access.register_rule("deneme_gorev", TASK, (PLANLAMA,), None)
        access.register_rule("deneme_bildirim", NOTIFY, (DEPO,), READINESS)
        make_user(PLANLAMA)
        depo = make_user(DEPO)
        assert coverage_check()["status"] == "OK"

        AccessOverride.objects.create(
            user=depo, key=READINESS[0], level=VIEW, effect="revoke", note="deneme"
        )
        check = coverage_check()
        assert check["status"] == "WARNING"
        assert check["count"] == 1
        (item,) = check["items"]
        assert "Depo rolünde" in item and "1 bildirim kimseye gitmez" in item
