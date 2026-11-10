"""GS1 okutma (kodlama sistematiği §6.2): tablo güdümlü AI çözümü, kontrol haneleri, uzunluklar,
FNC1/GS ve AIM, tarihler (yüzyıl, gün 00), ölçü alanları, koli GTIN'i, (02) palet içeriği, SKT
uyarısı ve üretim / dolum / sevkiyatın ortak lot çözümü (`resolve_lot`)."""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.exceptions import BusinessRuleError
from apps.core.labels import GS1_CHARSET_82, Barcode, gs1_check_digit
from apps.inventory import labels, selectors, services
from apps.inventory.api.serializers import LotSerializer, ScanResultSerializer
from apps.inventory.models import Lot, PalletLabel
from apps.inventory.selectors import (
    decode_scan,
    gs1_dates,
    gs1_decimal,
    parse_gs1,
    resolve_lot,
    scan_label,
)
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.models import Material, MaterialUnitConversion
from apps.masterdata.tests.factories import MaterialFactory, unit

GS = "\x1d"
TODAY = date(2026, 11, 5)
GTIN = "8690000000012"  # ürün GTIN'i (GTIN-13)
GTIN14 = f"0{GTIN}"
CASE_GTIN = "1869000000001" + gs1_check_digit("1869000000001")  # koli GTIN'i (GTIN-14)
GLN = "8690000000012"
LOT_NO = "D-261015-001"
SCAN = "/api/v1/inventory/scan/"
LOTS = "/api/v1/inventory/lots/"
db_test = pytest.mark.usefixtures("invariants")


def sscc(serial: int) -> str:
    body = f"08691234{serial:09d}"
    return body + gs1_check_digit(body)


def bracketed(*elements: tuple[str, str]) -> str:
    return "".join(f"({ai}){value}" for ai, value in elements)


# Önceden tanımlı uzunluklu alanların ilk iki hanesi: ham veride arkalarına GS gerekmez.
PREDEFINED = {"00", "01", "02", "11", "12", "13", "15", "16", "17", "20", "41"} | {
    str(n) for n in range(31, 37)
}


def raw(*elements: tuple[str, str]) -> str:
    """Ham GS1 verisi: önceden tanımlı uzunlukta olmayan alanın arkasına GS (FNC1)."""
    parts = []
    for index, (ai, value) in enumerate(elements):
        parts.append(ai + value)
        if ai[:2] not in PREDEFINED and index < len(elements) - 1:
            parts.append(GS)
    return "".join(parts)


def error_of(code: str, today: date | None = None) -> BusinessRuleError:
    with pytest.raises(BusinessRuleError) as error:
        parse_gs1(code, today=today)
    return error.value


# --- AI tablosu ----------------------------------------------------------------------------------

EVERY_AI = [
    ("00", sscc(1)),
    ("01", GTIN14),
    ("02", CASE_GTIN),
    ("10", LOT_NO),
    ("11", "261015"),
    ("12", "261231"),
    ("13", "261016"),
    ("15", "281015"),
    ("16", "280915"),
    ("17", "281015"),
    ("20", "07"),
    ("21", "SN-0001"),
    ("22", "CPV/1"),
    ("240", "EK-1"),
    ("241", "MUS-PARCA-9"),
    ("250", "IKINCIL-1"),
    ("251", "KAYNAK-1"),
    ("30", "12"),
    ("37", "40"),
    ("3102", "001250"),
    ("3151", "000155"),
    ("3200", "000010"),
    ("3303", "001500"),
    ("3365", "000001"),
    ("3570", "000003"),
    ("3695", "123456"),
    ("400", "PO-2026/0001"),
    ("401", "GINC-1"),
    ("403", "ROTA-34"),
    *[(f"41{n}", GLN) for n in range(8)],
    ("420", "34000"),
    ("421", "79234000"),
    ("422", "792"),
    ("424", "792"),
    ("426", "792"),
    ("7003", "2810151230"),
    ("90", "ANLASMA-1"),
    *[(str(n), f"IC-{n}") for n in range(91, 100)],
]


@pytest.mark.parametrize(("ai", "value"), EVERY_AI)
def test_every_ai_type_parses_the_same_bracketed_and_raw(ai: str, value: str) -> None:
    expected = {ai: value}
    assert parse_gs1(bracketed((ai, value))) == expected
    assert parse_gs1(raw((ai, value))) == expected
    assert parse_gs1(f"]C1{raw((ai, value))}") == expected


def test_all_ais_in_one_code_bracketed_equals_raw() -> None:
    expected = dict(EVERY_AI)
    assert parse_gs1(bracketed(*EVERY_AI)) == expected
    assert parse_gs1(raw(*EVERY_AI)) == expected
    assert parse_gs1(f"]C1{raw(*reversed(EVERY_AI))}") == expected


def test_ai_table_is_consistent() -> None:
    """Her AI'nın uzunluğu ilk iki hanesine uyar; önceden tanımlı uzunluklu alanlar sabit rakam."""
    for ai, spec in selectors._GS1_AIS.items():
        assert selectors._GS1_AI_LENGTH[ai[:2]] == len(ai), ai
        size = selectors._GS1_PREDEFINED.get(ai[:2])
        if size is not None:
            assert spec.parts == (("N", size, size),), ai


@pytest.mark.parametrize(
    ("ai", "valid"),
    [("00", sscc(7)), ("01", GTIN14), ("02", CASE_GTIN), ("410", GLN), ("414", GLN), ("417", GLN)],
)
def test_check_digit_is_verified(ai: str, valid: str) -> None:
    assert parse_gs1(bracketed((ai, valid))) == {ai: valid}
    wrong = valid[:-1] + str((int(valid[-1]) + 1) % 10)
    for code in (bracketed((ai, wrong)), raw((ai, wrong)), f"]C1{raw((ai, wrong))}"):
        error = error_of(code)
        assert error.code == "gs1_check_digit", code
        assert f"({ai})" in error.message


