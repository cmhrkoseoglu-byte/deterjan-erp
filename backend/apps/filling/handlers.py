"""Olay dinleyicileri: emrin son dolum lotu serbest bırakılınca dolum emri kendiliğinden
tamamlanır."""

import logging

from django.db import transaction

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.filling import services
from apps.filling.models import FillingOrder, FillingRun

logger = logging.getLogger(__name__)


@events.subscribe(ev.LOT_RELEASED)
def complete_order_when_lots_released(event: events.Event) -> None:
    """Serbest bırakılan lot bir dolum partisinin lotuysa ve emir analiz bekliyorsa emri kapatır."""
    if event.payload.get("model") != "inventory.lot":
        return
    run = (
        FillingRun.objects.select_related("order")
        .filter(output_lot_id=event.payload.get("id"))
        .first()
    )
    if run is None or run.order.status != FillingOrder.Status.QC_PENDING:
        return
    actor = User.objects.filter(pk=event.actor_id).first() if event.actor_id else None
    try:
        with transaction.atomic():
            services.complete_order(actor, run.order)
    except BusinessRuleError as exc:
        # Diğer partilerin lotları henüz karar bekliyor.
        logger.info("Dolum emri %s henüz tamamlanmadı: %s", run.order.number, exc.message)
