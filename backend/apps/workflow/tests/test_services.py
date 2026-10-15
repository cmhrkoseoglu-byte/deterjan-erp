from unittest import mock

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.core.tasks import publish_daily_check
from apps.workflow import services
from apps.workflow.models import Comment, Notification, Task
from apps.workflow.realtime import user_group
from apps.workflow.state import task_states
from apps.workflow.tests.factories import WidgetFactory

pytestmark = pytest.mark.django_db


def related_to(obj):
    return ContentType.objects.get_for_model(obj), obj.pk, str(obj)


@pytest.fixture
def role_task(make_user):
    make_user("depo")  # rolün en az bir üyesi olsun

    def _make(role="depo", **kwargs):
        return services.create_task(None, title="Malzeme hazırla", role=role, **kwargs)

    return _make


@pytest.fixture
def published():
    received: list[events.Event] = []
    events.subscribe("task.*")(received.append)
    return received


# --- Görev durum makinesi -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "final"),
    [
        (["claim", "complete"], "DONE"),
        (["complete"], "DONE"),
        (["cancel"], "CANCELLED"),
        (["claim", "cancel"], "CANCELLED"),
    ],
)
def test_allowed_task_transitions(
    make_user, role_task, path, final, published, django_capture_on_commit_callbacks
):
    user = make_user("depo")
    task = role_task()
    with django_capture_on_commit_callbacks(execute=True):
        for step in path:
            if step == "claim":
                services.claim_task(user, task)
            elif step == "complete":
                services.complete_task(user, task, note="Bitti")
            else:
                services.cancel_task(user, task, reason="Gerek kalmadı")

    task.refresh_from_db()
    assert task.status == final
    assert [e.name for e in published][-1] == f"task.{final.lower()}"
    logs = AuditLog.objects.filter(object_id=task.pk, content_type__model="task")
    assert logs.filter(action__in=["status_change", "cancel"]).count() == len(path)


@pytest.mark.parametrize("terminal", ["DONE", "CANCELLED"])
def test_closed_task_cannot_change(make_user, role_task, terminal):
    user = make_user("depo")
    task = role_task()
    if terminal == "DONE":
        services.complete_task(user, task)
    else:
        services.cancel_task(user, task, reason="İptal")

    with pytest.raises(BusinessRuleError) as exc:
        services.claim_task(user, task)
    assert exc.value.code == "invalid_transition"
    with pytest.raises(BusinessRuleError):
        services.complete_task(user, task)


def test_state_machine_table():
    assert task_states.allowed_transitions("OPEN") == ["CANCELLED", "DONE", "IN_PROGRESS"]
    assert task_states.allowed_transitions("IN_PROGRESS") == ["CANCELLED", "DONE"]
    assert not task_states.can_transition("IN_PROGRESS", "OPEN")


# --- Görev oluşturma, üstlenme, tamamlama -------------------------------------------------------


def test_create_task_requires_assignee():
    with pytest.raises(BusinessRuleError) as exc:
        services.create_task(None, title="Sahipsiz")
    assert exc.value.code == "task_assignee_required"


def test_create_task_for_user_notifies_that_user(make_user):
    user = make_user("planlama")
    actor = make_user("yonetim")

    task = services.create_task(
        actor, title="Raporu incele", user=user, priority=Task.Priority.URGENT
    )

    assert task.assigned_user == user
    assert task.created_by == actor
    notification = Notification.objects.get(recipient=user)
    assert notification.task == task
    assert notification.title == "Yeni görev: Raporu incele"
    assert AuditLog.objects.filter(action="create", object_id=task.pk).exists()


def test_claim_sets_claimer_and_blocks_second_claim(make_user, role_task):
    first, second = make_user("depo"), make_user("depo")
    task = role_task()

    services.claim_task(first, task)

    task.refresh_from_db()
    assert task.status == Task.Status.IN_PROGRESS
    assert task.claimed_by == first
    assert task.claimed_at is not None
    with pytest.raises(BusinessRuleError) as exc:
        services.claim_task(second, task)
    assert exc.value.code == "task_already_claimed"


def test_user_outside_role_cannot_claim_or_complete(make_user, role_task):
    task = role_task()
    outsider = make_user("uretim")

    with pytest.raises(PermissionDenied):
        services.claim_task(outsider, task)
    with pytest.raises(PermissionDenied):
        services.complete_task(outsider, task)


