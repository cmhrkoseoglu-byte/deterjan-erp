"""PDF çıktılarının ortak sayfa çerçevesi: doküman kontrol bandı (ISO 9001 md. 7.5) ve "Sayfa x/y".

Kullanım (üretici):

    control = document_control("quality.coa", on=karar_tarihi)
    doc.build(story, canvasmaker=controlled_canvas(control))

Bant kapalıysa `controlled_canvas` düz `Canvas` döner: çıktı bugünkü gibi basılır.
"""

from collections.abc import Callable
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from apps.core.coding.outputs import DocumentControl
from apps.core.labels import FONT, register_fonts

BAND_FONT_SIZE = 7
PageDraw = Callable[[Canvas, int, int], None]


def numbered_canvas(draw: PageDraw) -> type[Canvas]:
    """Sayfaları sonda çizen canvas sınıfı: `draw(canvas, sayfa, toplam)` her sayfada çağrılır;
    böylece "Sayfa x/y"deki toplam bilinir."""

    class NumberedCanvas(Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 (reportlab adı)
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            for number, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                draw(self, number, total)
                super().showPage()
            super().save()

    return NumberedCanvas


def draw_band(
    canvas: Canvas,
    control: DocumentControl,
    page: int | None,
    total: int | None,
    *,
    left: float = 15 * mm,
    baseline: float = 7 * mm,
) -> None:
    """Sayfanın altına tek satır bant: doküman no, yayın tarihi, revizyon ve (verilirse) sayfa."""
    canvas.saveState()
    canvas.setFillColor(colors.grey)
    canvas.setFont(FONT, BAND_FONT_SIZE)
    canvas.drawString(left, baseline, control.band(page, total))
    canvas.restoreState()


def controlled_canvas(
    control: DocumentControl | None, *, left: float = 15 * mm, baseline: float = 7 * mm
) -> type[Canvas]:
    """Bant açıksa her sayfaya doküman kontrol bandını çizen canvas; değilse düz `Canvas`."""
    if control is None:
        return Canvas
    register_fonts()

    def draw(canvas: Canvas, page: int, total: int) -> None:
        draw_band(canvas, control, page, total, left=left, baseline=baseline)

    return numbered_canvas(draw)
