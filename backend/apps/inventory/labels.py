"""Lot, mamul koli ve palet etiketleri (100 × 150 mm, Karar D-8). Çıktı `core.labels` ile PDF ya
da ZPL.

Okutma içerikleri (`selectors.decode_scan` çözer):
- Lot etiketi: Code128 + QR, `LOT:<lot_no>`.
- Koli etiketi: GTIN varsa GS1-128 (01) GTIN + (17) SKT + (10) lot; yoksa firma içi Code128
  `LOT:<lot_no>` (Karar D-6). (01) malzemenin koli GTIN'idir (KOLI dönüşümünde); tanımlı değilse
  ürün GTIN'i basılır. Her ikisinde QR `LOT:<lot_no>`.
- Palet etiketi: SSCC (00) + içerik barkodları (02) GTIN + (37) koli sayısı ve (17) SKT + (10) lot.
  (02) koli GTIN'idir; tanımlı değilse ürün GTIN'i basılır.
- Koli GTIN'i lotun açıldığı anda yürürlükteki koli GTIN'idir (`masterdata.case_gtin_at`): koli
  içi miktar değişmeden önce açılmış lotun etiketi yeniden basılınca da eski koli GTIN'ini taşır,
  sonra açılan lot yenisini.
- Okutulamayan GS1 barkodu basılmaz: GTIN'i geçersiz (kontrol hanesi yanlış eski veri) ya da lot
  numarası (10) alanına uymayan (20 karakterden uzun, boşluklu, Türkçe harfli; ZPL'de bozulan
  "(", ")", ">" karakterli) lotta ve (37) alanına sığmayan (8 haneden uzun) koli sayısında etiket
  GTIN'siz malzemedeki gibi firma içi Code128 `LOT:<lot_no>` taşır; geçersiz GTIN yazı olarak da
  basılmaz.
- Code128 Türkçe harfi, ZPL'de ">"yi (kip öneki) taşımaz: böyle lot noda firma içi barkod basılmaz
  (başka lot no okuturdu); yerine hangi kodun okutulacağı yazılır: lot ve koli etiketinde QR, palet
  etiketinde SSCC.
"""

from collections.abc import Sequence
from datetime import datetime

from apps.core.labels import (
    GS1_CASE_COUNT_MAX,
    NO_BARCODE_QR,
    Barcode,
    Box,
    Element,
    Gs1Elements,
    Label,
    QRCode,
    Text,
    code128_or_note,
    fit_size,
    gtin14,
    is_gs1_printable,
    is_valid_gtin,
)
from apps.inventory.models import Lot, PalletLabel
from apps.masterdata import services as masterdata
from apps.masterdata.labels import INNER, LABEL_HEIGHT, LABEL_WIDTH, MARGIN, barcode_module
from apps.masterdata.models import Material

LOT_PREFIX = "LOT:"
# GS1 (10) lot alanı en çok 20 karakterdir (GS1 General Specifications); (37) koli sayısı en çok 8
# hane (`GS1_CASE_COUNT_MAX`).
GS1_LOT_MAX_LENGTH = 20
# Firma içi barkodu basılamayan lot noda (Türkçe harf, ">") barkodun yerine basılan yazı: lot ve
# koli etiketinde `NO_BARCODE_QR`, QR'ı olmayan palet etiketinde bu.
NO_BARCODE_SSCC = "Lot barkodu yok: SSCC barkodunu okutun."


def lot_scan_code(lot: Lot) -> str:
    return f"{LOT_PREFIX}{lot.lot_no}"


def _lot_barcode(lot: Lot, x: float, y: float, height: float, width: float, hint: str) -> Element:
    """Firma içi Code128 `LOT:<lot_no>`, `width` içinde ortalı; Code128'e yazılamayan lot noda
    (Türkçe harf, ">") barkod yerine hangi kodun okutulacağını söyleyen yazı (`hint`,
    `code128_or_note`)."""
    data = lot_scan_code(lot)
    return code128_or_note(data, x, y, height, width, hint, module=barcode_module(data, width))


def _date(value: object) -> str:
    return f"{value:%d.%m.%Y}" if value else "-"


def _wrap(text: str, chars: int, lines: int = 2) -> list[str]:
    """Metni kelime sınırından en çok `lines` satıra böler (yaklaşık karakter sayısıyla)."""
    words, out, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > chars and current:
            out.append(current)
            current = word
        else:
            current = candidate
    if current:
        out.append(current)
    if len(out) > lines:
        out = [*out[: lines - 1], " ".join(out[lines - 1 :])]
    return out


