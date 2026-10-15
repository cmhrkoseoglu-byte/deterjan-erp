import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.workflow import services
from apps.workflow.models import Notification, Task
from apps.workflow.tests.factories import WidgetFactory

pytestmark = pytest.mark.django_db

BASE = "/api/v1/workflow"


def client_as(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# --- Yetki: giriş yapmamış 401 ------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/tasks/",
        f"{BASE}/notifications/",
        f"{BASE}/notifications/unread-count/",
        f"{BASE}/comments/?content_type=core_testapp.widget&object_id=1",
        f"{BASE}/record-history/?content_type=core_testapp.widget&object_id=1",
        f"{BASE}/mentionable-users/",
    ],
)
def test_anonymous_gets_401(api_client, url):
    response = api_client.get(url)
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


# --- Görevler -----------------------------------------------------------------------------------


@pytest.fixture
def tasks(make_user):
    depo_task = services.create_task(None, title="Depo işi", role="depo")
    lab_task = services.create_task(
        None, title="Lab işi", role="laboratuvar", priority=Task.Priority.URGENT
    )
    return depo_task, lab_task


def titles(response):
    return [t["title"] for t in response.json()["results"]]


def test_my_tasks_shows_only_my_roles(make_user, tasks):
    depo = make_user("depo")

    response = client_as(depo).get(f"{BASE}/tasks/", {"mine": "true", "open": "true"})

    assert response.status_code == 200
    assert titles(response) == ["Depo işi"]
    item = response.json()["results"][0]
    assert item["assigned_role"] == "depo"
    assert item["status_label"] == "Açık"
    assert item["can_act"] is True


def test_other_roles_cannot_see_or_act_on_foreign_task(make_user, tasks):
    depo_task, lab_task = tasks
    depo = make_user("depo")
    client = client_as(depo)

    assert titles(client.get(f"{BASE}/tasks/")) == ["Depo işi"]
    assert client.get(f"{BASE}/tasks/{lab_task.pk}/").status_code == 404
    assert client.post(f"{BASE}/tasks/{lab_task.pk}/claim/").status_code == 404


@pytest.mark.parametrize("role", ["yonetim", "admin"])
def test_management_sees_all_tasks_ordered_by_priority(make_user, tasks, role):
    response = client_as(make_user(role)).get(f"{BASE}/tasks/")

    assert titles(response) == ["Lab işi", "Depo işi"]


def test_management_sees_all_but_cannot_act_on_other_roles_task(make_user, tasks):
    depo_task, _ = tasks
    client = client_as(make_user("yonetim"))

    item = client.get(f"{BASE}/tasks/{depo_task.pk}/").json()
    assert item["can_act"] is False
    response = client.post(f"{BASE}/tasks/{depo_task.pk}/complete/")
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_claim_and_complete_endpoints(make_user, tasks):
    depo_task, _ = tasks
    depo = make_user("depo")
    client = client_as(depo)

    claimed = client.post(f"{BASE}/tasks/{depo_task.pk}/claim/")
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "IN_PROGRESS"
    assert claimed.json()["claimed_by"]["id"] == depo.pk

    again = client_as(make_user("depo")).post(f"{BASE}/tasks/{depo_task.pk}/claim/")
    assert again.status_code == 400
    assert again.json()["code"] == "task_already_claimed"

    done = client.post(
        f"{BASE}/tasks/{depo_task.pk}/complete/", {"note": "Hazırlandı"}, format="json"
    )
    assert done.status_code == 200
    assert done.json()["status"] == "DONE"
    assert done.json()["completion_note"] == "Hazırlandı"
    assert done.json()["can_act"] is False

    closed = client.post(f"{BASE}/tasks/{depo_task.pk}/complete/")
    assert closed.status_code == 400
    assert closed.json()["code"] == "invalid_transition"


def test_task_status_cannot_be_patched(make_user, tasks):
    depo_task, _ = tasks
    response = client_as(make_user("depo")).patch(
        f"{BASE}/tasks/{depo_task.pk}/", {"status": "DONE"}, format="json"
    )

    assert response.status_code == 405
    depo_task.refresh_from_db()
    assert depo_task.status == Task.Status.OPEN


def test_task_filters_by_related_record(make_user):
    record = WidgetFactory()
    ct = ContentType.objects.get_for_model(record)
    services.create_task(None, title="Bağlı", role="depo", related=(ct, record.pk, "Kayıt"))
    services.create_task(None, title="Bağsız", role="depo")

    response = client_as(make_user("depo")).get(
        f"{BASE}/tasks/", {"content_type": "core_testapp.widget", "object_id": record.pk}
    )

    assert titles(response) == ["Bağlı"]
    assert response.json()["results"][0]["related"] == {
        "model": "core_testapp.widget",
        "id": record.pk,
        "repr": "Kayıt",
    }


# --- Bildirimler --------------------------------------------------------------------------------


def test_notifications_list_count_and_mark_read(make_user):
    me, other = make_user(), make_user()
    first = services.notify([me], title="Bir")[0]
    services.notify([me], title="İki", level="WARNING")
    foreign = services.notify([other], title="Başkası")[0]
    client = client_as(me)

    listed = client.get(f"{BASE}/notifications/")
    assert [n["title"] for n in listed.json()["results"]] == ["İki", "Bir"]
    assert client.get(f"{BASE}/notifications/unread-count/").json() == {"count": 2}
    assert client.get(f"{BASE}/notifications/{foreign.pk}/").status_code == 404

    marked = client.post(
        f"{BASE}/notifications/mark-read/", {"ids": [first.pk, foreign.pk]}, format="json"
    )
    assert marked.json() == {"updated": 1}
    assert client.get(f"{BASE}/notifications/unread-count/").json() == {"count": 1}
    unread = client.get(f"{BASE}/notifications/", {"unread": "true"})
    assert [n["title"] for n in unread.json()["results"]] == ["İki"]

    assert client.post(f"{BASE}/notifications/mark-read/", {"all": True}, format="json").json() == {
        "updated": 1
    }
    foreign.refresh_from_db()
    assert foreign.read_at is None


