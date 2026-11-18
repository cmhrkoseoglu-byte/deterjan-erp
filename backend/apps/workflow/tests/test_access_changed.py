"""`access.changed` olayı (docs/plan/kisi-yetkileri.md §8 madde 11): yetkisi değişen kişinin açık
sayfalarına WebSocket iletisi gider; bildirim ve denetim kaydı yazılmaz, olay kural tablosunda
değildir."""

import asyncio

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.core import event_names
from apps.core import services as core_services
from apps.core.models import AuditLog
from apps.core.roles import ADMIN, DEPO, PLANLAMA
from apps.workflow import rules
from apps.workflow.models import Notification, Task
from apps.workflow.realtime import user_group

pytestmark = pytest.mark.django_db


def test_access_changed_is_not_a_rule_event():
    assert event_names.ACCESS_CHANGED not in rules.all_event_names()


def test_role_change_pushes_access_changed_to_user_only(
    make_user, django_capture_on_commit_callbacks
):
    user = make_user(DEPO)
    other = make_user(DEPO)
    layer = get_channel_layer()
    mine = async_to_sync(layer.new_channel)()
    theirs = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(user_group(user.pk), mine)
    async_to_sync(layer.group_add)(user_group(other.pk), theirs)
    audit_before = AuditLog.objects.count()

    with django_capture_on_commit_callbacks(execute=True):
        core_services.set_user_roles(user, [PLANLAMA], None)

    message = async_to_sync(layer.receive)(mine)
    assert message == {"type": "workflow.message", "data": {"type": "access.changed"}}
    assert not Notification.objects.exists()
    assert not Task.objects.exists()
    # Yalnız rol değişikliğinin kendi kaydı.
    assert AuditLog.objects.count() == audit_before + 1

    with django_capture_on_commit_callbacks(execute=True):
        core_services.set_user_roles(other, [DEPO], None)  # değişmedi: ileti yok
    with pytest.raises(TimeoutError):  # kanal boş kalmalı
        async_to_sync(_receive_now)(layer, theirs)


async def _receive_now(layer, channel):
    return await asyncio.wait_for(layer.receive(channel), timeout=0.2)


# --- "Yetkileriniz güncellendi" (plan §5.10, §6.5, §8 madde 15) ---------------------------------


def test_access_updated_is_not_a_rule_event():
    assert event_names.ACCESS_UPDATED not in rules.all_event_names()
    assert not [rule for rule in rules.RULES if rule.event == event_names.ACCESS_UPDATED]


def _save_access(actor, user, **kwargs):
    from apps.core import user_access
    from apps.core.effective_access import active_overrides

    version = user_access.access_version(user, list(active_overrides().filter(user=user)))
    return core_services.set_user_access(actor, user, version=version, **kwargs)


def test_access_updated_notifies_target_only_without_note(
    make_user, django_capture_on_commit_callbacks
):
    from apps.core.user_access import OverrideSpec

    admin = make_user(ADMIN)
    depo = make_user(DEPO)
    note = "Gizli gerekçe: hazırlığı amir yapacak"

    with django_capture_on_commit_callbacks(execute=True):
        _save_access(
            admin,
            depo,
            overrides=[OverrideSpec("production.prep", "change", "revoke")],
            note=note,
        )

    (notification,) = Notification.objects.all()
    assert notification.recipient == depo
    assert notification.title == "Yetkileriniz güncellendi"
    assert notification.body == (
        "Rolleriniz ya da yetkileriniz değişti. Güncel hâlini Yetkilerim sayfasında görebilirsiniz."
    )
    assert notification.event_name == "access.updated" and notification.rule_code == ""
    assert note not in notification.body and "Gizli" not in notification.title
    assert notification.related_object_id is None
    assert not Task.objects.exists()


def test_access_updated_skips_actor_inactive_and_unchanged(
    make_user, django_capture_on_commit_callbacks
):
    admin = make_user(ADMIN)
    with django_capture_on_commit_callbacks(execute=True):
        _save_access(admin, admin, overrides=[], roles=[ADMIN, PLANLAMA], note="Kendi rolüm")
        _save_access(
            admin,
            make_user(DEPO, is_active=False),
            overrides=[],
            roles=[PLANLAMA],
            note="Pasif kişi",
        )
        _save_access(admin, make_user(DEPO), overrides=[], roles=[DEPO], note="Değişiklik yok")
        # Kullanıcı açma ve yönetim komutları bildirim yazmaz (yalnız access.changed).
        core_services.set_user_roles(make_user(DEPO), [PLANLAMA], admin)
    assert not Notification.objects.exists()