def _header(
    company_name: str, material: Material, y: float = MARGIN
) -> tuple[list[Element], float]:
    elements: list[Element] = []
    if company_name:
        elements.append(Text(MARGIN, y, company_name, size=8, max_width=INNER))
        y += 5
    code_size = fit_size(material.code, 18, width=INNER, bold=True)
    elements.append(Text(MARGIN, y, material.code, size=code_size, bold=True, max_width=INNER))
    y += 9
    for line in _wrap(material.name, 34):
        elements.append(Text(MARGIN, y, line, size=12, max_width=INNER))
        y += 6
    return elements, y


def lot_label(lot: Lot, company_name: str = "") -> Label:
    """Lot etiketi: malzeme, lot no, tarihler, QR ve Code128 (`LOT:<lot_no>`; Code128'e
    yazılamayan lot noda yalnız QR)."""
    data = lot_scan_code(lot)
    elements, y = _header(company_name, lot.material)
    y += 2
    elements.append(Text(MARGIN, y, "LOT", size=9))
    # Lot no kesilmez (okutulamazsa etiketten elle girilir): sığmazsa yazı küçülür.
    lot_size = fit_size(lot.lot_no, 24, width=INNER, bold=True)
    elements.append(Text(MARGIN, y + 4, lot.lot_no, size=lot_size, bold=True, max_width=INNER))
    y += 16
    details = [f"SKT: {_date(lot.expiry_date)}", f"Üretim: {_date(lot.manufactured_at)}"]
    if lot.supplier_lot_no:
        details.append(f"Tedarikçi lot: {lot.supplier_lot_no}")
    if lot.supplier is not None:
        details.append(f"Tedarikçi: {lot.supplier.name}")
    for line in details:
        elements.append(Text(MARGIN, y, line, size=10, max_width=INNER))
        y += 5.5
    elements.append(QRCode(32.5, max(y + 2, 72), 35, data))
    elements.append(_lot_barcode(lot, MARGIN, 118, 18, INNER, NO_BARCODE_QR))
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title=f"Lot {lot.lot_no}")


def case_gtin14(material: Material, when: datetime | None = None) -> str:
    """Koli etiketinin (01) ve palet etiketinin (02) GTIN'i, 14 hane: malzemenin koli GTIN'i (KOLI
    dönüşümünde) varsa o, yoksa ürün GTIN'i (eski davranış); ikisi de yoksa ya da GTIN geçersizse
    (kontrol hanesi yanlış eski veri: barkodu okutulamaz) "". Geçersiz koli GTIN'i ürün GTIN'ine
    düşmez. `when` (lotun açıldığı an) verilirse o an yürürlükteki koli GTIN'i
    (`masterdata.case_gtin_at`: koli içi miktar sonra değiştiyse eski koli GTIN'i); verilmezse
    bugünkü."""
    gtin = masterdata.case_gtin_at(material, when) or material.gtin
    return gtin14(gtin) if gtin and is_valid_gtin(gtin) else ""


def gs1_lot_no(lot: Lot) -> bool:
    """Lot numarası GS1 (10) alanına yazılabilir mi: 1-20 karakter, GS1 karakter kümesinden; ZPL'de
    bozulan "(", ")", ">" olmadan (`is_gs1_printable`). Uymayan (ör. açılış stokunun uzun lot
    numarası, boşluklu lot no) firma içi `LOT:` barkoduyla basılır."""
    return is_gs1_printable(lot.lot_no, GS1_LOT_MAX_LENGTH)


def _case_elements(lot: Lot, gtin: str) -> Gs1Elements:
    elements: list[tuple[str, str]] = [("01", gtin)]
    if lot.expiry_date:
        elements.append(("17", f"{lot.expiry_date:%y%m%d}"))
    elements.append(("10", lot.lot_no))
    return tuple(elements)


def case_gs1(lot: Lot) -> Gs1Elements | None:
    """Koli GS1-128 içeriği: (01) lotun açıldığı andaki koli GTIN'i (tanımlı değilse ürün GTIN'i) +
    (17) SKT + (10) lot; basılabilir GTIN yoksa ya da lot numarası (10) alanına uymuyorsa None
    (firma içi `LOT:`)."""
    gtin = case_gtin14(lot.material, lot.created_at)
    return _case_elements(lot, gtin) if gtin and gs1_lot_no(lot) else None


