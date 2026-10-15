import pytest

from apps.core.models import AuditLog
from apps.core.roles import ADMIN, DEPO, PLANLAMA

pytestmark = pytest.mark.django_db


def test_has_role_checks_assigned_roles(make_user):
    user = make_user(DEPO)

    assert user.has_role(DEPO)
    assert user.has_role(PLANLAMA, DEPO)
    assert not user.has_role(PLANLAMA)
    assert user.roles == [DEPO]


def test_roles_are_sorted(make_user):
    user = make_user(PLANLAMA, DEPO)

    assert user.roles == [DEPO, PLANLAMA]


def test_is_admin_for_admin_role_and_superuser(make_user):
    assert make_user(ADMIN).is_admin
    assert make_user(is_superuser=True).is_admin
    assert not make_user(DEPO).is_admin


def test_admin_role_does_not_imply_other_roles(make_user):
    # has_role yalnızca atanmış rollere bakar (görev ataması vb. için); yetki HasRole'dadır.
    assert not make_user(ADMIN).has_role(DEPO)


def test_str_prefers_full_name(make_user):
    assert str(make_user(full_name="Ayşe Yılmaz")) == "Ayşe Yılmaz"
    assert str(make_user(full_name="", username="ayse")) == "ayse"


def test_audit_log_cannot_be_modified_or_deleted(make_user):
    entry = AuditLog.objects.create(action=AuditLog.Action.CUSTOM, note="ilk")

    entry.note = "değişti"
    with pytest.raises(ValueError):
        entry.save()
    with pytest.raises(ValueError):
        entry.delete()
    entry.refresh_from_db()
    assert entry.note == "ilk"
