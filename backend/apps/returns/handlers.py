"""Olay dinleyicileri: iade edilen lotun kalite sonucu karar bekleyen iade satırlarına uygulanır
(Faz 3, Adım 3.3). Lot serbest → yeniden sevke uygun, reddedildi → imha, yeniden işleme kararı →
yeniden işleme. Lot elle serbest bırakılsa da (D-5) aynı yol işler."""

from apps.core import event_names as ev
from apps.core import events
from apps.core.models import User
from apps.inventory.models import Lot
from apps.quality.models import QualityDecision
from apps.returns import services
from apps.returns.models import CustomerReturnLine

Disposition = CustomerReturnLine.Disposition


def _actor(event: events.Event) -> User | None:
    return User.objects.filter(pk=event.actor_id).first() if event.actor_id else None


def _apply(event: events.Event, lot_id: int | None, disposition: str, note: str) -> None:
    lot = Lot.objects.filter(pk=lot_id).first() if lot_id else None
    if lot is None:
        return
    services.apply_lot_outcome(_actor(event), lot, disposition, note)


@events.subscribe(ev.LOT_RELEASED)
def lot_released(event: events.Event) -> None:
    """Serbest bırakılan lotun iade satırları yeniden sevke uygun."""
    _apply(event, event.payload.get("id"), Disposition.RESTOCK, event.payload.get("note", ""))


@events.subscribe(ev.LOT_REJECTED)
def lot_rejected(event: events.Event) -> None:
    """Reddedilen lotun iade satırları imha bekler."""
    _apply(event, event.payload.get("id"), Disposition.SCRAP, event.payload.get("note", ""))


@events.subscribe(ev.SAMPLE_DECIDED)
def rework_decided(event: events.Event) -> None:
    """Yeniden işleme kararında lot bloke kalır; iade satırları yeniden işlemeye gider."""
    if event.payload.get("decision") != QualityDecision.Decision.REWORK:
        return
    if event.payload.get("stage") == "IN_PROCESS":
        return
    lot = event.payload.get("lot") or {}
    _apply(event, lot.get("id"), Disposition.REWORK, event.payload.get("reason", ""))
