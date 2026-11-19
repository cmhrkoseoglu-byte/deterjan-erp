"""İrsaliye PDF'i (Faz 3, Adım 3.2). Veri `sales.selectors.waybill_data` ile hazırlanır; e-İrsaliye
entegrasyonu Faz 5'te aynı veriyi kullanır. Şoför TC kimlik no yalnızca bu belgede tam yazılır.

Müşteri nüshası (`customer_copy=True`, müşteri portalı; docs/plan/musteri-siparis-takibi.md §4.3):
lot ve SKT sütunu yoktur, satırlar sipariş satırı başına toplanır, şoför TC'si maskelidir."""

import io
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.audit import mask_identifier
from apps.core.coding.outputs import document_control
from apps.core.pdf import controlled_canvas
from apps.inventory.services import format_quantity
from apps.quality.coa import FONT, FONT_BOLD, _register_fonts
from apps.sales import selectors
from apps.sales.models import Shipment

LINE_HEADER = ("Sıra", "Ürün", "Lot", "SKT", "Miktar", "Koli")
CUSTOMER_LINE_HEADER = ("Sıra", "Ürün", "Miktar", "Koli")


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _cases(line: dict[str, Any]) -> str:
    cases = line["cases"]
    if cases is None:
        return ""
    loose: Decimal = line["loose_units"]
    if loose:
        return f"{cases} + {format_quantity(loose)} {line['unit']}"
    return str(cases)


def line_rows(data: dict[str, Any]) -> list[list[str]]:
    """İrsaliye satırları: sıra, ürün, lot, SKT, miktar, koli."""
    return [
        [
            str(index),
            f"{line['product_code']} — {line['product_name']}",
            line["lot_no"],
            _date(line["expiry_date"]),
            f"{format_quantity(line['quantity'])} {line['unit']}",
            _cases(line),
        ]
        for index, line in enumerate(data["lines"], start=1)
    ]


def customer_copy_data(data: dict[str, Any]) -> dict[str, Any]:
    """Müşteri nüshasının verisi: lot ve SKT olmadan, sipariş satırı başına toplanmış satırlar;
    şoför TC'si maskeli. Koli sayısı lotlardan biri bilinmiyorsa boş kalır."""
    merged: dict[int, dict[str, Any]] = {}
    for line in data["lines"]:
        row = merged.get(line["line_no"])
        if row is None:
            merged[line["line_no"]] = {
                key: line[key]
                for key in (
                    "line_no",
                    "product_code",
                    "product_name",
                    "quantity",
                    "unit",
                    "cases",
                    "loose_units",
                )
            }
            continue
        row["quantity"] += line["quantity"]
        if row["cases"] is None or line["cases"] is None:
            row["cases"], row["loose_units"] = None, Decimal(0)
        else:
            row["cases"] += line["cases"]
            row["loose_units"] += line["loose_units"]
    return {
        **data,
        "driver_id_no": mask_identifier(data["driver_id_no"]),
        "lines": [merged[key] for key in sorted(merged)],
    }


def customer_line_rows(data: dict[str, Any]) -> list[list[str]]:
    """Müşteri nüshasının satırları: sıra, ürün, miktar, koli."""
    return [
        [
            str(index),
            f"{line['product_code']} — {line['product_name']}",
            f"{format_quantity(line['quantity'])} {line['unit']}",
            _cases(line),
        ]
        for index, line in enumerate(data["lines"], start=1)
    ]


WAYBILL_OUTPUT = "sales.waybill"


