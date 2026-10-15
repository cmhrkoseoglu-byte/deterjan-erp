import pytest
from django.db import transaction

from apps.core import events
from apps.core.tests.testapp.models import Widget

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def received():
    calls: list[events.Event] = []

    @events.subscribe("widget.*")
    def handler(event: events.Event) -> None:
        calls.append(event)

    return calls


def test_handler_called_after_commit(received, make_user):
    actor = make_user()
    with transaction.atomic():
        events.publish("widget.created", {"id": 1}, actor)
        assert received == []  # commit öncesi çağrılmaz

    assert len(received) == 1
    assert received[0].name == "widget.created"
    assert received[0].payload == {"id": 1}
    assert received[0].actor_id == actor.pk


def test_handler_not_called_when_transaction_rolls_back(received):
    with pytest.raises(RuntimeError), transaction.atomic():
        events.publish("widget.created", {"id": 1})
        raise RuntimeError("geri al")

    assert received == []


def test_rolled_back_savepoint_drops_its_events(received):
    with transaction.atomic():
        events.publish("widget.kept", {})
        try:
            with transaction.atomic():
                events.publish("widget.dropped", {})
                raise RuntimeError
        except RuntimeError:
            pass

    assert [e.name for e in received] == ["widget.kept"]


def test_publish_outside_transaction_dispatches_immediately(received):
    events.publish("widget.created", {})

    assert len(received) == 1


def test_wildcard_and_exact_subscriptions():
    names: list[str] = []
    events.subscribe("production_order.*")(lambda e: names.append(f"wild:{e.name}"))
    events.subscribe("production_order.approved")(lambda e: names.append(f"exact:{e.name}"))

    events.publish("production_order.approved", {})
    events.publish("production_order.cancelled", {})
    events.publish("batch.approved", {})

    assert names == [
        "wild:production_order.approved",
        "exact:production_order.approved",
        "wild:production_order.cancelled",
    ]


def test_handler_error_is_logged_and_does_not_break_others(caplog):
    calls: list[str] = []

    @events.subscribe("widget.created")
    def broken(event: events.Event) -> None:
        Widget.objects.create(name="yarım kalan")
        raise ValueError("bozuk handler")

    @events.subscribe("widget.created")
    def healthy(event: events.Event) -> None:
        calls.append(event.name)

    with transaction.atomic():
        Widget.objects.create(name="ana işlem")
        events.publish("widget.created", {})

    assert calls == ["widget.created"]
    assert "bozuk handler" in caplog.text
    # Ana işlem commit edildi; hatalı handler'ın yazdığı geri alındı.
    assert list(Widget.objects.values_list("name", flat=True)) == ["ana işlem"]


def test_subscribe_same_handler_twice_registers_once(received):
    handler = events._subscribers["widget.*"][0]
    events.subscribe("widget.*")(handler)

    events.publish("widget.created", {})

    assert len(received) == 1
