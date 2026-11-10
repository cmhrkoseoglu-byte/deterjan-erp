"""Etiket çizim altyapısı: bir etiketi öğe listesi olarak tanımlar, PDF (reportlab) ve ZPL
(Zebra) olarak üretir.

Koordinatlar milimetre, başlangıç sol üst köşedir. Yazı boyutu punto (pt) olarak verilir.
ZPL 203 dpi (8 nokta/mm) için üretilir (Karar D-8); başka çözünürlük `dpi` ile verilebilir.

GS1-128 barkodları uygulama tanımlayıcısı (AI) + değer çiftleriyle verilir. PDF'te başa ve
değişken uzunluklu alanların arkasına FNC1 konur; ZPL'de `^BC` UCC/EAN kipi (D) kullanılır ve
veri "(01)…(10)…" biçiminde gönderilir, FNC1'i yazıcı ekler. Bu kipte değer parantez ve ">"
taşıyamaz (`is_gs1_printable`). Code128 yalnızca yazdırılabilir ASCII taşır, ">" hariç: ZPL'de
`^BC` kip öneki (`is_code128_text`).

ZPL'de "^" ve "~" komut önekidir: bunları ya da ters bölü taşıyan alan verisi onaltılık kaçışla
(`^FH\\`) gönderilir, yazıcı veriyi aynen basar ve kodlar (`_zpl_field`).
"""

