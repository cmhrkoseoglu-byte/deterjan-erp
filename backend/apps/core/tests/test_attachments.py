"""Ekler (Adım 2.4): yükleme, listeleme, indirme, kaldırma ve kurallar."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import Attachment, AuditLog
from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA
from apps.core.services import add_attachment, remove_attachment
from apps.inventory.tests.factories import stocked_lot
from apps.workflow.services import add_comment

URL = "/api/v1/attachments/"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _upload(client: APIClient, target: str, object_id: int, **extra: object):
    data = {
        "content_type": target,
        "object_id": object_id,
        "file": SimpleUploadedFile("foto.png", PNG, content_type="image/png"),
        "kind": "PHOTO",
        **extra,
    }
    return client.post(URL, data, format="multipart")


@pytest.mark.django_db
def test_upload_list_download_and_remove_on_lot(make_user) -> None:
    lot = stocked_lot()
    user = make_user(DEPO)
    client = APIClient()
    client.force_authenticate(user)

    created = _upload(client, "inventory.lot", lot.pk, note="Tedarikçi etiketi")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["original_name"] == "foto.png"
    assert body["kind"] == "PHOTO" and body["kind_display"] == "Fotoğraf"
    assert body["size"] == len(PNG) and body["mime_type"] == "image/png"
    assert body["can_remove"] is True

    listed = client.get(URL, {"content_type": "inventory.lot", "object_id": str(lot.pk)})
    assert [item["id"] for item in listed.json()] == [body["id"]]

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.getvalue() == PNG
    assert download["Content-Disposition"].startswith("inline")
    assert download["X-Content-Type-Options"] == "nosniff"
    forced = client.get(body["download_url"], {"download": "1"})
    assert forced["Content-Disposition"].startswith("attachment")

    removed = client.post(f"{URL}{body['id']}/remove/", {"reason": "Yanlış dosya"})
    assert removed.status_code == 200
    assert removed.json()["is_active"] is False
    assert client.get(URL, {"content_type": "inventory.lot", "object_id": str(lot.pk)}).json() == []
    assert client.get(body["download_url"]).status_code == 404
    # Ek silinmez; dosya ve kayıt durur, admin hâlâ indirebilir.
    attachment = Attachment.objects.get(pk=body["id"])
    assert attachment.removed_by == user and attachment.removal_reason == "Yanlış dosya"
    with pytest.raises(ValueError):
        attachment.delete()
    admin = APIClient()
    admin.force_authenticate(make_user("admin"))
    assert admin.get(body["download_url"]).status_code == 200
    everything = admin.get(
        URL, {"content_type": "inventory.lot", "object_id": str(lot.pk), "include_removed": "true"}
    )
    assert len(everything.json()) == 1

    notes = set(
        AuditLog.objects.filter(object_id__in=[lot.pk, body["id"]]).values_list("note", flat=True)
    )
    assert "Dosya eklendi: foto.png" in notes and "Ek kaldırıldı" in notes


@pytest.mark.django_db
def test_goods_receipt_and_sample_types_are_registered(make_user) -> None:
    from apps.core.attachments import attachment_targets

    assert {"inventory.lot", "inventory.goodsreceipt", "quality.sample", "workflow.comment"} <= set(
        attachment_targets()
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("target", "code"),
    [("core.user", "invalid_record_type"), ("inventory.stockmovement", "invalid_record_type")],
)
def test_unregistered_types_are_rejected(client_for, target, code) -> None:
    response = _upload(client_for(DEPO), target, 1)
    assert response.status_code == 400 and response.json()["code"] == code


@pytest.mark.django_db
def test_missing_record_is_rejected(client_for) -> None:
    response = _upload(client_for(DEPO), "inventory.lot", 999999)
    assert response.status_code == 400 and response.json()["code"] == "record_not_found"


@pytest.mark.django_db
def test_disallowed_extension_and_size(make_user, settings) -> None:
    lot = stocked_lot()
    user = make_user(DEPO)
    bad = SimpleUploadedFile("script.exe", b"MZ" * 10, content_type="application/octet-stream")
    with pytest.raises(BusinessRuleError) as exc:
        add_attachment(user, target_type="inventory.lot", object_id=lot.pk, file=bad)
    assert exc.value.code == "file_type_not_allowed"

    settings.ATTACHMENT_MAX_BYTES = 10
    big = SimpleUploadedFile("coa.pdf", b"%PDF" + b"0" * 20, content_type="application/pdf")
    with pytest.raises(BusinessRuleError) as exc:
        add_attachment(user, target_type="inventory.lot", object_id=lot.pk, file=big)
    assert exc.value.code == "file_too_large"

    empty = SimpleUploadedFile("bos.pdf", b"", content_type="application/pdf")
    with pytest.raises(BusinessRuleError) as exc:
        add_attachment(user, target_type="inventory.lot", object_id=lot.pk, file=empty)
    assert exc.value.code == "file_empty"
    assert not Attachment.objects.exists()


@pytest.mark.django_db
def test_only_comment_author_attaches_to_comment(make_user) -> None:
    lot = stocked_lot()
    author = make_user(DEPO)
    other = make_user(LABORATUVAR)
    comment = add_comment(author, content_type="inventory.lot", object_id=lot.pk, body="Hasarlı")

    other_client = APIClient()
    other_client.force_authenticate(other)
    denied = _upload(other_client, "workflow.comment", comment.pk)
    assert denied.status_code == 400 and denied.json()["code"] == "attachment_forbidden"

    author_client = APIClient()
    author_client.force_authenticate(author)
    assert _upload(author_client, "workflow.comment", comment.pk).status_code == 201

    comments = author_client.get(
        "/api/v1/workflow/comments/", {"content_type": "inventory.lot", "object_id": str(lot.pk)}
    ).json()
    rows = comments["results"] if isinstance(comments, dict) else comments
    assert [a["original_name"] for a in rows[0]["attachments"]] == ["foto.png"]


@pytest.mark.django_db
def test_only_uploader_or_admin_can_remove(make_user) -> None:
    lot = stocked_lot()
    uploader = make_user(DEPO)
    attachment = add_attachment(
        uploader,
        target_type="inventory.lot",
        object_id=lot.pk,
        file=SimpleUploadedFile("coa.pdf", b"%PDF-1.4", content_type="application/pdf"),
        kind=Attachment.Kind.SUPPLIER_COA,
    )
    with pytest.raises(BusinessRuleError) as exc:
        remove_attachment(make_user(PLANLAMA), attachment)
    assert exc.value.code == "attachment_forbidden"
    removed = remove_attachment(make_user("admin"), attachment, "Mükerrer")
    assert not removed.is_active
    with pytest.raises(BusinessRuleError) as exc:
        remove_attachment(uploader, removed)
    assert exc.value.code == "already_removed"


@pytest.mark.django_db
def test_anonymous_gets_401(api_client) -> None:
    assert api_client.get(URL, {"content_type": "inventory.lot", "object_id": 1}).status_code == 401
    assert api_client.post(URL, {}).status_code == 401