@pytest.mark.parametrize(
    ("ai", "value"),
    [
        ("01", "0869000000001"),  # 13 hane
        ("01", "086900000000123"),  # 15 hane
        ("00", "08691234000000001"),  # 17 hane
        ("01", "0869000000001A"),
        ("01", "٠٨٦٩٠٠٠٠٠٠٠٠١٢"),  # ASCII olmayan rakamlar
        ("10", "A" * 65),  # okurken (10) en çok 64 karakter (eski lot numaraları)
        ("21", "B" * 21),
        ("22", "C" * 21),
        ("240", "D" * 31),
        ("400", "E" * 31),
        ("420", "F" * 21),
        ("90", "G" * 31),
        ("91", "H" * 91),
        ("30", "123456789"),
        ("37", "4O"),  # O harfi
        ("20", "7"),
        ("3102", "12345"),
        ("422", "79"),
        ("421", "79"),
        ("421", "7921234567890"),  # posta kodu 10 karakter
        ("7003", "281015123"),
        # Boşluk ve # GS1 kümesinde yok; yalnız (10) okurken yazdırılabilir ASCII kabul eder.
        ("21", "SN 1"),
        ("240", "EK#1"),
        ("90", "A B"),
        ("10", "LOTÇ"),
        ("10", "ŞUBAT-01"),
        ("10", "LOT\x7f1"),
        ("10", ""),
    ],
)
def test_value_length_and_charset_are_checked(ai: str, value: str) -> None:
    error = error_of(bracketed((ai, value)))
    assert error.code == "gs1_malformed"
    assert f"({ai})" in error.message


def test_maximum_lengths_are_accepted() -> None:
    longest = [("10", "A" * 20), ("21", "B" * 20), ("240", "C" * 30), ("91", "D" * 90)]
    longest += [("30", "12345678"), ("421", "792123456789"), ("10", "A(B)%&'*+,-./:;<=>?_")]
    for ai, value in longest:
        assert parse_gs1(bracketed((ai, value))) == {ai: value}
        assert parse_gs1(raw((ai, value))) == {ai: value}


def test_x_fields_read_the_whole_gs1_character_set() -> None:
    """Okurken "X" alanları etiketlerle aynı 82 karakterlik GS1 kümesindendir
    (`core.labels.GS1_CHARSET_82`), kümenin tamamı: ZPL'nin basamadığı "(", ")", ">" yalnızca
    basmayı sınırlar. Kümede olmayan karakter hatadır."""
    assert selectors.GS1_CHARSET_82 is GS1_CHARSET_82
    every = "".join(sorted(GS1_CHARSET_82))
    assert parse_gs1(f"(91){every}") == {"91": every}
    assert parse_gs1(f"]C191{every}") == {"91": every}
    assert parse_gs1("(21)LOT(2)>1") == {"21": "LOT(2)>1"}
    for char in (" ", "#", "~", "Ş", "\x7f"):
        assert error_of(f"(91)A{char}B").code == "gs1_malformed", repr(char)


@pytest.mark.parametrize(
    "lot_no", ["ACILIS-MAMUL-DETERJAN-0001", "LOT 12", "LOT#1", "A" * 64, "A ~{|}`$@[\\]^"]
)
def test_lot_field_accepts_legacy_lot_numbers_when_reading(lot_no: str) -> None:
    """Açılış stoku ve canlıya geçiş lot numaraları (en çok 64 karakter, boşluk olabilir) bu
    adımdan önce basılmış etiketlerin (10) alanındadır: okurken 1-64 yazdırılabilir ASCII
    karakteri kabul edilir; GS alanı yine bitirir."""
    expected = {"01": GTIN14, "10": lot_no, "17": "281015"}
    assert parse_gs1(f"(01){GTIN14}(10){lot_no}(17)281015") == expected
    assert parse_gs1(f"]C101{GTIN14}10{lot_no}{GS}17281015") == expected


def test_raw_data_separators() -> None:
    expected = {"01": GTIN14, "10": "ABC", "17": "281015"}
    # Değişken alandan sonra GS (FNC1).
    assert parse_gs1(f"01{GTIN14}10ABC{GS}17281015") == expected
    # Sabit alandan sonra da GS kabul edilir; baştaki ve art arda GS'ler de.
    assert parse_gs1(f"{GS}01{GTIN14}{GS}10ABC{GS}{GS}17281015{GS}") == expected
    # Kenardan her boşluk karakteri (NBSP, FS …, GS de) atılır; boşluk olmayan kontrol karakteri
    # veridir.
    assert parse_gs1(f" \t]C101{GTIN14}10ABC{GS}17281015\r\n") == expected
    assert parse_gs1(f"\xa0\x0b]C101{GTIN14}10ABC{GS}17281015\x1c{GS}\u3000") == expected
    assert parse_gs1("(10)ABC\x1c") == {"10": "ABC"}
    assert error_of("(10)ABC\x04").code == "gs1_malformed"
    # GS'siz değişken alan veri sonuna kadar sürer.
    assert parse_gs1(f"01{GTIN14}17281015" + "10ABC17281015") == {
        "01": GTIN14,
        "17": "281015",
        "10": "ABC17281015",
    }
    # Önceden tanımlı uzunlukta olmayan sabit alan (422) da GS ister.
    assert parse_gs1(f"422792{GS}10ABC") == {"422": "792", "10": "ABC"}
    assert error_of("42279210ABC").code == "gs1_malformed"
    # Eksik AI, AI ile başlamayan veri, boş veri.
    assert "(31)" in error_of(f"01{GTIN14}31").message
    assert error_of("]C1D-261015-001").code == "gs1_malformed"
    assert error_of("]C1").code == "gs1_malformed"
    # Aynı AI iki kez: aynı değer kabul, farklı değer hata.
    assert parse_gs1("(10)ABC(10)ABC") == {"10": "ABC"}
    assert error_of("(10)ABC(10)ABD").code == "gs1_malformed"


@pytest.mark.parametrize("aim", ["]C1", "]e0", "]d2", "]Q3", "]J1"])
def test_aim_prefixes(aim: str) -> None:
    expected = {"01": GTIN14, "10": "ABC"}
    assert parse_gs1(f"{aim}01{GTIN14}10ABC") == expected
    assert parse_gs1(f"{aim}(01){GTIN14}(10)ABC") == expected


