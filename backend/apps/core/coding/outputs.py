"""Çıktı doküman kodları (ISO 9001 md. 7.5): basılı çıktılarda doküman no, yayın tarihi,
revizyon no ve tarihi (docs/plan/kodlama-sistematigi.md §6.1).

ISO bir kod biçimi istemez; kodlar firmanın kalite yönetim sisteminin doküman listesinden girilir.
Her çıktı başlangıçta kapalıdır (çıktı bugünkü gibi basılır). Admin doküman no ve en az bir revizyon
girip "çıktıya basılsın"ı açınca bant basılır. Yeniden basım ilk basımdaki gibidir (CUMHUR,
2026-11-05): belge kendi tarihindeki bant durumuyla ve o tarihte yürürlükte olan (o güne kadar
girilmiş) revizyonun saklanan doküman no ve ilk yayın tarihiyle basılır. Bu yüzden ilk
revizyondan sonra doküman no ve ilk yayın tarihi yalnız yeni revizyonla değişir.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from apps.core.audit import log_change
from apps.core.coding.registry import OutputType, output_type, output_types
from apps.core.coding.services import require_admin
from apps.core.exceptions import BusinessRuleError
from apps.core.models import (
    AuditLog,
    OutputBandChange,
    OutputDocument,
    OutputDocumentRevision,
    User,
)
from apps.core.services import save_with_audit

# KYS doküman numaraları: FR-KAL-001, F.KAL.01, PR/01 gibi.
DOC_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9./-]{0,31}$")
MAX_REVISION = 99
# Hatalı yazılan tarih (ör. 0026 yılı) revizyonlar değiştirilemediği için geri alınamaz.
EARLIEST_DATE = date(2000, 1, 1)
# Çıktı ayarı değişiklikleri sırayla (doküman no tekliği, ilk kaydın açılışı, revizyonlar).
_OUTPUT_LOCK_ID = 730102


def _day(value: date | None) -> str:
    """15.11.2026: yıl her zaman dört hane."""
    return f"{value.day:02d}.{value.month:02d}.{value.year:04d}" if value else "—"


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
    """Çıktı basılırken belgenin tarihindeki (`on`, yoksa bugün) doküman kontrol bilgisi: o gün
    bant açıktıysa o gün yürürlükte olan ve o güne kadar sisteme girilmiş revizyon, revizyonun
    saklanan doküman no ve ilk yayın tarihiyle (yeniden basım ilk basımdaki gibidir; geriye
    tarihli girilen revizyon, girildiği günden önceki tarihli belgeleri değiştirmez). O gün bant
    kapalıysa (henüz açılmamışsa) ya da yürürlükte revizyon yoksa None: belge bantsız basılır.
    Kayıtsız çıktı geliştirme hatasıdır (anahtar yazım hatası): fırlatır, böylece üreticinin testi
    yakalar."""
    if output_type(key) is None:
        raise ImproperlyConfigured(f"Kayıtsız çıktı: {key}")
    on = on or timezone.localdate()
    # Aynı gün birden çok değişiklikte sonuncusu geçerlidir.
    band_on = (
        OutputBandChange.objects.filter(output__key=key, effective_date__lte=on)
        .order_by("-effective_date", "-pk")
        .values_list("is_active", flat=True)
        .first()
    )
    if not band_on:
        return None
    # Belgenin günü bitmeden girilmemiş revizyon o gün basılamazdı (`created_at` yerel güne göre).
    revision = (
        OutputDocumentRevision.objects.filter(
            output__key=key, revision_date__lte=on, created_at__date__lte=on
        )
        .order_by("-revision_no")
        .first()
    )
    if revision is None or not revision.doc_code:
        return None
    return DocumentControl(
        doc_code=revision.doc_code,
        first_issue_date=revision.first_issue_date,
        revision_no=revision.revision_no,
        revision_date=revision.revision_date,
    )


def _revision_dict(revision: OutputDocumentRevision) -> dict[str, Any]:
    user = revision.created_by
    return {
        "id": revision.pk,
        "revision_no": revision.revision_no,
        "revision_date": revision.revision_date,
        "doc_code": revision.doc_code,
        "first_issue_date": revision.first_issue_date,
        "change_note": revision.change_note,
        "approved_by_name": revision.approved_by_name,
        "approved_on": revision.approved_on,
        "template_version": revision.template_version,
        "created_at": revision.created_at,
        "created_by_name": (user.full_name or user.username) if user else "",
    }


def _rows() -> QuerySet[OutputDocument]:
    """Çıktı kayıtları, revizyonları (en yeniden eskiye) önceden alınmış."""
    return OutputDocument.objects.prefetch_related(
        Prefetch(
            "revisions",
            queryset=OutputDocumentRevision.objects.select_related("created_by").order_by(
                "-revision_no"
            ),
        )
    )


def describe_output(
    item: OutputType, row: OutputDocument | None = None, *, with_row: bool = True
) -> dict[str, Any]:
    """Kodlama ekranındaki çıktı satırı. `row` verilmezse okunur (`with_row=False`: kaydın
    olmadığı biliniyor, yeniden sorulmaz); verilen `row` `_rows()` ile okunmuş olmalıdır."""
    if row is None and with_row:
        row = _rows().filter(key=item.key).first()
    revisions = list(row.revisions.all()) if row is not None else []
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
        # İlk revizyondan sonra doküman no ve ilk yayın tarihi yalnız yeni revizyonla değişir.
        "doc_locked": bool(revisions),
        "is_active": bool(row and row.is_active),
        "revision_no": latest.revision_no if latest else None,
        "revision_date": latest.revision_date if latest else None,
        "template_version": item.template_version,
        # Şablon kodda değişti ama yeni revizyon girilmedi: ekran uyarır.
        "template_changed": bool(latest and latest.template_version < item.template_version),
        "revisions": [_revision_dict(revision) for revision in revisions],
    }


def overview() -> list[dict[str, Any]]:
    """Bütün kayıtlı çıktılar (sabit sayıda sorgu: kayıtlar ve revizyonları)."""
    rows = {row.key: row for row in _rows()}
    return [describe_output(item, rows.get(item.key), with_row=False) for item in output_types()]


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
        raise BusinessRuleError(
            "note_required", "Değişiklik notu yazın (denetim günlüğüne yazılır)."
        )
    return note


def _doc_code(value: str, *, allow_blank: bool) -> str:
    """Büyük harfe çevrilmiş ve biçimi denetlenmiş doküman no (`allow_blank`: boş, doküman no
    yok demektir)."""
    code = value.strip().upper()
    if (code or not allow_blank) and not DOC_CODE_RE.match(code):
        raise BusinessRuleError(
            "invalid_doc_code",
            "Doküman no harf ya da rakamla başlamalı; yalnızca A-Z, 0-9, -, . ve / içermelidir "
            "(en fazla 32 karakter).",
        )
    return code


def _check_code_free(row: OutputDocument, code: str) -> None:
    """Doküman no çıktılar arasında tektir: başka bir çıktının bugünkü numarası da revizyonlarına
    yazılmış numarası da (bant hiç açılmamış olsa da) verilmez."""
    if OutputDocument.objects.filter(doc_code=code).exclude(pk=row.pk).exists():
        raise BusinessRuleError(
            "output_code_taken", "Bu doküman numarası başka bir çıktıda kullanılıyor."
        )
    if OutputDocumentRevision.objects.filter(doc_code=code).exclude(output=row).exists():
        raise BusinessRuleError(
            "output_code_taken",
            "Bu doküman numarası başka bir çıktının revizyonlarında kullanıldı; başka çıktıya "
            "verilemez.",
        )


def _check_date(value: date, future_message: str) -> None:
    if value > timezone.localdate():
        raise BusinessRuleError("future_date", future_message)
    if value < EARLIEST_DATE:
        raise BusinessRuleError("invalid_date", "Tarih 01.01.2000'den önce olamaz.")


def _doc_locked() -> BusinessRuleError:
    return BusinessRuleError(
        "output_doc_locked",
        "Doküman no ve ilk yayın tarihi ilk revizyondan sonra yalnız yeni revizyonla değişir.",
    )


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
    zorunlu). Doküman no çıktılar arasında tektir; ilk yayın tarihi ileri bir tarih ya da
    01.01.2000'den önce olamaz. İlk revizyondan sonra doküman no ve ilk yayın tarihi yalnız yeni
    revizyonla değişir (`add_revision`; aynı değeri göndermek değişiklik sayılmaz). Bandı açmak
    için doküman no, ilk yayın tarihi ve en az bir revizyon gerekir. Bandı açmak ya da kapatmak
    bugünden geçerli bir bant kaydı yazar: önceki tarihli belgeler o günkü durumlarıyla basılır."""
    require_admin(actor)
    item = _get_output(key)
    note = _note(note)
    row = _row(item, actor)
    locked = row.revisions.exists()
    if doc_code is not None and doc_code.strip().upper() != row.doc_code:
        if locked:
            raise _doc_locked()
        code = _doc_code(doc_code, allow_blank=True)
        if code:
            _check_code_free(row, code)
        row.doc_code = code
    if first_issue_date is not None and first_issue_date != row.first_issue_date:
        if locked:
            raise _doc_locked()
        _check_date(first_issue_date, "İlk yayın tarihi ileri bir tarih olamaz.")
        row.first_issue_date = first_issue_date
    band_changed = is_active is not None and is_active != row.is_active
    if is_active is not None:
        row.is_active = is_active
    if row.is_active and (not row.doc_code or row.first_issue_date is None or not locked):
        raise BusinessRuleError(
            "output_not_ready",
            "Bandı açmak için önce doküman no, ilk yayın tarihi ve en az bir revizyon "
            "girilmelidir.",
        )
    row = save_with_audit(row, actor, note=note)
    if band_changed:
        OutputBandChange.objects.create(
            output=row,
            is_active=row.is_active,
            effective_date=timezone.localdate(),
            created_by=actor,
        )
    return row


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
    doc_code: str | None = None,
    first_issue_date: date | None = None,
) -> OutputDocumentRevision:
    """Yeni revizyon ekler (yalnız admin). İlk revizyonun numarası seçilebilir (varsayılan 00;
    kalite sisteminde revizyonu ilerlemiş form, ör. Rev. 03, olduğu gibi girilir), sonrakiler birer
    artar. Revizyon onaylandıktan sonra yürürlüğe girer: onay tarihi yürürlük tarihinden sonra,
    yürürlük tarihi ileri bir tarih, 01.01.2000'den, önceki revizyondan ve ilk yayın tarihinden
    önce olamaz. Değişiklik açıklaması, onaylayan ve onay tarihi zorunludur. Revizyonlar
    değiştirilemez. Geriye tarihli revizyon, girildiği günden önceki tarihli belgelere basılmaz
    (o belgeler ilk basımdaki gibi kalır; `document_control`).

    Doküman no ve ilk yayın tarihi yeni revizyonla değişir (`doc_code`, `first_issue_date`;
    `update_output`'taki gibi denetlenir, ilk yayın tarihi ilk revizyondan sonra olamaz): çıktı
    kaydına değişiklik açıklamasıyla yazılır. Revizyon o anki doküman no ve ilk yayın tarihini
    saklar; belge, tarihinde yürürlükte olan revizyonun bu bilgileriyle basılır. İlk revizyon için
    ikisi de kayıtlı olmalı ya da bu çağrıda verilmelidir."""
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
    if revision_date < EARLIEST_DATE or approved_on < EARLIEST_DATE:
        raise BusinessRuleError("invalid_date", "Tarih 01.01.2000'den önce olamaz.")
    if approved_on > revision_date:
        raise BusinessRuleError(
            "approval_after_effective",
            "Onay tarihi yürürlük tarihinden sonra olamaz (revizyon onaylanınca yürürlüğe girer).",
        )
    new_code = _doc_code(doc_code, allow_blank=False) if doc_code is not None else None
    if first_issue_date is not None:
        _check_date(first_issue_date, "İlk yayın tarihi ileri bir tarih olamaz.")
    row = _row(item, actor)
    previous = OutputDocumentRevision.objects.filter(output=row).order_by("-revision_no").first()
    code = row.doc_code if new_code is None else new_code
    issue = row.first_issue_date if first_issue_date is None else first_issue_date
    if previous is None and (not code or issue is None):
        raise BusinessRuleError(
            "revision_needs_doc", "İlk revizyon için doküman no ve ilk yayın tarihi girilmelidir."
        )
    if code != row.doc_code:
        _check_code_free(row, code)
    if previous is not None and revision_date < previous.revision_date:
        raise BusinessRuleError(
            "revision_date_invalid", "Revizyon tarihi önceki revizyondan önce olamaz."
        )
    if issue is not None and revision_date < issue:
        raise BusinessRuleError(
            "revision_date_invalid", "Revizyon tarihi ilk yayın tarihinden önce olamaz."
        )
    if previous is not None and issue != row.first_issue_date:
        first = (
            OutputDocumentRevision.objects.filter(output=row)
            .order_by("revision_date", "revision_no")
            .first()
        )
        if first is not None and issue is not None and issue > first.revision_date:
            raise BusinessRuleError(
                "issue_after_revision", "İlk yayın tarihi ilk revizyonun tarihinden sonra olamaz."
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
    note = f"Yeni revizyon {number:02d}: {change_note}"
    if code != row.doc_code or issue != row.first_issue_date:
        row.doc_code = code
        row.first_issue_date = issue
        row = save_with_audit(row, actor, note=note)
    revision = OutputDocumentRevision.objects.create(
        output=row,
        revision_no=number,
        revision_date=revision_date,
        doc_code=code,
        first_issue_date=issue,
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
        note,
    )
    return revision
