"""Cari hesap çıktıları: cari listesi ve ekstre Excel'i, mutabakat için A4 ekstre PDF'i.

Tutarlar yalnız "Fiyatları görür" ile yazılır (Excel'de tutar sütunları yoktur; PDF uç noktası bu
hakkı ister). PDF'te carinin adres ve vergi bilgisi yalnız iletişim bilgisini görebilene basılır.
"""

import io
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.access import PRICES
from apps.core.coding.outputs import document_control
from apps.core.formatting import format_money
from apps.core.pdf import controlled_canvas
from apps.core.permissions import has_access, sees_fields
from apps.core.xlsx import apply_document_control
from apps.ledger import selectors
from apps.ledger.models import Side
from apps.masterdata import services as masterdata
from apps.quality.coa import FONT, FONT_BOLD, _register_fonts

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STATEMENT_OUTPUT = "ledger.statement"
PARTNERS_OUTPUT = "ledger.partners"
CONTACT_GROUPS: dict[str, str] = {
    Side.CUSTOMER: "masterdata.customer.contact",
    Side.SUPPLIER: "masterdata.supplier.contact",
}
SIDE_TITLES: dict[str, str] = {
    Side.CUSTOMER: "Müşteri carileri",
    Side.SUPPLIER: "Tedarikçi carileri",
}
AGING_LABELS = ("Vadesi gelmemiş", "1-30 gün", "31-60 gün", "61-90 gün", "90+ gün")


