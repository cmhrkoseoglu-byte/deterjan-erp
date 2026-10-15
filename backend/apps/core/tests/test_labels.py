import re

from apps.core.labels import (
    FNC1,
    Barcode,
    Box,
    Label,
    QRCode,
    Text,
    _barcode_modules,
    gs1_check_digit,
    gs1_pdf_data,
    gs1_text,
    gtin14,
    is_valid_gtin,
    render_pdf,
    render_zpl,
)


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type /Page[^s]", pdf))


def _label() -> Label:
    return Label(
        100,
        150,
        [
            Text(5, 5, "Şampuan ĞÜŞİÖÇ", size=12, bold=True, max_width=90),
            Barcode(5, 100, 20, data="LOT:B-261015-001", center_width=90),
            Barcode(5, 125, 20, gs1=(("01", "08690000000017"), ("10", "D-1"))),
            QRCode(30, 40, 35, "LOT:B-261015-001"),
            Box(5, 5, 90, 140),
        ],
    )


def test_gs1_check_digit_and_gtin_validation() -> None:
    assert gs1_check_digit("869000000001") == "2"  # 8690000000012
    assert is_valid_gtin("8690000000012")
    assert not is_valid_gtin("8690000000013")
    assert not is_valid_gtin("86900")
    assert not is_valid_gtin("869000000001A")
    assert is_valid_gtin("96385074")  # GTIN-8
    assert gtin14("8690000000012") == "08690000000012"


def test_gs1_data_puts_fnc1_after_variable_fields_only() -> None:
    elements = (("01", "08690000000012"), ("10", "LOT1"), ("17", "271015"))
    assert gs1_pdf_data(elements) == f"{FNC1}010869000000001210LOT1{FNC1}17271015"
    assert gs1_pdf_data((("01", "08690000000012"), ("10", "LOT1"))) == (
        f"{FNC1}010869000000001210LOT1"
    )
    assert gs1_text(elements) == "(01)08690000000012(10)LOT1(17)271015"


def test_render_zpl_uses_203_dpi_dots_and_utf8() -> None:
    zpl = render_zpl([_label()])
    assert zpl.startswith("^XA\n^CI28\n^PW799\n^LL1199")
    assert "^FDŞampuan ĞÜŞİÖÇ^FS" in zpl
    assert "^BCN,160,Y,N,N,A^FDLOT:B-261015-001^FS" in zpl
    assert "^BCN,160,Y,N,N,D^FD(01)08690000000017(10)D-1^FS" in zpl
    assert "^BQN,2," in zpl and "^FDQA,LOT:B-261015-001^FS" in zpl
    assert zpl.strip().endswith("^XZ")
    # 300 dpi yazıcıda nokta sayıları ölçeklenir.
    assert "^PW1181" in render_zpl([_label()], dpi=300)


def test_render_zpl_strips_control_characters() -> None:
    zpl = render_zpl([Label(100, 150, [Text(1, 1, "a^b~c")])])
    assert "^FDa b c^FS" in zpl


def test_render_pdf_label_and_a4() -> None:
    single = render_pdf([_label(), _label()])
    assert single.startswith(b"%PDF")
    assert _pages(single) == 2
    # A4'e 100 × 150 mm etiketten iki tane sığar: üç etiket iki sayfa.
    a4 = render_pdf([_label()] * 3, a4=True)
    assert _pages(a4) == 2
    assert render_pdf([]).startswith(b"%PDF")


def test_render_zpl_barcode_fits_its_width() -> None:
    """Nokta yuvarlaması (0,369 mm → 3 nokta) barkodu alanından taşırmaz."""
    element = Barcode(5, 100, 18, data="LOT:ACILIS-KORUYUCU", module=0.369, center_width=90)
    zpl = render_zpl([Label(100, 150, [element])])
    module = int(re.search(r"\^BY(\d+),", zpl).group(1))  # type: ignore[union-attr]
    assert module * _barcode_modules(element) <= 90 * 203 / 25.4
    assert module == 2
