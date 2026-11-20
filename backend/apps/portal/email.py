"""Müşteriye giden portal e-postalarının içeriği (docs/plan/musteri-siparis-takibi.md §4.5).

Fiyat yazılmaz (e-posta yönlendirilebilir; fiyat portalda). Sevk e-postasında şoför adı ve TC
yazılmaz, irsaliye eklenmez (portaldan iner). Düz metin ve HTML aynı bilgiyi taşır.
"""

from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.utils.html import escape

from apps.inventory.services import format_quantity
from apps.masterdata import services as masterdata
from apps.portal import selectors
from apps.sales.models import SalesOrder, Shipment


@dataclass(frozen=True)
class Content:
    subject: str
    text: str
    html: str


def _company() -> str:
    return masterdata.get_company_profile().legal_name or "Firmamız"


def _date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _render(
    subject: str,
    greeting: str,
    intro: str,
    rows: list[tuple[str, str]],
    items: list[str],
    link: str,
) -> Content:
    company = _company()
    text_rows = "\n".join(f"{label}: {value}" for label, value in rows)
    text_items = "\n".join(f"- {item}" for item in items)
    text = (
        f"{greeting}\n\n{intro}\n\n{text_rows}\n"
        + (f"\n{text_items}\n" if items else "")
        + f"\nAyrıntılar portalda: {link}\n\nSaygılarımızla,\n{company}\n"
    )
    html_rows = "".join(
        f'<tr><td style="padding:2px 12px 2px 0;color:#555">{escape(label)}</td>'
        f'<td style="padding:2px 0">{escape(value)}</td></tr>'
        for label, value in rows
    )
    html_items = (
        "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>" if items else ""
    )
    html = (
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#222">'
        f"<p>{escape(greeting)}</p><p>{escape(intro)}</p>"
        f"<table>{html_rows}</table>{html_items}"
        f'<p><a href="{escape(link)}">Ayrıntıları portalda görün</a></p>'
        f"<p>Saygılarımızla,<br>{escape(company)}</p></div>"
    )
    return Content(subject=subject, text=text, html=html)


def order_confirmed(order: SalesOrder) -> Content:
    """Sipariş onaylandı: sipariş no, müşteri sipariş no, termin, satır sayısı ve bağlantı."""
    rows = [("Sipariş no", order.number)]
    if order.customer_po_no:
        rows.append(("Sipariş no'nuz", order.customer_po_no))
    rows += [
        ("Termin", _date(order.promised_date)),
        ("Satır sayısı", str(order.lines.count())),
    ]
    return _render(
        subject=f"Siparişiniz onaylandı: {order.number}",
        greeting=f"Sayın {order.customer.name},",
        intro=f"{order.number} numaralı siparişiniz onaylandı.",
        rows=rows,
        items=[],
        link=f"{settings.PORTAL_BASE_URL}/portal/siparisler/{order.pk}",
    )


def shipment_dispatched(shipment: Shipment) -> Content:
    """Sevk edildi: sevkiyat ve sipariş no, sevk tarihi, plaka, ürün ve miktarlar, bağlantı."""
    order = shipment.sales_order
    rows = [("Sevkiyat no", shipment.number), ("Sipariş no", order.number)]
    if order.customer_po_no:
        rows.append(("Sipariş no'nuz", order.customer_po_no))
    rows += [
        ("Sevk tarihi", _date(shipment.dispatched_at.date() if shipment.dispatched_at else None)),
        ("Araç plakası", shipment.vehicle_plate or "—"),
    ]
    items = []
    for line in selectors.shipment_lines(shipment):
        quantity = format_quantity(line["quantity_in_unit"])
        items.append(
            f"{line['product_code']} {line['product_name']}: {quantity} {line['unit_code']}"
        )
    return _render(
        subject=f"Siparişiniz sevk edildi: {shipment.number}",
        greeting=f"Sayın {order.customer.name},",
        intro=(
            f"{order.number} numaralı siparişinizin {shipment.number} numaralı sevkiyatı "
            "yola çıktı."
        ),
        rows=rows,
        items=items,
        link=f"{settings.PORTAL_BASE_URL}/portal/sevkiyatlar/{shipment.pk}",
    )