@pytest.mark.parametrize(
    ("code", "ai"),
    [
        ("(8008)261015123000", "8008"),
        (f"01{GTIN14}8008261015123000", "8008"),
        ("(14)261015", "14"),
        ("(3106)001250", "3106"),  # en çok 5 ondalık
        ("(3170)001250", "3170"),  # 317n tanımsız
        ("(310)001250", "310"),
        (f"(03){GTIN14}", "03"),
        (f"]C105{GTIN14}", "05"),
        ("]C1710ABC", "710"),
        ("(23)ABC", "23"),
        ("(01)08690000000012(9999)X", "9999"),
    ],
)
def test_unknown_ai_is_an_error_in_both_forms(code: str, ai: str) -> None:
    error = error_of(code)
    assert error.code == "gs1_unsupported_ai"
    assert f"({ai})" in error.message


# --- tarihler ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "iso", "today"),
    [
        ("261105", "2026-11-05", TODAY),
        ("760101", "2076-01-01", TODAY),  # 50 yıl ileri: bu yüzyıl
        ("770101", "1977-01-01", TODAY),  # 51 yıl ileri: önceki yüzyıl
        ("000229", "2000-02-29", TODAY),
        ("310101", "2031-01-01", date(2080, 6, 1)),  # 49 yıl geri: bu yüzyıl
        ("300101", "2130-01-01", date(2080, 6, 1)),  # 50 yıl geri: sonraki yüzyıl
    ],
)
def test_date_century_sliding_window(value: str, iso: str, today: date) -> None:
    gs1 = parse_gs1(f"(17){value}", today=today)
    assert gs1_dates(gs1, today=today) == {"17": iso}


def test_century_decides_leap_day() -> None:
    assert gs1_dates(parse_gs1("(17)000229", today=TODAY), today=TODAY) == {"17": "2000-02-29"}
    # 2080'de 00 = 2100 (artık yıl değil).
    assert error_of("(17)000229", today=date(2080, 6, 1)).code == "gs1_invalid_date"


def test_day_zero_is_month_end_for_expiry_and_no_day_for_production() -> None:
    gs1 = parse_gs1("(11)261000(12)261100(13)261100(15)270200(16)261100(17)280200", today=TODAY)
    assert gs1_dates(gs1, today=TODAY) == {
        "15": "2027-02-28",
        "16": "2026-11-30",
        "17": "2028-02-29",
    }
    every = parse_gs1("(11)261015(12)261231(13)261016(15)281015(16)280915(17)281015")
    assert gs1_dates(every, today=TODAY) == {
        "11": "2026-10-15",
        "12": "2026-12-31",
        "13": "2026-10-16",
        "15": "2028-10-15",
        "16": "2028-09-15",
        "17": "2028-10-15",
    }
    # 7003 (tarih ve saat) denetlenir ama tarih listesine girmez.
    assert gs1_dates(parse_gs1("(7003)2810151230"), today=TODAY) == {}


@pytest.mark.parametrize(
    "code",
    [
        "(17)261301",
        "(17)260230",
        "(17)260001",
        "(17)260000",
        "(11)261032",
        "(13)261300",
        "(15)270229",
        "(7003)2810000000",  # 7003'te gün 00 olamaz
        "(7003)2810152400",
        "(7003)2810151260",
        "(7003)2813151200",
    ],
)
def test_invalid_dates(code: str) -> None:
    error = error_of(code, today=TODAY)
    assert error.code == "gs1_invalid_date"
    assert code[: code.index(")") + 1] in error.message


def test_date_with_letters_is_malformed() -> None:
    assert error_of("(17)26A015").code == "gs1_malformed"


@pytest.mark.parametrize(
    ("ai", "value", "expected"),
    [
        ("3100", "000012", Decimal("12")),
        ("3102", "001250", Decimal("12.50")),
        ("3105", "123456", Decimal("1.23456")),
        ("3151", "000155", Decimal("15.5")),
        ("3303", "001500", Decimal("1.500")),
    ],
)
def test_measure_decimal_places_come_from_the_ai(ai: str, value: str, expected: Decimal) -> None:
    assert parse_gs1(f"({ai}){value}") == {ai: value}
    assert gs1_decimal(ai, value) == expected


def test_measure_helper_rejects_other_ais() -> None:
    with pytest.raises(ValueError):
        gs1_decimal("10", "001250")
    with pytest.raises(ValueError):
        gs1_decimal("3106", "001250")


# --- okutma: koli GTIN'i, palet, SKT uyarısı ----------------------------------------------------


@pytest.fixture
def product() -> Material:
    """Mamul (ADET), ürün GTIN'i ve 1 KOLI = 12 ADET koli dönüşümünde koli GTIN'i."""
    material = MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), gtin=GTIN
    )
    MaterialUnitConversion.objects.create(
        material=material, unit=unit("KOLI"), factor_to_base=Decimal("12"), gtin=CASE_GTIN
    )
    return material


def finished_lot(
    material: Material, lot_no: str = LOT_NO, expiry_date: date = date(2028, 10, 15)
) -> Lot:
    return services.create_lot(
        None,
        material=material,
        source=Lot.Source.FILLING,
        lot_no=lot_no,
        manufactured_at=date(2026, 10, 15),
        expiry_date=expiry_date,
    )


@db_test
def test_case_gtin_resolves_with_case_unit(product: Material) -> None:
    lot = finished_lot(product)
    case = decode_scan(f"(01){CASE_GTIN}(17)281015(10){LOT_NO}", today=TODAY)
    assert (case.kind, case.lots, case.material) == ("lot", [lot], product)
    assert (case.unit, case.units_per_case) == ("KOLI", Decimal("12"))
    assert (case.warnings, case.gs1_dates) == ([], {"17": "2028-10-15"})
    raw_case = decode_scan(f"]C101{CASE_GTIN}17281015" + f"10{LOT_NO}")
    assert (raw_case.lots, raw_case.unit) == ([lot], "KOLI")
    # Lotsuz koli barkodu: malzeme, koli birimiyle.
    only = decode_scan(f"(01){CASE_GTIN}")
    assert (only.kind, only.material, only.unit) == ("material", product, "KOLI")
    # Ürün GTIN'i: birim yok.
    item = decode_scan(f"(01){GTIN14}(10){LOT_NO}")
    assert (item.lots, item.unit, item.units_per_case) == ([lot], "", None)
    # Rakamlardan oluşan çıplak GTIN (ITF-14 koli, EAN-13 ürün barkodu).
    assert decode_scan(CASE_GTIN).unit == "KOLI"
    bare = decode_scan(GTIN)
    assert (bare.kind, bare.material, bare.unit) == ("material", product, "")
    # Kontrol hanesi tutmayan rakamlar GTIN sayılmaz.
    with pytest.raises(BusinessRuleError) as error:
        decode_scan(GTIN[:-1] + "3")
    assert error.value.code == "scan_not_found"