import io
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import reportlab
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT, FONT_BOLD = "Vera", "VeraBd"
DEFAULT_DPI = 203
FNC1 = "\xf1"
# Sabit uzunluklu GS1 uygulama tanımlayıcıları (değer uzunluğu); listede olmayanlar değişkendir.
GS1_FIXED_LENGTH = {"00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
# GS1 (37) koli sayısı alanı en çok 8 hanedir (GS1 General Specifications).
GS1_CASE_COUNT_MAX = 99_999_999
# GS1'in 82 karakterlik kümesi (GS1 General Specifications): (10) lot gibi alfanümerik alanlar
# yalnızca bunlardan oluşur; boşluk ve Türkçe harfler kümede yoktur.
GS1_CHARSET_82 = frozenset(
    "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"
)
# ZPL `^BC` UCC/EAN kipi (D) veriyi "(AI)değer" biçiminde alır: parantezleri AI sınırı sayıp veriden
# çıkarır, ">" kip (invocation) karakteridir. Bu karakterli değer GS1-128 barkoduna yazılmaz.
ZPL_GS1_RESERVED = frozenset("()>")
# Code128'e yazılamayan veride (Türkçe harf, ">") barkodun yerine basılan yazı; QR veriyi aynen
# taşır.
NO_BARCODE_QR = "Barkod yok: QR kodu okutun."

Gs1Elements = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Text:
    x: float
    y: float
    text: str
    size: float = 10
    bold: bool = False
    max_width: float | None = None


@dataclass(frozen=True)
class Barcode:
    """Code128 barkod. `gs1` verilirse GS1-128 olarak kodlanır, `data` yok sayılır. `data`
    Code128'e aynen yazılabilmelidir (`is_code128_text`); değişken veri `code128_or_note` ile
    basılır."""

    x: float
    y: float
    height: float
    data: str = ""
    gs1: Gs1Elements | None = None
    module: float = 0.375  # dar çubuk genişliği (mm); 203 dpi'de 3 nokta
    human_readable: bool = True
    center_width: float | None = None  # verilirse barkod bu genişlik içinde ortalanır (PDF)

    def __post_init__(self) -> None:
        # Yazılamayan veri barkodda sessizce başka bir değer olurdu (Türkçe harf, ZPL'de ">").
        if self.gs1 is None and not is_code128_text(self.data):
            raise ValueError(f"Code128'e aynen yazılamayan barkod verisi: {self.data!r}")


@dataclass(frozen=True)
class QRCode:
    x: float
    y: float
    size: float
    data: str


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float
    thickness: float = 0.4


Element = Text | Barcode | QRCode | Box


@dataclass
class Label:
    width: float  # mm
    height: float  # mm
    elements: list[Element] = field(default_factory=list)
    title: str = "Etiket"


# --- GS1 yardımcıları --------------------------------------------------------------------------


def gs1_check_digit(digits: str) -> str:
    """GS1 mod-10 kontrol hanesi (GTIN, SSCC). `digits` kontrol hanesi hariç sayılardır."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        total += int(char) * (3 if index % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def is_ascii_digits(value: str) -> bool:
    """Yalnızca ASCII rakam (0-9) mı? `str.isdigit` Arapça-Hint ve üst simge rakamları da kabul
    eder; barkoda yalnızca ASCII rakam girer."""
    return value.isascii() and value.isdigit()


def is_valid_gtin(value: str) -> bool:
    """GTIN-8/12/13/14 biçimi (yalnızca ASCII rakam) ve kontrol hanesi doğru mu."""
    return (
        is_ascii_digits(value)
        and len(value) in (8, 12, 13, 14)
        and gs1_check_digit(value[:-1]) == value[-1]
    )


def gtin14(value: str) -> str:
    """GTIN'i (01) alanı için 14 haneye tamamlar."""
    return value.zfill(14)


def is_gs1_text(value: str, max_length: int) -> bool:
    """Değer GS1 alfanümerik alanına (ör. (10) lot, en çok 20 karakter) yazılabilir mi: 1 ile
    `max_length` arası karakter, hepsi GS1'in 82 karakterlik kümesinden."""
    return 1 <= len(value) <= max_length and set(value) <= GS1_CHARSET_82


def is_gs1_printable(value: str, max_length: int) -> bool:
    """Değer bu modülün GS1-128 barkoduna (PDF ve ZPL) aynen yazılabilir mi: GS1 alanına uyar
    (`is_gs1_text`) ve ZPL'nin UCC/EAN kipinde (D) yorumlanan "(", ")", ">" karakterlerini taşımaz
    (ör. LOT(2) yazıcıda LOT2 olarak kodlanır)."""
    return is_gs1_text(value, max_length) and not set(value) & ZPL_GS1_RESERVED


def is_code128_text(value: str) -> bool:
    """Değer Code128 barkoduna aynen yazılabilir mi: yalnızca yazdırılabilir ASCII (boşluk dahil),
    ">" hariç. Code128 Türkçe harfi taşımaz; reportlab onu sessizce atar (LOT:ŞUBAT-01 →
    LOT:UBAT-01) ve barkod başka bir değer okutur. ZPL `^BC`'de ">" otomatik kipte de kip
    (invocation) önekidir: Zebra tablosunda "><" = "^", ">0" = ">" (alt küme A ve B; C'de "30").
    Doğru kaçış yazıcının seçtiği alt kümeye bağlı olduğundan ">" taşıyan veri barkoda yazılmaz."""
    return bool(value) and value.isascii() and value.isprintable() and ">" not in value


def code128_or_note(
    data: str, x: float, y: float, height: float, width: float, note: str, *, module: float
) -> Element:
    """Code128 barkod (`data`, `width` içinde ortalı). Code128'e yazılamayan veride (Türkçe harf:
    reportlab sessizce atar; ">": ZPL'de kip öneki; barkod başka değer okuturdu) barkod basılmaz;
    yerine hangi kodun okutulacağını söyleyen kalın yazı (`note`) basılır."""
    if is_code128_text(data):
        return Barcode(x, y, height, data=data, module=module, center_width=width)
    size = fit_size(note, 11, width=width, bold=True)
    return Text(x, y + height / 2 - 2, note, size=size, bold=True, max_width=width)


def gs1_text(elements: Gs1Elements) -> str:
    """İnsan okunur GS1 metni: (01)08690000000017(10)B-261015-001"""
    return "".join(f"({ai}){value}" for ai, value in elements)


def gs1_pdf_data(elements: Gs1Elements) -> str:
    """reportlab Code128 verisi: FNC1 + AI + değer; değişken alanın arkasında FNC1 ayırıcı."""
    parts = [FNC1]
    for index, (ai, value) in enumerate(elements):
        parts.append(ai + value)
        if ai not in GS1_FIXED_LENGTH and index < len(elements) - 1:
            parts.append(FNC1)
    return "".join(parts)


# --- PDF ---------------------------------------------------------------------------------------


def register_fonts() -> None:
    """Türkçe karakterler için reportlab ile gelen Vera yazı tiplerini kaydeder."""
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    pdfmetrics.registerFont(TTFont(FONT, os.path.join(folder, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(folder, "VeraBd.ttf")))


def fit_size(
    text: str, size: float, *, width: float, bold: bool = False, minimum: float = 8
) -> float:
    """Metnin `width` (mm) genişliğe sığdığı yazı boyutu: en fazla `size`, en az `minimum`.

    Kod gibi kısaltılmaması gereken metinler için (`fit_text` sığmayanı "…" ile keser). PDF yazı
    tipiyle ölçülür; Zebra'nın A0 yazı tipi daha dar olduğundan ZPL'de de sığar.
    """
    register_fonts()
    natural = pdfmetrics.stringWidth(text, FONT_BOLD if bold else FONT, size)
    limit = width * mm
    if natural <= limit or natural == 0:
        return size
    return max(minimum, int(size * limit / natural * 10) / 10)


def fit_text(text: str, font: str, size: float, width: float) -> str:
    """Metni genişliğe (pt) sığacak şekilde kısaltır."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _draw_pdf(pdf: canvas.Canvas, label: Label) -> None:
    height = label.height * mm

    def top(y: float, h: float) -> float:
        return height - (y + h) * mm

    for element in label.elements:
        if isinstance(element, Text):
            font = FONT_BOLD if element.bold else FONT
            text = element.text
            if element.max_width is not None:
                text = fit_text(text, font, element.size, element.max_width * mm)
            pdf.setFont(font, element.size)
            # Yazı kutusunun üstü y; taban çizgisi bir punto yüksekliğinin %80'i aşağıda.
            pdf.drawString(element.x * mm, height - element.y * mm - element.size * 0.8, text)
        elif isinstance(element, Barcode):
            if element.gs1 is not None:
                data = gs1_pdf_data(element.gs1)
                readable = gs1_text(element.gs1)
            else:
                data = readable = element.data
            barcode = code128.Code128(
                data, barHeight=element.height * mm, barWidth=element.module * mm, quiet=False
            )
            if element.center_width is not None and barcode.width > element.center_width * mm:
                # Sığmayan barkod daraltılır (uzun lot numaraları).
                barcode = code128.Code128(
                    data,
                    barHeight=element.height * mm,
                    barWidth=element.module * mm * element.center_width * mm / barcode.width,
                    quiet=False,
                )
            x = element.x * mm
            if element.center_width is not None:
                x += max(0.0, (element.center_width * mm - barcode.width) / 2)
            barcode.drawOn(pdf, x, top(element.y, element.height))
            if element.human_readable:
                pdf.setFont(FONT, 8)
                pdf.drawCentredString(
                    x + barcode.width / 2, top(element.y, element.height) - 9, readable
                )
        elif isinstance(element, QRCode):
            size = element.size * mm
            widget = qr.QrCodeWidget(element.data)
            x1, y1, x2, y2 = widget.getBounds()
            drawing = Drawing(
                size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0]
            )
            drawing.add(widget)
            renderPDF.draw(drawing, pdf, element.x * mm, top(element.y, element.size))
        elif isinstance(element, Box):
            pdf.setLineWidth(element.thickness * mm)
            pdf.rect(
                element.x * mm,
                top(element.y, element.height),
                element.width * mm,
                element.height * mm,
            )


def render_pdf(labels: Sequence[Label], *, a4: bool = False) -> bytes:
    """Etiketleri tek PDF'te üretir. `a4=False`: her etiket kendi boyutunda bir sayfa.
    `a4=True`: A4 kâğıda sığdığı kadar yan yana / alt alta, kesim çizgisiyle."""
    register_fonts()
    buffer = io.BytesIO()
    first = labels[0] if labels else Label(100, 150)
    page = A4 if a4 else (first.width * mm, first.height * mm)
    pdf = canvas.Canvas(buffer, pagesize=page)
    pdf.setTitle(first.title)
    if not labels:
        pdf.showPage()
    elif not a4:
        for label in labels:
            pdf.setPageSize((label.width * mm, label.height * mm))
            _draw_pdf(pdf, label)
            pdf.showPage()
    else:
        page_w, page_h = A4
        cols = max(1, int(page_w // (first.width * mm)))
        rows = max(1, int(page_h // (first.height * mm)))
        margin_x = (page_w - cols * first.width * mm) / 2
        margin_y = (page_h - rows * first.height * mm) / 2
        per_page = cols * rows
        for index, label in enumerate(labels):
            slot = index % per_page
            if index and slot == 0:
                pdf.showPage()
            col, row = slot % cols, slot // cols
            pdf.saveState()
            pdf.translate(
                margin_x + col * first.width * mm,
                page_h - margin_y - (row + 1) * first.height * mm,
            )
            pdf.setDash(2, 2)
            pdf.setLineWidth(0.3)
            pdf.rect(0, 0, first.width * mm, first.height * mm)
            pdf.setDash()
            _draw_pdf(pdf, label)
            pdf.restoreState()
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


# --- ZPL ---------------------------------------------------------------------------------------


# Onaltılık kaçış (`^FH\`, kaçış işareti ters bölü): yazıcı \5C, \5E, \7E'yi \, ^, ~ olarak okur.
_ZPL_HEX_ESCAPES = {"\\": "\\5C", "^": "\\5E", "~": "\\7E"}


def _zpl_field(data: str, *, block: bool = False) -> str:
    """ZPL alan verisi (`^FD…^FS`). "^" ve "~" komut önekidir: bunları ya da ters bölü taşıyan
    veri onaltılık kaçışla gönderilir (`^FH\\`), yazıcı veriyi aynen basar ve kodlar. Öteki veri
    değişmeden gider.

    `block`: alan bir ^FB metin bloğudur. Orada ters bölü de kaçış karakteridir ("\\&" yeni
    satır); ters bölünün kendisi "\\\\" yazılır (ZPL ^FB). Yazıcı önce onaltılık kaçışı çözer."""
    if _ZPL_HEX_ESCAPES.keys().isdisjoint(data):
        return f"^FD{data}^FS"
    if block:
        data = data.replace("\\", "\\\\")
    escaped = "".join(_ZPL_HEX_ESCAPES.get(char, char) for char in data)
    return f"^FH\\^FD{escaped}^FS"


def _barcode_modules(element: Barcode) -> float:
    """Code128 barkodun (sessiz bölgesiz) modül sayısı; ZPL'de genişlik hesabı için."""
    data = gs1_pdf_data(element.gs1) if element.gs1 is not None else element.data
    return float(code128.Code128(data, barWidth=1, quiet=False).width)


def render_zpl(labels: Iterable[Label], *, dpi: int = DEFAULT_DPI) -> str:
    """Etiketleri ZPL II olarak üretir (her etiket ^XA … ^XZ). UTF-8 (^CI28)."""
    dots = dpi / 25.4

    def d(value: float) -> int:
        return round(value * dots)

    out: list[str] = []
    for label in labels:
        lines = ["^XA", "^CI28", f"^PW{d(label.width)}", f"^LL{d(label.height)}", "^LH0,0"]
        for element in label.elements:
            if isinstance(element, Text):
                h = max(10, round(element.size * dpi / 72))
                font = f"^A0N,{h},{h if element.bold else round(h * 0.85)}"
                block = ""
                if element.max_width is not None:
                    block = f"^FB{d(element.max_width)},1,0,L,0"
                field = _zpl_field(element.text, block=bool(block))
                lines.append(f"^FO{d(element.x)},{d(element.y)}{font}{block}{field}")
            elif isinstance(element, Barcode):
                module = max(1, d(element.module))
                if element.center_width is not None:
                    # Yazıcı nokta tam sayıdır: yuvarlanan çubuk genişliği alanı taşırmasın.
                    fit = int(element.center_width * dots // _barcode_modules(element))
                    module = max(1, min(module, fit))
                readable = "Y" if element.human_readable else "N"
                if element.gs1 is not None:
                    data = gs1_text(element.gs1)
                    mode = "D"
                else:
                    data = element.data  # ">" (kip öneki) taşımaz: `is_code128_text`
                    mode = "A"
                lines.append(
                    f"^FO{d(element.x)},{d(element.y)}^BY{module},3,{d(element.height)}"
                    f"^BCN,{d(element.height)},{readable},N,N,{mode}{_zpl_field(data)}"
                )
            elif isinstance(element, QRCode):
                # Kısa içerik ~25 modül (sürüm 2) + sessiz bölge; büyütme kutuya göre.
                magnification = min(10, max(1, d(element.size) // 29))
                lines.append(
                    f"^FO{d(element.x)},{d(element.y)}^BQN,2,{magnification}"
                    + _zpl_field(f"QA,{element.data}")
                )
            elif isinstance(element, Box):
                lines.append(
                    f"^FO{d(element.x)},{d(element.y)}"
                    f"^GB{d(element.width)},{d(element.height)},{max(1, d(element.thickness))}^FS"
                )
        lines.append("^XZ")
        out.append("\n".join(lines))
    return "\n".join(out) + "\n"
