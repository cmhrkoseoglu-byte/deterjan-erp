from collections.abc import Callable
from datetime import date

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import selectors, services
from apps.personnel.models import Employee
from apps.personnel.tests.factories import employee

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


def test_create_employee_writes_audit_log(manager: User) -> None:
    card = employee(
        manager,
        employee_no=" S-0001 ",
        full_name="  Ayşe   Demir ",
        hire_date=date(2024, 3, 1),
        phone="0500 000 00 01",
        emergency_contact_name="Ali Demir",
        emergency_contact_phone="0500 000 00 02",
    )
    assert card.employee_no == "S-0001" and card.full_name == "Ayşe Demir"
    assert card.is_active and card.termination_date is None
    assert card.created_by == manager and card.updated_by == manager
    log = AuditLog.objects.get(object_id=card.pk, action=AuditLog.Action.CREATE)
    assert log.actor == manager
    assert log.changes["full_name"] == [None, "Ayşe Demir"]
    assert log.changes["emergency_contact_phone"] == [None, "0500 000 00 02"]


def test_name_and_department_required(manager: User) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        employee(manager, full_name="  ")
    assert exc.value.code == "full_name_required"
    with pytest.raises(BusinessRuleError) as exc:
        employee(manager, department="")
    assert exc.value.code == "department_required"


def test_department_reuses_existing_spelling(manager: User) -> None:
    employee(manager, department="İdari İşler")
    second = employee(manager, full_name="Can Kaya", department="  idari   işler ")
    assert second.department == "İdari İşler"
    employee(manager, full_name="Ece Ak", department="Depo")
    assert selectors.departments() == ["Depo", "İdari İşler"]


def test_employee_no_is_optional_but_unique(manager: User) -> None:
    employee(manager, employee_no="")
    employee(manager, full_name="Can Kaya", employee_no="")  # boş sicil no tekrarlanabilir
    employee(manager, full_name="Ece Ak", employee_no="S-7")
    with pytest.raises(BusinessRuleError) as exc:
        employee(manager, full_name="Deniz Su", employee_no="S-7")
    assert exc.value.code == "employee_no_taken"
    assert "Ece Ak" in exc.value.message


def test_linking_a_user(manager: User, make_user: Callable[..., User]) -> None:
    operator = make_user("dolum", username="dolum1")
    card = employee(manager, user=operator)
    assert card.user == operator
    # Aynı kullanıcıyla kaydetmek sorun değil; başka karta bağlamak hata.
    services.update_employee(manager, card, {"user": operator, "title": "Hat şefi"})
    with pytest.raises(BusinessRuleError) as exc:
        employee(manager, full_name="Can Kaya", user=operator)
    assert exc.value.code == "user_already_linked"
    former = make_user("depo", username="eski", is_active=False)
    with pytest.raises(BusinessRuleError) as exc:
        employee(manager, full_name="Ece Ak", user=former)
    assert exc.value.code == "inactive_user"
    assert list(selectors.linkable_users()) == [manager]
    assert set(selectors.linkable_users(card)) == {manager, operator}


def test_update_logs_old_and_new_values(manager: User) -> None:
    card = employee(manager, phone="0500 000 00 01")
    services.update_employee(manager, card, {"phone": "0500 000 00 09", "title": "Hat şefi"})
    log = AuditLog.objects.get(object_id=card.pk, action=AuditLog.Action.UPDATE)
    assert log.changes["phone"] == ["0500 000 00 01", "0500 000 00 09"]
    assert log.changes["title"] == ["Dolum operatörü", "Hat şefi"]


def test_status_fields_change_only_through_their_services(manager: User) -> None:
    card = employee(manager)
    for field, value in (("is_active", False), ("termination_date", date(2026, 1, 1))):
        with pytest.raises(ValueError):
            services.update_employee(manager, card, {field: value})


def test_terminate_and_reinstate(manager: User) -> None:
    card = employee(manager, hire_date=date(2024, 3, 1))
    with pytest.raises(BusinessRuleError) as exc:
        services.terminate_employee(manager, card, date(2024, 2, 1))
    assert exc.value.code == "termination_before_hire"

    left = services.terminate_employee(manager, card, date(2026, 9, 30))
    assert not left.is_active and left.termination_date == date(2026, 9, 30)
    log = AuditLog.objects.filter(object_id=card.pk).latest("timestamp")
    assert log.note == "İşten ayrıldı"
    assert log.changes["is_active"] == [True, False]
    assert log.changes["termination_date"] == [None, "2026-09-30"]
    with pytest.raises(BusinessRuleError) as exc:
        services.terminate_employee(manager, left, date(2026, 10, 1))
    assert exc.value.code == "already_terminated"

    back = services.reinstate_employee(manager, left)
    assert back.is_active and back.termination_date is None
    assert AuditLog.objects.filter(object_id=card.pk).latest("timestamp").note == (
        "Yeniden işe başladı"
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.reinstate_employee(manager, back)
    assert exc.value.code == "already_active"


def test_status_and_termination_date_stay_consistent(manager: User) -> None:
    card = employee(manager)
    card.termination_date = date(2026, 1, 1)  # çalışan personelde çıkış tarihi olmaz
    with pytest.raises(ValidationError):
        card.full_clean()


@pytest.mark.parametrize("role", ["depo", "planlama", "uretim", "laboratuvar", "sevkiyat"])
def test_only_management_and_admin(make_user: Callable[..., User], role: str) -> None:
    with pytest.raises(PermissionDenied):
        employee(make_user(role))
    admin = make_user("admin")
    card = employee(admin)
    assert Employee.objects.filter(pk=card.pk).exists()
