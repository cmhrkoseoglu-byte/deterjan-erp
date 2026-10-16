from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import pytest

from apps.core.roles import DEPO, LABORATUVAR, SEVKIYAT
from apps.inventory.models import Lot
from apps.masterdata.tests.factories import unit
from apps.quality.models import QualityDecision, Sample
from apps.quality.testing import pass_sample
from apps.returns.tests.factories import Setup

URL = "/api/v1/returns/"
Commit = Callable[[], AbstractContextManager[Any]]

pytestmark = pytest.mark.usefixtures("invariants")


def payload(setup: Setup, quantity: str = "6") -> dict[str, Any]:
    return {
        "customer": setup.customer.pk,
        "return_date": "2026-10-16",
        "reason": "Kapak sızdırıyor",
        "quarantine_location": setup.quarantine.pk,
        "lines": [
            {
                "product": setup.product.pk,
                "lot": setup.lot.pk,
                "quantity": quantity,
                "unit": unit("ADET").pk,
            }
        ],
    }


def test_return_flow_over_api(client_for, setup: Setup, commit: Commit, lab) -> None:
    shipper = client_for(SEVKIYAT)
    created = shipper.post(URL, payload(setup), format="json")
    assert created.status_code == 201, created.data
    assert created.data["number"].startswith("IA-")
    assert created.data["lines"][0]["lot_no"] == setup.lot.lot_no
    pk = created.data["id"]
    with commit():
        response = shipper.post(f"{URL}{pk}/receive/")
    assert response.status_code == 200
    line = response.data["lines"][0]
    assert response.data["status"] == "RECEIVED"
    assert line["base_quantity"] == "6.0000"
    assert line["lot_status"] == Lot.Status.BLOCKED
    assert line["sample_number"].startswith("NM-")
    with commit():
        pass_sample(
            lab, Sample.objects.get(pk=line["sample"]), decision=QualityDecision.Decision.REJECT
        )
    depo = client_for(DEPO)
    with commit():
        scrapped = depo.post(
            f"{URL}{pk}/lines/{line['id']}/scrap/", {"note": "İmha"}, format="json"
        )
    assert scrapped.status_code == 200, scrapped.data
    assert scrapped.data["status"] == "CLOSED"
    assert scrapped.data["lines"][0]["is_scrapped"] is True
    listed = client_for(LABORATUVAR).get(URL, {"lot": setup.lot.pk})
    assert listed.data["count"] == 1


@pytest.mark.parametrize("role", [LABORATUVAR, DEPO])
def test_only_shipping_creates(client_for, setup: Setup, role: str) -> None:
    assert client_for(role).post(URL, payload(setup), format="json").status_code == 403


def test_lab_cannot_receive_or_scrap(client_for, setup: Setup) -> None:
    created = client_for(SEVKIYAT).post(URL, payload(setup), format="json")
    pk = created.data["id"]
    lab = client_for(LABORATUVAR)
    assert lab.post(f"{URL}{pk}/receive/").status_code == 403
    line_id = created.data["lines"][0]["id"]
    assert lab.post(f"{URL}{pk}/lines/{line_id}/scrap/").status_code == 403


def test_business_rule_errors_are_400(client_for, setup: Setup) -> None:
    body = payload(setup)
    body["quarantine_location"] = setup.store.pk
    response = client_for(SEVKIYAT).post(URL, body, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "invalid_quarantine_location"


def test_cancel_draft(client_for, setup: Setup) -> None:
    client = client_for(SEVKIYAT)
    pk = client.post(URL, payload(setup), format="json").data["id"]
    response = client.post(f"{URL}{pk}/cancel/", {"reason": "Yanlış kayıt"}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "CANCELLED"
