"""Satın alma siparişi PDF'i (Faz 4, Adım 4.2)."""

import io
from typing import Any
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.inventory.services import format_quantity
from apps.purchasing import selectors
from apps.purchasing.models import PurchaseOrder
from apps.quality.coa import FONT, FONT_BOLD, _register_fonts

LINE_HEADER = ("Sıra", "Malzeme", "Miktar", "Birim fiyat", "Tutar", "Teslim")


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _money(value: Any) -> str:
    text = f"{value:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _price(value: Any) -> str:
    return format_quantity(value)


def purchase_order_pdf(order: PurchaseOrder) -> bytes:
    """Siparişin tedarikçiye giden PDF'i (A4)."""
    _register_fonts()
    base = ParagraphStyle("base", fontName=FONT, fontSize=9, leading=12)
    bold = ParagraphStyle("bold", parent=base, fontName=FONT_BOLD)
    title = ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=16, leading=20)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.grey)

    def para(text: str, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), style)

    supplier = order.supplier
    lines = list(order.lines.select_related("material", "unit").order_by("line_no"))
    totals = selectors.order_totals(order)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Satın alma siparişi {order.number}",
    )
    buyer = [para(settings.COMPANY_NAME or "—", bold), para(settings.COMPANY_ADDRESS)]
    if settings.COMPANY_TAX_OFFICE or settings.COMPANY_TAX_NO:
        buyer.append(para(f"V.D.: {settings.COMPANY_TAX_OFFICE}  V.No: {settings.COMPANY_TAX_NO}"))
    document = [
        para("SATIN ALMA SİPARİŞİ", title),
        para(f"Sipariş no: {order.number}", bold),
        para(f"Tarih: {_date(order.order_date)}"),
        para(f"Para birimi: {order.currency}"),
    ]
    header = Table([[buyer, document]], colWidths=[100 * mm, 80 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    vendor = [para("Tedarikçi", bold), para(f"{supplier.code} — {supplier.name}")]
    for attr in ("address", "phone", "email"):
        value = getattr(supplier, attr, "")
        if value:
            vendor.append(para(str(value)))
    vendor_box = Table([[vendor]], colWidths=[180 * mm])
    vendor_box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd"))]))
    rows: list[list[Any]] = [list(LINE_HEADER)]
    for index, line in enumerate(lines, start=1):
        rows.append(
            [
                str(index),
                para(f"{line.material.code} — {line.material.name}"),
                f"{format_quantity(line.quantity)} {line.unit.code}",
                f"{_price(line.unit_price)} {order.currency}",
                _money(line.quantity * line.unit_price),
                _date(line.expected_date),
            ]
        )
    rows.append(["", "Toplam", "", "", f"{_money(totals.total)} {order.currency}", ""])
    table = Table(
        rows,
        colWidths=[12 * mm, 66 * mm, 28 * mm, 28 * mm, 26 * mm, 20 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), FONT, 9),
                ("FONT", (0, 0), (-1, 0), FONT_BOLD, 9),
                ("FONT", (0, -1), (-1, -1), FONT_BOLD, 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd")),
                ("ALIGN", (2, 1), (4, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story: list[object] = [header, Spacer(1, 5 * mm), vendor_box, Spacer(1, 5 * mm), table]
    if order.notes:
        story += [Spacer(1, 5 * mm), para("Notlar", bold), para(order.notes)]
    story += [
        Spacer(1, 8 * mm),
        para(
            f"Bu belge {timezone.localtime():%d.%m.%Y %H:%M} tarihinde sistemden üretilmiştir.",
            small,
        ),
    ]
    doc.build(story)  # type: ignore[arg-type]
    return buffer.getvalue()
