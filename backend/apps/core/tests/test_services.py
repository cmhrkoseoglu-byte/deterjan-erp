import threading
from decimal import Decimal

import pytest
from django.db import connection, transaction

from apps.core import events, services
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, DocumentSequence
from apps.core.tests.testapp.models import SampleDocument, Widget
from apps.core.tests.testapp.state import sample_document_states as machine

# --- next_document_number -------------------------------------------------------------------


@pytest.mark.django_db
def test_document_number_format_and_increment():
    assert services.next_document_number("UE", year=2026) == "UE-2026-00001"
    assert services.next_document_number("UE", year=2026) == "UE-2026-00002"
    assert services.next_document_number("SA", year=2026) == "SA-2026-00001"


@pytest.mark.django_db
def test_document_number_resets_each_year():
    services.next_document_number("UE", year=2026)

    assert services.next_document_number("UE", year=2027) == "UE-2027-00001"


@pytest.mark.django_db
def test_document_number_uses_istanbul_year(monkeypatch):
    import datetime

    from django.utils import timezone

    # UTC'de hâlâ 2026, İstanbul'da (UTC+3) 1 Ocak 2027 00:30.
    utc_now = datetime.datetime(2026, 12, 31, 21, 30, tzinfo=datetime.UTC)
    monkeypatch.setattr(timezone, "now", lambda: utc_now)

    assert services.next_document_number("UE") == "UE-2027-00001"


@pytest.mark.django_db
@pytest.mark.parametrize("prefix", ["", "ue", "U-E", "ABCDEFGHIJK", "1UE"])
def test_document_number_rejects_invalid_prefix(prefix):
    with pytest.raises(ValueError):
        services.next_document_number(prefix)


@pytest.mark.django_db
def test_document_number_rolled_back_with_transaction():
    with pytest.raises(RuntimeError), transaction.atomic():
        services.next_document_number("UE", year=2026)
        raise RuntimeError

    assert services.next_document_number("UE", year=2026) == "UE-2026-00001"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("existing_row", [False, True], ids=["new-sequence", "existing-sequence"])
def test_document_number_concurrent_calls_are_unique(existing_row):
    if existing_row:
        DocumentSequence.objects.create(prefix="UE", year=2026, last_number=7)
    workers = 20
    barrier = threading.Barrier(workers)
    numbers: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            barrier.wait()
            number = services.next_document_number("UE", year=2026)
            with lock:
                numbers.append(number)
        except BaseException as exc:  # pragma: no cover - hata ayıklama için
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    start = 8 if existing_row else 1
    assert sorted(numbers) == [f"UE-2026-{n:05d}" for n in range(start, start + workers)]
    assert DocumentSequence.objects.get(prefix="UE", year=2026).last_number == start + workers - 1


# --- save_with_audit ------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_with_audit_create_sets_users_and_logs(make_user):
    actor = make_user()
    widget = services.save_with_audit(Widget(name="Tank", quantity=Decimal("12.5")), actor)

    assert widget.created_by == actor
    assert widget.updated_by == actor
    entry = AuditLog.objects.get()
    assert entry.action == AuditLog.Action.CREATE
    assert entry.actor == actor
    assert entry.target == widget
    assert entry.object_repr == "Tank"
    assert entry.changes == {
        "name": [None, "Tank"],
        "quantity": [None, "12.5000"],
        "is_active": [None, True],
    }


@pytest.mark.django_db
def test_save_with_audit_update_logs_old_and_new_values(make_user):
    creator, editor = make_user(), make_user()
    widget = services.save_with_audit(Widget(name="Tank", quantity=Decimal("12.5")), creator)

    widget.name = "Tank 2"
    widget.quantity = "12.50"  # aynı miktar: değişiklik sayılmaz
    widget.owner = editor
    services.save_with_audit(widget, editor)

    widget.refresh_from_db()
    assert widget.created_by == creator
    assert widget.updated_by == editor
    entry = AuditLog.objects.filter(action=AuditLog.Action.UPDATE).get()
    assert entry.actor == editor
    assert entry.changes == {"name": ["Tank", "Tank 2"], "owner": [None, editor.pk]}


