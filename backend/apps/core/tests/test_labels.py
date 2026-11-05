import re

import pytest
from reportlab.graphics.barcode import code128

from apps.core.labels import (
    FNC1,
    GS1_CHARSET_82,
    NO_BARCODE_QR,
    Barcode,
    Box,
    Label,
    QRCode,
    Text,
    _barcode_modules,
    code128_or_note,
    gs1_check_digit,
    gs1_pdf_data,
    gs1_text,
    gtin14,
    is_ascii_digits,
    is_code128_text,
    is_gs1_printable,
    is_gs1_text,
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


def test_gtin_accepts_only_ascii_digits() -> None:
    """`str.isdigit` Arapça-Hint ve üst simge rakamları da kabul eder: barkoda girmez, kontrol
    hanesi hesabında hata vermeden reddedilir."""
    arabic = "8690000000012".translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    assert arabic.isdigit() and not is_ascii_digits(arabic)
    assert not is_valid_gtin(arabic)
    assert not is_valid_gtin("869000000001²")  # üst simge "2": isdigit, ama int() hata verir
    assert not is_valid_gtin(" 8690000000012")
    assert is_ascii_digits("0123456789") and not is_ascii_digits("")
    # Gövdesi Arapça-Hint ya da tam genişlik rakam, kontrol hanesi ASCII: `isdigit` ve kontrol
    # hanesi hesabı (int() bu rakamları okur) geçer, yine de GTIN değildir.
    for digits in ("٠١٢٣٤٥٦٧٨٩", "０１２３４５６７８９"):
        mixed = "869000000001".translate(str.maketrans("0123456789", digits)) + "2"
        assert mixed.isdigit() and gs1_check_digit(mixed[:-1]) == mixed[-1]
        assert not is_valid_gtin(mixed)


def test_gs1_text_fits_the_82_character_set_and_length() -> None:
    """(10) lot gibi GS1 alanları: 1 ile en çok uzunluk arası, GS1'in 82 karakterlik kümesinden."""
    assert len(GS1_CHARSET_82) == 82
    assert is_gs1_text("D-261015-001", 20) and is_gs1_text("ACILIS-DETERJAN-0001", 20)
    assert is_gs1_text("a/b.c_(1)%&'*+,:;<=>?!\"", 30)
    assert not is_gs1_text("ACILIS-MAMUL-DETERJAN-0001", 20)  # 26 karakter
    assert not is_gs1_text("", 20)
    for value in ("LOT 12", "ŞAMPUAN-1", "LOT#1", "LOT@1", "LOT\t1", "LOT\x1d1"):
        assert not is_gs1_text(value, 20)


def test_gs1_printable_leaves_out_characters_of_the_zpl_gs1_mode() -> None:
    """ZPL GS1-128'i UCC/EAN kipinde (D) "(AI)değer" olarak gönderir: parantez AI sınırı sayılıp
    veriden çıkarılır, ">" kip karakteridir. Bu karakterli değer GS1 alanına uysa da barkoda
    yazılmaz."""
    zpl = render_zpl([Label(100, 150, [Barcode(5, 5, 10, gs1=(("10", "LOT(2)"),))])])
    assert "^FD(10)LOT(2)^FS" in zpl  # yazıcı bunu (10)LOT2 diye kodlar
    for value in ("LOT(2)", "X(17)991231", "A)B", "A>B"):
        assert is_gs1_text(value, 20) and not is_gs1_printable(value, 20)
    assert is_gs1_printable("D-261015-001", 20) and is_gs1_printable("a/b.c_%&'*+,:;<=?!\"", 30)
    assert not is_gs1_printable("ACILIS-DETERJAN-00001", 20)  # 21 karakter
    assert not is_gs1_printable("LOT 12", 20) and not is_gs1_printable("", 20)


def test_code128_text_is_printable_ascii_only() -> None:
    """Code128 Türkçe harfi taşımaz: reportlab onu sessizce atar ve barkod başka değer okutur.
    ZPL'de ">" `^BC`'nin kip önekidir: o da yazılmaz. "^", "~" ve ters bölü ZPL'de onaltılık
    kaçışla gider."""
    dropped = code128.Code128("LOT:ŞUBAT-01")
    dropped.validate()
    assert dropped.validated == "LOT:UBAT-01"
    for value in ("LOT:ŞUBAT-01", "LOT:ÇAY", "LOT:İ1", "LOT:A\tB", "LOT:A\x7fB", "", "LOT:LOT>1"):
        assert not is_code128_text(value)
    assert is_code128_text("LOT:LOT 12") and is_code128_text("LOT:A(1)<B")
    assert is_code128_text("LOT:A^B~C\\1")


def test_barcode_takes_only_code128_text() -> None:
    """Barkod öğesi Code128'e aynen yazılamayan veriyi kabul etmez (sessizce başka değer
    basılırdı): değişken veri `code128_or_note` ile basılır; yazılamayan verinin yerine yazı
    çıkar."""
    for value in ("LOT:ŞUBAT-01", "LOT:LOT>1", ""):
        with pytest.raises(ValueError):
            Barcode(5, 100, 20, data=value)
        note = code128_or_note(value, 5, 100, 20, 90, NO_BARCODE_QR, module=0.3)
        assert isinstance(note, Text) and note.text == NO_BARCODE_QR and note.bold
    barcode = code128_or_note("LOT:A^B", 5, 100, 20, 90, NO_BARCODE_QR, module=0.3)
    assert barcode == Barcode(5, 100, 20, data="LOT:A^B", module=0.3, center_width=90)
    assert Barcode(5, 5, 10, gs1=(("10", "A"),)).data == ""  # GS1-128'de `data` yok sayılır


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


# Zebra `^BC` kip (invocation) kodlarından veri karakteri olanlar (alt küme A ve B): "><" = "^",
# ">0" = ">", ">=" = "~" (B). Öteki ">x" FNC, alt küme ya da başlangıç kodudur: veri değildir.
_BC_DATA_INVOCATIONS = {"<": "^", "0": ">", "=": "~"}


def _printed(line: str) -> str:
    """Yazıcının bir ZPL alanından bastığı ya da kodladığı veri. Alan verisinde çıplak "^" ya da
    "~" olamaz: yazıcı orada alanı bitirip komut okur. `^FH\\` alanında "\\XX" onaltılık kaçışları
    bayt olarak çözülür; ^FB bloğunda ters bölü kaçış karakteridir ("\\\\" ters bölü, "\\&" yeni
    satır; tanımsız kaçışın basılışı belirsizdir: "?"); Code128'de (^BC) ">" kip önekidir
    (`_BC_DATA_INVOCATIONS`; veri olmayan kod "?")."""
    data = line.split("^FD", 1)[1].removesuffix("^FS")
    assert not {"^", "~"} & set(data), line
    if "^FH\\^FD" in line:
        raw = re.sub(rb"\\([0-9A-Fa-f]{2})", lambda m: bytes([int(m[1], 16)]), data.encode())
        data = raw.decode()
    if "^FB" in line:
        data = re.sub(r"\\(.)", lambda m: {"\\": "\\", "&": "\n"}.get(m[1], "?"), data, flags=re.S)
    if "^BC" in line:
        data = re.sub(r">(.?)", lambda m: _BC_DATA_INVOCATIONS.get(m[1], "?"), data, flags=re.S)
    return data


def test_render_zpl_hex_escapes_command_characters() -> None:
    """ZPL'de "^" ve "~" komut önekidir: yazı, Code128 ve QR verisinde onaltılık kaçışla gider
    (`^FH\\`, kaçış işareti ters bölü; eskiden boşluğa çevrilirdi). Bunları taşımayan alan
    değişmez."""
    value = "a^b~c\\d"
    label = Label(
        100,
        150,
        [
            Text(1, 1, value),
            Text(1, 9, "a-b"),
            Barcode(1, 20, 10, data=value),
            QRCode(1, 40, 30, value),
        ],
    )
    zpl = render_zpl([label])
    assert "^FO8,8^A0N,28,24^FH\\^FDa\\5Eb\\7Ec\\5Cd^FS" in zpl
    assert "^FO8,72^A0N,28,24^FDa-b^FS" in zpl
    assert "^BCN,80,Y,N,N,A^FH\\^FDa\\5Eb\\7Ec\\5Cd^FS" in zpl
    assert "^FH\\^FDQA,a\\5Eb\\7Ec\\5Cd^FS" in zpl


def test_render_zpl_keeps_command_characters_of_the_data() -> None:
    """Değerinde "^", "~" ve ters bölü olan veri (ör. içe aktarılmış lot no) ZPL'nin yazı, Code128
    ve QR alanında aynen basılır ve kodlanır: onaltılık kaçışlar çözülünce değerin kendisi çıkar
    (kaçışsız ters bölü + iki onaltılık hane yazıcıda tek bayta dönerdi)."""
    value = "LOT:A^B~C\\12"
    label = Label(
        100,
        150,
        [
            Text(5, 5, value),
            Text(5, 20, value, max_width=90),  # ^FB bloğu: ters bölü "\\" yazılır
            Barcode(5, 100, 20, data=value, center_width=90),
            QRCode(30, 40, 35, value),
        ],
    )
    fields = [line for line in render_zpl([label]).splitlines() if "^FD" in line]
    assert "^FB" in fields[1] and "^BC" in fields[2] and "^BQ" in fields[3]
    assert [_printed(line) for line in fields] == [value, value, value, f"QA,{value}"]


def test_render_zpl_escapes_a_lone_backslash() -> None:
    """Yalnız ters bölü taşıyan veri de onaltılık kaçışla gider: ^FB bloğunda kaçışsız "\\1"
    yazıcıda ^FB kaçışı sayılır, değer başka basılırdı."""
    value = "LOT:A\\12"
    label = Label(
        100,
        150,
        [
            Text(5, 20, value, max_width=90),
            Barcode(5, 100, 20, data=value, center_width=90),
            QRCode(30, 40, 35, value),
        ],
    )
    fields = [line for line in render_zpl([label]).splitlines() if "^FD" in line]
    assert all("^FH\\^FD" in line for line in fields)
    assert [_printed(line) for line in fields] == [value, value, f"QA,{value}"]


def test_zpl_code128_carries_no_greater_than_sign() -> None:
    """ZPL `^BC`'de ">" otomatik kipte (A) de kip (invocation) önekidir. Zebra tablosu: "><" = "^",
    ">0" = ">", ">=" = "~" (alt küme A ve B; C'de ">0" = "30"). Eski "><" kaçışı LOT>1'i LOT^1
    diye kodlardı. ">" taşıyan veri Code128'e yazılmaz: yerinde QR'ın okutulacağı yazılır; QR'da
    (^BQ) kip öneki yoktur, veri aynen gider."""
    assert _printed("^BCN,80,Y,N,N,A^FDLOT:LOT><1^FS") == "LOT:LOT^1"  # eski çıktı
    assert _printed("^BCN,80,Y,N,N,A^FD>0>=><>8^FS") == ">~^?"  # ">8" FNC1: veri değil
    value = "LOT:LOT>1"
    note = code128_or_note(value, 5, 100, 20, 90, NO_BARCODE_QR, module=0.3)
    zpl = render_zpl([Label(100, 150, [note, QRCode(30, 40, 35, value)])])
    assert "^BC" not in zpl
    fields = [line for line in zpl.splitlines() if "^FD" in line]
    assert [_printed(line) for line in fields] == [NO_BARCODE_QR, f"QA,{value}"]


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
