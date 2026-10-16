"""İSG testleri için yardımcılar (kayıtlar servislerle oluşturulur)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models import User
from apps.core.services import add_attachment
from apps.hse import services
from apps.hse.models import HazardStatement, Incident, SafetyDataSheet, WasteContractor
from apps.masterdata.models import Material
from apps.masterdata.tests.factories import MaterialFactory


def statement(code: str) -> HazardStatement:
    """Migration ile yüklenen ifade."""
    return HazardStatement.objects.get(code=code)


def hazardous_material(actor: User, pictograms: list[str] | None = None, **kwargs: Any) -> Material:
    """Tehlike bilgisi girilmiş malzeme (varsayılan: aşındırıcı, GHS05)."""
    material = MaterialFactory.create(**kwargs)
    services.set_material_hazard(
        actor,
        material,
        {"pictograms": pictograms or ["GHS05"], "signal_word": "DANGER"},
    )
    material.refresh_from_db()
    return material


def pdf() -> SimpleUploadedFile:
    return SimpleUploadedFile("gbf.pdf", b"%PDF-1.4 test", content_type="application/pdf")


def sds(
    actor: User,
    material: Material,
    *,
    revision_date: date | None = None,
    valid_until: date | None = None,
    revision_no: str = "1",
    with_file: bool = True,
) -> SafetyDataSheet:
    sheet = services.create_sds(
        actor,
        {
            "material": material,
            "revision_no": revision_no,
            "revision_date": revision_date or timezone.localdate() - timedelta(days=30),
            "valid_until": valid_until,
        },
    )
    if with_file:
        add_attachment(actor, target_type="hse.safetydatasheet", object_id=sheet.pk, file=pdf())
    return sheet


def contractor(actor: User, *, valid_until: date | None = None, **data: Any) -> WasteContractor:
    return services.create_contractor(
        actor,
        {
            "name": "Çevre Geri Dönüşüm A.Ş.",
            "license_no": "LIS-2026-001",
            "license_valid_until": valid_until or timezone.localdate() + timedelta(days=365),
            **data,
        },
    )


def waste_data(firm: WasteContractor, **extra: Any) -> dict[str, Any]:
    return {
        "waste_code": "07 06 01*",
        "description": "Sulu yıkama sıvıları",
        "quantity_kg": Decimal("250"),
        "contractor": firm,
        "delivered_on": timezone.localdate(),
        "document_no": "UATF-123",
        **extra,
    }


def incident_data(**extra: Any) -> dict[str, Any]:
    occurred: datetime = timezone.now() - timedelta(hours=2)
    return {
        "incident_type": Incident.Type.NEAR_MISS,
        "occurred_at": occurred,
        "place": "Hammadde deposu",
        "description": "Forklift raf ayağına çarptı.",
        **extra,
    }


def report(actor: User, **extra: Any) -> Incident:
    return services.report_incident(actor, incident_data(**extra))
