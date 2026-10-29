"""Özlük belgeleri: kimlik fotokopisi, bordro, sözleşme, diploma (servisler ve API)."""

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import selectors, services
from apps.personnel.models import Employee, EmployeeDocument
from apps.personnel.tests.factories import PDF, document, employee, pdf

pytestmark = pytest.mark.django_db
URL = "/api/v1/personnel/documents/"
Kind = EmployeeDocument.Kind


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


@pytest.fixture
def card(manager: User) -> Employee:
    return employee(manager, hire_date=date(2024, 3, 1))


def _notes(card: Employee) -> list[str]:
    return list(selectors.employee_history(card).values_list("note", flat=True))


def test_add_documents_by_kind(manager: User, card: Employee) -> None:
    payroll = document(manager, card, Kind.PAYROLL, file=pdf("eylul.pdf"), period=date(2026, 9, 15))
    assert payroll.period == date(2026, 9, 1)  # dönem ayın ilk günü
    assert payroll.valid_from is None and payroll.valid_until is None
    assert payroll.mime_type == "application/pdf" and payroll.size == len(PDF)
    assert payroll.original_name == "eylul.pdf"
    stored = str(payroll.file.name)
    assert stored.startswith("personnel/") and "eylul" not in stored
    assert payroll.created_by == manager

    contract = document(
        manager,
        card,
        Kind.CONTRACT,
        file=pdf("sozlesme.pdf"),
        valid_from=date(2024, 3, 1),
        period=date(2026, 9, 1),  # türüne uymayan alan yok sayılır
        note="  Belirsiz   süreli ",
    )
    assert contract.period is None and contract.valid_until is None
    assert contract.note == "Belirsiz süreli"
    photo = SimpleUploadedFile("kimlik.JPG", b"\xff\xd8\xff" + b"0" * 64)
    id_copy = document(manager, card, Kind.ID_COPY, file=photo, valid_from=date(2024, 1, 1))
    assert id_copy.mime_type == "image/jpeg" and id_copy.valid_from is None

    assert _notes(card)[:3] == [
        "Belge eklendi: Kimlik fotokopisi (kimlik.JPG)",
        "Belge eklendi: Sözleşme 01.03.2024 – belirsiz süreli (sozlesme.pdf)",
        "Belge eklendi: Bordro 09.2026 (eylul.pdf)",
    ]
    log = AuditLog.objects.get(object_id=payroll.pk, action=AuditLog.Action.CREATE)
    assert log.changes["kind"] == [None, "PAYROLL"]


def test_document_rules(manager: User, card: Employee, settings: Any) -> None:
    cases: list[tuple[dict[str, Any], str]] = [
        ({"kind": Kind.PAYROLL}, "period_required"),
        ({"kind": Kind.CONTRACT}, "valid_from_required"),
        (
            {
                "kind": Kind.CONTRACT,
                "valid_from": date(2025, 1, 1),
                "valid_until": date(2024, 12, 31),
            },
            "invalid_contract_dates",
        ),
        ({"kind": "OTHER"}, "invalid_kind"),
        ({"kind": Kind.DIPLOMA, "file": pdf("diploma.docx")}, "file_type_not_allowed"),
        ({"kind": Kind.DIPLOMA, "file": pdf("bos.pdf", b"")}, "file_empty"),
    ]
    for data, code in cases:
        with pytest.raises(BusinessRuleError) as exc:
            services.add_document(manager, card, **{"file": pdf(), **data})
        assert exc.value.code == code
    settings.ATTACHMENT_MAX_BYTES = 10
    with pytest.raises(BusinessRuleError) as exc:
        document(manager, card)
    assert exc.value.code == "file_too_large"
    assert not EmployeeDocument.objects.exists()

    # Belirli süreli sözleşme: bitiş başlangıçla aynı gün olabilir.
    settings.ATTACHMENT_MAX_BYTES = 1024
    contract = document(
        manager, card, Kind.CONTRACT, valid_from=date(2025, 1, 1), valid_until=date(2025, 1, 1)
    )
    assert contract.valid_until == date(2025, 1, 1)


def test_terminated_employee_can_receive_documents(manager: User, card: Employee) -> None:
    left = services.terminate_employee(manager, card, date(2026, 9, 30))
    final = document(manager, left, Kind.PAYROLL, period=date(2026, 9, 1))
    assert final.employee == left


def test_remove_document(manager: User, card: Employee) -> None:
    diploma = document(manager, card, file=pdf("diploma.pdf"))
    with pytest.raises(BusinessRuleError) as exc:
        services.remove_document(manager, diploma, "   ")
    assert exc.value.code == "reason_required"

    removed = services.remove_document(manager, diploma, "  Yanlış   kişiye yüklendi ")
    assert not removed.is_active and removed.removed_by == manager
    assert removed.removal_reason == "Yanlış kişiye yüklendi" and removed.removed_at
    assert _notes(card)[0] == (
        "Belge kaldırıldı: Diploma (diploma.pdf). Neden: Yanlış kişiye yüklendi"
    )
    assert list(selectors.employee_documents(card)) == []
    with pytest.raises(BusinessRuleError) as exc:
        services.remove_document(manager, removed, "Tekrar")
    assert exc.value.code == "already_removed"
    with pytest.raises(ValueError):
        removed.delete()
    assert EmployeeDocument.objects.filter(pk=diploma.pk).exists()


