"""Maliyet olay handler'ları: lot oluşunca / şarj ve dolum partisi bitince maliyet hesaplanır.

Handler'lar commit sonrası çalışır; hata ana işlemi bozmaz (loglanır). Hesaplanmamış lotun
maliyeti, girdi olarak kullanıldığında ya da yeniden hesaplamada yine hesaplanır.
"""

from apps.core import event_names as ev
from apps.core.events import Event, subscribe
from apps.core.models import User
from apps.costing import services
from apps.inventory.models import Lot


def _actor(event: Event) -> User | None:
    if event.actor_id is None:
        return None
    return User.objects.filter(pk=event.actor_id).first()


def _lot(payload: object) -> Lot | None:
    if not isinstance(payload, dict) or payload.get("id") is None:
        return None
    return Lot.objects.filter(pk=payload["id"]).first()


@subscribe(ev.GOODS_RECEIPT_POSTED)
def cost_received_lots(event: Event) -> None:
    actor = _actor(event)
    for payload in event.payload.get("lots", []):
        lot = _lot(payload)
        if lot is not None:
            services.ensure_lot_cost(actor, lot)


@subscribe(ev.GOODS_RECEIPT_COST_CHANGED)
def recost_received_lots(event: Event) -> None:
    actor = _actor(event)
    note = f"{event.payload.get('number', '')} fiyat düzeltmesi: {event.payload.get('note', '')}"
    for payload in event.payload.get("lots", []):
        lot = _lot(payload)
        if lot is not None:
            services.calculate_lot_cost(actor, lot, note=note.strip())


@subscribe(ev.PRODUCTION_BATCH_COMPLETED)
@subscribe(ev.FILLING_RUN_COMPLETED)
def cost_output_lot(event: Event) -> None:
    lot = _lot(event.payload.get("output_lot"))
    if lot is not None:
        services.ensure_lot_cost(_actor(event), lot)
