"""Lot, mamul koli ve palet etiketleri (100 × 150 mm, Karar D-8). Çıktı `core.labels` ile PDF ya
da ZPL.

Okutma içerikleri (`selectors.decode_scan` çözer):
- Lot etiketi: Code128 + QR, `LOT:<lot_no>`.
- Koli etiketi: malzemenin GTIN'i varsa GS1-128 (01) GTIN + (17) SKT + (10) lot; yoksa firma içi
  Code128 `LOT:<lot_no>` (Karar D-6). Her ikisinde QR `LOT:<lot_no>`.
- Palet etiketi: SSCC (00) + içerik barkodları (02) GTIN + (37) koli sayısı ve (17) SKT + (10) lot.
"""

from collections.abc import Sequence

from apps.core.labels import Barcode, Box, Element, Gs1Elements, Label, QRCode, Text, gtin14
from apps.inventory.models import Lot, PalletLabel
from apps.masterdata.labels import INNER, LABEL_HEIGHT, LABEL_WIDTH, MARGIN, barcode_module
from apps.masterdata.models import Material

LOT_PREFIX = "LOT:"


def lot_scan_code(lot: Lot) -> str:
    return f"{LOT_PREFIX}{lot.lot_no}"


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
    elements.append(Text(MARGIN, y, material.code, size=18, bold=True, max_width=INNER))
    y += 9
    for line in _wrap(material.name, 34):
        elements.append(Text(MARGIN, y, line, size=12, max_width=INNER))
        y += 6
    return elements, y


def lot_label(lot: Lot, company_name: str = "") -> Label:
    """Lot etiketi: malzeme, lot no, tarihler, QR ve Code128 (`LOT:<lot_no>`)."""
    data = lot_scan_code(lot)
    elements, y = _header(company_name, lot.material)
    y += 2
    elements.append(Text(MARGIN, y, "LOT", size=9))
    elements.append(Text(MARGIN, y + 4, lot.lot_no, size=24, bold=True, max_width=INNER))
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
    elements.append(
        Barcode(MARGIN, 118, 18, data=data, module=barcode_module(data), center_width=INNER)
    )
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title=f"Lot {lot.lot_no}")


def case_gs1(lot: Lot) -> Gs1Elements | None:
    """Koli GS1-128 içeriği; malzemenin GTIN'i yoksa None."""
    gtin = lot.material.gtin
    if not gtin:
        return None
    elements: list[tuple[str, str]] = [("01", gtin14(gtin))]
    if lot.expiry_date:
        elements.append(("17", f"{lot.expiry_date:%y%m%d}"))
    elements.append(("10", lot.lot_no))
    return tuple(elements)


def case_label(lot: Lot, company_name: str = "", units_per_case: int | None = None) -> Label:
    """Mamul koli etiketi (Karar D-6: GTIN varsa GS1-128, yoksa firma içi Code128)."""
    elements, y = _header(company_name, lot.material)
    y += 2
    rows = [
        ("LOT", lot.lot_no),
        ("SKT", _date(lot.expiry_date)),
        ("ÜRETİM", _date(lot.manufactured_at)),
    ]
    if lot.material.gtin:
        rows.insert(0, ("GTIN", gtin14(lot.material.gtin)))
    if units_per_case:
        rows.append(("KOLİ İÇİ", f"{units_per_case} adet"))
    for caption, value in rows:
        elements.append(Text(MARGIN, y, caption, size=9))
        elements.append(Text(30, y - 1, value, size=14, bold=True, max_width=INNER - 25))
        y += 8
    elements.append(QRCode(65, max(y, 70), 28, lot_scan_code(lot)))
    gs1 = case_gs1(lot)
    if gs1 is not None:
        elements.append(Barcode(MARGIN, 108, 25, gs1=gs1, module=0.33, center_width=INNER))
    else:
        data = lot_scan_code(lot)
        elements.append(
            Barcode(MARGIN, 108, 25, data=data, module=barcode_module(data), center_width=INNER)
        )
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title=f"Koli {lot.lot_no}")


def pallet_label(pallet: PalletLabel, company_name: str = "") -> Label:
    """SSCC palet etiketi (GS1 lojistik etiketi düzeninde)."""
    lot = pallet.lot
    material = lot.material
    elements: list[Element] = [Box(MARGIN, MARGIN, INNER, LABEL_HEIGHT - 2 * MARGIN, thickness=0.5)]
    y = MARGIN + 3
    if company_name:
        elements.append(Text(8, y, company_name, size=9, bold=True, max_width=INNER - 6))
        y += 6
    elements.append(Text(8, y, material.code, size=14, bold=True, max_width=INNER - 6))
    y += 7
    elements.append(Text(8, y, material.name, size=10, max_width=INNER - 6))
    y += 7
    elements.append(Text(8, y, "SSCC", size=8))
    elements.append(Text(8, y + 4, pallet.sscc, size=16, bold=True))
    y += 13
    rows = [("LOT", lot.lot_no), ("SKT", _date(lot.expiry_date)), ("KOLİ", str(pallet.case_count))]
    if material.gtin:
        rows.insert(0, ("İÇERİK (GTIN)", gtin14(material.gtin)))
    if pallet.units_per_case:
        rows.append(("TOPLAM", f"{pallet.case_count * pallet.units_per_case} adet"))
    for caption, value in rows:
        elements.append(Text(8, y, caption, size=8))
        elements.append(Text(38, y - 1, value, size=11, bold=True, max_width=INNER - 36))
        y += 6
    if material.gtin:
        # İçerik iki barkoda bölünür (GS1 lojistik etiketi): genişlik etikete sığsın.
        content: Gs1Elements = (("02", gtin14(material.gtin)), ("37", str(pallet.case_count)))
        elements.append(Barcode(8, 74, 14, gs1=content, module=0.33, center_width=84))
        dates: list[tuple[str, str]] = []
        if lot.expiry_date:
            dates.append(("17", f"{lot.expiry_date:%y%m%d}"))
        dates.append(("10", lot.lot_no))
        elements.append(Barcode(8, 96, 14, gs1=tuple(dates), module=0.33, center_width=84))
    else:
        data = lot_scan_code(lot)
        elements.append(
            Barcode(8, 85, 18, data=data, module=barcode_module(data, 84), center_width=84)
        )
    elements.append(Barcode(8, 119, 18, gs1=(("00", pallet.sscc),), module=0.33, center_width=84))
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title=f"Palet {pallet.sscc}")


def lot_labels(lots: Sequence[Lot], company_name: str = "", copies: int = 1) -> list[Label]:
    return [lot_label(lot, company_name) for lot in lots for _ in range(copies)]