@db_test
def test_case_gtin_is_found_in_its_14_digit_form() -> None:
    material = MaterialFactory.create(material_type=Material.Type.FINISHED, base_unit=unit("ADET"))
    MaterialUnitConversion.objects.create(
        material=material, unit=unit("KOLI"), factor_to_base=Decimal("6"), gtin="8690000000029"
    )
    found = decode_scan("(01)08690000000029")
    assert (found.material, found.unit, found.units_per_case) == (material, "KOLI", Decimal("6"))


@db_test
def test_pallet_content_02_on_new_and_legacy_labels(product: Material) -> None:
    lot = finished_lot(product)
    new = decode_scan(f"(02){CASE_GTIN}(37)40")
    assert (new.kind, new.material, new.unit, new.units_per_case) == (
        "material",
        product,
        "KOLI",
        Decimal("12"),
    )
    assert new.gs1 == {"02": CASE_GTIN, "37": "40"}
    legacy = decode_scan(f"(02){GTIN14}(37)40")
    assert (legacy.material, legacy.unit, legacy.units_per_case) == (product, "", None)
    with_lot = decode_scan(f"(02){CASE_GTIN}(37)40(10){LOT_NO}")
    assert (with_lot.kind, with_lot.lots, with_lot.unit) == ("lot", [lot], "KOLI")


@db_test
def test_02_looks_for_case_gtin_first_and_01_for_item_gtin_first() -> None:
    """Veri tutarsızsa (aynı GTIN bir malzemede ürün, başkasında koli GTIN'i) sıra belirler."""
    shared = "8690000000036"
    item = MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), gtin=shared
    )
    boxed = MaterialFactory.create(material_type=Material.Type.FINISHED, base_unit=unit("ADET"))
    MaterialUnitConversion.objects.create(
        material=boxed, unit=unit("KOLI"), factor_to_base=Decimal("24"), gtin=shared
    )
    found = decode_scan(f"(01)0{shared}")
    assert (found.material, found.unit) == (item, "")
    content = decode_scan(f"(02)0{shared}(37)10")
    assert (content.material, content.unit, content.units_per_case) == (
        boxed,
        "KOLI",
        Decimal("24"),
    )


@db_test
def test_pallet_sscc(product: Material) -> None:
    lot = finished_lot(product)
    pallet = PalletLabel.objects.create(sscc=sscc(42), lot=lot, case_count=20)
    found = decode_scan(f"(00){pallet.sscc}")
    assert (found.kind, found.pallet, found.lots, found.unit) == ("pallet", pallet, [lot], "")
    assert decode_scan(f"]C100{pallet.sscc}").pallet == pallet
    with pytest.raises(BusinessRuleError) as error:
        decode_scan(f"(00){sscc(43)}")
    assert error.value.code == "scan_not_found"
    with pytest.raises(BusinessRuleError) as error:
        decode_scan(f"(00){pallet.sscc[:-1]}{(int(pallet.sscc[-1]) + 1) % 10}")
    assert error.value.code == "gs1_check_digit"


@db_test
def test_expiry_on_barcode_is_compared_with_the_lot(product: Material) -> None:
    lot = finished_lot(product)
    differs = decode_scan(f"(01){GTIN14}(17)281016(10){LOT_NO}")
    assert differs.lots == [lot]
    assert differs.warnings == [
        "Barkoddaki SKT (16.10.2028) lot kaydındaki SKT'den (15.10.2028) farklı."
    ]
    assert decode_scan(f"(01){GTIN14}(17)281015(10){LOT_NO}").warnings == []
    # Gün 00: ayın son günü; lot SKT'si ayın son günüyse uyarı yok.
    month_end = finished_lot(product, "D-261015-002", expiry_date=date(2028, 10, 31))
    found = decode_scan(f"(01){GTIN14}(17)281000(10){month_end.lot_no}")
    assert (found.gs1_dates, found.warnings) == ({"17": "2028-10-31"}, [])
    Lot.objects.filter(pk=lot.pk).update(expiry_date=None)
    assert decode_scan(f"(01){GTIN14}(17)281015(10){LOT_NO}").warnings == [
        "Barkoddaki SKT (15.10.2028) lot kaydında yok."
    ]


@db_test
def test_gs1_lot_without_gtin(product: Material) -> None:
    """Palet etiketinin (17)+(10) barkodu: GTIN'siz lot no ile lot bulunur."""
    lot = finished_lot(product)
    for code in (f"(17)281015(10){LOT_NO}", "]C117281015" + f"10{LOT_NO}", f"]d210{LOT_NO}"):
        found = decode_scan(code)
        assert (found.kind, found.lots) == ("lot", [lot]), code
    with pytest.raises(BusinessRuleError) as error:
        decode_scan("(10)YOK-1")
    assert error.value.code == "scan_not_found"
    with pytest.raises(BusinessRuleError) as error:
        decode_scan("(37)40")
    assert error.value.code == "scan_not_found"
    # GS1 işareti olmayan "10…" GS1 sayılmaz (düz lot no aranır).
    with pytest.raises(BusinessRuleError) as error:
        decode_scan(f"10{LOT_NO}")
    assert error.value.message == f"Okutulan kod tanınmadı: 10{LOT_NO}."


# Palet etiketinin (17)+(10) barkodu: SSCC/GTIN ile başlamaz, GS1 olduğunu işaret söyler.
PALLET_LOT_BARCODE = "17281015" + f"10{LOT_NO}"


