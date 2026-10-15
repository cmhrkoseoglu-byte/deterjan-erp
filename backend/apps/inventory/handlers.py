"""Olay dinleyicileri: 07:00 günlük kontrolünde SKT'si yaklaşan lotları ve minimum stok altındaki
malzemeleri yayınlar (bildirimleri workflow üretir; DECISIONS.md "İş akışı: 07:00 kontrolleri")."""

from decimal import Decimal

from apps.core import event_names as ev
from apps.core import events
from apps.inventory import selectors
from apps.inventory.services import format_quantity

EXPIRY_WARNING_DAYS = 30


@events.subscribe(ev.DAILY_CHECK)
def publish_daily_stock_checks(event: events.Event) -> None:
    """`inventory.lots_expiring` ve `inventory.below_min_stock` olaylarını yayınlar. Liste boşsa
    olay yine yayınlanır; workflow boş listede bildirim göndermez."""
    lots = [
        {
            "model": "inventory.lot",
            "id": lot.pk,
            "lot_no": lot.lot_no,
            "material_code": lot.material.code,
            "material_name": lot.material.name,
            "expiry_date": lot.expiry_date.strftime("%d.%m.%Y") if lot.expiry_date else "",
        }
        for lot in selectors.expiring_lots(EXPIRY_WARNING_DAYS)
    ]
    events.publish(ev.LOTS_EXPIRING, {"days": EXPIRY_WARNING_DAYS, "lots": lots})
    materials = [
        {
            "model": "masterdata.material",
            "id": material.pk,
            "code": material.code,
            "name": material.name,
            "quantity": format_quantity(material.stock_quantity),  # type: ignore[attr-defined]
            "min_stock": format_quantity(material.min_stock or Decimal(0)),
            "unit": material.base_unit.code,
        }
        for material in selectors.below_min_stock()
    ]
    events.publish(ev.BELOW_MIN_STOCK, {"materials": materials})
