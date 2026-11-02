"""Bordro PDF'leri (docs/DECISIONS.md "Personel bordrosu"): işveren maliyeti tablosu.

Satırlar saf işlevlerle kurulur (`employer_cost_rows`; testler içeriği bunlardan denetler), PDF
reportlab ile bellekte üretilir. Her sayfada ön bordro notu ve "Sayfa x/y"; onaylanmamış bordroda
çapraz "TASLAK" damgası. Yazı tipi Vera (Türkçe karakterler); "₺" işareti olmadığı için tutarlar
"TL" ile yazılır, kalın yazı ayrı yazı tipiyle (Paragraph içinde <b> kalın basmaz).
"""

import io
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.formatting import format_money
from apps.core.labels import FONT, FONT_BOLD, register_fonts
from apps.masterdata import services as masterdata
from apps.personnel.selectors import FALLBACK, LEGAL_DEFAULT, PayrollMonth, PayrollRow

PRELIMINARY_NOTE = (
    "Ön bordrodur; SGK (e-Bildirge) ve vergi (MUHSGK) bildirimi yerine geçmez, mali müşavir "
    "kontrolüne tabidir."
)
EMPLOYER_COST_HEADER = (
    "Sicil no",
    "Ad soyad",
    "Birim",
    "SGK gün",
    "Brüt toplam",
    "SGK matrahı",
    "SGK işveren",
    "Teşvik",
    "İşsizlik işveren",
    "Alt sınır farkı",
    "İşverene maliyet",
    "Maliyet / brüt",
)
EXTERNAL_TEXT = "Bordrosu mali müşavirde"
GRID = colors.HexColor("#adb5bd")
HEADER_FILL = colors.HexColor("#e9ecef")
SUBTOTAL_FILL = colors.HexColor("#f8f9fa")


def _money(value: Decimal) -> str:
    return format_money(value)


def _rate(value: Decimal) -> str:
    """Yüzde, Türkçe biçimde ve gereksiz sıfırsız: Decimal("18.75") → "18,75"."""
    text = f"{value.normalize():f}"
    return text.replace(".", ",")


def _share(cost: Decimal, gross: Decimal) -> str:
    """Maliyetin brüte oranı (%), iki ondalık; brüt sıfırsa boş."""
    if not gross:
        return ""
    return f"%{_rate((cost / gross * 100).quantize(Decimal('0.01')))}"


def parameter_line(month: PayrollMonth) -> str:
    """Parametre özeti: "Asgari ücret 33.030,00 TL · SGK günlük alt/üst sınır …"."""
    params = month.settings.params
    return (
        f"Asgari ücret {_money(params.minimum_wage)} TL · SGK günlük alt / üst sınır "
        f"{_money(params.daily_floor)} / {_money(params.daily_ceiling)} TL · SGK işveren "
        f"%{_rate(params.employer_sgk_rate)} − teşvik {_rate(params.incentive_points)} puan · "
        f"işsizlik işveren %{_rate(params.employer_unemployment_rate)} · etkin işveren oranı "
        f"%{_rate(params.employer_rate)}"
    )


def status_line(month: PayrollMonth) -> str:
    """Puantajın ve parametrelerin durumu (taslak çıktıda neyin kesin olmadığı)."""
    if month.attendance_approved:
        attendance = f"Puantaj onaylı ({month.attendance_number})"
    else:
        attendance = "Puantaj açık: girilmemiş günler takvimden sayıldı"
    source = month.settings.source
    if source == LEGAL_DEFAULT:
        parameters = f"parametreler kaydedilmedi ({month.settings.year} yasal değerleriyle)"
    elif source == FALLBACK:
        parameters = (
            f"{month.year} parametreleri yok: {month.settings.year} değerleriyle tahmin edildi"
        )
    else:
        record = month.settings.record
        since = f"{record.valid_from:%m.%Y}" if record else ""
        parameters = f"parametreler kayıtlı ({since} itibarıyla)"
    return f"{attendance}; {parameters}."


