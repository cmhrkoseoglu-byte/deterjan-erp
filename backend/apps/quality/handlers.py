"""Olay dinleyicileri: mal kabul kaydedilince giriş kontrolü gereken her lota giriş numunesi, şarj
bitince çıktı lotuna son kontrol numunesi açılır (Faz 2, Adım 2.1). Numune görevi workflow'da
`sample.created` ile açılır."""

import logging

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.inventory.models import Lot
from apps.quality import services
from apps.quality.models import Sample, SampleStage

logger = logging.getLogger(__name__)


def _actor(event: events.Event) -> User | None:
    return User.objects.filter(pk=event.actor_id).first() if event.actor_id else None


def _open(event: events.Event, lot_id: int | None, stage: str, origin: str) -> None:
    if lot_id is None:
        return
    lot = Lot.objects.filter(pk=lot_id).first()
    if lot is None:
        return
    try:
        services.open_sample(_actor(event), lot, stage, origin=origin)
    except BusinessRuleError as exc:
        # Ör. aynı aşamada açık numune zaten var.
        logger.info("Numune açılmadı (lot %s): %s", lot.lot_no, exc.message)


@events.subscribe(ev.GOODS_RECEIPT_POSTED)
def open_incoming_samples(event: events.Event) -> None:
    """Giriş kontrolü gereken (`requires_qc`) her lot için giriş numunesi."""
    for lot in event.payload.get("lots", []):
        if lot.get("requires_qc"):
            _open(event, lot.get("id"), SampleStage.INCOMING, Sample.Origin.GOODS_RECEIPT)


@events.subscribe(ev.PRODUCTION_BATCH_COMPLETED)
def open_batch_sample(event: events.Event) -> None:
    """Şarjın çıktı lotu için son kontrol numunesi."""
    lot = event.payload.get("output_lot") or {}
    if lot.get("id"):
        _open(event, lot["id"], SampleStage.FINAL, Sample.Origin.PRODUCTION)
