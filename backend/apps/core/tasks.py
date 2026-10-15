"""Çekirdek arka plan işleri (Celery)."""

from celery import shared_task
from django.utils import timezone

from apps.core import event_names, events


@shared_task(name="core.publish_daily_check")
def publish_daily_check() -> None:
    """Celery Beat her sabah 07:00'de çağırır: `system.daily_check` olayını yayınlar.

    Günlük kontrolleri (SKT'si yaklaşan lotlar, minimum stok altı malzemeler) yapan modüller bu
    olayı dinler; böylece zamanlama tek yerde durur ve modüller birbirine bağımlı olmaz.
    """
    events.publish(event_names.DAILY_CHECK, {"date": timezone.localdate().isoformat()})