def waybill_pdf(shipment: Shipment, *, customer_copy: bool = False) -> bytes:
    """Sevkiyatın irsaliyesi (A4 PDF baytları); `customer_copy` müşteri nüshası."""
    _register_fonts()
    data = selectors.waybill_data(shipment)
    if customer_copy:
        data = customer_copy_data(data)
    base = ParagraphStyle("base", fontName=FONT, fontSize=9, leading=12)
    bold = ParagraphStyle("bold", parent=base, fontName=FONT_BOLD)
    title = ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=16, leading=20)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.grey)

    def para(text: str, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), style)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"İrsaliye {data['number']}",
    )
    company = data["company"]
    customer = data["customer"]
    seller = [para(company["name"] or "—", bold), para(company["address"])]
    if company["tax_office"] or company["tax_no"]:
        seller.append(para(f"V.D.: {company['tax_office']}  V.No: {company['tax_no']}"))
    if company.get("registry"):
        seller.append(para(company["registry"]))
    document = [
        para("SEVK İRSALİYESİ", title),
        para(f"İrsaliye no: {data['number']}", bold),
        para(f"Tarih: {_date(data['date'])}"),
        para(f"Sipariş: {data['order_number']}"),
    ]
    if data["customer_po_no"]:
        document.append(para(f"Müşteri sipariş no: {data['customer_po_no']}"))
    header = Table([[seller, document]], colWidths=[100 * mm, 80 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    buyer = [
        para("Alıcı", bold),
        para(f"{customer['code']} — {customer['name']}"),
        para(customer["address"]),
    ]
    if customer["tax_office"] or customer["tax_no"]:
        buyer.append(para(f"V.D.: {customer['tax_office']}  V.No/TCKN: {customer['tax_no']}"))
    delivery = [para("Teslim adresi", bold), para(data["delivery_address"])]
    transport = [
        para("Taşıma", bold),
        para(f"Plaka: {data['vehicle_plate']}"),
        para(f"Şoför: {data['driver_name']}"),
        para(f"Şoför TCKN: {data['driver_id_no']}"),
    ]
    if data["carrier"]:
        transport.append(para(f"Taşıyıcı: {data['carrier']}"))
    parties = Table([[buyer, delivery, transport]], colWidths=[64 * mm, 60 * mm, 56 * mm])
    parties.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd")),
            ]
        )
    )

    total_quantity = (
        f"{format_quantity(data['total_quantity'])} {data['total_unit']}"
        if data["total_quantity"] is not None
        else ""
    )
    total_cases = str(data["total_cases"]) if data["total_cases"] else ""
    rows: list[list[Any]]
    if customer_copy:
        rows = [list(CUSTOMER_LINE_HEADER), *customer_line_rows(data)]
        rows.append(["", "Toplam", total_quantity, total_cases])
        widths = [12 * mm, 118 * mm, 26 * mm, 24 * mm]
    else:
        rows = [list(LINE_HEADER), *line_rows(data)]
        rows.append(["", "Toplam", "", "", total_quantity, total_cases])
        widths = [12 * mm, 66 * mm, 30 * mm, 22 * mm, 26 * mm, 24 * mm]
    first_number = len(widths) - 2
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), FONT, 9),
                ("FONT", (0, 0), (-1, 0), FONT_BOLD, 9),
                ("FONT", (0, -1), (-1, -1), FONT_BOLD, 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd")),
                ("ALIGN", (first_number, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    signatures = Table(
        [[para("Teslim eden", bold), para("Teslim alan", bold)], ["", ""]],
        colWidths=[90 * mm, 90 * mm],
        rowHeights=[6 * mm, 18 * mm],
    )
    story: list[object] = [
        header,
        Spacer(1, 5 * mm),
        parties,
        Spacer(1, 5 * mm),
        table,
        Spacer(1, 10 * mm),
        signatures,
        Spacer(1, 6 * mm),
        para(
            f"Bu belge {timezone.localtime():%d.%m.%Y %H:%M} tarihinde sistemden üretilmiştir. "
            "e-İrsaliye değildir.",
            small,
        ),
    ]
    control = document_control(WAYBILL_OUTPUT, on=data["date"])
    doc.build(story, canvasmaker=controlled_canvas(control))  # type: ignore[arg-type]
    return buffer.getvalue()
