from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.roles import DEPO, LABORATUVAR, SEVKIYAT, URETIM, YONETIM
from apps.maintenance import services
from apps.maintenance.models import MaintenanceKind
from apps.maintenance.tests.factories import plan, run_batch, scale, second_product
from apps.masterdata.tests.factories import EquipmentFactory

pytestmark = pytest.mark.django_db

BASE = "/api/v1/maintenance"


def test_plan_crud_and_permissions(client_for):
    tank = EquipmentFactory.create()
    body = {
        "equipment": tank.pk,
        "kind": "PERIODIC",
        "title": "Aylık bakım",
        "interval_days": 30,
        "checklist": ["Conta"],
    }
    assert client_for(DEPO).post(f"{BASE}/plans/", body, format="json").status_code == 403
    client = client_for(URETIM)
    response = client.post(f"{BASE}/plans/", body, format="json")
    assert response.status_code == 201, response.data
    data = response.json()
    assert data["responsible_role"] == "uretim"
    assert data["is_due"] is False
    response = client.patch(f"{BASE}/plans/{data['id']}/", {"interval_days": 0}, format="json")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_interval"
    assert client.post(f"{BASE}/plans/{data['id']}/deactivate/").json()["is_active"] is False
    assert client_for(SEVKIYAT).get(f"{BASE}/plans/").status_code == 403


def test_work_order_flow(client_for, make_user):
    operator = make_user(URETIM)
    plan(operator, EquipmentFactory.create(), next_due_date=timezone.localdate())
    [order] = services.create_due_work_orders()
    client = client_for(URETIM)
    url = f"{BASE}/work-orders/{order.pk}"
    assert client.post(f"{url}/start/").json()["status"] == "IN_PROGRESS"
    response = client.post(
        f"{url}/complete/",
        {"work_done": "Yapıldı", "duration_minutes": 30, "checklist": [{"done": True}] * 2},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.json()["status_display"] == "Tamamlandı"
    listing = client.get(f"{BASE}/work-orders/", {"status": "COMPLETED"}).json()
    assert listing["count"] == 1


def test_work_order_wrong_role_forbidden(client_for, make_user):
    order = services.create_work_order(
        make_user(URETIM), {"equipment": EquipmentFactory.create(), "title": "Kontrol"}
    )
    response = client_for(LABORATUVAR).post(f"{BASE}/work-orders/{order.pk}/start/")
    assert response.status_code == 403


def test_breakdown_by_any_role_and_downtime_end(client_for):
    tank = EquipmentFactory.create()
    response = client_for(SEVKIYAT).post(
        f"{BASE}/breakdowns/", {"equipment": tank.pk, "description": "Sızıntı"}, format="json"
    )
    assert response.status_code == 201, response.data
    assert response.json()["source"] == "BREAKDOWN"
    client = client_for(URETIM)
    [downtime] = client.get(f"{BASE}/downtimes/", {"is_open": True}).json()["results"]
    assert downtime["reason"] == "BREAKDOWN"
    assert client_for(SEVKIYAT).post(f"{BASE}/downtimes/{downtime['id']}/end/").status_code == 403
    ended = client.post(f"{BASE}/downtimes/{downtime['id']}/end/", {"note": "Tamir"}).json()
    assert ended["ended_at"] is not None
    summary = client.get(f"{BASE}/downtime-summary/").json()
    assert summary[0]["equipment_code"] == tank.code


def test_cleaning_check_and_record(client_for, make_user, plant, planner, depo, operator):
    run_batch(plant, planner, depo, operator)
    other = second_product(plant, planner).recipe.product
    client = client_for(URETIM)
    params = {"equipment": plant.tank.pk, "product": other.pk}
    check = client.get(f"{BASE}/cleaning-check/", params).json()
    assert check["required"] is True
    assert check["previous_product_code"] == plant.product.code
    assert (
        client_for(DEPO)
        .post(f"{BASE}/cleanings/", {"equipment": plant.tank.pk, "work_done": "Yıkandı"})
        .status_code
        == 403
    )
    response = client.post(
        f"{BASE}/cleanings/", {"equipment": plant.tank.pk, "work_done": "Yıkandı"}, format="json"
    )
    assert response.status_code == 201, response.data
    assert client.get(f"{BASE}/cleaning-check/", params).json()["required"] is False


def test_changeover_rules_written_by_lab(client_for, plant, planner):
    other = second_product(plant, planner).recipe.product
    body = {"from_product": plant.product.pk, "to_product": other.pk, "note": "Aynı baz"}
    assert client_for(URETIM).post(f"{BASE}/changeover-rules/", body).status_code == 403
    response = client_for(LABORATUVAR).post(f"{BASE}/changeover-rules/", body)
    assert response.status_code == 201, response.data
    assert response.json()["to_product_code"] == other.code


def test_calibration_status_endpoint(client_for, make_user):
    lab = make_user(LABORATUVAR)
    terazi = scale()
    plan(
        lab,
        terazi,
        kind=MaintenanceKind.CALIBRATION,
        title="Kalibrasyon",
        next_due_date=timezone.localdate() + timedelta(days=2),
    )
    [row] = client_for(URETIM).get(f"{BASE}/calibration/").json()
    assert (row["equipment_code"], row["status"], row["days_left"]) == (
        terazi.code,
        "DUE_SOON",
        2,
    )


def test_settings_endpoint(client_for):
    assert client_for(URETIM).get(f"{BASE}/settings/").json()["calibration_warning_days"] == 7
    assert client_for(URETIM).patch(f"{BASE}/settings/", {"plan_lead_days": 3}).status_code == 403
    response = client_for(YONETIM).patch(f"{BASE}/settings/", {"plan_lead_days": 3})
    assert response.json()["plan_lead_days"] == 3