def _row_cells(row: PayrollRow) -> list[str]:
    person = row.employee
    if row.external:
        figure = row.figure
        gross = _money(figure.gross_total) if figure else ""
        cost = _money(figure.employer_cost) if figure else "rakam girilmedi"
        share = _share(figure.employer_cost, figure.gross_total) if figure else ""
        # Not, hesaplanmayan sütunları (SGK matrahı … alt sınır farkı) kaplar; brüt görünür kalır.
        return [
            person.employee_no,
            person.full_name,
            person.department,
            "—",
            gross,
            EXTERNAL_TEXT,
            "",
            "",
            "",
            "",
            cost,
            share,
        ]
    line = row.line
    return [
        person.employee_no,
        person.full_name,
        person.department,
        str(line.sgk_days),
        _money(line.gross_total),
        _money(line.sgk_base),
        _money(line.employer_sgk_gross),
        f"−{_money(line.incentive)}" if line.incentive else _money(line.incentive),
        _money(line.employer_unemployment),
        _money(line.floor_gap),
        _money(line.employer_cost),
        _share(line.employer_cost, line.gross_total),
    ]


def _total_cells(label: str, rows: Sequence[PayrollRow]) -> list[str]:
    computed = [row for row in rows if not row.external]

    def total(name: str) -> Decimal:
        return sum((getattr(row.line, name) for row in computed), Decimal(0))

    gross = sum((row.gross_total for row in rows), Decimal(0))
    cost = sum((row.employer_cost for row in rows), Decimal(0))
    incentive = total("incentive")
    return [
        "",
        label,
        "",
        "",
        _money(gross),
        _money(total("sgk_base")),
        _money(total("employer_sgk_gross")),
        f"−{_money(incentive)}" if incentive else _money(incentive),
        _money(total("employer_unemployment")),
        _money(total("floor_gap")),
        _money(cost),
        _share(cost, gross),
    ]


def employer_cost_rows(month: PayrollMonth) -> list[tuple[str, list[str]]]:
    """İşveren maliyeti tablosunun satırları: birim birim kişiler, birim toplamı (birden çok kişili
    birimde) ve genel toplam. Her satır (tür, hücreler); tür "row", "subtotal" ya da "total"."""
    groups: dict[str, list[PayrollRow]] = {}
    for row in sorted(month.rows, key=lambda item: (item.employee.department, item.employee.pk)):
        groups.setdefault(row.employee.department, []).append(row)
    lines: list[tuple[str, list[str]]] = []
    for department, members in groups.items():
        lines.extend(("row", _row_cells(row)) for row in members)
        if len(groups) > 1 and len(members) > 1:
            lines.append(("subtotal", _total_cells(f"{department} toplamı", members)))
    lines.append(("total", _total_cells("Genel toplam", month.rows)))
    return lines


class _Chrome:
    """Sayfa çerçevesi: alt bilgi (not, üretim zamanı, Sayfa x/y) ve taslak damgası."""

    def __init__(self, title: str, draft: bool) -> None:
        self.title = title
        self.draft = draft
        self.produced = f"{timezone.localtime():%d.%m.%Y %H:%M}"

    def canvas_maker(self) -> Callable[..., Canvas]:
        chrome = self

        class NumberedCanvas(Canvas):
            """Sayfalar sonda yazılır; böylece "Sayfa x/y"deki toplam bilinir."""

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
                    chrome.draw(self, number, total)
                    super().showPage()
                super().save()

        return NumberedCanvas

    def draw(self, canvas: Canvas, number: int, total: int) -> None:
        width, height = canvas._pagesize
        canvas.saveState()
        if self.draft:
            canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.10))
            canvas.setFont(FONT_BOLD, 96)
            canvas.translate(width / 2, height / 2)
            canvas.rotate(30)
            canvas.drawCentredString(0, -30, "TASLAK")
            canvas.rotate(-30)
            canvas.translate(-width / 2, -height / 2)
        canvas.setFillColor(colors.grey)
        canvas.setFont(FONT, 7)
        canvas.drawString(10 * mm, 6 * mm, PRELIMINARY_NOTE)
        canvas.drawRightString(
            width - 10 * mm, 6 * mm, f"{self.title} · {self.produced} · Sayfa {number}/{total}"
        )
        canvas.restoreState()


