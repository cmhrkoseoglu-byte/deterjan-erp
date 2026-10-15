"""Analiz sertifikası (CoA) PDF'i: serbest bırakılan lot için ürün, lot, üretim ve SKT tarihleri,
test / spesifikasyon / sonuç tablosu ve onaylayan (Faz 2, Adım 2.1). A4, reportlab.

Türkçe karakterler için reportlab ile gelen Vera yazı tipi kullanılır (lot etiketiyle aynı).
"""

import io
import os
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

import reportlab
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.exceptions import BusinessRuleError
from apps.inventory.models import Lot
from apps.quality import services
from apps.quality.models import (
    QualityDecision,
    Sample,
    SampleStage,
    SpecificationLine,
    TestDefinition,
    TestResult,
)

FONT, FONT_BOLD = "Vera", "VeraBd"
RELEASING = (QualityDecision.Decision.RELEASE, QualityDecision.Decision.CONDITIONAL_RELEASE)


def _register_fonts() -> None:
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    pdfmetrics.registerFont(TTFont(FONT, os.path.join(folder, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(folder, "VeraBd.ttf")))


def format_decimal(value: Decimal | None, places: int) -> str:
    """Türkçe biçim: ondalık ayırıcı virgül, `places` basamak."""
    if value is None:
        return ""
    return f"{value:.{places}f}".replace(".", ",")


def spec_text(line: SpecificationLine) -> str:
    """Spesifikasyon sütunu: "6,50 – 8,00", "≥ 20,00", "≤ 1,05" ya da beklenen değer."""
    test = line.test
    if test.result_type != TestDefinition.ResultType.NUMERIC:
        if line.text_expected:
            return line.text_expected
        return "Uygun" if test.result_type == TestDefinition.ResultType.PASS_FAIL else ""
    places = test.decimal_places
    low = format_decimal(line.min_value, places)
    high = format_decimal(line.max_value, places)
    if low and high:
        return f"{low} – {high}"
    return f"≥ {low}" if low else f"≤ {high}"


def result_text(result: TestResult) -> str:
    """Sonuç sütunu (test türüne göre)."""
    test = result.spec_line.test
    if test.result_type == TestDefinition.ResultType.NUMERIC:
        return format_decimal(result.numeric_value, test.decimal_places)
    if test.result_type == TestDefinition.ResultType.PASS_FAIL:
        return "Uygun" if result.passed else "Uygun değil"
    return result.text_value


def _user_name(user: object) -> str:
    return str(user) if user is not None else ""


def releasing_decision(sample: Sample) -> QualityDecision:
    """CoA'yı doğuran karar: lotu serbest bırakan yürürlükteki karar. Yoksa `coa_not_available`."""
    decision = services.effective_decision(sample)
    if (
        decision is None
        or decision.decision not in RELEASING
        or sample.stage == SampleStage.IN_PROCESS
        or sample.lot.status != Lot.Status.RELEASED
    ):
        raise BusinessRuleError(
            "coa_not_available",
            "Analiz sertifikası yalnızca bu numuneyle serbest bırakılan lot için üretilir.",
        )
    return decision


def coa_available(sample: Sample) -> bool:
    """Numune için CoA üretilebilir mi?"""
    try:
        releasing_decision(sample)
    except BusinessRuleError:
        return False
    return True


RESULT_HEADER = ("Test", "Birim", "Spesifikasyon", "Sonuç", "Uygunluk")


def _date(value: Any) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _when(value: Any) -> str:
    return f"{timezone.localtime(value):%d.%m.%Y %H:%M}" if value else ""


def info_rows(sample: Sample) -> list[list[str]]:
    """Üst bilgi tablosu: ürün, lot, tarihler, numune ve spesifikasyon."""
    lot = sample.lot
    material = lot.material
    return [
        ["Ürün", f"{material.code} — {material.name}"],
        ["Lot no", lot.lot_no],
        ["Üretim tarihi", _date(lot.manufactured_at)],
        ["Son kullanma tarihi", _date(lot.expiry_date)],
        ["Numune no", sample.number],
        ["Spesifikasyon", str(sample.specification) if sample.specification else "—"],
    ]


def result_row(result: TestResult) -> list[str]:
    """Sonuç tablosunun bir satırı."""
    test = result.spec_line.test
    return [
        test.name,
        test.unit,
        spec_text(result.spec_line),
        result_text(result),
        "Uygun" if result.is_within_spec else "Spesifikasyon dışı",
    ]


def decision_rows(decision: QualityDecision) -> list[tuple[str, str]]:
    """Karar, şartlı kabul ayrıntısı ve onaylayan."""
    rows = [("Karar", decision.get_decision_display())]
    if decision.decision == QualityDecision.Decision.CONDITIONAL_RELEASE:
        rows.append(("Şartlı kabul gerekçesi", decision.reason))
        rows.append(
            ("Yönetim onayı", f"{_user_name(decision.approved_by)}, {_when(decision.approved_at)}")
        )
    rows.append(("Onaylayan", f"{_user_name(decision.decided_by)}, {_when(decision.decided_at)}"))
    return rows


def coa_pdf(sample: Sample) -> bytes:
    """Numunenin analiz sertifikası (PDF baytları)."""
    _register_fonts()
    sample = Sample.objects.select_related("lot__material", "specification").get(pk=sample.pk)
    decision = releasing_decision(sample)
    lot = sample.lot
    results = sorted(services.current_results(sample), key=lambda r: r.spec_line.sequence)

    base = ParagraphStyle("base", fontName=FONT, fontSize=9, leading=12)
    title = ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=16, leading=20)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.grey)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Analiz Sertifikası {lot.lot_no}",
    )
    story: list[object] = []
    company = getattr(settings, "COMPANY_NAME", "")
    if company:
        story.append(Paragraph(company, base))
    story.append(Paragraph("ANALİZ SERTİFİKASI", title))
    story.append(Paragraph("Certificate of Analysis", small))
    story.append(Spacer(1, 6 * mm))

    info_table = Table(info_rows(sample), colWidths=[45 * mm, 129 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), FONT, 9),
                ("FONT", (0, 0), (0, -1), FONT_BOLD, 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.extend([info_table, Spacer(1, 6 * mm)])

    rows = [list(RESULT_HEADER), *(result_row(result) for result in results)]
    table = Table(rows, colWidths=[52 * mm, 18 * mm, 40 * mm, 30 * mm, 34 * mm], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, -1), FONT, 9),
        ("FONT", (0, 0), (-1, 0), FONT_BOLD, 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for index, result in enumerate(results, start=1):
        if not result.is_within_spec:
            style.append(("TEXTCOLOR", (3, index), (4, index), colors.HexColor("#c92a2a")))
    table.setStyle(TableStyle(style))
    story.extend([table, Spacer(1, 6 * mm)])

    for label, value in decision_rows(decision):
        story.append(Paragraph(f"<b>{label}:</b> {escape(value)}", base))
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            f"Bu belge {timezone.localtime():%d.%m.%Y %H:%M} tarihinde sistemden üretilmiştir.",
            small,
        )
    )
    doc.build(story)  # type: ignore[arg-type]
    return buffer.getvalue()
