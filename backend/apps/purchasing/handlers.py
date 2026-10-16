"""Olay dinleyicileri ve kancalar:

- Mal kabul kaydı kancası (`services.on_receipt_posting`, inventory'ye `services` import edilince
  kaydolur): siparişe bağlı satırların toleransı ve sipariş durumu.
- Günlük kontrolde (07:00) talep önerileri otomatik talep olarak açılır.
"""

from apps.core import event_names as ev
from apps.core import events
from apps.purchasing import services


@events.subscribe(ev.DAILY_CHECK)
def open_suggested_requests(event: events.Event) -> None:
    """Minimum stok ve açık emir ihtiyaçlarından otomatik satın alma talebi açar."""
    services.create_suggested_requests()