@pytest.mark.django_db
def test_save_with_audit_without_changes_writes_no_log(make_user):
    widget = services.save_with_audit(Widget(name="Tank"), make_user())

    services.save_with_audit(widget, make_user())

    assert not AuditLog.objects.filter(action=AuditLog.Action.UPDATE).exists()


@pytest.mark.django_db
def test_save_with_audit_system_actor():
    widget = services.save_with_audit(Widget(name="Tank"), None)

    assert widget.created_by is None
    assert AuditLog.objects.get().actor is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [("status", "DONE"), ("number", "X-1"), ("cancel_reason", "elle"), ("cancelled_at", "now")],
)
def test_save_with_audit_rejects_direct_state_change(document, make_user, field, value):
    from django.utils import timezone

    loaded = SampleDocument.objects.get(pk=document.pk)
    setattr(loaded, field, timezone.now() if value == "now" else value)

    with pytest.raises(ValueError):
        services.save_with_audit(loaded, make_user())
    loaded.refresh_from_db()
    assert loaded.status == "DRAFT"
    assert loaded.cancel_reason == ""


@pytest.mark.django_db
def test_save_with_audit_refuses_to_create_documents(make_user):
    with pytest.raises(ValueError):
        services.save_with_audit(
            SampleDocument(number="T-1", status="DONE", title="x"), make_user()
        )
    assert not SampleDocument.objects.exists()


@pytest.mark.django_db
def test_save_with_audit_keeps_current_state_of_stale_document(document, make_user):
    stale = SampleDocument.objects.get(pk=document.pk)
    services.transition_status(document, "APPROVED", make_user(), machine=machine)

    stale.title = "Yeni başlık"
    services.save_with_audit(stale, make_user())

    stale.refresh_from_db()
    assert stale.title == "Yeni başlık"
    assert stale.status == "APPROVED"  # bayat nesne durumu geri almadı
    entry = AuditLog.objects.filter(action=AuditLog.Action.UPDATE).get()
    assert entry.changes == {"title": ["Belge", "Yeni başlık"]}


@pytest.mark.django_db
def test_save_with_audit_logs_stored_decimal_value(make_user):
    widget = services.save_with_audit(Widget(name="Tank", quantity=Decimal("1.23455")), None)

    widget.refresh_from_db()
    assert widget.quantity == Decimal("1.2346")  # PostgreSQL yuvarlaması
    assert AuditLog.objects.get().changes["quantity"] == [None, "1.2346"]

    widget.quantity = Decimal("1.23456")  # saklanan değerle aynı: değişiklik yok
    services.save_with_audit(widget, make_user())
    assert not AuditLog.objects.filter(action=AuditLog.Action.UPDATE).exists()


@pytest.mark.django_db
def test_save_with_audit_without_changes_does_not_touch_record(make_user):
    widget = services.save_with_audit(Widget(name="Tank"), make_user())
    stamp = Widget.objects.get(pk=widget.pk).updated_at

    services.save_with_audit(widget, make_user())

    fresh = Widget.objects.get(pk=widget.pk)
    assert fresh.updated_at == stamp
    assert fresh.updated_by == widget.created_by


@pytest.mark.django_db
def test_save_with_audit_rolls_back_log_with_failed_save(make_user, monkeypatch):
    widget = services.save_with_audit(Widget(name="Tank"), make_user())

    def fail(*args, **kwargs):
        raise RuntimeError("yazma hatası")

    monkeypatch.setattr("apps.core.services.log_change", fail)
    widget.name = "Yeni"
    with pytest.raises(RuntimeError):
        services.save_with_audit(widget, None)

    widget.refresh_from_db()
    assert widget.name == "Tank"


# --- transition_status / cancel_document -----------------------------------------------------