@db_test
@pytest.mark.parametrize("aim", ["]C1", "]e0", "]d2", "]Q3", "]J1"])
def test_gs1_aim_marks_gs1_data(product: Material, aim: str) -> None:
    """GS1-128, GS1 DataBar, GS1 DataMatrix, GS1 QR ve GS1 DotCode AIM kimlikli veri GS1'dir."""
    lot = finished_lot(product)
    found = decode_scan(f"{aim}{PALLET_LOT_BARCODE}")
    assert (found.kind, found.lots, found.gs1_dates) == ("lot", [lot], {"17": "2028-10-15"})
    assert resolve_lot(f"{aim}{PALLET_LOT_BARCODE}") == lot


@db_test
def test_gs_anywhere_marks_gs1_data(product: Material, client_for) -> None:
    """GS (FNC1) GS1 verisinin işaretidir, ortada da kenarda da: AIM göndermeyen okuyucu baştaki
    FNC1'i GS olarak gönderir. Kenardaki GS, boşluklar gibi atılır ama işaret olarak kalır."""
    lot = finished_lot(product)
    codes = [
        f"17281015{GS}10{LOT_NO}",
        f"{GS}{PALLET_LOT_BARCODE}",
        f"{PALLET_LOT_BARCODE}{GS}",
        f" \t{GS}{PALLET_LOT_BARCODE}\r\n",
    ]
    for code in codes:
        assert decode_scan(code).lots == [lot], code
        assert resolve_lot(code) == lot, code
    response = client_for("depo").get(SCAN, {"code": f"{GS}{PALLET_LOT_BARCODE}"})
    assert response.status_code == 200, response.json()
    assert [row["id"] for row in response.json()["lots"]] == [lot.pk]
    # GS1 olmayan AIM kimliği (]C0 düz Code 128, ]Q1 düz QR) işaret değildir.
    for aim in ("]C0", "]Q1"):
        with pytest.raises(BusinessRuleError) as error:
            decode_scan(f"{aim}{PALLET_LOT_BARCODE}")
        assert error.value.message == f"Okutulan kod tanınmadı: {PALLET_LOT_BARCODE}.", aim


@db_test
def test_every_edge_whitespace_is_trimmed(product: Material) -> None:
    """Okutulan kodun kenarından her boşluk karakteri atılır (NBSP, dikey sekme, FS, NEL …), önceki
    gibi; GS1 verisinde de (kenardaki boşluk hiçbir GS1 alanında veri değildir). Kenardaki GS de
    atılır ama GS1 işaretidir."""
    lot = finished_lot(product)
    location = storage_location(code="RAF-1")
    for edge in ("\xa0", "\x0b", "\x0c", "\x1c", "\x1e", "\x1f", "\x85", "\u3000"):
        for code in (f"{LOT_NO}{edge}", f"{edge}{LOT_NO}", f"{edge}LOT:{LOT_NO}{edge}"):
            assert decode_scan(code).lots == [lot], repr(code)
            assert resolve_lot(code) == lot, repr(code)
        assert decode_scan(f"{edge}RAF-1{edge}").location == location, repr(edge)
        assert decode_scan(f"{product.code}{edge}").material == product, repr(edge)
        assert scan_label(f"{edge}YOK-1{edge}") == "YOK-1", repr(edge)
        gs1_codes = (
            f"(10){LOT_NO}{edge}",
            f"{edge}(01){GTIN14}(10){LOT_NO}{edge}",
            f"]C110{LOT_NO}{edge}",
            f"{GS}10{LOT_NO}{edge}",
            f"{edge}{GS}{edge}17281015" + f"10{LOT_NO}{edge}{GS}{edge}",
        )
        for code in gs1_codes:
            assert decode_scan(code).lots == [lot], repr(code)
            assert resolve_lot(code, materials=[product.pk]) == lot, repr(code)
        assert scan_label(f"(01){GTIN14}(10)YOK-1{edge}") == "YOK-1", repr(edge)


@db_test
def test_marker_behind_other_edge_whitespace_is_still_found(product: Material) -> None:
    """Kodun başındaki NBSP, dikey sekme gibi boşluğun arkasındaki AIM kimliği ya da parantezli AI
    yine işarettir: GS1 verisi çözülür, GS1 olmayan AIM metinde kalmaz."""
    lot = finished_lot(product)
    for edge in ("\xa0", "\x0b", "\u3000"):
        for code in (f"{edge}(01){GTIN14}(10){LOT_NO}", f"{edge}]C101{GTIN14}10{LOT_NO}"):
            assert decode_scan(code).lots == [lot], repr(code)
            assert resolve_lot(code, materials=[product.pk]) == lot, repr(code)
        assert scan_label(f"{edge}]C0YOK-1") == "YOK-1", repr(edge)
        with pytest.raises(BusinessRuleError) as error:
            decode_scan(f"{edge}]C0YOK-1")
        assert error.value.message == "Okutulan kod tanınmadı: YOK-1.", repr(edge)
        # GS1 olmayan AIM'in arkasındaki boşluk da atılır.
        assert decode_scan(f"]C0{edge}{LOT_NO}").lots == [lot], repr(edge)
    # AIM yalnızca bir kez atılır: AIM ve boşluk tekrarı metinde kalır (özyineleme yok).
    with pytest.raises(BusinessRuleError) as error:
        decode_scan("\xa0]C0" * 1500 + "YOK-1")
    assert error.value.code == "scan_not_found"


@db_test
def test_marked_gs1_data_does_not_fall_back_to_lot_numbers() -> None:
    """GS içeren veri GS1'dir: kontrol hanesi hatalıysa aynı metinde lot olsa da GS1 hatası verir
    (yalnızca SSCC/GTIN gibi başlayan işaretsiz veri lot no olarak da aranır)."""
    material = MaterialFactory.create()
    inner = f"0108690000000013{GS}10ABC"  # (01) kontrol hanesi tutmuyor
    for lot_no in (inner, "0108690000000013"):
        services.create_lot(None, material=material, source=Lot.Source.PURCHASE, lot_no=lot_no)
    for code in (inner, f"{GS}0108690000000013", f"0108690000000013{GS}"):
        with pytest.raises(BusinessRuleError) as error:
            decode_scan(code)
        assert error.value.code == "gs1_check_digit", code
    assert decode_scan("0108690000000013").lots[0].lot_no == "0108690000000013"


