from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.core.models import User
from apps.personnel.models import Employee
from apps.personnel.tests.factories import employee

pytestmark = pytest.mark.django_db
BASE = "/api/v1/personnel"
OTHER_ROLES = ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]


@pytest.fixture
def manager_user(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


@pytest.fixture
def manager(manager_user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(manager_user)
    return client


def test_create_list_and_filter(manager: APIClient, make_user: Callable[..., User]) -> None:
    operator = make_user("dolum", username="dolum1", full_name="Ayşe Demir")
    response = manager.post(
        f"{BASE}/employees/",
        {
            "employee_no": "S-1",
            "full_name": "Ayşe Demir",
            "department": "Dolum",
            "title": "Dolum operatörü",
            "hire_date": "2024-03-01",
            "phone": "0500 000 00 01",
            "user": operator.pk,
        },
    )
    assert response.status_code == 201, response.json()
    card = response.json()
    assert card["user_info"] == {
        "id": operator.pk,
        "username": "dolum1",
        "full_name": "Ayşe Demir",
        "is_active": True,
    }
    assert card["is_active"] is True and card["termination_date"] is None
    response = manager.post(f"{BASE}/employees/", {"full_name": "Can Kaya", "department": "depo"})
    assert response.status_code == 201, response.json()
    assert response.json()["user"] is None and response.json()["employee_no"] == ""

    rows = manager.get(f"{BASE}/employees/").json()["results"]
    assert [row["full_name"] for row in rows] == ["Ayşe Demir", "Can Kaya"]
    rows = manager.get(f"{BASE}/employees/", {"department": "Dolum"}).json()["results"]
    assert [row["full_name"] for row in rows] == ["Ayşe Demir"]
    rows = manager.get(f"{BASE}/employees/", {"search": "s-1"}).json()["results"]
    assert [row["full_name"] for row in rows] == ["Ayşe Demir"]
    assert manager.get(f"{BASE}/departments/").json() == ["depo", "Dolum"]


def test_validation_errors_have_codes(manager: APIClient) -> None:
    response = manager.post(f"{BASE}/employees/", {"full_name": " ", "department": "Depo"})
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    assert "full_name" in response.json()["errors"]
    response = manager.post(f"{BASE}/employees/", {"full_name": "Can Kaya"})
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    assert "department" in response.json()["errors"]
    manager.post(
        f"{BASE}/employees/", {"full_name": "Ece Ak", "department": "Depo", "employee_no": "S-9"}
    )
    response = manager.post(
        f"{BASE}/employees/", {"full_name": "Can Kaya", "department": "Depo", "employee_no": "S-9"}
    )
    assert response.status_code == 400 and response.json()["code"] == "employee_no_taken"


def test_identity_and_education_fields(manager: APIClient) -> None:
    response = manager.post(
        f"{BASE}/employees/",
        {
            "full_name": "Ayşe Demir",
            "department": "Laboratuvar",
            "national_id": "100 000 001 46",
            "birth_date": "1990-05-17",
            "birth_place": "İzmir",
            "education_level": "BACHELOR",
            "school": "Ege Üniversitesi",
            "field_of_study": "Kimya",
            "graduation_year": 2012,
        },
    )
    assert response.status_code == 201, response.json()
    card = response.json()
    # Yönetim kartta numaranın tamamını görür; günlükte maskelidir.
    assert card["national_id"] == "10000000146"
    assert card["education_level_display"] == "Lisans" and card["graduation_year"] == 2012
    url = f"{BASE}/employees/{card['id']}/"
    body = {"education_level": "MASTER", "graduation_year": None}
    response = manager.patch(url, body, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["education_level_display"] == "Yüksek lisans"
    assert response.json()["graduation_year"] is None
    assert response.json()["national_id"] == "10000000146"  # gönderilmeyen alan değişmez
    history = manager.get(f"{url}history/").json()
    assert history[-1]["changes"]["national_id"] == [None, "*******0146"]

    response = manager.patch(url, {"national_id": "12345678901"})
    assert response.status_code == 400 and response.json()["code"] == "invalid_national_id"
    response = manager.patch(url, {"education_level": "UNIVERSITY"})
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    response = manager.patch(url, {"birth_date": "2999-01-01"})
    assert response.status_code == 400 and response.json()["code"] == "invalid_birth_date"


def test_update_terminate_reinstate_and_history(manager: APIClient, manager_user: User) -> None:
    card = employee(manager_user, hire_date=None)
    url = f"{BASE}/employees/{card.pk}/"
    response = manager.patch(url, {"title": "Hat şefi", "termination_date": "2026-01-01"})
    assert response.status_code == 200, response.json()
    assert response.json()["title"] == "Hat şefi"
    assert response.json()["termination_date"] is None  # yalnızca ayrılışla yazılır

    response = manager.post(f"{url}terminate/", {"termination_date": "2026-09-30"})
    assert response.status_code == 200, response.json()
    assert response.json()["is_active"] is False
    assert response.json()["termination_date"] == "2026-09-30"
    response = manager.post(f"{url}terminate/", {"termination_date": "2026-10-01"})
    assert response.status_code == 400 and response.json()["code"] == "already_terminated"
    rows = manager.get(f"{BASE}/employees/", {"is_active": "false"}).json()["results"]
    assert [row["id"] for row in rows] == [card.pk]

    response = manager.post(f"{url}reinstate/")
    assert response.status_code == 200 and response.json()["is_active"] is True

    history = manager.get(f"{url}history/").json()
    assert [entry["action"] for entry in history] == ["update", "update", "update", "create"]
    assert history[0]["note"] == "Yeniden işe başladı"
    assert history[1]["changes"]["termination_date"] == [None, "2026-09-30"]
    assert "ip_address" not in history[0]
    assert history[-1]["action_label"] == "Oluşturma"


def test_linkable_users(manager: APIClient, make_user: Callable[..., User]) -> None:
    free = make_user("depo", username="depo1")
    taken = make_user("dolum", username="dolum1")
    make_user("dolum", username="eski", is_active=False)
    card = employee(User.objects.get(username="yonetim"), user=taken)
    names = {row["username"] for row in manager.get(f"{BASE}/linkable-users/").json()}
    assert names == {"yonetim", free.username}
    names = {
        row["username"]
        for row in manager.get(f"{BASE}/linkable-users/", {"employee": card.pk}).json()
    }
    assert names == {"yonetim", free.username, taken.username}


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_see_personnel(
    client_for: Callable[..., APIClient], manager_user: User, role: str
) -> None:
    card = employee(manager_user)
    client = client_for(role)
    assert client.get(f"{BASE}/employees/").status_code == 403
    assert client.get(f"{BASE}/employees/{card.pk}/").status_code == 403
    assert client.get(f"{BASE}/employees/{card.pk}/history/").status_code == 403
    assert client.get(f"{BASE}/departments/").status_code == 403
    assert client.get(f"{BASE}/linkable-users/").status_code == 403
    response = client.post(f"{BASE}/employees/", {"full_name": "X", "department": "Depo"})
    assert response.status_code == 403
    assert client.patch(f"{BASE}/employees/{card.pk}/", {"title": "X"}).status_code == 403
    response = client.post(
        f"{BASE}/employees/{card.pk}/terminate/", {"termination_date": "2026-01-01"}
    )
    assert response.status_code == 403
    assert client.post(f"{BASE}/employees/{card.pk}/reinstate/").status_code == 403
    # Genel kayıt geçmişi ve yorum uç noktaları personel kartını hiç kabul etmez.
    params = {"content_type": "personnel.employee", "object_id": str(card.pk)}
    response = client.get("/api/v1/workflow/record-history/", params)
    assert response.status_code == 400 and response.json()["code"] == "invalid_record_type"
    response = client.get("/api/v1/workflow/comments/", params)
    assert response.status_code == 400 and response.json()["code"] == "invalid_record_type"


def test_admin_sees_personnel_and_anonymous_does_not(
    client_for: Callable[..., APIClient], manager_user: User
) -> None:
    employee(manager_user)
    assert client_for("admin").get(f"{BASE}/employees/").json()["count"] == 1
    assert APIClient().get(f"{BASE}/employees/").status_code in (401, 403)
    assert Employee.objects.count() == 1


def test_no_delete_endpoint(manager: APIClient, manager_user: User) -> None:
    card = employee(manager_user)
    assert manager.delete(f"{BASE}/employees/{card.pk}/").status_code == 405
    assert Employee.objects.filter(pk=card.pk).exists()
