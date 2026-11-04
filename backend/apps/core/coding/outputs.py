"""Çıktı doküman kodları (ISO 9001 md. 7.5): basılı çıktılarda doküman no, yayın tarihi,
revizyon no ve tarihi (docs/plan/kodlama-sistematigi.md §6.1).

ISO bir kod biçimi istemez; kodlar firmanın kalite yönetim sisteminin doküman listesinden girilir.
Her çıktı başlangıçta kapalıdır (çıktı bugünkü gibi basılır). Admin doküman no ve en az bir revizyon
girip "çıktıya basılsın"ı açınca bant basılır. Belge, kendi tarihinde yürürlükte olan revizyonla
basılır (yeniden basımda da).
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.utils import timezone

from apps.core.audit import log_change
from apps.core.coding.registry import OutputType, output_type, output_types
from apps.core.coding.services import require_admin
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, OutputDocument, OutputDocumentRevision, User
from apps.core.services import save_with_audit

# KYS doküman numaraları: FR-KAL-001, F.KAL.01, PR/01 gibi.
DOC_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9./-]{0,31}$")
MAX_REVISION = 99
# Çıktı ayarı değişiklikleri sırayla (doküman no tekliği, ilk kaydın açılışı).
_OUTPUT_LOCK_ID = 730102


def _day(value: date | None) -> str:
    return f"{value:%d.%m.%Y}" if value else "—"


@dataclass(frozen=True)
class DocumentControl:
    """Bir çıktının basılacağı doküman kontrol bilgisi."""

    doc_code: str
    first_issue_date: date | None
    revision_no: int
    revision_date: date

    @property
    def revision_text(self) -> str:
        return f"{self.revision_no:02d}"

    def band(self, page: int | None = None, total: int | None = None) -> str:
        """ "Doküman no: FR-KAL-001 · Yayın tarihi: 15.11.2026 · Rev. no: 01 · Rev. tarihi: … ·
        Sayfa 1/2"."""
        parts = [
            f"Doküman no: {self.doc_code}",
            f"Yayın tarihi: {_day(self.first_issue_date)}",
            f"Rev. no: {self.revision_text}",
            f"Rev. tarihi: {_day(self.revision_date)}",
        ]
        if page is not None and total is not None:
            parts.append(f"Sayfa {page}/{total}")
        return " · ".join(parts)

    def short(self) -> str:
        """Dosya özellikleri ve denetim notu için: "FR-KAL-001 Rev.01"."""
        return f"{self.doc_code} Rev.{self.revision_text}"


def document_control(key: str, *, on: date | None = None) -> DocumentControl | None:
    """Çıktı basılırken: bant açık ve doküman no girilmişse belgenin tarihinde (`on`, yoksa bugün)
    yürürlükte olan revizyon. Bant kapalıysa ya da o tarihte yürürlükte revizyon yoksa None (çıktı
    bugünkü gibi basılır). Kayıtsız çıktı geliştirme hatasıdır (anahtar yazım hatası): fırlatır,
    böylece üreticinin testi yakalar."""
    if output_type(key) is None:
        raise ImproperlyConfigured(f"Kayıtsız çıktı: {key}")
    row = OutputDocument.objects.filter(key=key, is_active=True).exclude(doc_code="").first()
    if row is None:
        return None
    on = on or timezone.localdate()
    revision = (
        OutputDocumentRevision.objects.filter(output=row, revision_date__lte=on)
        .order_by("-revision_no")
        .first()
    )
    if revision is None:
        return None
    return DocumentControl(
        doc_code=row.doc_code,
        first_issue_date=row.first_issue_date,
        revision_no=revision.revision_no,
        revision_date=revision.revision_date,
    )