def test_documents_are_ordered_by_period_and_start(manager: User, card: Employee) -> None:
    august = document(manager, card, Kind.PAYROLL, period=date(2026, 8, 1))
    september = document(manager, card, Kind.PAYROLL, period=date(2026, 9, 1))
    july = document(manager, card, Kind.PAYROLL, period=date(2026, 7, 1))
    first = document(manager, card, Kind.CONTRACT, valid_from=date(2024, 3, 1))
    second = document(manager, card, Kind.CONTRACT, valid_from=date(2025, 3, 1))
    payrolls = [d for d in selectors.employee_documents(card) if d.kind == Kind.PAYROLL]
    contracts = [d for d in selectors.employee_documents(card) if d.kind == Kind.CONTRACT]
    assert payrolls == [september, august, july]
    assert contracts == [second, first]


@pytest.mark.parametrize("role", ["depo", "planlama", "uretim", "laboratuvar", "satin_alma"])
def test_only_management_and_admin_handle_documents(
    make_user: Callable[..., User], manager: User, card: Employee, role: str
) -> None:
    diploma = document(manager, card)
    other = make_user(role)
    with pytest.raises(PermissionDenied):
        document(other, card)
    with pytest.raises(PermissionDenied):
        services.remove_document(other, diploma, "Neden")
    with pytest.raises(PermissionDenied):
        services.record_document_access(other, diploma)
    admin = make_user("admin")
    assert services.remove_document(admin, diploma, "Eski belge").is_active is False


# --- API ------------------------------------------------------------------------------------------


@pytest.fixture
def api(manager: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(manager)
    return client


def _upload(client: APIClient, card: Employee, **extra: object):
    data = {"employee": card.pk, "kind": "PAYROLL", "file": pdf("eylul.pdf"), **extra}
    return client.post(URL, data, format="multipart")


def test_upload_list_download_and_remove(api: APIClient, card: Employee) -> None:
    created = _upload(api, card, period="2026-09", note="Eylül bordrosu")
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["kind_display"] == "Bordro" and body["period"] == "2026-09-01"
    assert body["uploaded_by_name"] and body["note"] == "Eylül bordrosu"
    assert body["download_url"] == f"{URL}{body['id']}/download/"
    assert "file" not in body  # dosya yolu verilmez

    listed = api.get(URL, {"employee": card.pk})
    assert listed.status_code == 200 and [d["id"] for d in listed.json()] == [body["id"]]

    download = api.get(body["download_url"])
    assert download.status_code == 200 and download.getvalue() == PDF
    assert download["Content-Type"] == "application/pdf"
    assert download["Content-Disposition"].startswith("inline")
    assert download["X-Content-Type-Options"] == "nosniff"
    assert download["Content-Security-Policy"].startswith("default-src 'none'")
    assert download["Cache-Control"] == "no-store"
    forced = api.get(body["download_url"], {"download": "1"})
    assert forced["Content-Disposition"].startswith("attachment")
    history = api.get(f"/api/v1/personnel/employees/{card.pk}/history/").json()
    assert [entry["note"] for entry in history[:2]] == [
        "Belge açıldı: Bordro 09.2026 (eylul.pdf)",
        "Belge açıldı: Bordro 09.2026 (eylul.pdf)",
    ]

    response = api.post(f"{URL}{body['id']}/remove/", {"reason": " "})
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    response = api.post(f"{URL}{body['id']}/remove/", {"reason": "Yanlış ay"})
    assert response.status_code == 200, response.json()
    assert api.get(URL, {"employee": card.pk}).json() == []
    assert api.get(body["download_url"]).status_code == 404
    assert api.post(f"{URL}{body['id']}/remove/", {"reason": "X"}).status_code == 404


def test_upload_and_list_errors(api: APIClient, card: Employee) -> None:
    response = api.get(URL)
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    response = api.get(URL, {"employee": 999999})
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    response = _upload(api, card)
    assert response.status_code == 400 and response.json()["code"] == "period_required"
    response = _upload(api, card, period="2026-13")
    assert response.status_code == 400 and response.json()["code"] == "validation_error"
    response = _upload(
        api, card, kind="CONTRACT", valid_from="2025-02-01", valid_until="2025-01-31"
    )
    assert response.status_code == 400 and response.json()["code"] == "invalid_contract_dates"
    response = api.post(URL, {"employee": card.pk, "kind": "DIPLOMA"}, format="multipart")
    assert response.status_code == 400 and "file" in response.json()["errors"]
    assert api.delete(f"{URL}1/").status_code == 405


def test_generic_attachments_do_not_accept_personnel_cards(api: APIClient, card: Employee) -> None:
    for target in ("personnel.employee", "personnel.employeedocument"):
        params = {"content_type": target, "object_id": str(card.pk)}
        response = api.get("/api/v1/attachments/", params)
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_record_type"
        upload = {**params, "kind": "DOCUMENT", "file": pdf()}
        response = api.post("/api/v1/attachments/", upload, format="multipart")
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_record_type"


@pytest.mark.parametrize(
    "role", ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]
)
def test_other_roles_cannot_reach_documents(
    client_for: Callable[..., APIClient], manager: User, card: Employee, role: str
) -> None:
    diploma = document(manager, card)
    client = client_for(role)
    assert client.get(URL, {"employee": card.pk}).status_code == 403
    assert client.get(f"{URL}{diploma.pk}/").status_code == 403
    assert client.get(f"{URL}{diploma.pk}/download/").status_code == 403
    assert client.post(f"{URL}{diploma.pk}/remove/", {"reason": "X"}).status_code == 403
    assert _upload(client, card, period="2026-09").status_code == 403
    assert EmployeeDocument.objects.filter(is_active=True).count() == 1
    assert not [note for note in _notes(card) if note.startswith("Belge açıldı")]
