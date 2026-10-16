"""Olay dinleyicileri:

- Rezerve lot serbest durumdan çıkınca (bloke, red, karantina) siparişlerdeki rezervasyonları
  bırakılır ve eksik yeniden yayınlanır.
- Günlük kontrolde (07:00) SKT'si yaklaşan rezerve lotlar için `lot.expiring` yayınlanır.
"""

from django.db import transaction

from apps.core import event_names as ev
from apps.core import events
from apps.core.models import User
from apps.inventory.models import Lot
from apps.sales import selectors, services

# `lot.quarantine`: iade gelince lot yeniden karantinaya alınırsa (Adım 3.3).
UNUSABLE_LOT_EVENTS = (ev.LOT_BLOCKED, ev.LOT_REJECTED, "lot.quarantine")


def release_reservations_of_unusable_lot(event: events.Event) -> None:
    """Lot artık sevk edilemiyorsa siparişlerdeki aktif rezervasyonlarını bırakır."""
    if event.payload.get("model") != "inventory.lot":
        return
    lot_id = event.payload.get("id")
    lot = Lot.objects.filter(pk=lot_id).first() if lot_id is not None else None
    if lot is None or lot.status == Lot.Status.RELEASED:
        return
    actor = User.objects.filter(pk=event.actor_id).first() if event.actor_id else None
    reason = f"Lot {lot.lot_no} {lot.get_status_display().lower()} durumuna geçti"
    with transaction.atomic():
        services.release_unusable_lot(actor, lot, reason)


for _name in UNUSABLE_LOT_EVENTS:
    events.subscribe(_name)(release_reservations_of_unusable_lot)


@events.subscribe(ev.DAILY_CHECK)
def publish_reserved_lots_expiring(event: events.Event) -> None:
    """SKT'si `EXPIRY_WARNING_DAYS` gün içinde dolacak rezerve lotlar (liste boşsa olay yine
    yayınlanır; workflow boş listede bildirim göndermez)."""
    events.publish(
        ev.RESERVED_LOTS_EXPIRING,
        {"days": selectors.EXPIRY_WARNING_DAYS, "lots": selectors.expiring_reserved_lots()},
    )
