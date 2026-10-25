"""Kayda bağlı yorum, geçmiş ve eklerin kaydın kendi ekranındaki okuma kuralına uyması
(`core.records`). Kaydı göremeyene kayıt yokmuş gibi davranılır; görüp tutarı göremeyen (lot
maliyeti, sipariş tutarı) geçmişte de tutarı görmez."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core import records
from apps.core.attachments import attachment_targets
from apps.core.models import Attachment, User
from apps.core.services import add_attachment
from apps.golive.services import report_problem
from apps.hse.tests.factories import report
from apps.inventory.services import set_lot_cost
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.tests.factories import MaterialFactory
from apps.purchasing.tests.factories import approved_order, line, raw_material
from apps.sales.tests.factories import draft_order, finished_product
from apps.workflow.models import Comment, Notification
from apps.workflow.services import add_comment

pytestmark = pytest.mark.django_db
BASE = "/api/v1/workflow"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

# Ön yüzde yorum/geçmiş paneli (RecordPanel) açılan kayıt türleri.
PANEL_TYPES = {
    "filling.fillingorder",
    "filling.fillingrun",
    "filling.packagingspec",
    "golive.problemreport",
    "hse.incident",
    "inventory.goodsreceipt",
    "inventory.lot",
    "inventory.stockadjustment",
    "maintenance.maintenanceworkorder",
    "production.productionbatch",
    "production.productionorder",
    "purchasing.purchaseorder",
    "quality.sample",
    "returns.customerreturn",
    "sales.salesorder",
    "sales.shipment",
}


def client(user: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(user)
    return api


def history(user: User, label: str, object_id: int) -> Any:
    return client(user).get(
        f"{BASE}/record-history/", {"content_type": label, "object_id": str(object_id)}
    )


def test_every_panel_and_attachment_type_has_a_read_rule() -> None:
    assert set(records.registered_record_types(commentable=True)) >= PANEL_TYPES
    assert set(attachment_targets()) <= set(records.registered_record_types())


def test_incident_is_visible_only_to_reporter_and_management(
    make_user: Callable[..., User],
) -> None:
    reporter, manager = make_user("depo"), make_user("yonetim", username="mudur")
    outsider = make_user("sevkiyat", username="sevk")
    incident = report(reporter)
    params = {"content_type": "hse.incident", "object_id": str(incident.pk)}
    for user in (reporter, manager, make_user("admin")):
        assert client(user).get(f"{BASE}/record-history/", params).status_code == 200
        assert client(user).get(f"{BASE}/comments/", params).status_code == 200

    response = client(outsider).get(f"{BASE}/record-history/", params)
    assert response.status_code == 400 and response.json()["code"] == "record_not_found"
    response = client(outsider).get(f"{BASE}/comments/", params)
    assert response.status_code == 400 and response.json()["code"] == "record_not_found"
    response = client(outsider).post(f"{BASE}/comments/", {**params, "body": "x"}, format="json")
    assert response.status_code == 400 and response.json()["code"] == "record_not_found"

    # Bildiren yorumda ikisinden de bahseder: kaydı göremeyene bildirim gitmez.
    comment = add_comment(
        reporter,
        content_type="hse.incident",
        object_id=incident.pk,
        body="@mudur @sevk bakar mısınız?",
    )
    assert set(comment.mentions.all()) == {manager}
    assert Notification.objects.filter(recipient=manager).exists()
    assert not Notification.objects.filter(recipient=outsider).exists()
    assert client(outsider).get(f"{BASE}/comments/{comment.pk}/").status_code == 404
    response = client(outsider).patch(
        f"{BASE}/comments/{comment.pk}/", {"body": "y"}, format="json"
    )
    assert response.status_code == 404
    assert client(manager).get(f"{BASE}/comments/{comment.pk}/").status_code == 200

    # @bahsetme önerisi yalnızca kaydı görebilenler.
    names = {
        row["username"]
        for row in client(reporter)
        .get(f"{BASE}/mentionable-users/", {"search": "", **params})
        .json()
    }
    assert "mudur" in names and "sevk" not in names
    response = client(outsider).get(f"{BASE}/mentionable-users/", {"search": "", **params})
    assert response.status_code == 400


def test_incident_attachments_follow_the_incident(make_user: Callable[..., User]) -> None:
    reporter, outsider = make_user("depo"), make_user("sevkiyat")
    incident = report(reporter)
    photo = add_attachment(
        reporter,
        target_type="hse.incident",
        object_id=incident.pk,
        file=SimpleUploadedFile("yara.png", PNG, content_type="image/png"),
    )
    comment = add_comment(reporter, content_type="hse.incident", object_id=incident.pk, body="x")
    comment_file = add_attachment(
        reporter,
        target_type="workflow.comment",
        object_id=comment.pk,
        file=SimpleUploadedFile("not.png", PNG, content_type="image/png"),
    )
    params = {"content_type": "hse.incident", "object_id": str(incident.pk)}
    assert client(reporter).get("/api/v1/attachments/", params).status_code == 200
    assert client(reporter).get(f"/api/v1/attachments/{photo.pk}/download/").status_code == 200

    response = client(outsider).get("/api/v1/attachments/", params)
    assert response.status_code == 400 and response.json()["code"] == "record_not_found"
    for attachment in (photo, comment_file):
        url = f"/api/v1/attachments/{attachment.pk}"
        assert client(outsider).get(f"{url}/").status_code == 404
        assert client(outsider).get(f"{url}/download/").status_code == 404
        assert client(outsider).post(f"{url}/remove/", {"reason": "x"}).status_code == 404
    upload = client(outsider).post(
        "/api/v1/attachments/",
        {
            **params,
            "file": SimpleUploadedFile("x.png", PNG, content_type="image/png"),
        },
        format="multipart",
    )
    assert upload.status_code == 400 and upload.json()["code"] == "record_not_found"
    assert Attachment.objects.count() == 2


def test_problem_report_is_visible_only_to_reporter_and_admin(
    make_user: Callable[..., User],
) -> None:
    reporter = make_user("depo")
    problem = report_problem(reporter, description="Etiket basılmıyor")
    assert history(reporter, "golive.problemreport", problem.pk).status_code == 200
    assert history(make_user("admin"), "golive.problemreport", problem.pk).status_code == 200
    response = history(make_user("yonetim"), "golive.problemreport", problem.pk)
    assert response.status_code == 400


def test_lot_history_hides_cost_from_non_management(make_user: Callable[..., User]) -> None:
    lot = stocked_lot()
    set_lot_cost(None, lot, Decimal("12.5000"), estimated=False, note="Maliyet sürüm 1: gizli")
    manager_entries = history(make_user("yonetim"), "inventory.lot", lot.pk).json()["results"]
    depo_entries = history(make_user("depo"), "inventory.lot", lot.pk).json()["results"]
    assert any("unit_cost" in entry["changes"] for entry in manager_entries)
    assert all("unit_cost" not in entry["changes"] for entry in depo_entries)
    assert all("gizli" not in entry["note"] for entry in depo_entries)
    assert len(depo_entries) == len(manager_entries) - 1


def test_purchase_order_history_hides_prices_from_depo(make_user: Callable[..., User]) -> None:
    manager = make_user("yonetim")
    order = approved_order(manager, [line(raw_material(), "10", "99")])
    buyer = history(make_user("satin_alma"), "purchasing.purchaseorder", order.pk).json()
    depo = history(make_user("depo"), "purchasing.purchaseorder", order.pk).json()
    price_keys = {"approval_total_try", "approval_limit_try", "exchange_rate"}
    assert any(price_keys & set(entry["changes"]) for entry in buyer["results"])
    assert all(not price_keys & set(entry["changes"]) for entry in depo["results"])
    assert history(make_user("uretim"), "purchasing.purchaseorder", order.pk).status_code == 400


def test_sales_order_follows_its_read_roles(make_user: Callable[..., User]) -> None:
    order = draft_order(make_user("sevkiyat"), [(finished_product(), "10", "ADET")])
    assert history(make_user("planlama"), "sales.salesorder", order.pk).status_code == 200
    assert history(make_user("uretim"), "sales.salesorder", order.pk).status_code == 400


@pytest.mark.parametrize("label", ["masterdata.material", "personnel.employee", "core.user"])
def test_unregistered_types_are_rejected_even_for_management(
    make_user: Callable[..., User], label: str
) -> None:
    material = MaterialFactory.create()
    response = history(make_user("yonetim"), label, material.pk)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_record_type"
    assert not Comment.objects.exists()
