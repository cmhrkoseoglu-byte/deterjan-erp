"""Olay dinleyicileri: emrin son çıktı lotu serbest bırakılınca emir kendiliğinden tamamlanır."""

import logging

from django.db import transaction

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.production import services
from apps.production.models import ProductionBatch, ProductionOrder

logger = logging.getLogger(__name__)


@events.subscribe(ev.LOT_RELEASED)
def complete_order_when_lots_released(event: events.Event) -> None:
    """Serbest bırakılan lot bir şarjın çıktısıysa ve emir analiz bekliyorsa emri tamamlar."""
    if event.payload.get("model") != "inventory.lot":
        return
    batch = (
        ProductionBatch.objects.select_related("order")
        .filter(output_lot_id=event.payload.get("id"))
        .first()
    )
    if batch is None or batch.order.status != ProductionOrder.Status.QC_PENDING:
        return
    actor = User.objects.filter(pk=event.actor_id).first() if event.actor_id else None
    try:
        with transaction.atomic():
            services.complete_order(actor, batch.order)
    except BusinessRuleError as exc:
        # Diğer şarjların lotları henüz karar bekliyor.
        logger.info("Emir %s henüz tamamlanmadı: %s", batch.order.number, exc.message)
