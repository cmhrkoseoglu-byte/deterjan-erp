from celery import shared_task

from apps.reporting import services


@shared_task(name="reporting.run_report_job")
def run_report_job(job_id: int) -> None:
    """Arka planda rapor dosyası hazırlar (`services.run_job`)."""
    services.run_job(job_id)