def test_mark_read_requires_ids_or_all(make_user):
    response = client_as(make_user()).post(f"{BASE}/notifications/mark-read/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


def test_notifications_are_read_only(make_user):
    notification = services.notify([user := make_user()], title="x")[0]
    client = client_as(user)

    assert client.delete(f"{BASE}/notifications/{notification.pk}/").status_code == 405
    assert client.post(f"{BASE}/notifications/", {"title": "x"}, format="json").status_code == 405


# --- Yorumlar -----------------------------------------------------------------------------------


def test_comment_create_list_and_edit(make_user):
    author = make_user("depo", username="ayse")
    mentioned = make_user("laboratuvar", username="mehmet")
    record = WidgetFactory()
    client = client_as(author)

    created = client.post(
        f"{BASE}/comments/",
        {
            "content_type": "core_testapp.widget",
            "object_id": record.pk,
            "body": "@mehmet bakar mısın?",
        },
        format="json",
    )
    assert created.status_code == 201
    body = created.json()
    assert body["author"]["username"] == "ayse"
    assert [m["username"] for m in body["mentions"]] == ["mehmet"]
    assert body["can_edit"] is True
    assert Notification.objects.filter(recipient=mentioned).count() == 1

    listed = client_as(mentioned).get(
        f"{BASE}/comments/", {"content_type": "core_testapp.widget", "object_id": record.pk}
    )
    assert listed.status_code == 200
    assert [c["body"] for c in listed.json()["results"]] == ["@mehmet bakar mısın?"]
    assert listed.json()["results"][0]["can_edit"] is False

    edited = client.patch(f"{BASE}/comments/{body['id']}/", {"body": "Düzeltme"}, format="json")
    assert edited.status_code == 200
    assert edited.json()["edited_at"] is not None

    forbidden = client_as(mentioned).patch(
        f"{BASE}/comments/{body['id']}/", {"body": "x"}, format="json"
    )
    assert forbidden.status_code == 403
    assert client.delete(f"{BASE}/comments/{body['id']}/").status_code == 405


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, "validation_error"),
        ({"content_type": "core.user", "object_id": 1}, "invalid_record_type"),
        ({"content_type": "core_testapp.widget", "object_id": "abc"}, "validation_error"),
    ],
)
def test_comment_list_validates_record(make_user, params, code):
    response = client_as(make_user()).get(f"{BASE}/comments/", params)

    assert response.status_code == 400
    assert response.json()["code"] == code


def test_comment_on_missing_record_is_rejected(make_user):
    response = client_as(make_user()).post(
        f"{BASE}/comments/",
        {"content_type": "core_testapp.widget", "object_id": 99999, "body": "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "record_not_found"


def test_record_history_lists_audit_entries_for_that_record(make_user):
    user = make_user("depo")
    record, other = WidgetFactory(), WidgetFactory()
    ct = ContentType.objects.get_for_model(record)
    AuditLog.objects.create(action="create", content_type=ct, object_id=record.pk, object_repr="A")
    AuditLog.objects.create(action="create", content_type=ct, object_id=other.pk, object_repr="B")

    response = client_as(user).get(
        f"{BASE}/record-history/", {"content_type": "core_testapp.widget", "object_id": record.pk}
    )

    assert response.status_code == 200
    assert [e["object_repr"] for e in response.json()["results"]] == ["A"]


def test_mentionable_users_search(make_user):
    make_user(username="mehmet", full_name="Mehmet Kaya")
    make_user(username="ayse", full_name="Ayşe Kaya")
    make_user(username="pasif", is_active=False)

    response = client_as(make_user(username="ben")).get(
        f"{BASE}/mentionable-users/", {"search": "kaya"}
    )

    assert response.status_code == 200
    assert [u["username"] for u in response.json()] == ["ayse", "mehmet"]
    assert set(response.json()[0]) == {"id", "username", "full_name"}


# --- WebSocket ----------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_websocket_receives_new_notification(make_user):
    from config.asgi import application

    user = make_user("depo")
    session_client = Client()
    session_client.force_login(user)
    cookie = f"sessionid={session_client.cookies['sessionid'].value}"

    async def scenario():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=[
                (b"cookie", cookie.encode()),
                (b"origin", b"http://localhost"),
                (b"host", b"localhost"),
            ],
        )
        connected, _ = await communicator.connect()
        assert connected
        await communicator.send_json_to({"type": "ping"})
        assert await communicator.receive_json_from() == {"type": "pong"}
        await database_sync_to_async(services.create_task)(None, title="Sayım", role="depo")
        messages = [await communicator.receive_json_from(timeout=2) for _ in range(2)]
        await communicator.disconnect()
        return messages

    messages = async_to_sync(scenario)()
    types = {m["type"] for m in messages}
    assert types == {"task.changed", "notification.created"}


@pytest.mark.django_db(transaction=True)
def test_websocket_rejects_anonymous():
    from config.asgi import application

    async def scenario():
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=[(b"origin", b"http://localhost"), (b"host", b"localhost")],
        )
        connected, code = await communicator.connect()
        await communicator.disconnect()
        return connected, code

    connected, code = async_to_sync(scenario)()
    assert connected is False
    assert code == 4401
