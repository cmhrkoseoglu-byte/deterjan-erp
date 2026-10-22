import pytest
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command

from apps.core.models import AuditLog, User
from apps.core.roles import ALL_ROLES

pytestmark = pytest.mark.django_db


def test_seed_roles_creates_nine_roles_idempotently():
    call_command("seed_roles")
    call_command("seed_roles")

    assert sorted(Group.objects.values_list("name", flat=True)) == sorted(ALL_ROLES)
    assert len(ALL_ROLES) == 9


def test_create_demo_users_only_in_debug(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("create_demo_users")
    assert not User.objects.exists()


def test_create_demo_users_allowed_in_training_mode(settings):
    settings.DEBUG = False
    settings.TRAINING_MODE = True
    settings.DEMO_USER_PASSWORD = "Egitim.2026x"

    call_command("create_demo_users")

    assert User.objects.count() == len(ALL_ROLES)


def test_seed_demo_refused_on_live_server(settings):
    settings.DEBUG = False
    settings.TRAINING_MODE = False

    with pytest.raises(CommandError, match="eğitim ortamında"):
        call_command("seed_demo")
    assert not User.objects.exists()


def test_create_demo_users_requires_password(settings):
    settings.DEBUG = True
    settings.DEMO_USER_PASSWORD = ""

    with pytest.raises(CommandError):
        call_command("create_demo_users")


def test_create_demo_users_one_per_role(settings):
    settings.DEBUG = True
    settings.DEMO_USER_PASSWORD = "Demo.12345"

    call_command("create_demo_users")
    call_command("create_demo_users")  # tekrar çalıştırmak güvenli

    assert User.objects.count() == len(ALL_ROLES)
    for role in ALL_ROLES:
        user = User.objects.get(username=role)
        assert user.roles == [role]
        assert user.check_password("Demo.12345")
    admin = User.objects.get(username="admin")
    assert admin.is_staff and admin.is_superuser
    assert not User.objects.get(username="depo").is_staff
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE).count() == len(ALL_ROLES)
    # Rol atamaları da denetlenir (yalnızca ilk çalıştırmada; ikincide değişiklik yok).
    role_logs = AuditLog.objects.filter(changes__has_key="roles")
    assert role_logs.count() == len(ALL_ROLES)


def test_create_first_admin_once(monkeypatch):
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "Ilk.Yonetici.2026")

    call_command("create_first_admin")
    user = User.objects.get(username="yonetici")
    assert user.is_superuser and user.roles == ["admin"]
    assert user.check_password("Ilk.Yonetici.2026")
    assert AuditLog.objects.filter(note="create_first_admin").exists()

    # Tekrar çalıştırmak şifreyi değiştirmez, ikinci hesap açmaz.
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "Baska.Sifre.2026")
    call_command("create_first_admin", "--username", "ikinci")
    assert User.objects.count() == 1
    assert User.objects.get(username="yonetici").check_password("Ilk.Yonetici.2026")


def test_create_first_admin_rejects_weak_password(monkeypatch):
    monkeypatch.setenv("FIRST_ADMIN_PASSWORD", "12345")

    with pytest.raises(CommandError, match="FIRST_ADMIN_PASSWORD"):
        call_command("create_first_admin")
    assert not User.objects.exists()
