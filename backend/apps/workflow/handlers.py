"""Olay dinleyicileri: kural tablosundaki her olay `services.process_event`'e gider.

`access.changed` kural tablosunda değildir: kişinin açık sayfalarına yalnız WebSocket iletisi
gider (menü ve düğmeler yenilenir; plan §8 madde 11). Bildirim ve denetim kaydı yazılmaz.

`access.updated` de kural tablosunda değildir: Yetkiler ekranındaki gerçek bir kayıttan sonra
kişiye "Yetkileriniz güncellendi" bildirimi gider (plan §5.10, §6.5, §8 madde 15). Gerekçe
gösterilmez; kaydı yapan kişinin kendisine bildirim gitmez.
"""

from apps.core import event_names, events
from apps.core.events import Event
from apps.core.models import User
from apps.workflow import realtime, rules, services

for _event_name in sorted(rules.all_event_names()):
    events.subscribe(_event_name)(services.process_event)


@events.subscribe(event_names.ACCESS_CHANGED)
def push_access_changed(event: Event) -> None:
    """Yetkisi değişen kişiye `{"type": "access.changed"}` iletisini gönderir."""
    user_id = event.payload.get("user_id")
    if isinstance(user_id, int):
        realtime.push_to_users([user_id], {"type": "access.changed"})


ACCESS_UPDATED_TITLE = "Yetkileriniz güncellendi"
ACCESS_UPDATED_BODY = (
    "Rolleriniz ya da yetkileriniz değişti. Güncel hâlini Yetkilerim sayfasında görebilirsiniz."
)


@events.subscribe(event_names.ACCESS_UPDATED)
def notify_access_updated(event: Event) -> None:
    """Yetkisi ya da rolü değişen kişiye bildirim yazar (pasif kişiye ve kaydı yapana gitmez)."""
    user_id = event.payload.get("user_id")
    if not isinstance(user_id, int):
        return
    services.notify(
        User.objects.filter(pk=user_id),
        title=ACCESS_UPDATED_TITLE,
        body=ACCESS_UPDATED_BODY,
        event_name=event_names.ACCESS_UPDATED,
        exclude_user_id=event.actor_id,
    )