@db_test
@pytest.mark.parametrize("lot_no", ["ACILIS-MAMUL-DETERJAN-0001", "LOT 12"])
def test_old_labels_with_legacy_lot_numbers_still_scan(product: Material, lot_no: str) -> None:
    """Bu adımdan önce basılmış koli ve palet etiketlerinde (10) eski lot numarasıdır (26
    karakter, boşluklu): üretim, dolum ve sevkiyatın çözümü onları okur."""
    lot = finished_lot(product, lot_no)
    codes = [
        f"(01){GTIN14}(10){lot_no}",
        f"]C101{GTIN14}10{lot_no}",
        f"(01){CASE_GTIN}(17)281015(10){lot_no}",
        f"]C101{CASE_GTIN}17281015" + f"10{lot_no}",
        f"]C101{CASE_GTIN}10{lot_no}{GS}17281015",
    ]
    for code in codes:
        assert decode_scan(code).lots == [lot], code
        assert resolve_lot(code, materials=[product.pk]) == lot, code


@db_test
def test_lot_field_stays_limited_to_64_printable_ascii_characters(product: Material) -> None:
    """Okurken de (10) sınırlıdır: 64 karakterden uzun ya da ASCII dışı harfli lot no GS1
    barkodundan okunmaz (`gs1_malformed`)."""
    turkish = finished_lot(product, "ŞUBAT-01")
    for value in ("A" * 65, "ŞUBAT-01"):
        for code in (f"(01){GTIN14}(10){value}", f"]C101{GTIN14}10{value}"):
            with pytest.raises(BusinessRuleError) as error:
                resolve_lot(code)
            assert error.value.code == "gs1_malformed", code
            assert "(10)" in error.value.message
    # Böyle lot QR'daki lot etiketiyle (LOT:) okutulur.
    assert resolve_lot("LOT:ŞUBAT-01") == turkish


@db_test
def test_inactive_case_conversion_finds_the_material_without_case_quantity(
    product: Material,
) -> None:
    """Pasif koli dönüşümünün GTIN'i (basılmış etiketler) malzemeyi yine bulur; koli içi miktar
    önerilmez (birim boş, uyarı)."""
    lot = finished_lot(product)
    MaterialUnitConversion.objects.filter(material=product).update(is_active=False)
    warning = "Bu koli GTIN'inin dönüşümü pasif; koli içi miktar önerilmez."
    codes = [
        f"(01){CASE_GTIN}(10){LOT_NO}",
        f"(01){CASE_GTIN}",
        f"(02){CASE_GTIN}(37)40",
        CASE_GTIN,
    ]
    for code in codes:
        found = decode_scan(code)
        assert (found.material, found.unit, found.units_per_case) == (product, "", None), code
        assert found.warnings == [warning], code
    expiry = decode_scan(f"(01){CASE_GTIN}(17)281016(10){LOT_NO}")
    assert expiry.lots == [lot]
    assert expiry.warnings == [
        warning,
        "Barkoddaki SKT (16.10.2028) lot kaydındaki SKT'den (15.10.2028) farklı.",
    ]
    assert decode_scan(f"(01){GTIN14}(10){LOT_NO}").warnings == []


@db_test
def test_codes_that_only_look_like_gs1_fall_back_to_lot_numbers() -> None:
    """SSCC/GTIN gibi başlayan ama GS1 olarak çözülemeyen ham veri önce lot, lokasyon, malzeme
    kodu olarak aranır; bulunamazsa GS1 hatası döner."""
    material = MaterialFactory.create()
    bad_check = services.create_lot(
        None, material=material, source=Lot.Source.PURCHASE, lot_no="0108690000000013"
    )
    unregistered = services.create_lot(
        None, material=material, source=Lot.Source.PURCHASE, lot_no="0108690000000029"
    )
    assert decode_scan("0108690000000013").lots == [bad_check]
    assert decode_scan("0108690000000029").lots == [unregistered]
    with pytest.raises(BusinessRuleError) as error:
        decode_scan("0108690000000044")
    assert error.value.code == "gs1_check_digit"
    with pytest.raises(BusinessRuleError) as error:
        decode_scan("0108690000000043")
    assert error.value.message == "Bu GTIN ile kayıtlı malzeme yok: 08690000000043."
    # GS1 olduğu belli veride geri düşüş yok.
    with pytest.raises(BusinessRuleError) as error:
        decode_scan("(01)08690000000013")
    assert error.value.code == "gs1_check_digit"


@db_test
def test_scan_api_returns_gs1_fields(client_for, product: Material) -> None:
    finished_lot(product)
    client = client_for("depo")
    body = client.get(SCAN, {"code": f"(01){CASE_GTIN}(17)281016(10){LOT_NO}"}).json()
    assert body["kind"] == "lot" and body["unit"] == "KOLI"
    assert body["units_per_case"] == "12.0000"
    assert body["gs1_dates"] == {"17": "2028-10-16"}
    assert body["warnings"] == [
        "Barkoddaki SKT (16.10.2028) lot kaydındaki SKT'den (15.10.2028) farklı."
    ]
    # Lotsuz koli barkodu: "1 koli = 12 ADET" için malzemenin temel birimi.
    case = client.get(SCAN, {"code": f"(01){CASE_GTIN}"}).json()
    assert (case["kind"], case["unit"], case["units_per_case"]) == ("material", "KOLI", "12.0000")
    assert case["material"]["base_unit_code"] == "ADET"
    plain = client.get(SCAN, {"code": f"LOT:{LOT_NO}"}).json()
    assert (plain["unit"], plain["units_per_case"], plain["warnings"], plain["gs1_dates"]) == (
        "",
        None,
        [],
        {},
    )
    errors = {
        "(01)08690000000013": "gs1_check_digit",
        "(01)08690000000012(8008)2610151230": "gs1_unsupported_ai",
        "(01)08690000000012(17)261301": "gs1_invalid_date",
        "(01)0869000000001": "gs1_malformed",
    }
    for code, expected in errors.items():
        response = client.get(SCAN, {"code": code})
        assert response.status_code == 400, code
        assert response.json()["code"] == expected, code
        assert "(" in response.json()["detail"]
    assert client_for().get(SCAN, {"code": LOT_NO}).status_code == 200


