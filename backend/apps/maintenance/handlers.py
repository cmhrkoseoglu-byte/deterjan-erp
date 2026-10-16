"""Olay dinleyicileri: günlük kontrolde (07:00) vadesi gelen bakım planları için iş emri.

Ekipman kancası (`services.equipment_guard`) bu modül `services`'i import edince kaydolur.
"""

from apps.core import event_names as ev
from apps.core import events
from apps.maintenance import services


@events.subscribe(ev.DAILY_CHECK)
def open_due_work_orders(event: events.Event) -> None:
    """Vadesi gelen bakım planları için iş emri açar, termini geçenleri bildirir."""
    services.create_due_work_orders()