@pytest.fixture
def document(make_user):
    return services.create_document(
        SampleDocument(title="Belge"), make_user(), prefix="TB", machine=machine
    )


@pytest.fixture
def published():
    names: list[events.Event] = []
    events.subscribe("sample_document.*")(names.append)
    return names


@pytest.mark.django_db(transaction=True)
def test_transition_status_audits_and_publishes(document, make_user, published):
    actor = make_user()

    services.transition_status(document, "APPROVED", actor, machine=machine, note="tamam")

    document.refresh_from_db()
    assert document.status == "APPROVED"
    assert document.updated_by == actor
    entry = AuditLog.objects.get(action=AuditLog.Action.STATUS_CHANGE)
    assert entry.changes == {"status": ["DRAFT", "APPROVED"]}
    assert entry.note == "tamam"
    assert [e.name for e in published] == ["sample_document.approved"]
    assert published[0].payload["number"] == document.number
    assert published[0].actor_id == actor.pk


@pytest.mark.django_db(transaction=True)
def test_transition_status_rejects_forbidden_transition(document, make_user, published):
    with pytest.raises(BusinessRuleError) as exc_info:
        services.transition_status(document, "DONE", make_user(), machine=machine)

    assert exc_info.value.code == "invalid_transition"
    document.refresh_from_db()
    assert document.status == "DRAFT"
    assert not AuditLog.objects.filter(action=AuditLog.Action.STATUS_CHANGE).exists()
    assert published == []


@pytest.mark.django_db
def test_transition_status_uses_database_state_not_stale_instance(document, make_user):
    stale = SampleDocument.objects.get(pk=document.pk)
    services.transition_status(document, "APPROVED", make_user(), machine=machine)

    services.transition_status(stale, "DONE", make_user(), machine=machine)

    assert AuditLog.objects.filter(action=AuditLog.Action.STATUS_CHANGE).latest("id").changes == {
        "status": ["APPROVED", "DONE"]
    }


@pytest.mark.django_db
def test_transition_status_refuses_cancel(document, make_user):
    with pytest.raises(ValueError):
        services.transition_status(document, "CANCELLED", make_user(), machine=machine)


@pytest.mark.django_db(transaction=True)
def test_cancel_document(document, make_user, published):
    actor = make_user()

    services.cancel_document(document, actor, reason=" Yanlış açıldı ", machine=machine)

    document.refresh_from_db()
    assert document.status == "CANCELLED"
    assert document.cancelled_by == actor
    assert document.cancelled_at is not None
    assert document.cancel_reason == "Yanlış açıldı"
    entry = AuditLog.objects.get(action=AuditLog.Action.CANCEL)
    assert entry.changes == {
        "status": ["DRAFT", "CANCELLED"],
        "cancel_reason": ["", "Yanlış açıldı"],
    }
    assert [e.name for e in published] == ["sample_document.cancelled"]


@pytest.mark.django_db
def test_cancel_document_requires_reason(document, make_user):
    with pytest.raises(BusinessRuleError) as exc_info:
        services.cancel_document(document, make_user(), reason="  ", machine=machine)

    assert exc_info.value.code == "cancel_reason_required"


@pytest.mark.django_db
def test_cancel_document_rejects_terminal_state(document, make_user):
    services.transition_status(document, "APPROVED", make_user(), machine=machine)
    services.transition_status(document, "DONE", make_user(), machine=machine)

    with pytest.raises(BusinessRuleError):
        services.cancel_document(document, make_user(), reason="geç", machine=machine)
    document.refresh_from_db()
    assert document.cancelled_at is None


