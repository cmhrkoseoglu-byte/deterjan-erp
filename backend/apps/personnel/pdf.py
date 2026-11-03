"""Bordro PDF'leri (docs/DECISIONS.md "Personel bordrosu"): işveren maliyeti tablosu ve bordro
listesi (icmal sayfasıyla).

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
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.core.audit import mask_identifier
from apps.core.formatting import format_money
from apps.core.labels import FONT, FONT_BOLD, register_fonts
from apps.masterdata import services as masterdata
from apps.personnel import selectors
from apps.personnel.models import PayrollItemKind
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


def row_order(row: PayrollRow) -> tuple[str, str, int]:
    """Satır sırası: birim, sonra ad (ekrandaki ve Excel'deki gibi)."""
    person = row.employee
    return (person.department, selectors.fold(person.full_name), person.pk)


def employer_cost_rows(month: PayrollMonth) -> list[tuple[str, list[str]]]:
    """İşveren maliyeti tablosunun satırları: birim birim kişiler, birim toplamı (birden çok kişili
    birimde) ve genel toplam. Her satır (tür, hücreler); tür "row", "subtotal" ya da "total"."""
    groups: dict[str, list[PayrollRow]] = {}
    for row in sorted(month.rows, key=row_order):
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
        [[_company_block(para, bold), heading]], colWidths=[146 * mm, 126 * mm], hAlign="LEFT"
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


# --- bordro listesi ------------------------------------------------------------------------------

REGISTER_HEADER = (
    "Kişi",
    "SGK gün",
    "Kazançlar",
    "Brüt toplam",
    "SGK matrahı",
    "SGK işçi / işsizlik işçi",
    "GV matrahı / kümülatif",
    "Gelir vergisi (hesaplanan / istisna / kesilen)",
    "Damga vergisi (hesaplanan / istisna / kesilen)",
    "Net ücret",
    "Kesintiler",
    "Ödenecek / işverene maliyet",
    "Not",
)
# Sütun genişlikleri (mm): A4 yatay, 10 mm kenar boşluklarıyla çerçeveye (yaklaşık 272,8 mm) sığar.
REGISTER_WIDTHS = (34, 10, 29, 19, 20, 20, 23, 23, 19, 19, 25, 25, 6)
# Satır işaretleri ve açıklamaları (sayfanın altında).
REGISTER_MARKS = (
    (selectors.OPENING_MISSING, "D", "devir girilmedi: gelir vergisi kümülatifsiz hesaplandı"),
    (
        selectors.CARRY_INCOMPLETE,
        "Z",
        "kümülatif eksik: önceki bir ayda ücret eksik, parametre tahmini ya da devir eski "
        "parametrelerle kaydedilmiş",
    ),
    (selectors.MISSING_WAGE, "Ü", "ücreti girilmemiş günler sıfır sayıldı"),
    (selectors.NEGATIVE_PAYABLE, "N", "kesintiler netten fazla: ödenecek negatif"),
    (
        selectors.CEILING_WITH_BONUS,
        "P",
        "tavanı aşan prim / ikramiye: sonraki aylara devreden SGK matrahı mali müşavirde",
    ),
    ("floor", "A", "SGK matrahı alt sınıra çıkarıldı"),
    ("ceiling", "T", "SGK matrahı tavanla kesildi"),
)
EXTERNAL_HEADER = ("Kişi", "Brüt toplam", "İşverene maliyet", "Not")


def register_marks(row: PayrollRow) -> list[str]:
    """Satırın işaret harfleri (açıklamaları `REGISTER_MARKS`)."""
    present = set(row.warnings)
    if row.line.floor_applied:
        present.add("floor")
    if row.line.ceiling_applied:
        present.add("ceiling")
    return [mark for key, mark, _ in REGISTER_MARKS if key in present]


def _person_cell(row: PayrollRow) -> str:
    person = row.employee
    lines = [person.full_name, " · ".join(filter(None, [person.employee_no, person.department]))]
    if person.national_id:
        lines.append(f"TC {mask_identifier(person.national_id)}")
    return "\n".join(lines)


def _deduction_lines(rows: Sequence[PayrollRow]) -> list[str]:
    """BES ve kesintiler kategoriye göre (açıklama yazılmaz: icra ve nafaka bilgisi)."""
    bes = sum((row.line.bes_deduction for row in rows), Decimal(0))
    totals: dict[str, Decimal] = {}
    for row in rows:
        for item in row.items:
            if item.kind == PayrollItemKind.DEDUCTION:
                label = item.get_category_display()
                totals[label] = totals.get(label, Decimal(0)) + item.amount
    lines = [f"BES {_money(bes)}"] if bes else []
    lines.extend(f"{label} {_money(amount)}" for label, amount in totals.items())
    return lines or ["—"]


def _sum(rows: Sequence[PayrollRow], name: str) -> Decimal:
    return sum((getattr(row.line, name) for row in rows), Decimal(0))


def _register_cells(rows: Sequence[PayrollRow], person: str, marks: str) -> list[str]:
    """Bir satırın (kişi ya da toplam) hücreleri; kalemler alt alta."""

    def total(name: str) -> Decimal:
        return _sum(rows, name)

    earnings = [f"Normal {_money(total('salary'))}"]
    overtime = total("overtime_worked_pay") + total("overtime_rest_pay") + total("holiday_pay")
    if overtime:
        earnings.append(f"FM ve tatil {_money(overtime)}")
    if total("extras_total"):
        earnings.append(f"Ek ödeme {_money(total('extras_total'))}")
    base = [_money(total("sgk_base"))]
    if total("meal_exemption"):
        base.append(f"Yemek ist. {_money(total('meal_exemption'))}")
    days = [str(sum(row.line.sgk_days for row in rows))]
    return [
        person,
        "\n".join(days),
        "\n".join(earnings),
        _money(total("gross_total")),
        "\n".join(base),
        f"{_money(total('employee_sgk'))}\n{_money(total('employee_unemployment'))}",
        f"{_money(total('tax_base'))}\n{_money(total('cumulative_tax_base_after'))}",
        f"{_money(total('income_tax_computed'))}\n−{_money(total('income_tax_exemption'))}\n"
        f"{_money(total('income_tax'))}",
        f"{_money(total('stamp_tax_computed'))}\n−{_money(total('stamp_tax_exemption'))}\n"
        f"{_money(total('stamp_tax'))}",
        _money(total("net_pay")),
        "\n".join(_deduction_lines(rows)),
        f"{_money(total('payable'))}\n{_money(total('employer_cost'))}",
        marks,
    ]


def register_rows(month: PayrollMonth) -> list[tuple[str, list[str]]]:
    """Bordro listesinin satırları: birim birim ERP'de hesaplanan kişiler, birim toplamı (birden
    çok kişili birimde) ve genel toplam. Her satır (tür, hücreler); tür "row", "subtotal" ya da
    "total". Kümülatif GV matrahı bu ay dahildir (mali müşavir bordrolarındaki gibi)."""
    groups: dict[str, list[PayrollRow]] = {}
    for row in sorted(month.computed, key=row_order):
        groups.setdefault(row.employee.department, []).append(row)
    lines: list[tuple[str, list[str]]] = []
    for department, members in groups.items():
        for row in members:
            lines.append(
                ("row", _register_cells([row], _person_cell(row), " ".join(register_marks(row))))
            )
        if len(groups) > 1 and len(members) > 1:
            lines.append(("subtotal", _register_cells(members, f"{department} toplamı", "")))
    lines.append(("total", _register_cells(month.computed, "Genel toplam", "")))
    return lines


def external_rows(month: PayrollMonth) -> list[list[str]]:
    """Bordrosu mali müşavirde olan kişiler (bu listede hesaplanmadı; toplamlara katılmaz). Kişiye
    ERP'de girilmiş ek ödeme ve kesintiler hesaplanmaz; notta kalem toplamlarıyla (açıklamasız)
    yazılır, mali müşavire iletilsin."""
    found = []
    for row in sorted((item for item in month.rows if item.external), key=row_order):
        figure = row.figure
        notes = [] if figure else ["rakam girilmedi"]
        totals: dict[str, Decimal] = {}
        for item in row.items:
            label = item.get_category_display()
            totals[label] = totals.get(label, Decimal(0)) + item.amount
        if totals:
            listed = "; ".join(f"{label} {_money(amount)}" for label, amount in totals.items())
            notes.append(f"ERP'de girilen kalemler hesaplanmadı: {listed}")
        found.append(
            [
                _person_cell(row),
                _money(figure.gross_total) if figure else "",
                _money(figure.employer_cost) if figure else "",
                "\n".join(notes),
            ]
        )
    return found


def summary_rows(month: PayrollMonth) -> list[tuple[str, list[tuple[str, str]]]]:
    """İcmal (mali müşavirin icmaliyle karşılaştırma için): çalışan ve işveren tarafı."""
    rows = month.computed

    def total(name: str) -> str:
        return _money(_sum(rows, name))

    extras: dict[str, Decimal] = {}
    for row in rows:
        for item in row.items:
            if item.kind == PayrollItemKind.EXTRA:
                label = item.get_category_display()
                extras[label] = extras.get(label, Decimal(0)) + item.amount
    external = [row for row in month.rows if row.external]
    employee_side = [
        ("Kişi (ERP / mali müşavirde)", f"{len(rows)} / {len(external)}"),
        ("SGK gün toplamı", str(sum(row.line.sgk_days for row in rows))),
        ("Normal ücret", total("salary")),
        ("Fazla mesai (iş günü)", total("overtime_worked_pay")),
        ("Fazla mesai (hafta tatili)", total("overtime_rest_pay")),
        ("Resmî tatil", total("holiday_pay")),
        *((f"Ek ödeme: {label}", _money(amount)) for label, amount in extras.items()),
        ("Brüt toplam", total("gross_total")),
        ("Nakit yemek SGK istisnası", total("meal_exemption")),
        ("SGK matrahı", total("sgk_base")),
        ("SGK işçi payı", total("employee_sgk")),
        ("İşsizlik işçi payı", total("employee_unemployment")),
        ("Gelir vergisi matrahı", total("tax_base")),
        ("Hesaplanan gelir vergisi", total("income_tax_computed")),
        ("Asgari ücret GV istisnası", total("income_tax_exemption")),
        ("Kesilen gelir vergisi", total("income_tax")),
        ("Hesaplanan damga vergisi", total("stamp_tax_computed")),
        ("Asgari ücret DV istisnası", total("stamp_tax_exemption")),
        ("Kesilen damga vergisi", total("stamp_tax")),
        ("Net ücret", total("net_pay")),
        *((f"Kesinti: {line}", "") for line in _deduction_lines(rows) if line != "—"),
        ("Ödenecek", total("payable")),
    ]
    employer_side = [
        ("SGK işveren payı (teşvik öncesi)", total("employer_sgk_gross")),
        ("Teşvik", f"−{total('incentive')}"),
        ("SGK işveren payı (teşvik sonrası)", total("employer_sgk")),
        ("İşsizlik işveren payı", total("employer_unemployment")),
        ("Alt sınır farkı", total("floor_gap")),
        ("İşverene maliyet (ERP)", total("employer_cost")),
        (
            "Mali müşavirdekiler: brüt / maliyet",
            f"{_money(sum((row.gross_total for row in external), Decimal(0)))} / "
            f"{_money(sum((row.employer_cost for row in external), Decimal(0)))}",
        ),
        ("İşverene maliyet (hepsi)", _money(month.employer_cost)),
    ]
    return [("Çalışan", employee_side), ("İşveren", employer_side)]


def register_pdf(month: PayrollMonth, *, draft: bool = True) -> bytes:
    """Bordro listesi (A4 yatay): ERP'de hesaplanan kişiler brütten nete, birim ara toplamları ve
    genel toplam; bordrosu mali müşavirde olanlar ayrı blokta (toplamlara katılmaz); son sayfada
    icmal. Maskeli TC kimlik no; kesintiler kategoriyle (açıklama yazılmaz)."""
    register_fonts()
    base = ParagraphStyle("base", fontName=FONT, fontSize=6.5, leading=8)
    bold = ParagraphStyle("bold", parent=base, fontName=FONT_BOLD)
    right = ParagraphStyle("right", parent=base, alignment=2)
    right_bold = ParagraphStyle("right_bold", parent=right, fontName=FONT_BOLD)
    title_style = ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=14, leading=18)
    small = ParagraphStyle("small", parent=base, fontSize=7, leading=9, textColor=colors.grey)
    header_style = ParagraphStyle("header", parent=bold, fontSize=6.5, leading=8)

    def para(text: str, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), style)

    title = f"Bordro listesi — {month.label}"
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
        para("BORDRO LİSTESİ", title_style),
        para(f"Dönem: {month.label}", bold),
        para("Ön bordro" + (" · TASLAK" if draft else "")),
    ]
    header = Table(
        [[_company_block(para, bold), heading]], colWidths=[146 * mm, 126 * mm], hAlign="LEFT"
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    data: list[list[Any]] = [[para(text, header_style) for text in REGISTER_HEADER]]
    style: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]
    used: set[str] = set()
    for index, (kind, cells) in enumerate(register_rows(month), start=1):
        summary = kind in ("subtotal", "total")
        used.update(cells[-1].split())
        data.append(
            [
                para(cells[0], bold if summary else base),
                *(para(cell, right_bold if summary else right) for cell in cells[1:-1]),
                para(cells[-1], bold),
            ]
        )
        if summary:
            style.append(("BACKGROUND", (0, index), (-1, index), SUBTOTAL_FILL))
    table = Table(
        data, colWidths=[width * mm for width in REGISTER_WIDTHS], repeatRows=1, hAlign="LEFT"
    )
    table.setStyle(TableStyle(style))
    story: list[Any] = [
        header,
        Spacer(1, 3 * mm),
        para(status_line(month), small),
        para(parameter_line(month), small),
        Spacer(1, 3 * mm),
        table,
    ]
    legend = [f"{mark}: {text}" for _, mark, text in REGISTER_MARKS if mark in used]
    if legend:
        story += [Spacer(1, 2 * mm), para("İşaretler — " + "; ".join(legend) + ".", small)]
    externals = external_rows(month)
    if externals:
        block: list[list[Any]] = [[para(text, header_style) for text in EXTERNAL_HEADER]]
        block += [
            [para(cells[0]), para(cells[1], right), para(cells[2], right), para(cells[3])]
            for cells in externals
        ]
        external_table = Table(
            block, colWidths=[60 * mm, 30 * mm, 30 * mm, 90 * mm], repeatRows=1, hAlign="LEFT"
        )
        external_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
                    ("GRID", (0, 0), (-1, -1), 0.5, GRID),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story += [
            Spacer(1, 4 * mm),
            para(
                f"Bordrosu mali müşavirde olan {len(externals)} kişi (bu listede hesaplanmadı; "
                "toplamlara katılmadı)",
                bold,
            ),
            Spacer(1, 1 * mm),
            external_table,
        ]
    sides = []
    for caption, items in summary_rows(month):
        rows = [[para(caption, header_style), para("TL", header_style)]]
        rows += [[para(label), para(value, right)] for label, value in items]
        side = Table(rows, colWidths=[80 * mm, 40 * mm], hAlign="LEFT")
        side.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
                    ("GRID", (0, 0), (-1, -1), 0.5, GRID),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        sides.append(side)
    summary = Table([sides], colWidths=[130 * mm, 130 * mm], hAlign="LEFT")
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [
        PageBreak(),
        para(f"İCMAL — {month.label}", title_style),
        para(status_line(month), small),
        Spacer(1, 3 * mm),
        summary,
        Spacer(1, 3 * mm),
        para(
            "Kümülatif gelir vergisi matrahı bu ay dahildir. Kesintiler kategoriyle yazılır; "
            "açıklamalar kişinin pusulasındadır. Asgari ücret desteği düşülmemiştir.",
            small,
        ),
    ]
    chrome = _Chrome(title, draft)
    doc.build(story, canvasmaker=chrome.canvas_maker())
    return buffer.getvalue()
