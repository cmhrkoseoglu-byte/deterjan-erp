from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory.models import Lot
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.tests.factories import unit
from apps.production import services
from apps.production.models import ProductionOrder
from apps.production.tests.factories import approved_order, ready_order

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal


def url(name, *args, **query):
    path = reverse(f"production:{name}", args=args)
    if query:
        path += "?" + "&".join(f"{key}={value}" for key, value in query.items())
    return path


def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def order_body(plant, quantity="1000"):
    return {
        "recipe_version": plant.version.pk,
        "planned_quantity": quantity,
        "unit": unit("KG").pk,
        "planned_date": "2026-10-20",
        "equipment": plant.tank.pk,
        "priority": 3,
    }


# --- yetki -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["order-list", "batch-list"])
def test_read_requires_login_but_no_role(name, client_for):
    assert APIClient().get(url(name)).status_code == 401
    assert client_for().get(url(name)).status_code == 200


@pytest.mark.parametrize("role", ["depo", "uretim", "laboratuvar", "yonetim"])
def test_only_planning_writes_orders(role, client_for, plant, planner):
    api = client_for(role)
    order = services.create_order(planner, {**_data(plant)})
    assert api.post(url("order-list"), order_body(plant), format="json").status_code == 403
    assert (
        api.patch(url("order-detail", order.pk), {"notes": "x"}, format="json").status_code == 403
    )
    assert api.post(url("order-approve", order.pk), {}, format="json").status_code == 403
    assert api.post(url("order-cancel", order.pk), {"reason": "x"}).status_code == 403


@pytest.mark.parametrize("role", ["planlama", "uretim", "laboratuvar"])
def test_only_depo_prepares(role, client_for, plant, planner):
    api = client_for(role)
    order = approved_order(plant, planner)
    assert api.post(url("order-start-prep", order.pk)).status_code == 403
    assert api.post(url("order-mark-ready", order.pk)).status_code == 403
    assert api.post(url("order-picks", order.pk), {}, format="json").status_code == 403
    assert api.get(url("order-picks", order.pk)).status_code == 200


@pytest.mark.parametrize("role", ["planlama", "depo", "laboratuvar"])
def test_only_production_runs_batches(role, client_for, plant, planner, depo, operator):
    api = client_for(role)
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    assert api.post(url("batch-list"), {"order": order.pk}, format="json").status_code == 403
    assert api.post(url("batch-consume", batch.pk), {}, format="json").status_code == 403
    assert api.post(url("batch-finish", batch.pk), {}, format="json").status_code == 403
    assert api.post(url("batch-cancel", batch.pk), {"reason": "x"}).status_code == 403


def _data(plant):
    return {
        "recipe_version": plant.version,
        "planned_quantity": D("1000"),
        "unit": unit("KG"),
        "planned_date": "2026-10-20",
        "equipment": plant.tank,
    }


# --- emir --------------------------------------------------------------------------------------


