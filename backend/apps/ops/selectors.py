"""Sistem izleme okuma sorguları: kontrollerin değerlendirilmesi ve Sistem durumu ekranı."""

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import redis
from django.conf import settings
from django.utils import timezone

from apps.ops.models import BackupRun, CheckState, Heartbeat

OK = "ok"
ERROR = "error"
UNKNOWN = "unknown"  # ölçülemedi ya da bu ortamda kapalı (uyarı üretmez)

CHECK_LABELS = {
    "backup": "Gece yedeği",
    "restore_test": "Geri yükleme testi",
    "disk": "Disk doluluğu",
    "cpu": "Sunucu yükü",
    "queue": "Arka plan iş kuyruğu",
    "celery": "Arka plan servisleri",
}


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: str
    title: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return CHECK_LABELS.get(self.check, self.check)


@dataclass(frozen=True)
class DiskUsage:
    path: str
    total_bytes: int
    free_bytes: int
    used_pct: float


def _fmt(at: datetime | None) -> str:
    return timezone.localtime(at).strftime("%d.%m.%Y %H:%M") if at else "—"


def latest_run(kind: str, *, status: str | None = None) -> BackupRun | None:
    runs = BackupRun.objects.filter(kind=kind)
    if status:
        runs = runs.filter(status=status)
    return runs.order_by("-finished_at", "-id").first()


def check_backup(now: datetime) -> CheckResult:
    title = CHECK_LABELS["backup"]
    if not settings.OPS_BACKUP_CHECK_ENABLED:
        return CheckResult("backup", UNKNOWN, title, "Bu ortamda yedek denetimi kapalı.")
    latest = latest_run(BackupRun.Kind.BACKUP)
    last_ok = latest_run(BackupRun.Kind.BACKUP, status=BackupRun.Status.OK)
    max_age = timedelta(hours=int(settings.BACKUP_MAX_AGE_HOURS))
    if latest is not None and latest.status == BackupRun.Status.FAILED:
        return CheckResult(
            "backup",
            ERROR,
            "Gece yedeği alınamadı",
            f"{_fmt(latest.finished_at)}: {latest.message}",
        )
    if last_ok is None:
        return CheckResult(
            "backup", ERROR, "Hiç başarılı yedek yok", "Yedek servisini kontrol edin."
        )
    if now - last_ok.finished_at > max_age:
        return CheckResult(
            "backup",
            ERROR,
            "Yedek gecikti",
            f"Son başarılı yedek {_fmt(last_ok.finished_at)}; "
            f"{settings.BACKUP_MAX_AGE_HOURS} saatten eski.",
        )
    if last_ok.offsite == BackupRun.Offsite.FAILED:
        return CheckResult(
            "backup",
            ERROR,
            "Yedek ayrı konuma kopyalanamadı",
            f"{_fmt(last_ok.finished_at)}: {last_ok.offsite_message}",
        )
    return CheckResult(
        "backup", OK, title, f"Son yedek {_fmt(last_ok.finished_at)}, {last_ok.rows} satır."
    )


def check_restore_test(now: datetime) -> CheckResult:
    title = CHECK_LABELS["restore_test"]
    if not settings.OPS_BACKUP_CHECK_ENABLED:
        return CheckResult("restore_test", UNKNOWN, title, "Bu ortamda yedek denetimi kapalı.")
    latest = latest_run(BackupRun.Kind.RESTORE_TEST)
    max_age = timedelta(days=int(settings.RESTORE_TEST_MAX_AGE_DAYS))
    if latest is None:
        # İlk haftalık test zamanı gelmeden uyarı verme: ilk yedek de o kadar eski değilse bekle.
        first = BackupRun.objects.filter(kind=BackupRun.Kind.BACKUP).order_by("finished_at").first()
        if first is None or now - first.finished_at <= max_age:
            return CheckResult("restore_test", UNKNOWN, title, "Henüz geri yükleme testi yok.")
        return CheckResult("restore_test", ERROR, "Geri yükleme testi yapılmadı", "")
    if latest.status == BackupRun.Status.FAILED:
        detail = latest.message
        if latest.mismatches:
            tables = ", ".join(str(m.get("table")) for m in latest.mismatches[:5])
            detail = f"{detail} Sayısı tutmayan tablolar: {tables}".strip()
        return CheckResult(
            "restore_test",
            ERROR,
            "Geri yükleme testi başarısız",
            f"{_fmt(latest.finished_at)}: " + detail,
        )
    if now - latest.finished_at > max_age:
        return CheckResult(
            "restore_test",
            ERROR,
            "Geri yükleme testi gecikti",
            f"Son test {_fmt(latest.finished_at)}.",
        )
    return CheckResult(
        "restore_test",
        OK,
        title,
        f"Son test {_fmt(latest.finished_at)}: {latest.source_run_id} yedeği kuruldu, "
        "sayılar tuttu.",
    )


def disk_usage() -> list[DiskUsage]:
    """İzlenen klasörlerin bulunduğu disklerin doluluğu (aynı diskteki klasörler bir kez)."""
    seen: set[int] = set()
    usages = []
    for raw in settings.OPS_DISK_PATHS:
        path = Path(raw)
        if not path.exists():
            continue
        device = path.stat().st_dev
        if device in seen:
            continue
        seen.add(device)
        usage = shutil.disk_usage(path)
        used_pct = round(100 * (usage.total - usage.free) / usage.total, 1) if usage.total else 0.0
        usages.append(DiskUsage(str(path), usage.total, usage.free, used_pct))
    return usages