def _revision_dict(revision: OutputDocumentRevision) -> dict[str, Any]:
    user = revision.created_by
    return {
        "id": revision.pk,
        "revision_no": revision.revision_no,
        "revision_date": revision.revision_date,
        "change_note": revision.change_note,
        "approved_by_name": revision.approved_by_name,
        "approved_on": revision.approved_on,
        "template_version": revision.template_version,
        "created_at": revision.created_at,
        "created_by_name": (user.full_name or user.username) if user else "",
    }


def describe_output(item: OutputType, row: OutputDocument | None = None) -> dict[str, Any]:
    """Kodlama ekranındaki çıktı satırı."""
    if row is None:
        row = OutputDocument.objects.filter(key=item.key).first()
    revisions = (
        list(
            OutputDocumentRevision.objects.filter(output=row)
            .select_related("created_by")
            .order_by("-revision_no")
        )
        if row is not None
        else []
    )
    latest = revisions[0] if revisions else None
    return {
        "key": item.key,
        "label": item.label,
        "group": item.group,
        "formats": list(item.formats),
        "legal": item.legal,
        "suggested_code": item.suggested_code,
        "doc_code": row.doc_code if row else "",
        "first_issue_date": row.first_issue_date if row else None,
        "is_active": bool(row and row.is_active),
        "revision_no": latest.revision_no if latest else None,
        "revision_date": latest.revision_date if latest else None,
        "template_version": item.template_version,
        # Şablon kodda değişti ama yeni revizyon girilmedi: ekran uyarır.
        "template_changed": bool(latest and latest.template_version < item.template_version),
        "revisions": [_revision_dict(revision) for revision in revisions],
    }


def overview() -> list[dict[str, Any]]:
    rows = {row.key: row for row in OutputDocument.objects.all()}
    return [describe_output(item, rows.get(item.key)) for item in output_types()]


def _get_output(key: str) -> OutputType:
    item = output_type(key)
    if item is None:
        raise BusinessRuleError("unknown_output", "Tanımsız çıktı.")
    return item


def _lock() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_OUTPUT_LOCK_ID])


def _row(item: OutputType, actor: User) -> OutputDocument:
    _lock()
    row = OutputDocument.objects.select_for_update().filter(key=item.key).first()
    if row is None:
        row = save_with_audit(OutputDocument(key=item.key), actor, note="Çıktı kaydı açıldı")
    return row


def _note(note: str) -> str:
    note = (note or "").strip()
    if not note:
        raise BusinessRuleError("note_required", "Değişiklik notu yazın (geçmişte görünür).")
    return note


@transaction.atomic
def update_output(
    actor: User,
    key: str,
    *,
    note: str,
    doc_code: str | None = None,
    first_issue_date: date | None = None,
    is_active: bool | None = None,
) -> OutputDocument:
    """Çıktının doküman no, ilk yayın tarihi ve bant ayarını değiştirir (yalnız admin; not
    zorunlu). Doküman no çıktılar arasında tektir; bandı açmak için doküman no, ilk yayın tarihi ve
    en az bir revizyon gerekir; ilk yayın tarihi ileri bir tarih ve ilk revizyondan sonra
    olamaz."""
    require_admin(actor)
    item = _get_output(key)
    note = _note(note)
    row = _row(item, actor)
    if doc_code is not None:
        code = doc_code.strip().upper()
        if code and not DOC_CODE_RE.match(code):
            raise BusinessRuleError(
                "invalid_doc_code",
                "Doküman no harf ya da rakamla başlamalı; yalnızca A-Z, 0-9, -, . ve / içermelidir "
                "(en fazla 32 karakter).",
            )
        if code and OutputDocument.objects.filter(doc_code=code).exclude(pk=row.pk).exists():
            raise BusinessRuleError(
                "output_code_taken", "Bu doküman numarası başka bir çıktıda kullanılıyor."
            )
        row.doc_code = code
    if first_issue_date is not None:
        if first_issue_date > timezone.localdate():
            raise BusinessRuleError("future_date", "İlk yayın tarihi ileri bir tarih olamaz.")
        first = row.revisions.order_by("revision_date").first()
        if first is not None and first_issue_date > first.revision_date:
            raise BusinessRuleError(
                "issue_after_revision", "İlk yayın tarihi ilk revizyonun tarihinden sonra olamaz."
            )
        row.first_issue_date = first_issue_date
    if is_active is not None:
        row.is_active = is_active
    if row.is_active and (
        not row.doc_code or row.first_issue_date is None or not row.revisions.exists()
    ):
        raise BusinessRuleError(
            "output_not_ready",
            "Bandı açmak için önce doküman no, ilk yayın tarihi ve en az bir revizyon "
            "girilmelidir.",
        )
    return save_with_audit(row, actor, note=note)