@db_test
def test_scanned_material_comes_with_its_base_unit(
    product: Material, django_assert_num_queries
) -> None:
    """Okutma sonucundaki malzeme temel birimiyle birlikte yüklenir: yanıt sorgusuz seri hale
    gelir, her okutma yolunda."""
    lot = finished_lot(product)
    pallet = PalletLabel.objects.create(sscc=sscc(9), lot=lot, case_count=10)
    codes = [
        f"(01){CASE_GTIN}",
        f"(02){CASE_GTIN}(37)40",
        f"(01){GTIN14}",
        CASE_GTIN,
        GTIN,
        product.code,
        f"MAT:{product.code}",
        LOT_NO,
        f"LOT:{LOT_NO}",
        f"(01){CASE_GTIN}(10){LOT_NO}",
        f"(10){LOT_NO}",
        f"(00){pallet.sscc}",
    ]
    for code in codes:
        result = decode_scan(code)
        with django_assert_num_queries(0):
            data = ScanResultSerializer(result).data
        assert data["material"]["base_unit_code"] == "ADET", code


@db_test
def test_lot_serializer_shows_case_gtin(client_for, product: Material) -> None:
    lot = stocked_lot("10", material=product)
    plain = stocked_lot("10")
    client = client_for("depo")
    rows = {row["id"]: row for row in client.get("/api/v1/inventory/lots/").json()["results"]}
    assert rows[lot.pk]["material_case_gtin"] == CASE_GTIN
    assert rows[plain.pk]["material_case_gtin"] == ""
    detail = client.get(f"/api/v1/inventory/lots/{lot.pk}/").json()
    assert detail["material_case_gtin"] == CASE_GTIN
    # Açıklamasız lot (başka bir sorgudan) da aynı değeri verir.
    assert LotSerializer(Lot.objects.get(pk=lot.pk)).data["material_case_gtin"] == CASE_GTIN
    assert LotSerializer(Lot.objects.get(pk=plain.pk)).data["material_case_gtin"] == ""


def gs1_on_labels(lot: Lot) -> list[bool]:
    """Lotun koli ve palet etiketinde GS1 içerik barkodu var mı (paletin SSCC'si (00) sayılmaz)."""
    pallet = PalletLabel(sscc=sscc(1), lot=lot, case_count=10)
    return [
        any(
            isinstance(element, Barcode) and element.gs1 is not None and element.gs1[0][0] != "00"
            for element in label.elements
        )
        for label in (labels.case_label(lot), labels.pallet_label(pallet))
    ]


def finished_material(gtin: str = "", case_gtin: str = "", *, active: bool = True) -> Material:
    """Mamul (eski veri gibi doğrudan, denetimsiz); `case_gtin` verilirse KOLI dönüşümünde."""
    material = MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), gtin=gtin
    )
    if case_gtin:
        MaterialUnitConversion.objects.create(
            material=material,
            unit=unit("KOLI"),
            factor_to_base=Decimal("12"),
            gtin=case_gtin,
            is_active=active,
        )
    return material


@db_test
def test_lot_serializer_tells_whether_labels_carry_gs1(
    client_for, product: Material, django_assert_num_queries
) -> None:
    """`gs1_label` (ön yüzün koli/palet etiketi ipucu): etiketler GS1 içerik barkodu taşır mı.
    Mamul, geçerli GTIN (koli GTIN'i, tanımlı değilse ürün GTIN'i; geçersiz koli GTIN'i ürün
    GTIN'ine düşmez) ve (10) alanına uyan lot no gerekir; değilse etikette firma içi `LOT:` var.
    Liste satır başına sorgu yapmaz."""
    client = client_for("depo")
    expected = {finished_lot(product): True}
    client.get(LOTS)  # ısınma
    with CaptureQueriesContext(connection) as one_row:
        assert client.get(LOTS).json()["count"] == 1
    raw_material = MaterialFactory.create(material_type=Material.Type.RAW, gtin="8690000000043")
    packaging = MaterialFactory.create(material_type=Material.Type.PACKAGING, gtin="8690000000050")
    bulk = MaterialFactory.create(material_type=Material.Type.BULK, gtin="8690000000067")
    expected |= {
        finished_lot(product, "A" * 20): True,
        finished_lot(finished_material("8690000000029")): True,  # yalnız ürün GTIN'i
        finished_lot(finished_material(case_gtin="28690000000016")): True,  # yalnız koli GTIN'i
        # Pasif koli dönüşümünün GTIN'i de basılır (okutmadaki gibi).
        finished_lot(finished_material(case_gtin="38690000000013", active=False)): True,
        finished_lot(finished_material("8690000000013")): False,  # kontrol hanesi yanlış eski GTIN
        finished_lot(finished_material("8690000000036", "18690000000010")): False,  # koli geçersiz
        finished_lot(finished_material()): False,  # GTIN yok
        finished_lot(product, "A" * 21): False,  # (10) en çok 20 karakter
        finished_lot(product, "LOT 12"): False,  # boşluk GS1 kümesinde yok
        finished_lot(product, "LOT(2)"): False,  # ZPL'de parantez AI sınırıdır
        finished_lot(product, "ŞUBAT-01"): False,  # Türkçe harf
        # Mamul değil (geçerli GTIN'le de): hammadde, ambalaj, bulk.
        **{
            services.create_lot(
                None, material=material, source=Lot.Source.PURCHASE, lot_no=LOT_NO
            ): False
            for material in (raw_material, packaging, bulk)
        },
    }
    with django_assert_num_queries(len(one_row)):
        rows = client.get(LOTS).json()["results"]
    assert {row["id"]: row["gs1_label"] for row in rows} == {
        lot.pk: flag for lot, flag in expected.items()
    }
    for lot, flag in expected.items():
        assert client.get(f"{LOTS}{lot.pk}/").json()["gs1_label"] is flag, lot.lot_no
        assert LotSerializer(Lot.objects.get(pk=lot.pk)).data["gs1_label"] is flag, lot.lot_no
        if lot.material.material_type == Material.Type.FINISHED:
            assert gs1_on_labels(lot) == [flag, flag], lot.lot_no


