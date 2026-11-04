"""Ücretler: geçerlilik tarihli brüt aylık ücret, zam, gerekçeyle kaldırma, ücret listesi ve yetki
(docs/DECISIONS.md "Personel maliyeti", "Personel bordrosu"). 2026-11-01'de maliyet modülünden
taşındı; hesapta kullanımı costing/tests/test_personnel_cost.py'de."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import selectors, services
from apps.personnel.api.serializers import WageSummarySerializer
from apps.personnel.models import Employee, EmployeeWage
from apps.personnel.tests.factories import employee

pytestmark = pytest.mark.django_db
D = Decimal
BASE = "/api/v1/personnel"
OTHER_ROLES = ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


def _wage(
    actor: User, person: Employee, amount: str, valid_from: date, **extra: Any
) -> EmployeeWage:
    return services.add_wage(
        actor, {"employee": person, "gross_monthly": D(amount), "valid_from": valid_from, **extra}
    )


def _code(call: Callable[[], Any]) -> str:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value.code


def _audit(wage: EmployeeWage, **filters: Any) -> Any:
    return AuditLog.objects.filter(
        content_type__app_label="personnel",
        content_type__model="employeewage",
        object_id=wage.pk,
        **filters,
    )


def test_wage_rules(manager: User) -> None:
    person = employee(manager)
    wage = _wage(manager, person, "30000", date(2026, 1, 1), note="  Yıllık   zam ")
    assert wage.created_by == manager and wage.is_active and wage.note == "Yıllık zam"

    def add(**values: Any) -> Callable[[], Any]:
        data = {"employee": person, "gross_monthly": D(1), "valid_from": date(2026, 1, 1)}
        return lambda: services.add_wage(manager, {**data, **values})

    assert _code(add()) == "duplicate_wage"
    assert _code(add(gross_monthly=D(0), valid_from=date(2026, 2, 1))) == "invalid_wage"
    assert _code(add(gross_monthly=D("100000000.01"), valid_from=date(2026, 2, 1))) == (
        "invalid_wage"
    )
    assert _code(add(valid_from=date(1999, 12, 31))) == "invalid_valid_from"
    assert _code(add(valid_from=date(2101, 1, 1))) == "invalid_valid_from"
    assert _code(add(valid_from=date(26, 9, 1))) == "invalid_valid_from"
    assert _code(add(valid_from=None)) == "valid_from_required"
    assert _code(add(employee=None)) == "employee_required"
    with pytest.raises(ValueError):
        services.add_wage(manager, {"employee": person, "gross_monthly": D(1), "extra": 1})
    top = _wage(manager, person, "100000000", date(2026, 2, 1))
    services.remove_wage(manager, top, "Deneme")
    created = _audit(wage, action=AuditLog.Action.CREATE).get()
    assert created.actor == manager
    assert _code(lambda: services.remove_wage(manager, wage, " ")) == "reason_required"
    removed = services.remove_wage(manager, wage, "  Yanlış   tutar ")
    assert not removed.is_active and removed.removed_by == manager
    assert removed.removal_reason == "Yanlış tutar" and removed.removed_at is not None
    assert _audit(wage, action=AuditLog.Action.UPDATE, note="Ücret kaydı kaldırıldı").exists()
    assert _code(lambda: services.remove_wage(manager, removed, "Tekrar")) == "already_removed"
    # Kaldırılan ücret hesaba ve geçmişe girmez.
    wages = selectors.wages_by_employee([person.pk], date(2026, 3, 31))
    assert selectors.wage_on(wages[person.pk], date(2026, 3, 1)) is None
    assert selectors.wage_summary(date(2026, 3, 1))[0]["history"] == []
    _wage(manager, person, "31000", date(2026, 1, 1))  # kaldırılan tarihe yeniden girilebilir
    summary = selectors.wage_summary(date(2026, 3, 1))
    assert [row["current_wage"] for row in summary] == [D("31000.00")]
    assert [item.gross_monthly for item in summary[0]["history"]] == [D("31000.00")]


def test_wage_on_follows_raises(manager: User) -> None:
    """Gün başına geçerli ücret: zam başladığı gün geçerlidir; ilk ücretten önce ücret yoktur,
    ay sonundan sonra başlayan zam listeye girmez."""
    person = employee(manager)
    _wage(manager, person, "30000", date(2026, 1, 10))
    _wage(manager, person, "36000", date(2026, 9, 16))
    _wage(manager, person, "40000", date(2026, 10, 1))
    wages = selectors.wages_by_employee([person.pk], date(2026, 9, 30))[person.pk]
    assert [wage.gross_monthly for wage in wages] == [D("30000.00"), D("36000.00")]
    assert selectors.wage_on(wages, date(2026, 1, 9)) is None
    assert selectors.wage_on(wages, date(2026, 1, 10)) == D("30000.00")
    assert selectors.wage_on(wages, date(2026, 9, 15)) == D("30000.00")
    assert selectors.wage_on(wages, date(2026, 9, 16)) == D("36000.00")
    assert selectors.wage_on([], date(2026, 9, 16)) is None


def test_wage_summary_lists_leavers_on_request(
    client_for: Callable[..., APIClient],
    manager: User,
    django_assert_max_num_queries: Callable[..., Any],
) -> None:
    today = timezone.localdate()
    working = employee(manager)
    leaving = employee(manager, full_name="Can Kaya")
    left = employee(manager, full_name="Ece Ak", hire_date=date(2020, 1, 1))
    services.terminate_employee(manager, leaving, today + timedelta(days=10))
    services.terminate_employee(manager, left, today - timedelta(days=40))
    names = [row["employee"].full_name for row in selectors.wage_summary()]
    assert names == ["Ayşe Demir", "Can Kaya"]  # çıkışı ileride olan listede kalır
    names = [row["employee"].full_name for row in selectors.wage_summary(include_former=True)]
    assert sorted(names) == ["Ayşe Demir", "Can Kaya", "Ece Ak"]
    client = client_for("yonetim")
    rows = client.get(f"{BASE}/wages/summary/", {"include_former": "true"}).json()
    ece = next(row for row in rows if row["employee"]["full_name"] == "Ece Ak")
    assert ece["employee"]["is_active"] is False
    assert ece["employee"]["termination_date"] == str(today - timedelta(days=40))
    assert "stage" not in ece  # maliyet aşaması Maliyet > Personel maliyeti'nde
    # Ayrılan kişiye ücret girilebilir (hesapta eksik görünen geçmiş ay için).
    _wage(manager, left, "30000", date(2020, 1, 1))
    _wage(manager, left, "32000", date(2021, 1, 1))
    _wage(manager, working, "30000", date(2020, 1, 1))
    assert working.is_active
    # Geçmiş ücretler kişi başına ek sorgu açmaz.
    with django_assert_max_num_queries(3):
        data = WageSummarySerializer(selectors.wage_summary(include_former=True), many=True).data
    assert [len(row["history"]) for row in data if row["employee"]["full_name"] == "Ece Ak"] == [2]


def test_concurrent_duplicate_wage_is_a_business_error(
    manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aynı kişi ve tarihe aynı anda iki ücret: tekil kısıt 500 değil `duplicate_wage` verir."""
    person = employee(manager)

    def clash(*args: Any, **kwargs: Any) -> Any:
        raise IntegrityError("costing_wage_employee_date_uniq")

    monkeypatch.setattr(services, "save_with_audit", clash)
    assert _code(lambda: _wage(manager, person, "30000", date(2026, 1, 1))) == "duplicate_wage"


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_only_management_handles_wages(
    make_user: Callable[..., User], manager: User, role: str
) -> None:
    person = employee(manager)
    wage = _wage(manager, person, "30000", date(2026, 1, 1))
    other = make_user(role)
    for call in (
        lambda: _wage(other, person, "30000", date(2026, 2, 1)),
        lambda: services.remove_wage(other, wage, "Neden"),
    ):
        with pytest.raises(PermissionDenied):
            call()
    assert EmployeeWage.objects.count() == 1


