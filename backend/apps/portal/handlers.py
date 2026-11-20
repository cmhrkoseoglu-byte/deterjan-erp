"""Olay dinleyicileri: sipariş onaylanınca ve sevk edilince müşterinin portal kullanıcılarına
e-posta sıraya alınır (docs/plan/musteri-siparis-takibi.md §4.5)."""

from apps.core import event_names as ev
from apps.core import events
from apps.portal import services
from apps.sales.models import SalesOrder, Shipment


@events.subscribe(ev.SALES_ORDER_CONFIRMED)
def email_order_confirmed(event: events.Event) -> None:
    order = SalesOrder.objects.filter(pk=event.payload["id"]).first()
    if order is not None:
        services.queue_order_confirmed(order)


@events.subscribe(ev.SHIPMENT_DISPATCHED)
def email_shipment_dispatched(event: events.Event) -> None:
    shipment = Shipment.objects.filter(pk=event.payload["id"]).first()
    if shipment is not None:
        services.queue_shipment_dispatched(shipment)