def _date(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _signed(value: Decimal) -> str:
    """Bakiye: tutar ve (B) borçlu / (A) alacaklı."""
    if value == 0:
        return format_money(Decimal(0))
    return f"{format_money(abs(value))} ({'B' if value > 0 else 'A'})"


def _period(date_from: date | None, date_to: date | None) -> str:
    if date_from and date_to:
        return f"{_date(date_from)} – {_date(date_to)}"
    if date_from:
        return f"{_date(date_from)} sonrası"
    if date_to:
        return f"{_date(date_to)} öncesi"
    return "Tüm hareketler"


def _response(content: bytes, content_type: str, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def _append(sheet: Worksheet, values: Sequence[Any], *, bold: bool = False) -> None:
    """Satır ekler; metin hücreleri her zaman metindir (= ile başlayan ünvan formül olmaz)."""
    sheet.append(list(values))
    if not values:
        return
    for column, value in enumerate(values, start=1):
        cell = sheet.cell(row=sheet.max_row, column=column)
        if isinstance(value, str):
            cell.data_type = "s"
        if isinstance(value, Decimal):
            cell.number_format = "#,##0.00"
        if bold:
            cell.font = Font(bold=True)


def _widths(sheet: Worksheet, widths: Sequence[int]) -> None:
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _workbook_bytes(workbook: Workbook, output: str) -> bytes:
    apply_document_control(workbook, document_control(output))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- cari listesi ----------------------------------------------------------------------------


def partners_workbook(side: str, rows: list[dict[str, Any]], *, amounts: bool) -> bytes:
    """Cari listesi: cari başına, para birimi başına bir satır."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Cariler"
    _append(sheet, [SIDE_TITLES[side]], bold=True)
    sheet["A1"].font = Font(bold=True, size=14)
    _append(sheet, ["Rapor zamanı", f"{timezone.localtime():%d.%m.%Y %H:%M}"])
    _append(sheet, [])
    header = ["Kod", "Ünvan", "Vade (gün)", "Para birimi", "Son hareket"]
    if amounts:
        header += ["Borç", "Alacak", "Bakiye", "B/A", "Vadesi geçen", *AGING_LABELS]
    header.append("Tutarı eksik belge")
    _append(sheet, header, bold=True)
    for row in rows:
        partner = row["partner"]
        balances = row["balances"] or [None]
        for balance in balances:
            values: list[Any] = [
                partner.code,
                partner.name,
                partner.payment_term_days,
                balance.currency if balance else "",
                _date(balance.last_date) if balance else "",
            ]
            if amounts:
                if balance is None:
                    values += [""] * (5 + len(AGING_LABELS))
                else:
                    values += [
                        balance.debit,
                        balance.credit,
                        abs(balance.balance),
                        ("B" if balance.balance > 0 else "A") if balance.balance else "",
                        balance.overdue,
                        *(balance.aging[key] for key in selectors.AGING_BUCKETS),
                    ]
            values.append(row["missing"] or "")
            _append(sheet, values)
    _widths(sheet, [14, 40, 10, 10, 12, *([14] * 10), 12])
    sheet.freeze_panes = "A5"
    return _workbook_bytes(workbook, PARTNERS_OUTPUT)


def partners_xlsx(actor: Any, side: str, rows: list[dict[str, Any]]) -> HttpResponse:
    content = partners_workbook(side, rows, amounts=has_access(actor, PRICES))
    name = "musteri-carileri" if side == Side.CUSTOMER else "tedarikci-carileri"
    return _response(content, XLSX, f"{name}-{timezone.localdate():%Y%m%d}.xlsx")


# --- ekstre ----------------------------------------------------------------------------------


def _entry_document(entry: Any) -> str:
    for attr in ("shipment", "goods_receipt", "customer_return", "reversal_of"):
        target = getattr(entry, attr)
        if target is not None:
            return str(target.number)
    return entry.reference


def statement_workbook(
    partner: Any, date_from: date | None, date_to: date | None, *, amounts: bool
) -> bytes:
    """Ekstre: para birimi başına bir sayfa; devreden bakiye, satırlar, toplam."""
    workbook = Workbook()
    first = workbook.active
    assert first is not None
    workbook.remove(first)
    side = selectors.side_of(partner)
    currencies = selectors.statement(partner, date_from, date_to)
    blocks: list[dict[str, Any] | None] = list(currencies) or [None]
    for block in blocks:
        sheet = workbook.create_sheet(block["currency"] if block else "Ekstre")
        _append(sheet, [f"Cari hesap ekstresi — {partner.code} {partner.name}"], bold=True)
        sheet["A1"].font = Font(bold=True, size=13)
        _append(sheet, ["Dönem", _period(date_from, date_to)])
        _append(sheet, ["Para birimi", block["currency"] if block else ""])
        _append(sheet, [])
        header = ["Tarih", "Kayıt no", "Tür", "Belge", "Açıklama", "Vade"]
        if amounts:
            header += ["Matrah", "KDV", "Borç", "Alacak", "Bakiye", "B/A"]
        _append(sheet, header, bold=True)
        if block is None:
            continue
        if amounts:
            _append(
                sheet,
                [
                    _date(date_from) if date_from else "",
                    "",
                    "Devreden bakiye",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    abs(block["opening"]),
                    ("B" if block["opening"] > 0 else "A") if block["opening"] else "",
                ],
            )
        for item in block["rows"]:
            entry = item["entry"]
            values: list[Any] = [
                _date(entry.entry_date),
                entry.number,
                entry.get_kind_display() + (" (iptal edildi)" if item["is_reversed"] else ""),
                _entry_document(entry),
                entry.description,
                _date(item["due_date"]),
            ]
            if amounts:
                values += [
                    entry.net_amount if entry.net_amount is not None else "",
                    entry.vat_amount if entry.vat_amount is not None else "",
                    entry.debit or "",
                    entry.credit or "",
                    abs(item["balance"]),
                    ("B" if item["balance"] > 0 else "A") if item["balance"] else "",
                ]
            _append(sheet, values)
        if amounts:
            _append(
                sheet,
                [
                    "",
                    "",
                    "Toplam",
                    "",
                    "",
                    "",
                    "",
                    "",
                    block["total_debit"],
                    block["total_credit"],
                    abs(block["closing"]),
                    ("B" if block["closing"] > 0 else "A") if block["closing"] else "",
                ],
                bold=True,
            )
        _widths(sheet, [11, 16, 22, 18, 42, 11, 14, 12, 14, 14, 14, 5])
    if side == Side.CUSTOMER:
        returns = list(selectors.returns_of(partner, date_from, date_to))
        if returns:
            sheet = workbook.create_sheet("İadeler")
            _append(sheet, ["İade no", "Tarih", "Sevkiyat", "İade dekontu"], bold=True)
            for document in returns:
                _append(
                    sheet,
                    [
                        document.number,
                        _date(document.return_date),
                        document.shipment.number if document.shipment else "",
                        "Girildi" if getattr(document, "has_credit", False) else "Girilmedi",
                    ],
                )
            _widths(sheet, [16, 12, 16, 14])
    return _workbook_bytes(workbook, STATEMENT_OUTPUT)


def _file_name(partner: Any, extension: str) -> str:
    code = "".join(char if char.isalnum() or char in "-_" else "-" for char in partner.code)
    return f"ekstre-{code}-{timezone.localdate():%Y%m%d}.{extension}"


def statement_xlsx(
    actor: Any, partner: Any, date_from: date | None, date_to: date | None
) -> HttpResponse:
    content = statement_workbook(partner, date_from, date_to, amounts=has_access(actor, PRICES))
    return _response(content, XLSX, _file_name(partner, "xlsx"))


def statement_document(
    partner: Any, date_from: date | None, date_to: date | None, *, contact: bool
) -> bytes:
    """Mutabakat ekstresi (A4 dikey): firma, cari, dönem; para birimi başına devreden bakiye,
    hareketler ve kapanış bakiyesi; mutabakat notu."""
    _register_fonts()
    base = ParagraphStyle("base", fontName=FONT, fontSize=8.5, leading=11)
    bold = ParagraphStyle("bold", parent=base, fontName=FONT_BOLD)
    title = ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=15, leading=19)
    cell = ParagraphStyle("cell", parent=base, fontSize=7.5, leading=9)
    small = ParagraphStyle("small", parent=base, fontSize=7.5, leading=10, textColor=colors.grey)

    def para(text: str, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(escape(text or "").replace("\n", "<br/>"), style)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"Cari hesap ekstresi {partner.code}",
    )
    company = masterdata.get_company_profile()
    ours = [para(company.legal_name or "—", bold), para(company.address)]
    if company.tax_office or company.tax_number:
        ours.append(para(f"V.D.: {company.tax_office}  V.No: {company.tax_number}"))
    document = [
        para("CARİ HESAP EKSTRESİ", title),
        para(f"Dönem: {_period(date_from, date_to)}"),
        para(f"Tarih: {_date(timezone.localdate())}"),
    ]
    header = Table([[ours, document]], colWidths=[100 * mm, 86 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    theirs = [para(f"{partner.code} — {partner.name}", bold)]
    if contact:
        if partner.address:
            theirs.append(para(partner.address))
        if partner.tax_office or partner.tax_number:
            theirs.append(para(f"V.D.: {partner.tax_office}  V.No: {partner.tax_number}"))
    if partner.payment_term_days:
        theirs.append(para(f"Vade: {partner.payment_term_days} gün"))
    box = Table([[theirs]], colWidths=[186 * mm])
    box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#adb5bd"))]))
    story: list[object] = [header, Spacer(1, 4 * mm), box]
    currencies = selectors.statement(partner, date_from, date_to)
    if not currencies:
        story += [Spacer(1, 6 * mm), para("Bu carinin hareketi yok.")]
    widths = [17 * mm, 25 * mm, 28 * mm, 52 * mm, 21 * mm, 21 * mm, 22 * mm]
    for block in currencies:
        rows: list[list[Any]] = [
            ["Tarih", "Kayıt no", "Tür / belge", "Açıklama", "Borç", "Alacak", "Bakiye"],
            ["", "", para("Devreden bakiye", cell), "", "", "", _signed(block["opening"])],
        ]
        for item in block["rows"]:
            entry = item["entry"]
            kind = entry.get_kind_display()
            reference = _entry_document(entry)
            rows.append(
                [
                    _date(entry.entry_date),
                    entry.number,
                    para(f"{kind}\n{reference}" if reference else kind, cell),
                    para(entry.description, cell),
                    format_money(entry.debit) if entry.debit else "",
                    format_money(entry.credit) if entry.credit else "",
                    _signed(item["balance"]),
                ]
            )
        rows.append(
            [
                "",
                "",
                para("Toplam", bold),
                "",
                format_money(block["total_debit"]),
                format_money(block["total_credit"]),
                _signed(block["closing"]),
            ]
        )
        table = Table(rows, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, -1), FONT, 7.5),
                    ("FONT", (0, 0), (-1, 0), FONT_BOLD, 7.5),
                    ("FONT", (0, -1), (-1, -1), FONT_BOLD, 7.5),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9ecef")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#adb5bd")),
                    ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story += [
            Spacer(1, 5 * mm),
            para(f"Para birimi: {block['currency']}", bold),
            Spacer(1, 1.5 * mm),
            table,
        ]
    closing = ", ".join(f"{_signed(b['closing'])} {b['currency']}" for b in currencies)
    story += [
        Spacer(1, 8 * mm),
        para(
            "Kayıtlarımıza göre dönem sonu bakiyeniz "
            f"{closing or '0,00'} olarak görünmektedir. Mutabık değilseniz hesap ekstrenizle "
            "birlikte bildirmenizi rica ederiz. (B): borçlu, (A): alacaklı."
        ),
        Spacer(1, 12 * mm),
        Table(
            [[para("Firmamız adına", bold), para("Cari adına (kaşe / imza)", bold)]],
            colWidths=[93 * mm, 93 * mm],
        ),
        Spacer(1, 14 * mm),
        para(
            f"Bu belge {timezone.localtime():%d.%m.%Y %H:%M} tarihinde sistemden üretilmiştir.",
            small,
        ),
    ]
    control = document_control(STATEMENT_OUTPUT)
    doc.build(story, canvasmaker=controlled_canvas(control))  # type: ignore[arg-type]
    return buffer.getvalue()


def statement_pdf(
    actor: Any, partner: Any, date_from: date | None, date_to: date | None
) -> HttpResponse:
    contact = sees_fields(actor, CONTACT_GROUPS[selectors.side_of(partner)])
    content = statement_document(partner, date_from, date_to, contact=contact)
    return _response(content, "application/pdf", _file_name(partner, "pdf"))
