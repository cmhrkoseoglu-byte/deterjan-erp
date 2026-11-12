"""Canlıda istek başına veritabanı işlemi yoktur (`ATOMIC_REQUESTS` kapalı): satır kilitleyen her
servis kendi işlemini açmalıdır. Testler normalde bir işlemin içinde koştuğu için eksik işlem fark
edilmez. Buradaki test, canlı gibi dış işlem olmadan üretim akışını uç noktalardan yürütür; şarj
bitirme işlemsiz kalınca (`select_for_update` işlem dışında) 500 dönüyordu."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import User
from apps.inventory.models import Lot
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.tests.factories import ensure_standard_units
from apps.production.models import ProductionBatch, ProductionOrder
from apps.production.tests.factories import build_plant, order_data

D = Decimal


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def url(name: str, *args: Any) -> str:
    return reverse(f"production:{name}", args=args)


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.content[:500]
    return response.json()


@pytest.mark.django_db(transaction=True)
def test_production_flow_runs_without_a_surrounding_transaction(
    make_user: Callable[..., User],
) -> None:
    ensure_standard_units()
    planner = make_user("planlama", username="planlama")
    depo = make_user("depo", username="depo")
    operator = make_user("uretim", username="uretim")
    plant = build_plant(planner)
    data = order_data(plant)
    payload = {
        "recipe_version": data["recipe_version"].pk,
        "planned_quantity": str(data["planned_quantity"]),
        "unit": data["unit"].pk,
        "planned_date": data["planned_date"].isoformat(),
        "equipment": data["equipment"].pk,
    }

    order = ok(api(planner).post(url("order-list"), payload, format="json"), 201)
    ok(api(planner).post(url("order-approve", order["id"]), {"note": ""}, format="json"))
    ok(api(depo).post(url("order-start-prep", order["id"])))
    detail = ok(api(depo).get(url("order-detail", order["id"])))
    for row in detail["requirements"]:
        if row["is_water"]:
            continue
        lot = Lot.objects.filter(material_id=row["material"], status=Lot.Status.RELEASED).first()
        assert lot is not None
        ok(
            api(depo).post(
                url("order-picks", order["id"]),
                {"requirement": row["id"], "lot": lot.pk, "quantity": row["required_quantity"]},
                format="json",
            ),
            201,
        )
    ok(api(depo).post(url("order-mark-ready", order["id"])))

    batch = ok(api(operator).post(url("batch-list"), {"order": order["id"]}, format="json"), 201)
    for row in detail["requirements"]:
        lot = Lot.objects.filter(material_id=row["material"], status=Lot.Status.RELEASED).first()
        assert lot is not None
        ok(
            api(operator).post(
                url("batch-consume", batch["id"]),
                {
                    "requirement": row["id"],
                    "lot": lot.pk,
                    "quantity": row["required_quantity"],
                    "note": "",
                },
                format="json",
            )
        )
    finished = ok(
        api(operator).post(
            url("batch-finish", batch["id"]), {"output_quantity": "1000", "note": ""}, format="json"
        )
    )

    assert finished["status"] == ProductionBatch.Status.COMPLETED
    assert ProductionOrder.objects.get(pk=order["id"]).status == ProductionOrder.Status.QC_PENDING
    assert_stock_invariants()