def test_admin_can_complete_any_task(make_user, role_task):
    admin = make_user("admin")
    task = role_task()

    services.complete_task(admin, task, note="Yönetici kapattı")

    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    assert task.completed_by == admin
    assert task.completion_note == "Yönetici kapattı"


def test_cancel_requires_reason(role_task):
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_task(None, role_task(), reason="  ")
    assert exc.value.code == "cancel_reason_required"


def test_auto_close_only_touches_matching_rule_and_record(role_task):
    record, other = WidgetFactory(), WidgetFactory()
    target = role_task(related=related_to(record), rule_code="material_prep")
    other_rule = role_task(related=related_to(record), rule_code="something_else")
    other_record = role_task(related=related_to(other), rule_code="material_prep")

    closed = services.auto_close_tasks(
        None, related=related_to(record), rule_codes=["material_prep"], event_name="x.y"
    )

    assert closed == [target]
    for task, status in ((target, "DONE"), (other_rule, "OPEN"), (other_record, "OPEN")):
        task.refresh_from_db()
        assert task.status == status


# --- Bildirim -----------------------------------------------------------------------------------


def test_notify_writes_one_record_per_active_recipient(make_user):
    a, b = make_user("depo"), make_user("depo")
    inactive = make_user("depo", is_active=False)

    created = services.notify_roles(["depo"], title="Duyuru", level="WARNING")

    assert {n.recipient for n in created} == {a, b}
    assert not Notification.objects.filter(recipient=inactive).exists()


def test_notify_rejects_unknown_level(make_user):
    with pytest.raises(ValueError):
        services.notify([make_user()], title="x", level="LOUD")


def test_mark_read_only_touches_own_notifications(make_user):
    me, other = make_user(), make_user()
    mine = services.notify([me, me], title="Bir")  # tekrar eden alıcı tek kayıt
    services.notify([me], title="İki")
    theirs = services.notify([other], title="Onların")[0]

    assert len(mine) == 1
    assert services.mark_notifications_read(me, [mine[0].pk, theirs.pk]) == 1
    assert Notification.objects.filter(recipient=me, read_at__isnull=True).count() == 1
    assert services.mark_notifications_read(me) == 1
    theirs.refresh_from_db()
    assert theirs.read_at is None


def test_new_notification_is_pushed_to_users_websocket_group(
    make_user, django_capture_on_commit_callbacks
):
    user = make_user()
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(user_group(user.pk), channel)

    with django_capture_on_commit_callbacks(execute=True):
        notification = services.notify([user], title="Merhaba", level="WARNING")[0]

    message = async_to_sync(layer.receive)(channel)
    assert message["type"] == "workflow.message"
    assert message["data"] == {
        "type": "notification.created",
        "id": notification.pk,
        "title": "Merhaba",
        "body": "",
        "level": "WARNING",
        "task_id": None,
    }


def test_new_role_task_is_pushed_to_role_members(make_user, django_capture_on_commit_callbacks):
    member = make_user("depo")
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(user_group(member.pk), channel)

    with django_capture_on_commit_callbacks(execute=True):
        task = services.create_task(None, title="Say", role="depo")

    received = [async_to_sync(layer.receive)(channel)["data"] for _ in range(2)]
    assert {"type": "task.changed", "id": task.pk, "status": "OPEN"} in received
    assert any(m["type"] == "notification.created" for m in received)


@pytest.mark.parametrize("failure", ["layer", "send"])
def test_push_failure_does_not_break_notification(
    make_user, django_capture_on_commit_callbacks, caplog, failure
):
    user = make_user()
    layer = mock.Mock()
    layer.group_send = mock.AsyncMock()
    layer.group_send.side_effect = RuntimeError("bağlantı yok")
    patch = (
        mock.patch(
            "apps.workflow.realtime.get_channel_layer", side_effect=RuntimeError("redis yok")
        )
        if failure == "layer"
        else mock.patch("apps.workflow.realtime.get_channel_layer", return_value=layer)
    )
    with patch, django_capture_on_commit_callbacks(execute=True):
        services.notify([user], title="x")

    assert "WebSocket mesajı gönderilemedi" in caplog.text
    assert Notification.objects.filter(recipient=user).count() == 1


# --- Yorum --------------------------------------------------------------------------------------