def test_create_update_approve_order(plant, planner):
    api = client(planner)

    response = api.post(url("order-list"), order_body(plant, "2000"), format="json")
    assert response.status_code == 201, response.data
    body = response.data
    assert body["number"].startswith("UE-")
    assert body["status"] == "DRAFT"
    assert body["product_code"] == "BULASIK"
    assert body["production_location_code"] == "URETIM"

    # Durum PATCH ile değişmez.
    response = api.patch(
        url("order-detail", body["id"]),
        {"status": "COMPLETED", "planned_quantity": "1500"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == "DRAFT"
    assert response.data["planned_base_quantity"] == "1500.0000"

    response = api.post(url("order-approve", body["id"]), {}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "APPROVED"
    codes = [(r["material_code"], r["required_quantity"]) for r in response.data["requirements"]]
    assert codes == [("LAS", "900.0000"), ("SLES", "450.0000"), ("SU", "150.0000")]
    assert response.data["allowed_transitions"] == ["CANCELLED", "MATERIAL_PREP"]
    # Hesaplanan miktarlar da JSON'da metin döner (arayüz "600.0000" bekler).
    assert response.json()["remaining_quantity"] == "1500.0000"
    assert response.json()["suggested_batch_quantity"] == "1000.0000"

    listing = api.get(url("order-list"), {"status": "APPROVED"})
    assert [row["id"] for row in listing.data["results"]] == [body["id"]]


def test_business_errors_are_400_with_code(plant, planner):
    api = client(planner)
    order = approved_order(plant, planner)

    response = api.post(url("order-approve", order.pk), {}, format="json")

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"


# --- hazırlama ---------------------------------------------------------------------------------


def test_pick_by_scanned_lot_number_and_mark_ready(plant, planner, depo):
    api = client(depo)
    order = approved_order(plant, planner)
    detail = api.get(url("order-detail", order.pk)).data
    rows = {r["material_code"]: r for r in detail["requirements"]}

    suggestions = api.get(
        url("order-pick-suggestions", order.pk), {"requirement": rows["LAS"]["id"]}
    )
    assert [s["lot_no"] for s in suggestions.data] == [plant.lots["las"].lot_no]

    for code in ("LAS", "SLES"):
        response = api.post(
            url("order-picks", order.pk),
            {
                "requirement": rows[code]["id"],
                "lot_no": plant.lots[code.lower()].lot_no.lower(),
                "quantity": rows[code]["required_quantity"],
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["to_location_code"] == "URETIM"

    response = api.post(url("order-mark-ready", order.pk))
    assert response.status_code == 200, response.data
    assert response.data["status"] == "MATERIAL_READY"
    assert all(r["is_ready"] for r in response.data["requirements"])
    assert len(response.data["picks"]) == 2


def test_quarantine_lot_scan_is_rejected(plant, planner, depo):
    api = client(depo)
    order = approved_order(plant, planner)
    quarantined = stocked_lot(
        "50", material=plant.las, location=plant.quarantine, status=Lot.Status.QUARANTINE
    )
    requirement = plant.requirement(order, plant.las)

    response = api.post(
        url("order-picks", order.pk),
        {"requirement": requirement.pk, "lot_no": quarantined.lot_no, "quantity": "10"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "lot_not_released"


def test_unknown_lot_scan_is_rejected(plant, planner, depo):
    api = client(depo)
    order = approved_order(plant, planner)
    requirement = plant.requirement(order, plant.las)

    response = api.post(
        url("order-picks", order.pk),
        {"requirement": requirement.pk, "lot_no": plant.lots["sles"].lot_no, "quantity": "10"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "lot_not_found"


# --- şarj ve tartım ----------------------------------------------------------------------------


def test_batch_start_weigh_finish(plant, planner, depo, operator):
    api = client(operator)
    order = ready_order(plant, planner, depo)

    response = api.post(url("batch-list"), {"order": order.pk}, format="json")
    assert response.status_code == 201, response.data
    batch = response.data
    assert batch["batch_no"].startswith("B-")
    assert batch["output_lot_status"] == "QUARANTINE"
    lines = {line["material_code"]: line for line in batch["lines"]}
    assert lines["LAS"]["planned_quantity"] == "600.0000"
    assert lines["LAS"]["state"] == "pending"
    assert [a["location_code"] for a in lines["LAS"]["available"]] == ["URETIM"]
    assert [a["location_code"] for a in lines["SU"]["available"]] == ["DEPO"]

    # Tolerans dışı tartım notsuz reddedilir.
    over = {"requirement": lines["SLES"]["requirement"], "lot_no": plant.lots["sles"].lot_no}
    response = api.post(url("batch-consume", batch["id"]), {**over, "quantity": "310"})
    assert response.status_code == 400
    assert response.data["code"] == "deviation_note_required"

    for code, quantity in (("LAS", "600"), ("SU", "100")):
        response = api.post(
            url("batch-consume", batch["id"]),
            {
                "requirement": lines[code]["requirement"],
                "lot": plant.lots[code.lower() if code != "SU" else "water"].pk,
                "quantity": quantity,
            },
            format="json",
        )
        assert response.status_code == 200, response.data
    response = api.post(
        url("batch-consume", batch["id"]), {**over, "quantity": "297", "note": ""}, format="json"
    )
    assert response.status_code == 200, response.data
    states = {line["material_code"]: line["state"] for line in response.data["lines"]}
    assert states == {"LAS": "ok", "SLES": "ok", "SU": "ok"}
    assert len(response.data["consumptions"]) == 3

    response = api.post(url("batch-finish", batch["id"]), {"output_quantity": "995"}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["status"] == "COMPLETED"
    assert response.data["yield_pct"] == "99.50"
    assert response.data["order_status"] == "QC_PENDING"
    assert response.data["lines"][0]["available"] == []


def test_cancel_batch(plant, planner, depo, operator):
    api = client(operator)
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)

    response = api.post(url("batch-cancel", batch.pk), {"reason": "Yanlış tank"}, format="json")

    assert response.status_code == 200
    assert response.data["status"] == "CANCELLED"
    assert ProductionOrder.objects.get(pk=order.pk).status == "IN_PRODUCTION"
