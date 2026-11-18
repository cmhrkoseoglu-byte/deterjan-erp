"""Olay dinleyicileri: sevk edilen sevkiyat ve kaydedilen (ya da fiyatı düzeltilen) mal kabul
cariye yazılır; günlük kontrolde (07:00) bütün belgeler eşitlenir (kaçan olay için)."""

from apps.core import event_names as ev
from apps.core import events
from apps.core.models import User
from apps.inventory.models import GoodsReceipt
from apps.ledger import services
from apps.sales.models import Shipment


def _actor(event: events.Event) -> User | None:
    return User.objects.filter(pk=event.actor_id).first() if event.actor_id else None


@events.subscribe(ev.SHIPMENT_DISPATCHED)
def post_dispatched_shipment(event: events.Event) -> None:
    """Sevk edilen sevkiyatı müşteri carisine borç yazar."""
    shipment = Shipment.objects.filter(pk=int(event.payload.get("id") or 0)).first()
    if shipment is not None:
        services.sync_shipment(_actor(event), shipment)


def post_goods_receipt(event: events.Event) -> None:
    """Kaydedilen ya da fiyatı düzeltilen mal kabulü tedarikçi carisine yazar."""
    receipt = GoodsReceipt.objects.filter(pk=int(event.payload.get("id") or 0)).first()
    if receipt is not None:
        services.sync_receipt(_actor(event), receipt)


for _name in (ev.GOODS_RECEIPT_POSTED, ev.GOODS_RECEIPT_COST_CHANGED):
    events.subscribe(_name)(post_goods_receipt)


@events.subscribe(ev.DAILY_CHECK)
def sync_all_documents(event: events.Event) -> None:
    services.sync_all()
