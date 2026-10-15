from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory.models import Lot
from apps.inventory.tests.factories import storage_location
from apps.masterdata.tests.factories import MaterialFactory
from apps.quality import services
from apps.quality.models import QualityDecision, Sample, SampleStage
from apps.quality.tests.factories import (
    approved_spec,
    line,
    quarantined_raw_lot,
    sample_with_spec,
    tdef,
)

D = Decimal


def url(name, *args, **query):
    path = reverse(f"quality:{name}", args=args)
    if query:
        path += "?" + "&".join(f"{key}={value}" for key, value in query.items())
    return path


@pytest.fixture
def lab_client(lab):
    client = APIClient()
    client.force_authenticate(lab)
    return client


@pytest.fixture
def manager_client(manager):
    client = APIClient()
    client.force_authenticate(manager)
    return client


# --- yetki -----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["test-list", "specification-list", "sample-list", "sample-queue"])
def test_reads_need_login_only(name, client_for):
    assert APIClient().get(url(name)).status_code == 401
    assert client_for("depo").get(url(name)).status_code == 200


@pytest.mark.parametrize("role", ["depo", "uretim", "planlama", "yonetim", "dolum"])
def test_writes_require_lab(role, client_for, lab):
    client = client_for(role)
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    ph = line(sample, "PH")
    assert client.post(url("test-list"), {}, format="json").status_code == 403
    assert client.post(url("specification-list"), {}, format="json").status_code == 403
    assert client.post(url("sample-list"), {}, format="json").status_code == 403
    assert (
        client.post(
            url("sample-results", sample.pk), {"spec_line": ph.pk, "numeric_value": "7"}
        ).status_code
        == 403
    )
    assert client.post(url("sample-decide", sample.pk), {"decision": "RELEASE"}).status_code == 403
    assert client.post(url("sample-cancel", sample.pk), {"reason": "x"}).status_code == 403


