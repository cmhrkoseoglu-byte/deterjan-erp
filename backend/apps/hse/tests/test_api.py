import io
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.models import User
from apps.hse import services
from apps.hse.models import Incident
from apps.hse.tests.factories import contractor, hazardous_material, pdf, report, statement
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.tests.factories import MaterialFactory

pytestmark = pytest.mark.django_db
BASE = "/api/v1/hse"


def test_material_hazard_over_api(client_for: Callable[..., APIClient]) -> None:
    lab = client_for("laboratuvar")
    material = MaterialFactory.create()
    url = f"{BASE}/materials/{material.pk}/hazard/"
    empty = client_for("sevkiyat").get(url)
    assert empty.status_code == 200 and empty.json()["pictograms"] == []
    body = {
        "pictograms": ["GHS05", "GHS07"],
        "signal_word": "DANGER",
        "statements": [statement("H314").pk, statement("P280").pk],
    }
    assert client_for("depo").put(url, body, format="json").status_code == 403
    response = lab.put(url, body, format="json")
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["is_hazardous"] is True
    assert data["pictogram_labels"] == ["Aşındırıcı", "Zararlı / tahriş edici"]
    assert data["signal_word_display"] == "Tehlike"
    assert [row["code"] for row in data["statement_rows"]] == ["H314", "P280"]
    response = lab.put(url, {"pictograms": ["GHS05"]}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "signal_word_required"
    listing = client_for("dolum").get(f"{BASE}/material-hazards/", {"pictogram": "GHS05"})
    assert listing.json()["results"][0]["material"] == material.pk


def test_hazard_statements_api(client_for: Callable[..., APIClient]) -> None:
    lab = client_for("laboratuvar")
    listing = client_for("uretim").get(f"{BASE}/hazard-statements/", {"search": "H290"})
    assert listing.json()["results"][0]["text"] == "Metallere karşı aşındırıcı olabilir."
    body = {"code": "H373", "kind": "H", "text": "Organlarda hasara yol açabilir."}
    assert client_for("uretim").post(f"{BASE}/hazard-statements/", body).status_code == 403
    response = lab.post(f"{BASE}/hazard-statements/", body)
    assert response.status_code == 201, response.json()
    pk = response.json()["id"]
    assert lab.post(f"{BASE}/hazard-statements/", body).status_code == 400  # tekrar
    response = lab.patch(f"{BASE}/hazard-statements/{pk}/", {"text": "Yeni metin."})
    assert response.json()["text"] == "Yeni metin."
    assert lab.post(f"{BASE}/hazard-statements/{pk}/deactivate/").json()["is_active"] is False


def test_sds_flow_and_gap_report(
    client_for: Callable[..., APIClient], make_user: Callable[..., User]
) -> None:
    manager = client_for("yonetim")
    depo = client_for("depo")
    material = MaterialFactory.create(code="HM-SDS")
    body = {
        "material": material.pk,
        "revision_no": "3",
        "revision_date": str(timezone.localdate() - timedelta(days=10)),
    }
    assert depo.post(f"{BASE}/sds/", body).status_code == 403
    response = manager.post(f"{BASE}/sds/", body)
    assert response.status_code == 201, response.json()
    sheet = response.json()
    assert sheet["is_current"] is True and sheet["file_count"] == 0
    gaps = depo.get(f"{BASE}/sds-gaps/").json()
    row = next(r for r in gaps if r["material_code"] == "HM-SDS")
    assert row["status"] == "NO_FILE" and row["sds_id"] == sheet["id"]
    # Dosyayı yalnızca yönetim yükler.
    upload = {"content_type": "hse.safetydatasheet", "object_id": sheet["id"], "file": pdf()}
    assert depo.post("/api/v1/attachments/", upload, format="multipart").status_code == 400
    upload["file"] = pdf()
    response = manager.post("/api/v1/attachments/", upload, format="multipart")
    assert response.status_code == 201, response.json()
    gaps = depo.get(f"{BASE}/sds-gaps/").json()
    assert "HM-SDS" not in [r["material_code"] for r in gaps]

    response = manager.post(f"{BASE}/sds/", {**body, "revision_no": "4"})
    assert response.status_code == 201
    current = depo.get(f"{BASE}/sds/", {"material": material.pk, "current": "true"}).json()
    assert [r["revision_no"] for r in current["results"]] == ["4"]
    everything = depo.get(f"{BASE}/sds/", {"material": material.pk}).json()
    assert everything["count"] == 2
    response = manager.patch(f"{BASE}/sds/{sheet['id']}/", {"note": "arşiv"}, format="json")
    assert response.status_code == 200 and response.json()["note"] == "arşiv"

    export = client_for("laboratuvar").get(f"{BASE}/sds-gaps/export/")
    assert export.status_code == 200
    assert export["Content-Disposition"].startswith('attachment; filename="eksik-gbf-')
    sheet_rows = list(load_workbook(io.BytesIO(export.content)).active.values)
    assert sheet_rows[0][0] == "Malzeme kodu"
    assert "HM-SDS" in [r[0] for r in sheet_rows[1:]]  # yeni revizyonun dosyası yok
    assert client_for("uretim").get(f"{BASE}/sds-gaps/").status_code == 403
    assert client_for("uretim").get(f"{BASE}/sds/").status_code == 403


def test_storage_limits_and_utilisation_api(
    client_for: Callable[..., APIClient], make_user: Callable[..., User], invariants: None
) -> None:
    manager_user = make_user("yonetim")
    manager = APIClient()
    manager.force_authenticate(manager_user)
    depo = client_for("depo")
    location = storage_location()
    body = {"location": location.pk, "hazard_class": "GHS05", "max_kg": "100"}
    assert depo.post(f"{BASE}/storage-limits/", body).status_code == 403
    response = manager.post(f"{BASE}/storage-limits/", body)
    assert response.status_code == 201, response.json()
    limit_id = response.json()["id"]
    duplicate = manager.post(f"{BASE}/storage-limits/", body)
    assert duplicate.status_code == 400
    material = hazardous_material(manager_user, ["GHS05"])
    stocked_lot("150", material=material, location=location)
    rows = depo.get(f"{BASE}/storage-utilisation/", {"location": location.pk}).json()
    assert rows[0]["quantity_kg"] == "150.0000" and rows[0]["exceeded"] is True
    assert rows[0]["pct"] == "150.00"
    response = manager.patch(f"{BASE}/storage-limits/{limit_id}/", {"max_kg": "200"})
    assert response.json()["max_kg"] == "200.0000"
    assert manager.post(f"{BASE}/storage-limits/{limit_id}/deactivate/").status_code == 200
    assert depo.get(f"{BASE}/storage-utilisation/").json() == []
    assert client_for("uretim").get(f"{BASE}/storage-utilisation/").status_code == 403
    assert client_for("uretim").get(f"{BASE}/storage-limits/").status_code == 403


def test_waste_api(client_for: Callable[..., APIClient], make_user: Callable[..., User]) -> None:
    manager = client_for("yonetim")
    response = manager.post(
        f"{BASE}/waste-contractors/",
        {
            "name": "Lisanslı Firma",
            "license_no": "L-1",
            "license_valid_until": str(timezone.localdate() - timedelta(days=1)),
        },
    )
    assert response.status_code == 201, response.json()
    firm = response.json()
    assert firm["license_expired"] is True
    body = {
        "waste_code": "070601*",
        "description": "Yıkama suyu",
        "quantity_kg": "120.5",
        "contractor": firm["id"],
        "delivered_on": str(timezone.localdate()),
    }
    response = manager.post(f"{BASE}/waste-records/", body)
    assert response.status_code == 400 and response.json()["code"] == "contractor_license_expired"
    renewed = manager.patch(
        f"{BASE}/waste-contractors/{firm['id']}/",
        {"license_valid_until": str(timezone.localdate() + timedelta(days=30))},
    )
    assert renewed.json()["license_expired"] is False
    response = manager.post(f"{BASE}/waste-records/", body)
    assert response.status_code == 201, response.json()
    record = response.json()
    assert record["number"].startswith("AT-")
    assert record["waste_code"] == "07 06 01*" and record["is_hazardous"] is True
    response = manager.post(f"{BASE}/waste-records/{record['id']}/cancel/", {"reason": ""})
    assert response.status_code == 400
    response = manager.post(f"{BASE}/waste-records/{record['id']}/cancel/", {"reason": "Hata"})
    assert response.json()["status"] == "CANCELLED"
    for role in ("depo", "laboratuvar"):
        client = client_for(role)
        assert client.get(f"{BASE}/waste-records/").status_code == 403
        assert client.post(f"{BASE}/waste-records/", body).status_code == 403
        assert client.get(f"{BASE}/waste-contractors/").status_code == 403


def test_incident_api(client_for: Callable[..., APIClient], make_user: Callable[..., User]) -> None:
    reporter_user = make_user("sevkiyat")
    reporter = APIClient()
    reporter.force_authenticate(reporter_user)
    manager = client_for("yonetim")
    body = {
        "incident_type": "WORK_ACCIDENT",
        "occurred_at": (timezone.now() - timedelta(hours=1)).isoformat(),
        "place": "Yükleme rampası",
        "description": "Palet devrildi.",
        "injury": True,
        "injured_person": "B. Kaya",
        "severity": "MEDIUM",
    }
    response = reporter.post(f"{BASE}/incidents/", body, format="json")
    assert response.status_code == 201, response.json()
    incident = response.json()
    assert incident["number"].startswith("OL-") and incident["status"] == "OPEN"
    assert incident["allowed_transitions"] == ["CANCELLED", "INVESTIGATING"]
    pk = incident["id"]
    # Başka birinin kaydı bildirene görünmez; yönetim hepsini görür.
    report(make_user("dolum"))
    assert reporter.get(f"{BASE}/incidents/").json()["count"] == 1
    assert manager.get(f"{BASE}/incidents/").json()["count"] == 2
    assert reporter.post(f"{BASE}/incidents/{pk}/investigate/", {}).status_code == 403
    response = manager.post(
        f"{BASE}/incidents/{pk}/investigate/", {"root_cause": "Hatalı istif"}, format="json"
    )
    assert response.json()["status"] == "INVESTIGATING"
    response = manager.post(f"{BASE}/incidents/{pk}/close/", {}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "corrective_action_required"
    response = manager.post(
        f"{BASE}/incidents/{pk}/investigation/",
        {"action_owner": "Sevkiyat şefi", "action_due": str(timezone.localdate())},
        format="json",
    )
    assert response.json()["action_owner"] == "Sevkiyat şefi"
    response = manager.post(
        f"{BASE}/incidents/{pk}/close/", {"corrective_action": "İstif eğitimi"}, format="json"
    )
    assert response.json()["status"] == "CLOSED"
    other = Incident.objects.exclude(pk=pk).get()
    response = manager.post(f"{BASE}/incidents/{other.pk}/cancel/", {"reason": "Mükerrer"})
    assert response.json()["status"] == "CANCELLED"

    summary = manager.get(f"{BASE}/summary/").json()
    assert summary["incidents"]["total"] == 1 and summary["incidents"]["injury_count"] == 1
    assert summary["waste"] == []
    assert reporter.get(f"{BASE}/summary/").status_code == 403
    bad = manager.get(f"{BASE}/summary/", {"date_from": "2026-10-10", "date_to": "2026-10-01"})
    assert bad.status_code == 400


def test_settings_api(client_for: Callable[..., APIClient]) -> None:
    assert client_for("depo").get(f"{BASE}/settings/").json() == {"sds_max_age_months": 36}
    response = client_for("yonetim").patch(f"{BASE}/settings/", {"sds_max_age_months": 24})
    assert response.json() == {"sds_max_age_months": 24}
    assert (
        client_for("depo").patch(f"{BASE}/settings/", {"sds_max_age_months": 12}).status_code == 403
    )


def test_waste_summary_in_api(client_for: Callable[..., APIClient], make_user: Callable) -> None:
    user = make_user("yonetim")
    firm = contractor(user)
    services.record_waste(
        user,
        {
            "waste_code": "150110*",
            "description": "Kontamine ambalaj",
            "quantity_kg": Decimal("40"),
            "contractor": firm,
            "delivered_on": timezone.localdate(),
        },
    )
    client = APIClient()
    client.force_authenticate(user)
    waste = client.get(f"{BASE}/summary/").json()["waste"]
    assert waste == [
        {
            "waste_code": "15 01 10*",
            "description": "Kontamine ambalaj",
            "is_hazardous": True,
            "count": 1,
            "quantity_kg": "40.0000",
        }
    ]
