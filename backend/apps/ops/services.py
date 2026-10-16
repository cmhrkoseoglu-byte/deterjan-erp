"""Sistem izleme servisleri (Faz 5, Adım 5.5).

- Yedek servisinin durum dosyalarını (`BACKUP_STATUS_DIR`) içe aktarır.
- Kontrolleri çalıştırır (yedek, geri yükleme testi, disk, sunucu yükü, Celery kuyruğu) ve sorun
  başlayınca `ops.alert`, geçince `ops.recovered` olayını yayınlar. Sorun sürerken aynı uyarı
  `OPS_ALERT_REPEAT_MINUTES` dolmadan tekrar gönderilmez.

Kontrol mantığı `selectors.evaluate_checks` içindedir; bu dosya yalnızca yazar.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core import event_names, events
from apps.ops import selectors
from apps.ops.models import BackupRun, CheckState, Heartbeat

logger = logging.getLogger(__name__)

STATUS_FILES = ("latest-backup.json", "latest-restore-test.json")
CELERY_HEARTBEAT = "celery"


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = parse_datetime(value)
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def import_status_record(data: dict[str, Any]) -> BackupRun | None:
    """Yedek servisinin bir durum kaydını içe aktarır (aynı çalışma ikinci kez eklenmez, günceller).
    Biçim docs/DECISIONS.md "Yedek durum dosyası" bölümündedir. Geçersiz kayıtta None."""
    kind = data.get("kind")
    run_id = str(data.get("run_id") or "")[:32]
    started_at = _parse_time(data.get("started_at"))
    finished_at = _parse_time(data.get("finished_at")) or started_at
    status = data.get("status")
    if (
        kind not in BackupRun.Kind.values
        or not run_id
        or started_at is None
        or finished_at is None
        or status not in BackupRun.Status.values
    ):
        logger.warning("Geçersiz yedek durum kaydı atlandı: %r", data)
        return None
    offsite = data.get("offsite")
    mismatches = data.get("mismatches")
    run, _ = BackupRun.objects.update_or_create(
        kind=kind,
        run_id=run_id,
        defaults={
            "source_run_id": str(data.get("source_run_id") or "")[:32],
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "message": str(data.get("message") or ""),
            "database_bytes": _int(data.get("database_bytes")),
            "media_bytes": _int(data.get("media_bytes")),
            "media_files": _int(data.get("media_files")),
            "tables": _int(data.get("tables")),
            "rows": _int(data.get("rows")),
            "offsite": offsite if offsite in BackupRun.Offsite.values else "disabled",
            "offsite_message": str(data.get("offsite_message") or ""),
            "mismatches": mismatches if isinstance(mismatches, list) else [],
        },
    )
    return run


def ingest_backup_status(directory: str | Path | None = None) -> list[BackupRun]:
    """Durum klasöründeki son yedek ve son geri yükleme testi dosyalarını içe aktarır.
    Klasör yoksa (geliştirme ortamı) hiçbir şey yapmaz."""
    path = Path(directory or settings.BACKUP_STATUS_DIR)
    runs: list[BackupRun] = []
    for name in STATUS_FILES:
        file = path / name
        if not file.is_file():
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Yedek durum dosyası okunamadı: %s", file)
            continue
        if isinstance(data, dict):
            run = import_status_record(data)
            if run is not None:
                runs.append(run)
    return runs


def record_heartbeat(name: str = CELERY_HEARTBEAT) -> None:
    """Celery Beat her dakika zamanlar, worker çalıştırır: ikisinin de canlı olduğunu gösterir."""
    Heartbeat.objects.update_or_create(name=name, defaults={"beat_at": timezone.now()})


def run_checks(now: datetime | None = None) -> list[selectors.CheckResult]:
    """Kontrolleri çalıştırır, durum değişikliklerinde olay yayınlar ve sonuçları döner."""
    now = now or timezone.now()
    results = selectors.evaluate_checks(now=now)
    repeat = timedelta(minutes=int(settings.OPS_ALERT_REPEAT_MINUTES))
    for result in results:
        if result.status == selectors.UNKNOWN:
            continue
        failing = result.status == selectors.ERROR
        with transaction.atomic():
            state, _ = CheckState.objects.select_for_update().get_or_create(code=result.check)
            payload = {"check": result.check, "title": result.title, "detail": result.detail}
            if failing:
                if not state.failing:
                    state.since = now
                if (
                    not state.failing
                    or state.last_alert_at is None
                    or (now - state.last_alert_at >= repeat)
                ):
                    state.last_alert_at = now
                    events.publish(event_names.OPS_ALERT, payload)
            elif state.failing:
                state.since = now
                events.publish(event_names.OPS_RECOVERED, payload)
            elif state.since is None:
                state.since = now
            state.failing = failing
            state.detail = result.detail
            state.save()
    return results