@transaction.atomic
def add_revision(
    actor: User,
    key: str,
    *,
    revision_date: date,
    change_note: str,
    approved_by_name: str,
    approved_on: date,
    revision_no: int | None = None,
) -> OutputDocumentRevision:
    """Yeni revizyon ekler (yalnız admin). İlk revizyonun numarası seçilebilir (varsayılan 00;
    kalite sisteminde revizyonu ilerlemiş form, ör. Rev. 03, olduğu gibi girilir), sonrakiler birer
    artar. Revizyon onaylandıktan sonra yürürlüğe girer: onay tarihi yürürlük tarihinden sonra,
    yürürlük tarihi ileri bir tarih, önceki revizyondan ve ilk yayın tarihinden önce olamaz.
    Değişiklik açıklaması, onaylayan ve onay tarihi zorunludur. Revizyonlar değiştirilemez."""
    require_admin(actor)
    item = _get_output(key)
    change_note = (change_note or "").strip()
    approved_by_name = (approved_by_name or "").strip()
    if not change_note:
        raise BusinessRuleError("change_note_required", "Değişiklik açıklaması girilmelidir.")
    if not approved_by_name:
        raise BusinessRuleError("approver_required", "Onaylayan girilmelidir.")
    today = timezone.localdate()
    if revision_date > today or approved_on > today:
        raise BusinessRuleError("future_date", "Revizyon ve onay tarihi ileri bir tarih olamaz.")
    if approved_on > revision_date:
        raise BusinessRuleError(
            "approval_after_effective",
            "Onay tarihi yürürlük tarihinden sonra olamaz (revizyon onaylanınca yürürlüğe girer).",
        )
    row = _row(item, actor)
    previous = OutputDocumentRevision.objects.filter(output=row).order_by("-revision_no").first()
    if previous is not None and revision_date < previous.revision_date:
        raise BusinessRuleError(
            "revision_date_invalid", "Revizyon tarihi önceki revizyondan önce olamaz."
        )
    if row.first_issue_date is not None and revision_date < row.first_issue_date:
        raise BusinessRuleError(
            "revision_date_invalid", "Revizyon tarihi ilk yayın tarihinden önce olamaz."
        )
    if previous is not None:
        number = previous.revision_no + 1
        if revision_no is not None and revision_no != number:
            raise BusinessRuleError(
                "revision_no_invalid", f"Sıradaki revizyon {number:02d} olmalıdır."
            )
    else:
        number = 0 if revision_no is None else revision_no
    if not 0 <= number <= MAX_REVISION:
        raise BusinessRuleError(
            "revision_no_invalid", f"Revizyon no 00-{MAX_REVISION} arasında olmalıdır."
        )
    revision = OutputDocumentRevision.objects.create(
        output=row,
        revision_no=number,
        revision_date=revision_date,
        change_note=change_note,
        approved_by_name=approved_by_name,
        approved_on=approved_on,
        template_version=item.template_version,
        created_by=actor,
    )
    log_change(
        actor,
        row,
        AuditLog.Action.CUSTOM,
        {"revision_no": [previous.revision_no if previous else None, number]},
        f"Yeni revizyon {number:02d}: {change_note}",
    )
    return revision
