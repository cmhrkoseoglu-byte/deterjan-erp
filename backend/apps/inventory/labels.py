"""Lot etiketi PDF'i: Code128 barkod + QR (içerik: lot no). Etiket 100 × 60 mm, her lot bir sayfa.

Zebra/ZPL yazıcı desteği Faz 2'de. Türkçe karakterler için reportlab ile gelen Vera yazı tipi
kullanılır.
"""

import io
import os
from collections.abc import Iterable

import reportlab
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from apps.inventory.models import Lot

LABEL_SIZE = (100 * mm, 60 * mm)
MARGIN = 4 * mm
FONT, FONT_BOLD = "Vera", "VeraBd"


def _register_fonts() -> None:
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    pdfmetrics.registerFont(TTFont(FONT, os.path.join(folder, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(folder, "VeraBd.ttf")))


def _fit(text: str, font: str, size: float, width: float) -> str:
    """Metni genişliğe sığacak şekilde kısaltır."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _draw_label(pdf: canvas.Canvas, lot: Lot) -> None:
    width, height = LABEL_SIZE
    material = lot.material
    text_width = width - 2 * MARGIN - 24 * mm
    y = height - MARGIN - 4 * mm
    pdf.setFont(FONT_BOLD, 11)
    pdf.drawString(MARGIN, y, _fit(material.code, FONT_BOLD, 11, text_width))
    y -= 4.5 * mm
    pdf.setFont(FONT, 8)
    pdf.drawString(MARGIN, y, _fit(material.name, FONT, 8, text_width))
    y -= 7 * mm
    pdf.setFont(FONT_BOLD, 16)
    pdf.drawString(MARGIN, y, _fit(lot.lot_no, FONT_BOLD, 16, text_width))
    y -= 5 * mm
    pdf.setFont(FONT, 8)
    details = []
    if lot.expiry_date:
        details.append(f"SKT: {lot.expiry_date:%d.%m.%Y}")
    if lot.supplier_lot_no:
        details.append(f"Tedarikçi lot: {lot.supplier_lot_no}")
    pdf.drawString(MARGIN, y, _fit("   ".join(details), FONT, 8, text_width))

    qr_size = 22 * mm
    widget = qr.QrCodeWidget(lot.lot_no)
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(
        qr_size, qr_size, transform=[qr_size / (x2 - x1), 0, 0, qr_size / (y2 - y1), 0, 0]
    )
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, width - MARGIN - qr_size, height - MARGIN - qr_size)

    barcode = code128.Code128(lot.lot_no, barHeight=14 * mm, barWidth=0.33 * mm, humanReadable=True)
    bar_x = max(MARGIN, (width - barcode.width) / 2)
    barcode.drawOn(pdf, bar_x, MARGIN + 2 * mm)


def lot_labels_pdf(lots: Iterable[Lot]) -> bytes:
    """Lotların etiketlerini tek PDF'te (lot başına bir sayfa) üretir."""
    _register_fonts()
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LABEL_SIZE)
    pdf.setTitle("Lot etiketi")
    pages = 0
    for lot in lots:
        _draw_label(pdf, lot)
        pdf.showPage()
        pages += 1
    if pages == 0:
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