# --- API -----------------------------------------------------------------------------------------


def test_wage_api(client_for: Callable[..., APIClient], manager: User) -> None:
    client = client_for("yonetim")
    person = employee(manager, employee_no="S-1")
    response = client.post(
        f"{BASE}/wages/",
        {"employee": person.pk, "gross_monthly": "30000", "valid_from": "2020-01-01"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    wage = response.json()
    assert wage["employee_name"] == "Ayşe Demir" and wage["gross_monthly"] == "30000.00"
    assert wage["created_by_name"] and wage["is_active"] is True
    response = client.post(
        f"{BASE}/wages/",
        {"employee": person.pk, "gross_monthly": "1", "valid_from": "2020-01-01"},
        format="json",
    )
    assert response.status_code == 400 and response.json()["code"] == "duplicate_wage"
    summary = client.get(f"{BASE}/wages/summary/").json()
    assert summary[0]["current_wage"] == "30000.00"
    assert summary[0]["employee"]["employee_no"] == "S-1"
    assert [item["id"] for item in summary[0]["history"]] == [wage["id"]]
    assert client.get(f"{BASE}/wages/", {"employee": person.pk}).json()["count"] == 1
    assert client.delete(f"{BASE}/wages/{wage['id']}/").status_code == 405
    assert client.patch(f"{BASE}/wages/{wage['id']}/", {"note": "x"}).status_code == 405
    response = client.post(f"{BASE}/wages/{wage['id']}/remove/", {"reason": ""})
    assert response.status_code == 400
    response = client.post(f"{BASE}/wages/{wage['id']}/remove/", {"reason": "Yanlış"})
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert response.json()["removal_reason"] == "Yanlış"
    assert client.get(f"{BASE}/wages/summary/").json()[0]["history"] == []


def test_admin_reaches_wages_and_anonymous_is_rejected(
    client_for: Callable[..., APIClient], api_client: APIClient, manager: User
) -> None:
    person = employee(manager)
    admin = client_for("admin")
    response = admin.post(
        f"{BASE}/wages/",
        {"employee": person.pk, "gross_monthly": "30000", "valid_from": "2020-01-01"},
        format="json",
    )
    assert response.status_code == 201
    assert admin.get(f"{BASE}/wages/summary/").status_code == 200
    for url in (f"{BASE}/wages/", f"{BASE}/wages/summary/"):
        assert api_client.get(url).status_code in (401, 403)


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_reach_wages(
    client_for: Callable[..., APIClient], manager: User, role: str
) -> None:
    person = employee(manager)
    wage = _wage(manager, person, "30000", date(2026, 1, 1))
    client = client_for(role)
    checks = [
        client.get(f"{BASE}/wages/"),
        client.get(f"{BASE}/wages/{wage.pk}/"),
        client.get(f"{BASE}/wages/summary/"),
        client.post(f"{BASE}/wages/", {"employee": person.pk, "gross_monthly": "1"}),
        client.post(f"{BASE}/wages/{wage.pk}/remove/", {"reason": "X"}),
    ]
    assert [response.status_code for response in checks] == [403] * len(checks)
    assert EmployeeWage.objects.count() == 1 and EmployeeWage.objects.get().is_active