# --- create_document ------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_create_document_assigns_number_and_initial_status(make_user, published):
    from django.utils import timezone

    actor = make_user()

    doc = services.create_document(
        SampleDocument(title="Belge"), actor, prefix="TB", machine=machine, note="ilk"
    )

    year = timezone.localdate().year
    assert doc.number == f"TB-{year}-00001"
    assert doc.status == "DRAFT"
    assert doc.created_by == actor
    entry = AuditLog.objects.get()
    assert entry.action == AuditLog.Action.CREATE
    assert entry.changes["number"] == [None, doc.number]
    assert entry.changes["status"] == [None, "DRAFT"]
    assert [e.name for e in published] == ["sample_document.created"]
    assert published[0].payload == {
        "model": "core_testapp.sampledocument",
        "id": doc.pk,
        "number": doc.number,
        "status": "DRAFT",
    }


@pytest.mark.django_db
def test_create_document_rejects_saved_instance(document, make_user):
    with pytest.raises(ValueError):
        services.create_document(document, make_user(), prefix="TB", machine=machine)


@pytest.mark.django_db
def test_create_document_rolls_back_number_on_failure(make_user, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("yazma hatası")

    monkeypatch.setattr("apps.core.services.log_change", fail)
    with pytest.raises(RuntimeError):
        services.create_document(
            SampleDocument(title="x"), make_user(), prefix="TB", machine=machine
        )
    monkeypatch.undo()

    doc = services.create_document(
        SampleDocument(title="y"), make_user(), prefix="TB", machine=machine
    )
    assert doc.number.endswith("-00001")
    assert SampleDocument.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_transitions_cannot_both_succeed(make_user, monkeypatch):
    """İki kullanıcı aynı taslak belgeyi aynı anda onaylamaya çalışır: satır kilidi sayesinde
    ikincisi güncel durumu (APPROVED) görür ve reddedilir; belge iki kez onaylanmaz."""
    import time

    doc = services.create_document(SampleDocument(title="x"), None, prefix="TB", machine=machine)
    original = machine.assert_can_transition

    def slow_check(from_state: str, to_state: str) -> None:
        original(from_state, to_state)
        time.sleep(0.3)  # kilit tutulurken diğer işlemin araya girme penceresini genişlet

    monkeypatch.setattr(machine, "assert_can_transition", slow_check)
    workers = 2
    barrier = threading.Barrier(workers)
    results: list[str] = []
    lock = threading.Lock()

    def approve() -> None:
        try:
            stale = SampleDocument.objects.get(pk=doc.pk)  # ikisi de DRAFT olarak okur
            barrier.wait()
            services.transition_status(stale, "APPROVED", None, machine=machine)
            outcome = "ok"
        except BusinessRuleError as exc:
            outcome = exc.code
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=approve) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["invalid_transition", "ok"]
    assert AuditLog.objects.filter(action=AuditLog.Action.STATUS_CHANGE).count() == 1


# --- set_user_roles -------------------------------------------------------------------------


@pytest.mark.django_db
def test_set_user_roles_replaces_roles_and_audits(make_user):
    admin, user = make_user("admin"), make_user("depo")

    services.set_user_roles(user, ["planlama", "depo", "planlama"], admin, note="görev değişti")

    assert user.roles == ["depo", "planlama"]
    entry = AuditLog.objects.get(action=AuditLog.Action.UPDATE)
    assert entry.actor == admin
    assert entry.target == user
    assert entry.changes == {"roles": [["depo"], ["depo", "planlama"]]}


@pytest.mark.django_db
def test_set_user_roles_without_change_writes_no_log(make_user):
    user = make_user("depo")

    services.set_user_roles(user, ["depo"], None)

    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_set_user_roles_rejects_unknown_role(make_user):
    user = make_user("depo")

    with pytest.raises(BusinessRuleError) as exc_info:
        services.set_user_roles(user, ["muhasebe"], None)

    assert exc_info.value.code == "unknown_role"
    assert user.roles == ["depo"]


@pytest.mark.django_db
def test_set_user_roles_requires_seeded_roles():
    from apps.core.tests.factories import UserFactory

    user = UserFactory()  # roller oluşturulmadı (seed_roles çalışmadı)

    with pytest.raises(BusinessRuleError) as exc_info:
        services.set_user_roles(user, ["depo"], None)

    assert exc_info.value.code == "role_not_seeded"