def check_disk() -> CheckResult:
    limit = float(settings.OPS_DISK_ALERT_PCT)
    usages = disk_usage()
    if not usages:
        return CheckResult("disk", UNKNOWN, CHECK_LABELS["disk"], "Ölçülemedi.")
    worst = max(usages, key=lambda u: u.used_pct)
    detail = ", ".join(f"{u.path} %{u.used_pct:g}" for u in usages)
    if worst.used_pct >= limit:
        return CheckResult(
            "disk",
            ERROR,
            f"Disk dolmak üzere (%{worst.used_pct:g})",
            f"{detail}. Sınır %{limit:g}.",
        )
    return CheckResult("disk", OK, CHECK_LABELS["disk"], detail)


def load_ratio() -> tuple[float, float, int] | None:
    """(15 dk yük ortalaması, çekirdek başına oran, çekirdek sayısı)."""
    try:
        load15 = os.getloadavg()[2]
    except OSError:
        return None
    cores = os.cpu_count() or 1
    return load15, load15 / cores, cores


def check_cpu() -> CheckResult:
    measured = load_ratio()
    if measured is None:
        return CheckResult("cpu", UNKNOWN, CHECK_LABELS["cpu"], "Ölçülemedi.")
    load15, ratio, cores = measured
    limit = float(settings.OPS_LOAD_ALERT_RATIO)
    detail = f"15 dakikalık yük {load15:.2f} ({cores} çekirdek)"
    if ratio >= limit:
        return CheckResult("cpu", ERROR, "Sunucu yükü yüksek", f"{detail}; uzun süredir yoğun.")
    return CheckResult("cpu", OK, CHECK_LABELS["cpu"], detail)


def queue_length() -> int | None:
    """Celery varsayılan kuyruğunda bekleyen iş sayısı (Redis broker)."""
    try:
        client = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        return int(client.llen("celery"))
    except Exception:
        return None


def check_queue() -> CheckResult:
    length = queue_length()
    if length is None:
        return CheckResult("queue", UNKNOWN, CHECK_LABELS["queue"], "Kuyruğa ulaşılamadı.")
    limit = int(settings.OPS_QUEUE_ALERT_LENGTH)
    if length > limit:
        return CheckResult(
            "queue", ERROR, f"Bekleyen arka plan işi çok ({length})", f"Sınır {limit} iş."
        )
    return CheckResult("queue", OK, CHECK_LABELS["queue"], f"{length} iş bekliyor.")


def check_celery(now: datetime) -> CheckResult:
    """Beat her dakika nabız işi zamanlar, worker çalıştırır; 3 dakikadan eskiyse biri durmuştur."""
    beat = Heartbeat.objects.filter(name="celery").first()
    title = CHECK_LABELS["celery"]
    if beat is None:
        return CheckResult("celery", UNKNOWN, title, "Henüz nabız yok.")
    if now - beat.beat_at > timedelta(minutes=3):
        return CheckResult(
            "celery",
            ERROR,
            "Arka plan servisleri yanıt vermiyor",
            f"Son nabız {_fmt(beat.beat_at)}.",
        )
    return CheckResult("celery", OK, title, f"Son nabız {_fmt(beat.beat_at)}.")


def evaluate_checks(now: datetime | None = None) -> list[CheckResult]:
    """Celery işinde çalışan kontroller (arka plan servislerinin kendi kontrolü hariç: o iş
    çalışıyorsa servisler zaten ayaktadır; durumu ekranda ve dış izleme ucunda görünür)."""
    now = now or timezone.now()
    return [check_backup(now), check_restore_test(now), check_disk(), check_cpu(), check_queue()]


def system_status(now: datetime | None = None) -> dict[str, Any]:
    """Sistem durumu ekranı: tüm kontroller, ölçümler ve son yedek çalışmaları."""
    now = now or timezone.now()
    checks = [*evaluate_checks(now), check_celery(now)]
    states = {state.code: state for state in CheckState.objects.all()}
    measured = load_ratio()
    return {
        "checks": [
            {
                "check": c.check,
                "label": c.label,
                "status": c.status,
                "title": c.title,
                "detail": c.detail,
                "since": states[c.check].since if c.check in states else None,
            }
            for c in checks
        ],
        "disks": [
            {
                "path": u.path,
                "total_bytes": u.total_bytes,
                "free_bytes": u.free_bytes,
                "used_pct": u.used_pct,
            }
            for u in disk_usage()
        ],
        "load_15": round(measured[0], 2) if measured else None,
        "cpu_count": measured[2] if measured else None,
        "queue_length": queue_length(),
        "runs": list(BackupRun.objects.order_by("-finished_at", "-id")[:20]),
    }


def health_summary(now: datetime | None = None) -> dict[str, str]:
    """Dış izleme aracı için kısa özet: her kontrol ok/error/unknown."""
    now = now or timezone.now()
    checks = [check_backup(now), check_restore_test(now), check_celery(now)]
    return {c.check: c.status for c in checks}
