"""Raporlama servisleri: rapor çıktısı (Excel/PDF) ve arka plan işleri (Faz 4, Adım 4.3).

- `SYNC_ROW_LIMIT` satıra kadar dosya istek içinde üretilir ve hemen iner.
- Daha büyük rapor `ReportJob` olarak Celery'de hazırlanır; bitince `report_job.done` olayı
  yayınlanır, iş akışı modülü isteyene bildirim gönderir (indirme bağlantısı bildirimin
  bağlı olduğu kayıttır).
- Dosyalar `FILE_RETENTION_DAYS` gün saklanır; sabah 07:00 kontrolünde (`system.daily_check`)
  süresi dolan dosyalar silinir, iş kaydı `EXPIRED` olarak kalır.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.services import save_with_audit
from apps.reporting import exports, filters, state
from apps.reporting.models import ReportJob
from apps.reporting.reports import (
    ReportDefinition,
    can_view,
    get_report,
    visible_columns,
    visible_summary,
)
from apps.reporting.selectors import Rows

logger = logging.getLogger(__name__)

SYNC_ROW_LIMIT = 5000
PDF_ROW_LIMIT = 10000
FILE_RETENTION_DAYS = 7
CONTENT_TYPES: dict[str, str] = {
    ReportJob.Format.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ReportJob.Format.PDF: "application/pdf",
}


@dataclass(frozen=True)
class ReportFile:
    content: bytes
    file_name: str
    content_type: str


@dataclass(frozen=True)
class ReportData:
    definition: ReportDefinition
    columns: list[Any]
    rows: Rows
    summary: list[dict[str, Any]]
    filters: list[tuple[str, str]]


def report_or_error(code: str) -> ReportDefinition:
    definition = get_report(code)
    if definition is None:
        raise BusinessRuleError("unknown_report", "Böyle bir rapor yok.")
    return definition


def report_data(definition: ReportDefinition, actor: User, values: dict[str, Any]) -> ReportData:
    """Raporu kullanıcının yetkisine göre hazırlar: görünür sütunlar, satırlar, özet."""
    rows = definition.rows(values)
    summary = definition.summary(rows) if definition.summary else []
    return ReportData(
        definition=definition,
        columns=visible_columns(definition, actor),
        rows=rows,
        summary=visible_summary(definition, actor, summary),
        filters=filters.describe(values),
    )


def file_name(definition: ReportDefinition, file_format: str, at: datetime | None = None) -> str:
    stamp = timezone.localtime(at or timezone.now())
    return f"{definition.code}-{stamp:%Y%m%d-%H%M}.{file_format}"


def render(data: ReportData, file_format: str) -> ReportFile:
    """Rapor dosyasını üretir."""
    definition = data.definition
    if file_format == ReportJob.Format.PDF:
        content = exports.to_pdf(
            definition.title,
            data.columns,
            data.rows,
            filters=data.filters,
            summary=data.summary,
            wide=definition.landscape,
        )
    elif file_format == ReportJob.Format.XLSX:
        content = exports.to_xlsx(
            definition.title, data.columns, data.rows, filters=data.filters, summary=data.summary
        )
    else:
        raise BusinessRuleError("unknown_format", "Dosya biçimi Excel ya da PDF olmalıdır.")
    return ReportFile(content, file_name(definition, file_format), CONTENT_TYPES[file_format])


def export_report(
    actor: User, definition: ReportDefinition, values: dict[str, Any], file_format: str
) -> ReportFile | ReportJob:
    """Raporu dışa aktarır. Küçük rapor dosya olarak döner; `SYNC_ROW_LIMIT` satırı aşan rapor
    için arka plan işi açılır (dosya hazır olunca bildirim gelir).

    Kurallar: rapor kullanıcının rolüne açık olmalı (`report_forbidden`); PDF en fazla
    `PDF_ROW_LIMIT` satır (`pdf_too_large`, Excel önerilir)."""
    if not can_view(definition, actor):
        raise BusinessRuleError("report_forbidden", "Bu raporu görme yetkiniz yok.")
    if file_format not in ReportJob.Format.values:
        raise BusinessRuleError("unknown_format", "Dosya biçimi Excel ya da PDF olmalıdır.")
    data = report_data(definition, actor, values)
    count = len(data.rows)
    if file_format == ReportJob.Format.PDF and count > PDF_ROW_LIMIT:
        raise BusinessRuleError(
            "pdf_too_large",
            f"Rapor {count} satır; PDF en fazla {PDF_ROW_LIMIT} satır olabilir. Filtreyi "
            "daraltın ya da Excel alın.",
        )
    if count <= SYNC_ROW_LIMIT:
        log_change(
            actor,
            None,
            AuditLog.Action.CUSTOM,
            {"report": definition.code, "format": file_format, "rows": count},
            note=f"Rapor indirildi: {definition.title}",
        )
        return render(data, file_format)
    return create_job(actor, definition, values, file_format)


@transaction.atomic
def create_job(
    actor: User, definition: ReportDefinition, values: dict[str, Any], file_format: str
) -> ReportJob:
    """Arka plan işi açar; Celery görevi commit sonrası kuyruğa girer."""
    job = save_with_audit(
        ReportJob(
            report_code=definition.code,
            title=definition.title,
            file_format=file_format,
            params=filters.to_params(values),
        ),
        actor,
        note="Rapor arka planda hazırlanacak.",
    )
    from apps.reporting.tasks import run_report_job

    transaction.on_commit(lambda: run_report_job.delay(job.pk))
    return job


def _transition(job: ReportJob, new: str, **fields: Any) -> ReportJob:
    if not state.can_transition(job.status, new):
        raise BusinessRuleError(
            "invalid_transition",
            f"Rapor işi {job.get_status_display()} durumundan "
            f"{ReportJob.Status(new).label} durumuna geçemez.",
        )
    job.status = new
    for name, value in fields.items():
        setattr(job, name, value)
    return save_with_audit(job, None)


def _job_payload(job: ReportJob) -> dict[str, Any]:
    return {
        "model": "reporting.reportjob",
        "id": job.pk,
        "repr": str(job),
        "report_code": job.report_code,
        "title": job.title,
        "file_format": job.file_format,
        "row_count": job.row_count,
        "requested_by_id": job.created_by_id,
        "error": job.error,
    }


def run_job(job_id: int) -> ReportJob:
    """Arka plan işini çalıştırır (Celery görevi çağırır). Hata işi `FAILED` yapar ve isteyene
    bildirim gider; hata yukarı fırlatılmaz (görev tekrar denenmez)."""
    with transaction.atomic():
        job = (
            ReportJob.objects.select_for_update(of=("self",))
            .select_related("created_by")
            .get(pk=job_id)
        )
        if job.status != ReportJob.Status.QUEUED:
            return job
        job = _transition(job, ReportJob.Status.RUNNING, started_at=timezone.now())
    try:
        definition = report_or_error(job.report_code)
        actor = job.created_by
        if actor is None or not can_view(definition, actor):
            raise BusinessRuleError("report_forbidden", "Bu raporu görme yetkiniz yok.")
        values = filters.parse_filters(definition, job.params)
        data = report_data(definition, actor, values)
        count = len(data.rows)
        output = render(data, job.file_format)
    except Exception as exc:  # noqa: BLE001 - her hata işi kapatır ve bildirilir
        logger.exception("Rapor işi başarısız: %s", job_id)
        message = exc.message if isinstance(exc, BusinessRuleError) else "Rapor hazırlanamadı."
        with transaction.atomic():
            job = _transition(
                job, ReportJob.Status.FAILED, error=message, finished_at=timezone.now()
            )
            events.publish(ev.REPORT_JOB_FAILED, _job_payload(job))
        return job
    with transaction.atomic():
        now = timezone.now()
        job.file.save(output.file_name, ContentFile(output.content), save=False)
        job = _transition(
            job,
            ReportJob.Status.DONE,
            file_name=output.file_name,
            row_count=count,
            finished_at=now,
            expires_at=now + timedelta(days=FILE_RETENTION_DAYS),
        )
        events.publish(ev.REPORT_JOB_DONE, _job_payload(job))
    return job


def expire_jobs(now: datetime | None = None) -> int:
    """Saklama süresi dolan dosyaları siler; iş kaydı `EXPIRED` olarak kalır."""
    now = now or timezone.now()
    count = 0
    for job in ReportJob.objects.filter(status=ReportJob.Status.DONE, expires_at__lt=now):
        with transaction.atomic():
            if job.file:
                job.file.delete(save=False)
            _transition(job, ReportJob.Status.EXPIRED, file="")
            count += 1
    return count