def test_add_comment_with_mentions_notifies_mentioned_users(make_user):
    author = make_user("depo", username="ayse", full_name="Ayşe Yılmaz")
    mehmet = make_user("laboratuvar", username="mehmet.k")
    make_user("planlama", username="zeynep")
    record = WidgetFactory(name="Lot H-1")

    comment = services.add_comment(
        author,
        content_type="core_testapp.widget",
        object_id=record.pk,
        body="@Mehmet.K bakar mısın? @ayse @yok. e-posta: x@zeynep",
    )

    assert comment.related_object == record
    assert set(comment.mentions.all()) == {author, mehmet}  # "@yok" ve "x@zeynep" bahsetme değil
    notification = Notification.objects.get(recipient=mehmet)
    assert notification.title == "Ayşe Yılmaz sizden bahsetti: Lot H-1"
    assert notification.related_object_id == record.pk
    assert notification.event_name == "comment.mention"
    assert not Notification.objects.filter(recipient=author).exists()  # kendinden bahsetme
    assert AuditLog.objects.filter(action="create", object_id=comment.pk).exists()


@pytest.mark.parametrize(
    ("content_type", "code"),
    [
        ("core.user", "invalid_record_type"),
        ("core.auditlog", "invalid_record_type"),
        ("auth.group", "invalid_record_type"),
        ("workflow.notification", "invalid_record_type"),
        ("yok.boyle", "invalid_record_type"),
        ("core_testapp", "invalid_record_type"),
    ],
)
def test_comment_rejects_non_commentable_types(make_user, content_type, code):
    with pytest.raises(BusinessRuleError) as exc:
        services.add_comment(make_user(), content_type=content_type, object_id=1, body="x")
    assert exc.value.code == code


def test_comment_rejects_missing_record_and_empty_body(make_user):
    user = make_user()
    with pytest.raises(BusinessRuleError) as exc:
        services.add_comment(user, content_type="core_testapp.widget", object_id=999999, body="x")
    assert exc.value.code == "record_not_found"
    record = WidgetFactory()
    with pytest.raises(BusinessRuleError) as exc:
        services.add_comment(
            user, content_type="core_testapp.widget", object_id=record.pk, body="  "
        )
    assert exc.value.code == "comment_empty"


def test_edit_comment_audits_old_text_and_notifies_only_new_mentions(make_user):
    author = make_user(username="ayse")
    old, new = make_user(username="ali"), make_user(username="veli")
    record = WidgetFactory()
    comment = services.add_comment(
        author, content_type="core_testapp.widget", object_id=record.pk, body="@ali ilk"
    )

    services.edit_comment(author, comment, body="@ali @veli düzeltildi")

    comment.refresh_from_db()
    assert comment.edited_at is not None
    log = AuditLog.objects.get(action="update", object_id=comment.pk)
    assert log.changes["body"] == ["@ali ilk", "@ali @veli düzeltildi"]
    assert log.note == "Yorum düzenlendi"
    assert Notification.objects.filter(recipient=old).count() == 1
    assert Notification.objects.filter(recipient=new).count() == 1


def test_only_author_can_edit_comment(make_user):
    author, other = make_user(), make_user()
    record = WidgetFactory()
    comment = services.add_comment(
        author, content_type="core_testapp.widget", object_id=record.pk, body="x"
    )

    with pytest.raises(PermissionDenied):
        services.edit_comment(other, comment, body="değiştir")


def test_comment_cannot_be_deleted(make_user):
    record = WidgetFactory()
    comment = services.add_comment(
        make_user(), content_type="core_testapp.widget", object_id=record.pk, body="x"
    )

    with pytest.raises(ValueError):
        comment.delete()
    assert Comment.objects.filter(pk=comment.pk).exists()


# --- 07:00 günlük kontrol -----------------------------------------------------------------------


def test_daily_check_task_publishes_event(django_capture_on_commit_callbacks):
    received: list[events.Event] = []
    events.subscribe(ev.DAILY_CHECK)(received.append)

    with django_capture_on_commit_callbacks(execute=True):
        publish_daily_check()

    assert len(received) == 1
    assert "date" in received[0].payload


def test_daily_check_is_scheduled_at_seven(settings):
    entry = settings.CELERY_BEAT_SCHEDULE["daily-check-0700"]
    assert entry["task"] == "core.publish_daily_check"
    assert entry["schedule"].hour == {7}
    assert entry["schedule"].minute == {0}