def test_review_requires_management(lab, lab_client, manager_client):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("8.3"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Berrak")
    decision = services.decide(
        lab,
        sample,
        QualityDecision.Decision.CONDITIONAL_RELEASE,
        "Sınırda",
        release_location=storage_location(),
    )
    path = url("decision-review", decision.pk)
    assert lab_client.post(path, {"approve": True}, format="json").status_code == 403
    response = manager_client.post(path, {"approve": True, "note": "Uygun"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["approval_status"] == "APPROVED"
    lot.refresh_from_db()
    assert lot.status == Lot.Status.RELEASED


# --- spesifikasyon ---------------------------------------------------------------------------


def test_specification_lifecycle_via_api(lab_client):
    material = MaterialFactory()
    response = lab_client.post(
        url("specification-list"),
        {
            "material": material.pk,
            "sample_stage": "INCOMING",
            "change_note": "İlk sürüm",
            "lines": [
                {"test": tdef("PH").pk, "min_value": "6", "max_value": "8"},
                {"test": tdef("RENK").pk, "is_mandatory": False},
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    spec = response.json()
    assert spec["status"] == "DRAFT" and spec["version_no"] == 1 and len(spec["lines"]) == 2
    response = lab_client.post(
        url("specification-lines", spec["id"]),
        {"test": tdef("VISK").pk, "max_value": "1500"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["sequence"] == 3
    renk = next(row for row in spec["lines"] if row["test"] == tdef("RENK").pk)
    assert lab_client.delete(url("spec-line-detail", renk["id"])).status_code == 204
    bad = lab_client.post(
        url("specification-lines", spec["id"]), {"test": tdef("PH").pk}, format="json"
    )
    assert bad.status_code == 400
    response = lab_client.post(url("specification-approve", spec["id"]), {}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "APPROVED"
    response = lab_client.post(url("specification-copy", spec["id"]), {}, format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["version_no"] == 2 and response.json()["status"] == "DRAFT"
    listed = lab_client.get(url("specification-list", material=material.pk)).json()
    assert listed["count"] == 2


# --- numune akışı ----------------------------------------------------------------------------


def test_sample_flow_via_api(lab, lab_client):
    lot, quarantine = quarantined_raw_lot("25")
    approved_spec(lab, lot.material)
    target = storage_location()
    response = lab_client.post(
        url("sample-list"), {"lot": lot.pk, "stage": "INCOMING"}, format="json"
    )
    assert response.status_code == 201, response.json()
    sample_id = response.json()["id"]
    queue = lab_client.get(url("sample-queue")).json()
    assert [row["id"] for row in queue["results"]] == [sample_id]
    detail = lab_client.get(url("sample-detail", sample_id)).json()
    assert [row["line"]["test_code"] for row in detail["lines"]] == ["PH", "GORUNUS", "RENK"]
    assert detail["missing_tests"] == ["PH", "GORUNUS"]
    lines = {row["line"]["test_code"]: row["line"]["id"] for row in detail["lines"]}

    response = lab_client.post(
        url("sample-results", sample_id),
        {"spec_line": lines["PH"], "numeric_value": "9.1"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "IN_TEST"
    assert response.json()["out_of_spec_tests"] == ["PH"]
    response = lab_client.post(
        url("sample-results", sample_id),
        {"spec_line": lines["PH"], "numeric_value": "7.0"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["code"] == "correction_reason_required"
    lab_client.post(
        url("sample-results", sample_id),
        {"spec_line": lines["PH"], "numeric_value": "7.0", "note": "Yanlış okuma"},
        format="json",
    )
    lab_client.post(
        url("sample-results", sample_id),
        {"spec_line": lines["GORUNUS"], "text_value": "Berrak"},
        format="json",
    )
    detail = lab_client.get(url("sample-detail", sample_id)).json()
    ph_row = detail["lines"][0]
    assert ph_row["current"]["numeric_value"] == "7.0000"
    assert len(ph_row["history"]) == 1 and ph_row["history"][0]["is_within_spec"] is False
    assert detail["missing_tests"] == [] and detail["out_of_spec_tests"] == []
    assert detail["coa_available"] is False

    response = lab_client.post(
        url("sample-decide", sample_id),
        {"decision": "RELEASE", "release_location": target.pk},
        format="json",
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "DECIDED" and body["coa_available"] is True
    assert body["decisions"][0]["decision"] == "RELEASE"
    lot.refresh_from_db()
    assert lot.status == Lot.Status.RELEASED
    assert lab_client.get(url("sample-queue")).json()["count"] == 0
    assert lab_client.get(url("sample-list", lot=lot.pk)).json()["count"] == 1

    response = lab_client.get(url("sample-coa", sample_id))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert lot.lot_no in response["Content-Disposition"]


def test_decision_errors_return_codes(lab, lab_client):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    response = lab_client.post(url("sample-decide", sample.pk), {"decision": "RELEASE"})
    assert response.status_code == 400
    assert response.json()["code"] == "mandatory_tests_missing"
    assert lab_client.get(url("sample-coa", sample.pk)).status_code == 400


def test_cancel_and_assign_via_api(lab, lab_client):
    lot, _q = quarantined_raw_lot()
    response = lab_client.post(
        url("sample-list"), {"lot": lot.pk, "stage": "INCOMING"}, format="json"
    )
    sample_id = response.json()["id"]
    assert response.json()["specification"] is None
    spec = approved_spec(lab, lot.material)
    response = lab_client.post(
        url("sample-assign-specification", sample_id), {"specification": spec.pk}
    )
    assert response.status_code == 200, response.json()
    assert response.json()["specification"] == spec.pk
    response = lab_client.post(url("sample-cancel", sample_id), {"reason": "Mükerrer"})
    assert response.status_code == 200
    assert Sample.objects.get(pk=sample_id).status == Sample.Status.CANCELLED


def test_sample_filters(lab, lab_client):
    raw, _q = quarantined_raw_lot()
    sample_with_spec(lab, raw)
    other, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, other)
    services.cancel_sample(lab, sample, "x")
    assert lab_client.get(url("sample-list", open="true")).json()["count"] == 1
    assert lab_client.get(url("sample-list", status="CANCELLED")).json()["count"] == 1
    assert lab_client.get(url("sample-list", stage=SampleStage.FINAL)).json()["count"] == 0