# --- ortak lot çözümü ----------------------------------------------------------------------------


@db_test
def test_resolve_lot_understands_every_lot_code(product: Material) -> None:
    lot = finished_lot(product)
    pallet = PalletLabel.objects.create(sscc=sscc(5), lot=lot, case_count=10)
    codes = [
        LOT_NO,
        LOT_NO.lower(),
        f" LOT:{LOT_NO} ",
        f"lot:{LOT_NO.lower()}",
        f"(01){GTIN14}(10){LOT_NO}",
        f"(01){CASE_GTIN}(17)281015(10){LOT_NO}",
        f"]C101{CASE_GTIN}10{LOT_NO}{GS}17281015",
        f"01{GTIN14}10{LOT_NO}",
        f"(00){pallet.sscc}",
        f"]C100{pallet.sscc}",
        f"(10){LOT_NO}",
    ]
    for code in codes:
        assert resolve_lot(code, materials=[product.pk]) == lot, code
        assert resolve_lot(code) == lot, code
    missing = ["YOK-1", "LOT:YOK-1", f"(01){GTIN14}(10)YOK-1", f"(00){sscc(6)}"]
    for code in [*missing, "(01)08690000000029(10)X"]:
        assert resolve_lot(code) is None, code
    # Lokasyon ya da malzeme kodu lot değildir.
    location = storage_location(code="RAF-1")
    assert resolve_lot(location.code) is None
    assert resolve_lot(product.code) is None
    assert resolve_lot(f"(01){CASE_GTIN}") is None
    # GS1 biçim hataları olduğu gibi yükselir.
    with pytest.raises(BusinessRuleError) as error:
        resolve_lot(f"(01)08690000000013(10){LOT_NO}")
    assert error.value.code == "gs1_check_digit"


@db_test
def test_resolve_lot_material_restriction_preference_and_ambiguity(product: Material) -> None:
    lot = finished_lot(product)
    other_material = MaterialFactory.create()
    other = services.create_lot(
        None, material=other_material, source=Lot.Source.PURCHASE, lot_no=LOT_NO
    )
    third = MaterialFactory.create()
    # Kısıtlı: yalnızca verilen malzemeler.
    assert resolve_lot(LOT_NO, materials=[product.pk]) == lot
    assert resolve_lot(LOT_NO, materials=[third.pk]) is None
    # Tercihli: verilenlerde yoksa başka malzemedeki lot (servis "yanlış malzeme" der).
    assert resolve_lot(LOT_NO, materials=[third.pk], restrict=False) == other
    # GTIN malzemeyi belirler: verilenlerde değilse kısıtlıda bulunmaz, tercihlide o lot.
    assert resolve_lot(f"(01){GTIN14}(10){LOT_NO}", materials=[other_material.pk]) is None
    assert (
        resolve_lot(f"(01){GTIN14}(10){LOT_NO}", materials=[other_material.pk], restrict=False)
        == lot
    )
    # Verilen malzemelerin birden çoğunda aynı numara: tekil istenirse `ambiguous_lot`, yoksa en
    # yeni lot.
    both = [product.pk, other_material.pk]
    with pytest.raises(BusinessRuleError) as error:
        resolve_lot(f"LOT:{LOT_NO.lower()}", materials=both, unique=True)
    assert error.value.code == "ambiguous_lot"
    assert (
        error.value.message == f"{LOT_NO} numarası birden çok malzemede var; lotu listeden seçin."
    )
    # Çağıran kendi bağlamını söyleyebilir (sevkiyat); {lot_no} lotun numarasıdır.
    with pytest.raises(BusinessRuleError) as error:
        resolve_lot(LOT_NO, materials=both, unique=True, ambiguous_message="{lot_no} iki üründe.")
    assert error.value.message == f"{LOT_NO} iki üründe."
    assert resolve_lot(LOT_NO, materials=both) == other
    assert resolve_lot(LOT_NO, materials=[product.pk], unique=True) == lot
    assert resolve_lot(f"(01){GTIN14}(10){LOT_NO}", materials=both, unique=True) == lot


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (f"]C101{CASE_GTIN}10YOK-1{GS}17281015", "YOK-1"),
        (f"(01){CASE_GTIN}(17)281015(10)YOK-1", "YOK-1"),
        (f"01{CASE_GTIN}10YOK-1", "YOK-1"),  # AIM'siz, GS'siz ham veri
        (f"{GS}1728101510YOK-1", "YOK-1"),
        (f"]C1(00){sscc(6)}", sscc(6)),
        (f"(01){CASE_GTIN}", CASE_GTIN),
        (f"(02){CASE_GTIN}(37)40", CASE_GTIN),
        (" LOT:YOK-1\r\n", "LOT:YOK-1"),
        ("]Q3LOT:YOK-1", "LOT:YOK-1"),
        ("]C0YOK-1", "YOK-1"),
        # İşaret NBSP, dikey sekme gibi boşluğun arkasında.
        ("\x0b]C0YOK-1", "YOK-1"),
        (f"\xa0(01){CASE_GTIN}(10)YOK-1", "YOK-1"),
        (f"\u3000]C101{CASE_GTIN}10YOK-1", "YOK-1"),
        # GS1 verisinin kenarındaki boşluk (NBSP, RS) da atılır.
        (f"(01){CASE_GTIN}(10)YOK-1\xa0", "YOK-1"),
        (f"{GS}1728101510YOK-1\x1e", "YOK-1"),
        # Çözülemeyen GS1 verisi: metin (AIM'siz, GS boşluk).
        (f"]C10108690000000013{GS}10YOK-1", "0108690000000013 10YOK-1"),
        ("(01)08690000000012(9999)X", "(01)08690000000012(9999)X"),
        ("(37)40", "(37)40"),
        (GS, ""),
        ("", ""),
    ],
)
def test_scan_label_is_readable(code: str, label: str) -> None:
    """Hata mesajlarında okutulan kodun gösterimi: GS1'de lot no / SSCC / GTIN, diğerlerinde AIM'siz
    metin; kontrol karakteri yok, hata vermez."""
    assert scan_label(code) == label
