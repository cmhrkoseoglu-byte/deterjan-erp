import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from apps.golive.models import ProblemReport, StockComparison
from apps.inventory import services as inventory
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.tests.factories import MaterialFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

READINESS = reverse("golive:readiness")
GO_LIVE = reverse("golive:go-live")
COMPARISONS = reverse("golive:comparison-list")
PROBLEMS = reverse("golive:problem-list")


def stock_file(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Malzeme kodu", "Miktar"])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile("stok.xlsx", buffer.getvalue())


@pytest.mark.parametrize("role,code", [("depo", 200), ("yonetim", 200), ("dolum", 403)])
def test_readiness_permissions(client_for, role, code):
    response = client_for(role).get(READINESS)
    assert response.status_code == code
    if code == 200:
        assert {c["code"] for c in response.json()} >= {"users", "opening_stock"}


def test_anonymous_gets_401(api_client):
    assert api_client.get(READINESS).status_code in (401, 403)
    assert api_client.post(PROBLEMS, {"description": "x"}).status_code in (401, 403)


def test_go_live_date_set_by_management_only(client_for):
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert client_for("depo").put(GO_LIVE, {"go_live_date": tomorrow}).status_code == 403
    response = client_for("yonetim").put(GO_LIVE, {"go_live_date": tomorrow}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json() == {"go_live_date": tomorrow, "opening_open": True}

    today = timezone.localdate().isoformat()
    client_for("admin").put(GO_LIVE, {"go_live_date": today}, format="json")
    assert client_for("depo").get(GO_LIVE).json()["opening_open"] is False
    assert not inventory.opening_is_open()


def test_opening_import_closed_after_go_live(client_for):
    inventory.set_go_live_date(None, timezone.localdate())  # type: ignore[arg-type]
    MaterialFactory(code="HM-A")
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Malzeme kodu", "Lot no", "Lokasyon kodu", "Miktar"])
    sheet.append(["HM-A", "L1", "YOK", 1])
    buffer = io.BytesIO()
    workbook.save(buffer)
    upload = SimpleUploadedFile("a.xlsx", buffer.getvalue())
    response = client_for("depo").post(reverse("inventory:opening-import"), {"file": upload})
    assert response.status_code == 400
    assert response.json()["code"] == "opening_closed"


def test_comparison_flow(client_for):
    material = MaterialFactory(code="HM-LAS")
    stocked_lot("10", material=material)
    depo = client_for("depo")

    assert client_for("planlama").post(COMPARISONS, {"file": stock_file([])}).status_code == 403
    bad = depo.post(COMPARISONS, {"file": stock_file([["HM-YOK", 1]])})
    assert bad.status_code == 400
    assert bad.json()["report"]["rows"][0]["errors"][0]["column"] == "Malzeme kodu"

    created = depo.post(COMPARISONS, {"file": stock_file([["HM-LAS", 7]]), "note": "1. hafta"})
    assert created.status_code == 201, created.json()
    body = created.json()
    assert (body["difference_count"], body["level"], body["note"]) == (1, "MATERIAL", "1. hafta")

    planlama = client_for("planlama")
    assert planlama.get(COMPARISONS).json()["count"] == 1
    lines = planlama.get(reverse("golive:comparison-lines", args=[body["id"]]))
    assert lines.json()["results"][0]["difference"] == "3.0000"
    only = planlama.get(
        reverse("golive:comparison-lines", args=[body["id"]]), {"only_differences": "true"}
    )
    assert only.json()["count"] == 1
    export = planlama.get(reverse("golive:comparison-export", args=[body["id"]]))
    assert export.status_code == 200
    assert export["Content-Disposition"].endswith(f'{body["number"]}.xlsx"')
    assert planlama.get(reverse("golive:comparison-template")).status_code == 200
    assert client_for("sevkiyat").get(COMPARISONS).status_code == 403
    assert StockComparison.objects.count() == 1


def test_problem_reports_visible_to_reporter_and_admin(client_for, make_user):
    dolum = client_for("dolum")
    png = SimpleUploadedFile("e.png", b"\x89PNG0000", content_type="image/png")
    response = dolum.post(
        PROBLEMS,
        {"description": "Tartım ekranı donuyor", "page_url": "/uretim", "screenshot": png},
    )
    assert response.status_code == 201, response.json()
    report_id = response.json()["id"]
    assert response.json()["has_screenshot"] is True

    assert dolum.get(PROBLEMS).json()["count"] == 1
    assert dolum.get(reverse("golive:problem-screenshot", args=[report_id])).status_code == 200
    other = client_for("dolum")
    assert other.get(PROBLEMS).json()["count"] == 0
    assert other.get(reverse("golive:problem-detail", args=[report_id])).status_code == 404
    assert other.get(reverse("golive:problem-screenshot", args=[report_id])).status_code == 404
    admin = client_for("admin")
    assert admin.get(PROBLEMS).json()["results"][0]["description"] == "Tartım ekranı donuyor"

    assert dolum.post(PROBLEMS, {"description": ""}).status_code == 400
    assert ProblemReport.objects.count() == 1
