"""Sistem izleme arka plan işleri (Celery Beat zamanlaması `settings.CELERY_BEAT_SCHEDULE`)."""

from celery import shared_task

from apps.ops import services


@shared_task(name="ops.heartbeat")
def heartbeat() -> None:
    """Her dakika: beat ve worker'ın canlı olduğunu kaydeder."""
    services.record_heartbeat()


@shared_task(name="ops.run_checks")
def run_checks() -> None:
    """Her 5 dakikada: yedek durum dosyalarını içe aktarır, kontrolleri çalıştırır."""
    services.ingest_backup_status()
    services.run_checks()
