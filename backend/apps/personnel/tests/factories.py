"""Personel testleri için yardımcılar (kartlar ve belgeler servislerle açılır)."""

from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models import User
from apps.personnel import services
from apps.personnel.models import Employee, EmployeeDocument

PDF = b"%PDF-1.4\n" + b"0" * 64


def employee(actor: User, **overrides: Any) -> Employee:
    """Varsayılan: dolum biriminde, sistemi kullanmayan bir operatör."""
    data = {
        "full_name": "Ayşe Demir",
        "department": "Dolum",
        "title": "Dolum operatörü",
        **overrides,
    }
    return services.create_employee(actor, data)


def pdf(name: str = "belge.pdf", content: bytes = PDF) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def document(
    actor: User, card: Employee, kind: str = EmployeeDocument.Kind.DIPLOMA, **overrides: Any
) -> EmployeeDocument:
    """Varsayılan: PDF diploma."""
    data = {"file": pdf(), **overrides}
    return services.add_document(actor, card, kind=kind, **data)