def case_label(lot: Lot, company_name: str = "", units_per_case: int | None = None) -> Label:
    """Mamul koli etiketi (Karar D-6: GTIN varsa GS1-128, yoksa firma içi Code128). GTIN satırı ve
    (01) alanı lotun açıldığı andaki koli GTIN'idir; tanımlı değilse ürün GTIN'i. Geçersiz GTIN'de
    ya da lot numarası (10) alanına uymuyorsa firma içi Code128 (`case_gs1`); Code128'e
    yazılamayan lot noda yalnız QR."""
    elements, y = _header(company_name, lot.material)
    y += 2
    gtin = case_gtin14(lot.material, lot.created_at)
    rows = [
        ("LOT", lot.lot_no),
        ("SKT", _date(lot.expiry_date)),
        ("ÜRETİM", _date(lot.manufactured_at)),
    ]
    if gtin:
        rows.insert(0, ("GTIN", gtin))
    if units_per_case:
        rows.append(("KOLİ İÇİ", f"{units_per_case} adet"))
    for caption, value in rows:
        elements.append(Text(MARGIN, y, caption, size=9))
        value_size = fit_size(value, 14, width=INNER - 25, bold=True)  # uzun lot no kesilmez
        elements.append(Text(30, y - 1, value, size=value_size, bold=True, max_width=INNER - 25))
        y += 8
    elements.append(QRCode(65, max(y, 70), 28, lot_scan_code(lot)))
    gs1 = _case_elements(lot, gtin) if gtin and gs1_lot_no(lot) else None
    if gs1 is not None:
        elements.append(Barcode(MARGIN, 108, 25, gs1=gs1, module=0.33, center_width=INNER))
    else:
        elements.append(_lot_barcode(lot, MARGIN, 108, 25, INNER, NO_BARCODE_QR))
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title=f"Koli {lot.lot_no}")


def pallet_label(pallet: PalletLabel, company_name: str = "") -> Label:
    """SSCC palet etiketi (GS1 lojistik etiketi düzeninde). İçerik (02) lotun açıldığı andaki koli
    GTIN'i + (37) koli sayısıdır; koli GTIN'i tanımlı değilse (02) ürün GTIN'i. İçerik barkodları
    basılabilir GTIN, (10) alanına uyan lot numarası ve (37) alanına sığan koli sayısı ister; yoksa
    firma içi Code128 `LOT:` (Code128'e yazılamayan lot noda yerine SSCC'nin okutulmasını söyleyen
    yazı). SSCC her zaman basılır."""
    lot = pallet.lot
    material = lot.material
    gtin = case_gtin14(material, lot.created_at)
    elements: list[Element] = [Box(MARGIN, MARGIN, INNER, LABEL_HEIGHT - 2 * MARGIN, thickness=0.5)]
    y = MARGIN + 3
    if company_name:
        elements.append(Text(8, y, company_name, size=9, bold=True, max_width=INNER - 6))
        y += 6
    code_size = fit_size(material.code, 14, width=INNER - 6, bold=True)
    elements.append(Text(8, y, material.code, size=code_size, bold=True, max_width=INNER - 6))
    y += 7
    elements.append(Text(8, y, material.name, size=10, max_width=INNER - 6))
    y += 7
    elements.append(Text(8, y, "SSCC", size=8))
    elements.append(Text(8, y + 4, pallet.sscc, size=16, bold=True))
    y += 13
    rows = [("LOT", lot.lot_no), ("SKT", _date(lot.expiry_date)), ("KOLİ", str(pallet.case_count))]
    if gtin:
        rows.insert(0, ("İÇERİK (GTIN)", gtin))
    if pallet.units_per_case:
        rows.append(("TOPLAM", f"{pallet.case_count * pallet.units_per_case} adet"))
    for caption, value in rows:
        elements.append(Text(8, y, caption, size=8))
        value_size = fit_size(value, 11, width=INNER - 36, bold=True)  # uzun lot no kesilmez
        elements.append(Text(38, y - 1, value, size=value_size, bold=True, max_width=INNER - 36))
        y += 6
    if gtin and gs1_lot_no(lot) and 1 <= pallet.case_count <= GS1_CASE_COUNT_MAX:
        # İçerik iki barkoda bölünür (GS1 lojistik etiketi): genişlik etikete sığsın.
        content: Gs1Elements = (("02", gtin), ("37", str(pallet.case_count)))
        elements.append(Barcode(8, 74, 14, gs1=content, module=0.33, center_width=84))
        dates: list[tuple[str, str]] = []
        if lot.expiry_date:
            dates.append(("17", f"{lot.expiry_date:%y%m%d}"))
        dates.append(("10", lot.lot_no))
        elements.append(Barcode(8, 96, 14, gs1=tuple(dates), module=0.33, center_width=84))
    else:
        # SSCC paletin lotunu da bulur (`decode_scan`): firma içi barkod basılamazsa o okutulur.
        elements.append(_lot_barcode(lot, 8, 85, 18, 84, NO_BARCODE_SSCC))
    elements.append(Barcode(8, 119, 18, gs1=(("00", pallet.sscc),), module=0.33, center_width=84))
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title=f"Palet {pallet.sscc}")


def lot_labels(lots: Sequence[Lot], company_name: str = "", copies: int = 1) -> list[Label]:
    return [lot_label(lot, company_name) for lot in lots for _ in range(copies)]