def _company_block(para: Callable[..., Paragraph], bold: ParagraphStyle) -> list[Paragraph]:
    company = masterdata.get_company_profile()
    block = [para(company.legal_name or "—", bold), para(company.address)]
    if company.tax_office or company.tax_number:
        block.append(para(f"V.D.: {company.tax_office}  V.No: {company.tax_number}"))
    registry = masterdata.company_registry_line(company)
    if registry:
        block.append(para(registry))
    return block


def employer_cost_pdf(month: PayrollMonth, *, draft: bool = True) -> bytes:
    """İşveren maliyeti tablosu (A4 yatay): kişi başına SGK günü, brüt, SGK matrahı, işveren
    payları ve işverene maliyet; birim toplamları ve genel toplam."""
    register_fonts()
    base = ParagraphStyle("base", fontName=FONT, fontSize=8, leading=10)
    bold = ParagraphStyle("bold", parent=base, fontName=FONT_BOLD)
    title_style = ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=14, leading=18)
    small = ParagraphStyle("small", parent=base, fontSize=7, leading=9, textColor=colors.grey)

    def para(text: str, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), style)

    title = f"İşveren maliyeti tablosu — {month.label}"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title=title,
    )
    heading = [
        para("İŞVEREN MALİYETİ TABLOSU", title_style),
        para(f"Dönem: {month.label}", bold),
        para("Ön bordro" + (" · TASLAK" if draft else "")),
    ]
    header = Table(
        [[_company_block(para, bold), heading]], colWidths=[150 * mm, 127 * mm], hAlign="LEFT"
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    lines = employer_cost_rows(month)
    data: list[list[Any]] = [[para(text, bold) for text in EMPLOYER_COST_HEADER]]
    style: list[tuple[Any, ...]] = [
        ("FONT", (0, 0), (-1, -1), FONT, 8),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for index, (kind, cells) in enumerate(lines, start=1):
        summary = kind in ("subtotal", "total")
        data.append([cells[0], para(cells[1], bold if summary else base), *cells[2:]])
        if summary:
            style.append(("FONT", (0, index), (-1, index), FONT_BOLD, 8))
            style.append(("BACKGROUND", (0, index), (-1, index), SUBTOTAL_FILL))
        elif cells[5] == EXTERNAL_TEXT:
            style.append(("SPAN", (5, index), (9, index)))
            style.append(("ALIGN", (5, index), (9, index), "CENTER"))
            style.append(("TEXTCOLOR", (5, index), (9, index), colors.grey))
    widths = [16, 42, 26, 13, 23, 23, 22, 20, 21, 20, 24, 17]
    table = Table(data, colWidths=[width * mm for width in widths], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle(style))
    story: list[Any] = [
        header,
        Spacer(1, 3 * mm),
        para(status_line(month), small),
        para(parameter_line(month), small),
        Spacer(1, 3 * mm),
        table,
        Spacer(1, 3 * mm),
        para(
            "İşverene maliyet = brüt toplam + SGK işveren payı (teşvik sonrası) + işsizlik işveren "
            "payı + alt sınır farkı (ücret SGK alt sınırının altındaysa işçi payı dahil farkın "
            "primi, 5510 s. Kanun m.82). Asgari ücret desteği düşülmemiştir.",
            small,
        ),
    ]
    chrome = _Chrome(title, draft)
    doc.build(story, canvasmaker=chrome.canvas_maker())
    return buffer.getvalue()
