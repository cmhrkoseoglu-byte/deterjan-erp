"""Olay dinleyicileri: kural tablosundaki her olay `services.process_event`'e gider.

`access.changed` kural tablosunda değildir: kişinin açık sayfalarına yalnız WebSocket iletisi
gider (menü ve düğmeler yenilenir; plan §8 madde 11). Bildirim ve denetim kaydı yazılmaz.
"""

from apps.core import event_names, events
from apps.core.events import Event
from apps.workflow import realtime, rules, services

for _event_name in sorted(rules.all_event_names()):
    events.subscribe(_event_name)(services.process_event)


@events.subscribe(event_names.ACCESS_CHANGED)
def push_access_changed(event: Event) -> None:
    """Yetkisi değişen kişiye `{"type": "access.changed"}` iletisini gönderir."""
    user_id = event.payload.get("user_id")
    if isinstance(user_id, int):
        realtime.push_to_users([user_id], {"type": "access.changed"})
