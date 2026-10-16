"""Raporlama olay dinleyicileri: sabah kontrolünde süresi dolan rapor dosyaları silinir."""

from apps.core import event_names as ev
from apps.core.events import Event, subscribe
from apps.reporting import services


@subscribe(ev.DAILY_CHECK)
def expire_report_files(event: Event) -> None:
    services.expire_jobs()
