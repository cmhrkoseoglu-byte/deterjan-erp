"""GS1 (Kodlama sistematiği, Paket 2, Adım 7): koli ve palet etiketinde koli GTIN'i, okutulamayan
GS1 barkodunun ve Türkçe harfli ya da ">" taşıyan lot noda firma içi barkodun basılmaması, ZPL'de
"^" ve "~" taşıyan lot no, palette koli sayısı sınırı, SSCC'nin yeniden verilmemesi, lotu olan
mamulde GTIN kilidi (eski veriler dahil), koli içi miktar değişince lotun etiketinde lotun açıldığı
andaki koli GTIN'i (3. tur; kurallar `masterdata/tests/test_pack_change.py`)."""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps as django_apps

from apps.core.exceptions import BusinessRuleError
from apps.core.labels import (
    FNC1,
    Barcode,
    Label,
    QRCode,
    Text,
    gs1_check_digit,
    gs1_pdf_data,
    render_zpl,
)
from apps.core.roles import ADMIN, DEPO, DOLUM, PLANLAMA
from apps.inventory import services
from apps.inventory.api.serializers import LotSerializer
from apps.inventory.labels import (
    NO_BARCODE_QR,
    NO_BARCODE_SSCC,
    case_gs1,
    case_label,
    lot_label,
    pallet_label,
)
from apps.inventory.models import Lot, PalletLabel
from apps.inventory.selectors import decode_scan
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata import services as masterdata
from apps.masterdata.models import LabelSettings, Material, MaterialUnitConversion, RetiredGtin
from apps.masterdata.tests.factories import MaterialFactory, unit

pytestmark = pytest.mark.django_db
LOTS = "/api/v1/inventory/lots/"
PALLETS = "/api/v1/inventory/pallet-labels/"
MATERIALS = "/api/v1/masterdata/materials/"
PREFIX = "8691234"
GTIN = "8690000000012"
CASE_GTIN = "18690000000019"  # GTIN'in gösterge hanesi 1 ile koli GTIN'i
NEW_CASE_GTIN = "28690000000016"  # gösterge hanesi 2 (koli içi miktar değişince)
THIRD_CASE_GTIN = "38690000000013"  # gösterge hanesi 3
OTHER_GTIN = "8690000000029"


@pytest.fixture
def admin(make_user):
    return make_user(ADMIN)


def enable_gs1(admin, prefix: str = PREFIX) -> None:
    masterdata.update_gs1_settings(admin, note="GS1 üyeliği", company_prefix=prefix)


def finished(gtin: str = GTIN, case_gtin: str | None = None, *, active: bool = True) -> Material:
    """Mamul (eski veri gibi doğrudan); `case_gtin` verilirse KOLI dönüşümü de açılır."""
    material = MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), gtin=gtin
    )
    if case_gtin is not None:
        MaterialUnitConversion.objects.create(
            material=material,
            unit=unit("KOLI"),
            factor_to_base=Decimal(12),
            gtin=case_gtin,
            is_active=active,
        )
    return material


def finished_lot(material: Material, lot_no: str = "D-261015-001") -> Lot:
    return services.create_lot(
        None,
        material=material,
        source=Lot.Source.FILLING,
        lot_no=lot_no,
        manufactured_at=date(2026, 10, 15),
        expiry_date=date(2028, 10, 15),
    )


def gs1_barcodes(label: Label) -> list[str]:
    """Etiketteki GS1-128 barkodlarının PDF verisi (FNC1 dahil)."""
    return [
        gs1_pdf_data(element.gs1)
        for element in label.elements
        if isinstance(element, Barcode) and element.gs1 is not None
    ]


def internal_barcodes(label: Label) -> list[Barcode]:
    """Etiketteki firma içi Code128 barkodları (GS1 olmayan)."""
    return [
        element
        for element in label.elements
        if isinstance(element, Barcode) and element.gs1 is None
    ]


def texts(label: Label) -> list[str]:
    return [element.text for element in label.elements if isinstance(element, Text)]


def qr_codes(label: Label) -> list[str]:
    return [element.data for element in label.elements if isinstance(element, QRCode)]


def zpl_gs1_fields(label: Label) -> list[str]:
    """ZPL'deki GS1-128 (UCC/EAN kipi D) barkod verileri."""
    return [
        line.split("^FD", 1)[1].removesuffix("^FS")
        for line in render_zpl([label]).splitlines()
        if ",D^FD" in line
    ]


# Zebra `^BC` kip (invocation) kodlarından veri karakteri olanlar: "><" = "^", ">0" = ">", ">=" =
# "~". Öteki ">x" FNC, alt küme ya da başlangıç kodudur: veri değildir.
BC_DATA_INVOCATIONS = {"<": "^", "0": ">", "=": "~"}


def zpl_printed(label: Label) -> dict[str, list[str]]:
    """ZPL'de yazıcının bastığı ve kodladığı veri, alan türüne göre (yazı, firma içi Code128, QR;
    GS1-128 hariç). Alan verisinde çıplak "^" ya da "~" olamaz (yazıcı orada alanı bitirip komut
    okur); `^FH\\` alanında "\\XX" onaltılık kaçışları çözülür, ^FB bloğunda ters bölü kaçış
    karakteridir ("\\\\" ters bölü, "\\&" yeni satır; tanımsız kaçış "?"), Code128'de ">" kip
    önekidir (`BC_DATA_INVOCATIONS`; veri olmayan kod "?")."""
    fields: dict[str, list[str]] = {"text": [], "code128": [], "qr": []}
    for line in render_zpl([label]).splitlines():
        if "^FD" not in line or ",D^F" in line:
            continue
        data = line.split("^FD", 1)[1].removesuffix("^FS")
        assert not {"^", "~"} & set(data), line
        if "^FH\\^FD" in line:
            raw = re.sub(rb"\\([0-9A-Fa-f]{2})", lambda m: bytes([int(m[1], 16)]), data.encode())
            data = raw.decode()
        if "^FB" in line:
            data = re.sub(
                r"\\(.)", lambda m: {"\\": "\\", "&": "\n"}.get(m[1], "?"), data, flags=re.S
            )
        if "^BC" in line:
            data = re.sub(r">(.?)", lambda m: BC_DATA_INVOCATIONS.get(m[1], "?"), data, flags=re.S)
        if "^BQ" in line:
            fields["qr"].append(data.removeprefix("QA,"))
        else:
            fields["code128" if "^BC" in line else "text"].append(data)
    return fields


def legacy_pallet(actor, lot: Lot, case_count: int) -> PalletLabel:
    """Koli sayısı sınırından önce açılmış palet kaydı (eski veri: 8 haneden büyük koli sayısı)."""
    pallet = services.create_pallet_label(actor, lot, 1)
    PalletLabel.objects.filter(pk=pallet.pk).update(case_count=case_count)
    pallet.refresh_from_db()
    return pallet


# --- koli etiketi ------------------------------------------------------------------------------


def test_case_label_prints_the_case_gtin_when_defined(client_for) -> None:
    lot = finished_lot(finished(case_gtin=CASE_GTIN))
    response = client_for(DOLUM).get(f"{LOTS}{lot.pk}/case-label/", {"output": "zpl"})
    assert response.status_code == 200
    zpl = response.content.decode()
    assert f"^FD(01){CASE_GTIN}(17)281015(10)D-261015-001^FS" in zpl
    assert f"^FD{CASE_GTIN}^FS" in zpl  # GTIN satırı
    assert "(01)08690000000012" not in zpl
    # PDF: başta FNC1; (01) ve (17) sabit uzunluklu, değişken (10) sonda: arada FNC1 yok.
    assert gs1_barcodes(case_label(lot)) == [f"{FNC1}01{CASE_GTIN}17281015" + "10D-261015-001"]


def test_case_label_without_case_gtin_keeps_the_item_gtin() -> None:
    no_conversion = finished_lot(finished(), lot_no="D-261015-001")
    blank_case = finished_lot(finished(OTHER_GTIN, case_gtin=""), lot_no="D-261015-002")
    assert case_gs1(no_conversion)[0] == ("01", "0" + GTIN)  # type: ignore[index]
    assert case_gs1(blank_case)[0] == ("01", "0" + OTHER_GTIN)  # type: ignore[index]
    assert case_gs1(finished_lot(finished(gtin=""), lot_no="D-261015-003")) is None
    # Ürün GTIN'i olmasa da koli GTIN'i basılır; pasif KOLI dönüşümünün GTIN'i de (okutmadaki gibi).
    only_case = finished_lot(finished(gtin="", case_gtin=CASE_GTIN), lot_no="D-261015-004")
    assert case_gs1(only_case)[0] == ("01", CASE_GTIN)  # type: ignore[index]
    inactive = finished_lot(
        finished("8690000000036", "28690000000016", active=False), lot_no="D-261015-005"
    )
    assert case_gs1(inactive)[0] == ("01", "28690000000016")  # type: ignore[index]


# --- palet etiketi -----------------------------------------------------------------------------


def test_pallet_label_prints_the_case_gtin_and_case_count(client_for, make_user, admin) -> None:
    enable_gs1(admin)
    lot = finished_lot(finished(case_gtin=CASE_GTIN))
    client = client_for(DOLUM)
    created = client.post(PALLETS, {"lot": lot.pk, "case_count": 40, "units_per_case": 12})
    assert created.status_code == 201, created.json()
    zpl = client.get(f"{PALLETS}{created.json()['id']}/label/", {"output": "zpl"}).content
    text = zpl.decode()
    assert f"^FD(02){CASE_GTIN}(37)40^FS" in text
    assert "^FD(17)281015(10)D-261015-001^FS" in text
    assert f"^FD{CASE_GTIN}^FS" in text  # İÇERİK (GTIN) satırı
    pallet = PalletLabel.objects.get(pk=created.json()["id"])
    codes = gs1_barcodes(pallet_label(pallet))
    assert codes[0] == f"{FNC1}02{CASE_GTIN}3740"  # (02) sabit uzunluklu: (37)'den önce FNC1 yok
    assert codes[-1] == f"{FNC1}00{pallet.sscc}"

    # Koli GTIN'i yoksa bugünkü gibi ürün GTIN'i.
    plain = finished_lot(finished(OTHER_GTIN), lot_no="D-261015-002")
    other = services.create_pallet_label(make_user(DEPO), plain, 10)
    assert gs1_barcodes(pallet_label(other))[0] == f"{FNC1}020{OTHER_GTIN}3710"


# --- okutulamayan GS1 barkodu basılmaz ---------------------------------------------------------


def test_invalid_legacy_gtin_is_not_printed(make_user, admin) -> None:
    """Kontrol hanesi yanlış eski GTIN'le basılan barkod okutulamaz: koli ve palet etiketinde
    GS1-128 ve GTIN satırı yoktur; barkod GTIN'siz malzemedeki gibi firma içi `LOT:`."""
    enable_gs1(admin)
    actor = make_user(DEPO)
    legacy = finished_lot(finished(gtin="8690000000013"))
    plain = finished_lot(finished(gtin=""))  # aynı lot no, GTIN'siz malzeme

    case = case_label(legacy)
    assert case_gs1(legacy) is None and gs1_barcodes(case) == []
    assert internal_barcodes(case) == internal_barcodes(case_label(plain))
    assert [barcode.data for barcode in internal_barcodes(case)] == ["LOT:D-261015-001"]
    assert "GTIN" not in texts(case)
    assert not [text for text in texts(case) if "869000000001" in text]

    pallet = services.create_pallet_label(actor, legacy, 10)
    printed = pallet_label(pallet)
    assert gs1_barcodes(printed) == [f"{FNC1}00{pallet.sscc}"]  # yalnız SSCC
    expected = pallet_label(services.create_pallet_label(actor, plain, 10))
    assert internal_barcodes(printed) == internal_barcodes(expected)
    assert "İÇERİK (GTIN)" not in texts(printed)
    # Geçersiz koli GTIN'i de basılmaz; yerine ürün GTIN'i de basılmaz (koli ayrı üründür).
    bad_case = finished_lot(finished(OTHER_GTIN, case_gtin="18690000000010"), lot_no="D-2")
    assert case_gs1(bad_case) is None and "GTIN" not in texts(case_label(bad_case))


@pytest.mark.parametrize(
    "lot_no",
    [
        "ACILIS-MAMUL-DETERJAN-0001",  # 26 karakter (açılış stoku)
        "ACILIS-DETERJAN-00001",  # 21 karakter
        "LOT 12",  # boşluk GS1 kümesinde yok
        "LOT(2)",  # ZPL GS1 kipinde parantez AI sınırıdır: (10)LOT2 basılırdı
    ],
)
def test_lot_number_outside_gs1_rules_gets_the_internal_barcode(make_user, admin, lot_no) -> None:
    """(10) lot alanı en çok 20 karakterdir ve GS1 karakter kümesindendir; ZPL'nin GS1 kipi (D)
    parantez taşıyamaz. Böyle lot no GS1-128'e girmez (PDF'te de, ZPL'de de): koli ve palet
    etiketinde barkod GTIN'siz malzemedeki gibi firma içi `LOT:`; geçerli GTIN yazı olarak kalır.
    ">" taşıyan lot no firma içi Code128'e de yazılmaz (ayrı test)."""
    enable_gs1(admin)
    actor = make_user(DEPO)
    lot = finished_lot(finished(case_gtin=CASE_GTIN), lot_no=lot_no)
    plain = finished_lot(finished(gtin=""), lot_no=lot_no)

    case = case_label(lot)
    assert case_gs1(lot) is None and gs1_barcodes(case) == []
    assert zpl_gs1_fields(case) == []
    assert internal_barcodes(case) == internal_barcodes(case_label(plain))
    assert [barcode.data for barcode in internal_barcodes(case)] == [f"LOT:{lot_no}"]
    assert CASE_GTIN in texts(case)

    pallet = services.create_pallet_label(actor, lot, 10)
    printed = pallet_label(pallet)
    assert gs1_barcodes(printed) == [f"{FNC1}00{pallet.sscc}"]
    assert zpl_gs1_fields(printed) == [f"(00){pallet.sscc}"]
    expected = pallet_label(services.create_pallet_label(actor, plain, 10))
    assert internal_barcodes(printed) == internal_barcodes(expected)
    assert CASE_GTIN in texts(printed)


def test_twenty_character_lot_number_is_still_gs1() -> None:
    lot = finished_lot(finished(), lot_no="ACILIS-DETERJAN-0001")
    assert case_gs1(lot) == (("01", "0" + GTIN), ("17", "281015"), ("10", "ACILIS-DETERJAN-0001"))
    assert zpl_gs1_fields(case_label(lot)) == [f"(01)0{GTIN}(17)281015(10)ACILIS-DETERJAN-0001"]


def test_lot_number_with_turkish_letters_gets_no_code128(make_user, admin) -> None:
    """Code128 Türkçe harfi taşımaz (reportlab sessizce atar: LOT:ŞUBAT-01 → LOT:UBAT-01, başka lot
    okutulur). Böyle lot noda lot, koli ve palet etiketine firma içi barkod basılmaz; yerine hangi
    kodun okutulacağı yazılır: lot ve koli etiketinde QR (`LOT:<lot_no>`), palette SSCC."""
    enable_gs1(admin)
    lot = finished_lot(finished(case_gtin=CASE_GTIN), lot_no="ŞUBAT-01")
    plain = finished_lot(finished(gtin=""), lot_no="ÇAY-01")
    for label, data in (
        (lot_label(lot), "LOT:ŞUBAT-01"),
        (case_label(lot), "LOT:ŞUBAT-01"),
        (lot_label(plain), "LOT:ÇAY-01"),
        (case_label(plain), "LOT:ÇAY-01"),
    ):
        assert gs1_barcodes(label) == [] and internal_barcodes(label) == []
        assert NO_BARCODE_QR in texts(label) and qr_codes(label) == [data]
        assert "^BC" not in render_zpl([label])  # ZPL'de de barkod yok
    assert CASE_GTIN in texts(case_label(lot))  # geçerli GTIN yazı olarak kalır

    pallet = services.create_pallet_label(make_user(DEPO), lot, 10)
    printed = pallet_label(pallet)
    assert gs1_barcodes(printed) == [f"{FNC1}00{pallet.sscc}"] and internal_barcodes(printed) == []
    assert NO_BARCODE_SSCC in texts(printed)
    assert render_zpl([printed]).count("^BC") == 1  # yalnız SSCC
    assert decode_scan(f"(00){pallet.sscc}").lots == [lot]  # SSCC paletin lotunu bulur

    # ASCII lot no aynen basılır (boşluk dahil).
    ascii_lot = finished_lot(finished(gtin=""), lot_no="LOT 12")
    assert [barcode.data for barcode in internal_barcodes(lot_label(ascii_lot))] == ["LOT:LOT 12"]
    assert NO_BARCODE_QR not in texts(lot_label(ascii_lot))


def test_lot_number_with_a_greater_than_sign_gets_no_code128(make_user, admin) -> None:
    """ZPL `^BC`'de ">" kip (invocation) önekidir; Zebra tablosunda "><" = "^": eski kaçış LOT>1'i
    LOT:LOT^1 diye kodlardı (lot bulunamaz ya da başka lot çıkar). ">" taşıyan lot no GS1-128'e de
    firma içi Code128'e de yazılmaz: lot ve koli etiketinde QR (veriyi aynen taşır), palette SSCC
    okutulur; etiket bunu yazar. PDF de aynı düzende basılır."""
    enable_gs1(admin)
    lot = finished_lot(finished(case_gtin=CASE_GTIN), lot_no="LOT>1")
    code = "LOT:LOT>1"
    pallet = services.create_pallet_label(make_user(DEPO), lot, 10)
    sscc = [f"{FNC1}00{pallet.sscc}"]
    for label, qr, note, gs1 in (
        (lot_label(lot), [code], NO_BARCODE_QR, []),
        (case_label(lot), [code], NO_BARCODE_QR, []),
        (pallet_label(pallet), [], NO_BARCODE_SSCC, sscc),
    ):
        printed = zpl_printed(label)  # eski kodda code128 == ["LOT:LOT^1"]
        assert printed["code128"] == [] and printed["qr"] == qr
        assert lot.lot_no in printed["text"] and note in printed["text"]
        assert internal_barcodes(label) == [] and gs1_barcodes(label) == gs1
        assert note in texts(label) and qr_codes(label) == qr
    assert decode_scan(code).lots == [lot]


def test_case_count_beyond_eight_digits_gets_the_internal_barcode(make_user, admin) -> None:
    """(37) koli sayısı alanı en çok 8 hanedir: sınırdan önce açılmış palet kaydındaki daha büyük
    sayı GS1-128'e girmez; palet etiketi GTIN'siz malzemedeki gibi firma içi `LOT:` taşır, sayı
    yazı olarak basılır."""
    enable_gs1(admin)
    actor = make_user(DEPO)
    lot = finished_lot(finished(case_gtin=CASE_GTIN))
    largest = pallet_label(services.create_pallet_label(actor, lot, 99_999_999))
    assert gs1_barcodes(largest)[0] == f"{FNC1}02{CASE_GTIN}3799999999"

    pallet = legacy_pallet(actor, lot, 100_000_000)
    printed = pallet_label(pallet)
    assert gs1_barcodes(printed) == [f"{FNC1}00{pallet.sscc}"]
    assert zpl_gs1_fields(printed) == [f"(00){pallet.sscc}"]
    plain = finished_lot(finished(gtin=""))
    expected = pallet_label(legacy_pallet(actor, plain, 100_000_000))
    assert internal_barcodes(printed) == internal_barcodes(expected)
    assert "100000000" in texts(printed) and CASE_GTIN in texts(printed)


def test_case_count_over_eight_digits_is_rejected(client_for, make_user, admin) -> None:
    """(37) koli sayısı alanı en çok 8 hanedir: daha büyük koli sayısıyla palet etiketi açılmaz
    (etiket GS1 içerik barkodlarını sessizce düşürürdü); SSCC harcanmaz."""
    enable_gs1(admin)
    lot = finished_lot(finished(case_gtin=CASE_GTIN))
    message = "Koli sayısı en çok 99.999.999 olabilir."
    with pytest.raises(BusinessRuleError) as exc:
        services.create_pallet_label(make_user(DEPO), lot, 100_000_000)
    assert exc.value.code == "invalid_case_count" and exc.value.message == message

    client = client_for(DOLUM)
    denied = client.post(PALLETS, {"lot": lot.pk, "case_count": 100_000_000, "units_per_case": 12})
    assert denied.status_code == 400
    assert denied.json() == {"code": "invalid_case_count", "detail": message}
    assert not PalletLabel.objects.exists()
    assert masterdata.get_label_settings().next_sscc_serial == 1  # SSCC harcanmadı
    created = client.post(PALLETS, {"lot": lot.pk, "case_count": 99_999_999})
    assert created.status_code == 201, created.json()
    assert created.json()["case_count"] == 99_999_999


def test_zpl_prints_lot_numbers_with_command_characters_unchanged(make_user, admin) -> None:
    """ZPL'de "^" ve "~" komut önekidir: eskiden boşluğa çevrilirdi (A^B lotu LOT:A B okuturdu:
    lot bulunamaz ya da başka lot çıkar). Lot no yazı, Code128 ve QR alanlarında onaltılık kaçışla
    gider; lot, koli ve palet etiketinde yazıcının kodladığı barkod lotun kendisini okutur."""
    enable_gs1(admin)
    lot = finished_lot(finished(case_gtin=CASE_GTIN), lot_no="A^B~C\\12")
    code = "LOT:A^B~C\\12"
    pallet = services.create_pallet_label(make_user(DEPO), lot, 10)
    for label, qr in (
        (lot_label(lot), [code]),
        (case_label(lot), [code]),  # GS1 kümesinde olmayan lot no: firma içi barkod
        (pallet_label(pallet), []),
    ):
        printed = zpl_printed(label)
        assert lot.lot_no in printed["text"]
        assert printed["code128"] == [code] and printed["qr"] == qr
    assert decode_scan(code).lots == [lot]


# --- SSCC --------------------------------------------------------------------------------------


def test_pallet_sscc_source_is_registered_by_the_inventory_app(monkeypatch) -> None:
    """Basılmış palet SSCC'lerinin kaynağı `InventoryConfig.ready()`'de kaydedilir; başka bir
    modülün `inventory.services`'i import etmesine bağlı değildir."""
    assert services.highest_pallet_sscc in masterdata._sscc_sources  # açılışta kayıtlı
    monkeypatch.setattr(masterdata, "_sscc_sources", [])
    django_apps.get_app_config("inventory").ready()
    assert masterdata._sscc_sources == [services.highest_pallet_sscc]


def test_switching_back_to_an_old_prefix_does_not_reuse_ssccs(make_user, admin) -> None:
    actor = make_user(DEPO)
    lot = finished_lot(finished())
    enable_gs1(admin)
    first = [services.create_pallet_label(actor, lot, 10).sscc for _ in range(3)]
    assert [code[8:17] for code in first] == ["000000001", "000000002", "000000003"]

    enable_gs1(admin, "8697777")
    assert masterdata.get_gs1_settings().next_sscc_serial == 1
    other = services.create_pallet_label(actor, lot, 10).sscc
    assert other.startswith("08697777") and other[8:17] == "000000001"

    enable_gs1(admin)  # eski öneke dönüş: basılmış en büyük seri no + 1
    assert masterdata.get_gs1_settings().next_sscc_serial == 4
    again = services.create_pallet_label(actor, lot, 10).sscc
    assert again[8:17] == "000000004" and again not in first

    # Uzantı hanesi değişince o uzantıyla basılmış SSCC yok: 1'den başlar.
    masterdata.update_gs1_settings(admin, note="Uzantı", extension_digit=1)
    assert masterdata.get_gs1_settings().next_sscc_serial == 1
    assert services.create_pallet_label(actor, lot, 10).sscc.startswith("18691234")
    codes = list(PalletLabel.objects.values_list("sscc", flat=True))
    assert len(codes) == len(set(codes)) == 6


def test_next_sscc_skips_printed_ssccs_when_the_counter_is_behind(make_user, admin) -> None:
    actor = make_user(DEPO)
    lot = finished_lot(finished())
    enable_gs1(admin)
    printed = [services.create_pallet_label(actor, lot, 10).sscc for _ in range(2)]
    # Eski veri: önek etiket ayarlarından değiştirilip geri alınmış, sayaç geride kalmış.
    LabelSettings.objects.update(next_sscc_serial=1)
    third = services.create_pallet_label(actor, lot, 10)
    assert third.sscc[8:17] == "000000003" and third.sscc not in printed
    assert masterdata.get_label_settings().next_sscc_serial == 4


def test_ssccs_of_an_overlapping_prefix_are_not_reused(make_user, admin) -> None:
    """6 haneli önekle basılmış bir SSCC, 7 haneli önekin bir seri numarasıyla aynı 18 haneyi
    taşıyabilir: o seri no da atlanır."""
    lot = finished_lot(finished())
    body = "0" + "869123" + "4000000001"  # = "0" + "8691234" + "000000001"
    PalletLabel.objects.create(sscc=body + gs1_check_digit(body), lot=lot, case_count=5)
    enable_gs1(admin)
    assert masterdata.get_gs1_settings().next_sscc_serial == 2
    pallet = services.create_pallet_label(make_user(DEPO), lot, 10)
    assert pallet.sscc[8:17] == "000000002"


def test_sscc_exhausted_is_still_reported(make_user, admin) -> None:
    prefix = "869123456789"  # 12 haneli önek: seri no 4 hane
    lot = finished_lot(finished())
    body = "0" + prefix + "9999"
    PalletLabel.objects.create(sscc=body + gs1_check_digit(body), lot=lot, case_count=1)
    enable_gs1(admin, prefix)
    assert masterdata.get_gs1_settings().next_sscc_serial == 10_000
    with pytest.raises(BusinessRuleError) as exc:
        services.create_pallet_label(make_user(DEPO), lot, 1)
    assert exc.value.code == "sscc_exhausted"
    assert PalletLabel.objects.count() == 1


# --- lotu olan malzemede GTIN kilidi (eski veriler) --------------------------------------------


def test_existing_material_with_gtin_and_lots_keeps_working(
    make_user, client_for, invariants
) -> None:
    planner = make_user(PLANLAMA)
    # Eski veri: kurallardan önce açılmış, GTIN'li ve stoklu mamul.
    material = finished()
    lot = stocked_lot("120", material=material, source=Lot.Source.FILLING)
    masterdata.update_record(planner, material, {"name": "Yeni ad", "min_stock": Decimal(10)})
    material.refresh_from_db()
    assert material.gtin == GTIN and material.name == "Yeni ad"
    for value in (OTHER_GTIN, ""):
        with pytest.raises(BusinessRuleError) as exc:
            masterdata.update_record(planner, material, {"gtin": value})
        assert exc.value.code == "gtin_locked"
        assert "değiştirilemez" in exc.value.message
    masterdata.update_record(planner, material, {"gtin": f" {GTIN} "})  # aynı GTIN: değişiklik yok

    # Koli GTIN'i boştan ilk kez girilir, sonra o da kilitlenir.
    case = masterdata.create_record(
        planner,
        MaterialUnitConversion,
        {"material": material, "unit": unit("KOLI"), "factor_to_base": Decimal(12), "gtin": ""},
    )
    case = masterdata.update_record(planner, case, {"gtin": CASE_GTIN})
    for value in (NEW_CASE_GTIN, ""):
        with pytest.raises(BusinessRuleError) as exc:
            masterdata.update_record(planner, case, {"gtin": value})
        assert exc.value.code == "gtin_locked"
    # Koli içi miktar yalnız yeni koli GTIN'iyle değişir (CUMHUR, 2026-11-05); eski GTIN eski
    # miktarıyla arşivlenir, önceden açılmış lotun etiketinde kalır.
    with pytest.raises(BusinessRuleError) as exc:
        masterdata.update_record(planner, case, {"factor_to_base": Decimal(24)})
    assert exc.value.code == "case_gtin_required"
    masterdata.update_record(planner, case, {"factor_to_base": Decimal(24), "gtin": NEW_CASE_GTIN})
    assert case_gs1(lot)[0] == ("01", CASE_GTIN)  # type: ignore[index]

    client = client_for(PLANLAMA)
    detail = client.get(f"{MATERIALS}{material.pk}/").json()
    assert detail["gtin_locked"] is True and detail["conversions"][0]["gtin_locked"] is True
    listed = client.get(MATERIALS, {"material_type": "FINISHED"}).json()["results"]
    assert [row["gtin_locked"] for row in listed] == [True]
    conversions = client.get("/api/v1/masterdata/conversions/", {"material": material.pk}).json()
    assert conversions["results"][0]["gtin_locked"] is True
    denied = client.patch(f"{MATERIALS}{material.pk}/", {"gtin": OTHER_GTIN}, format="json")
    assert denied.status_code == 400 and denied.json()["code"] == "gtin_locked"

    # GTIN'siz ama lotu olan malzemeye GTIN ilk kez girilebilir; sonra kilitlenir.
    blank = finished(gtin="")
    stocked_lot("10", material=blank, source=Lot.Source.FILLING)
    assert client.get(f"{MATERIALS}{blank.pk}/").json()["gtin_locked"] is False
    saved = client.patch(f"{MATERIALS}{blank.pk}/", {"gtin": OTHER_GTIN}, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["gtin"] == OTHER_GTIN and saved.json()["gtin_locked"] is True


def test_legacy_invalid_gtin_does_not_block_saving_and_can_be_corrected(
    make_user, invariants
) -> None:
    planner = make_user(PLANLAMA)
    # Eski veri: yönetim panelinden denetimsiz girilmiş, kontrol hanesi yanlış GTIN; lotu var.
    material = finished(gtin="8690000000013")
    stocked_lot("10", material=material, source=Lot.Source.FILLING)
    assert not masterdata.gtin_locked(material)  # okutulamayan GTIN kilitlenmez
    masterdata.update_record(planner, material, {"name": "Yeni ad"})  # öteki alanlar kaydedilir
    masterdata.update_record(planner, material, {"gtin": GTIN})  # düzeltme serbest
    material.refresh_from_db()
    assert material.gtin == GTIN and masterdata.gtin_locked(material)
    # Aynı GTIN'i 14 hane yazmak değişiklik sayılmaz; başka GTIN kilitli.
    masterdata.update_record(planner, material, {"gtin": "0" + GTIN})
    material.refresh_from_db()
    assert material.gtin == "0" + GTIN
    with pytest.raises(BusinessRuleError) as exc:
        masterdata.update_record(planner, material, {"gtin": OTHER_GTIN})
    assert exc.value.code == "gtin_locked"


# --- koli içi miktar değişikliği: lotun açıldığı andaki koli GTIN'i ------------------------------


def change_pack(actor, material: Material, factor: int, gtin: str) -> None:
    """Koli içi miktar yeni koli GTIN'iyle değişir; eski GTIN eski miktarıyla arşivlenir."""
    case = MaterialUnitConversion.objects.get(material=material, unit__code="KOLI")
    masterdata.update_record(actor, case, {"factor_to_base": Decimal(factor), "gtin": gtin})


def content_gtins(label: Label) -> list[str]:
    """Etiketteki GS1 içerik barkodlarının (01) ve (02) GTIN'leri (SSCC sayılmaz)."""
    return [
        value
        for element in label.elements
        if isinstance(element, Barcode) and element.gs1 is not None
        for ai, value in element.gs1
        if ai in ("01", "02")
    ]


def test_labels_carry_the_case_gtin_in_force_when_the_lot_was_made(
    make_user, admin, client_for, invariants
) -> None:
    """Önceden açılmış lotun koli ve palet etiketi yeniden basılınca da eski koli GTIN'ini taşır,
    sonra açılan lot yenisini; iki değişiklikte her lot kendi dönemindeki GTIN'le basılır."""
    enable_gs1(admin)
    planner, actor = make_user(PLANLAMA), make_user(DEPO)
    material = finished(case_gtin=CASE_GTIN)
    before = finished_lot(material, "D-261015-001")
    change_pack(planner, material, 24, NEW_CASE_GTIN)
    between = finished_lot(material, "D-261015-002")
    change_pack(planner, material, 36, THIRD_CASE_GTIN)
    after = finished_lot(material, "D-261015-003")
    gtins = (CASE_GTIN, NEW_CASE_GTIN, THIRD_CASE_GTIN)
    for made, gtin in zip((before, between, after), gtins, strict=True):
        lot = Lot.objects.get(pk=made.pk)  # yeniden basım: kayıt veritabanından
        others = set(gtins) - {gtin}
        case = case_label(lot)
        assert content_gtins(case) == [gtin]
        assert case_gs1(lot)[0] == ("01", gtin)  # type: ignore[index]
        assert zpl_gs1_fields(case) == [f"(01){gtin}(17)281015(10){lot.lot_no}"]
        assert gtin in texts(case) and not others & set(texts(case))
        pallet = pallet_label(services.create_pallet_label(actor, lot, 10))
        assert content_gtins(pallet) == [gtin]
        assert gs1_barcodes(pallet)[0] == f"{FNC1}02{gtin}3710"
        assert gtin in texts(pallet) and not others & set(texts(pallet))
    # Koli etiketi uç noktası da lotun dönemindeki GTIN'i basar.
    response = client_for(DOLUM).get(f"{LOTS}{before.pk}/case-label/", {"output": "zpl"})
    zpl = response.content.decode()
    assert f"^FD(01){CASE_GTIN}(17)281015(10)D-261015-001^FS" in zpl
    assert THIRD_CASE_GTIN not in zpl


def test_other_materials_keep_their_own_gtin_after_a_pack_change(
    make_user, admin, client_for, invariants
) -> None:
    """Bir mamulün koli içi miktar değişikliği başka malzemenin etiketine dokunmaz: değişiklikten
    önce açılmış öteki lotların koli ve palet etiketi kendi koli GTIN'ini, koli GTIN'i yoksa ürün
    GTIN'ini taşır; değişen mamulün arşivdeki eski koli GTIN'i onlara basılmaz."""
    enable_gs1(admin)
    planner, actor = make_user(PLANLAMA), make_user(DEPO)
    changed = finished(case_gtin=CASE_GTIN)
    finished_lot(changed, "D-261015-001")  # lotu var: koli GTIN'i kilitli
    other = finished(OTHER_GTIN, case_gtin="18690000000026")
    plain = finished("8690000000036")  # koli GTIN'i yok: ürün GTIN'i basılır
    lots = [
        (finished_lot(other, "D-261015-002"), "18690000000026"),
        (finished_lot(plain, "D-261015-003"), "08690000000036"),
    ]
    change_pack(planner, changed, 24, NEW_CASE_GTIN)
    assert RetiredGtin.objects.get().gtin == CASE_GTIN
    client = client_for(DOLUM)
    for made, gtin in lots:
        lot = Lot.objects.get(pk=made.pk)  # yeniden basım: kayıt veritabanından
        assert case_gs1(lot)[0] == ("01", gtin)  # type: ignore[index]
        case = case_label(lot)
        assert content_gtins(case) == [gtin]
        assert gtin in texts(case) and CASE_GTIN not in texts(case)
        pallet = pallet_label(services.create_pallet_label(actor, lot, 10))
        assert content_gtins(pallet) == [gtin]
        assert gtin in texts(pallet) and CASE_GTIN not in texts(pallet)
        zpl = client.get(f"{LOTS}{lot.pk}/case-label/", {"output": "zpl"}).content.decode()
        assert f"^FD(01){gtin}(17)281015(10){lot.lot_no}^FS" in zpl
        assert CASE_GTIN not in zpl


def test_label_fallbacks_still_apply_after_a_pack_change(make_user, admin, invariants) -> None:
    """2. turun kuralları: (10) alanına uymayan lot noda firma içi `LOT:` basılır, lotun
    dönemindeki koli GTIN'i yazı olarak kalır. Geçersiz (okutulamayan eski) koli GTIN'i basılmaz ve
    ürün GTIN'ine düşmez; kilitlenmediği için miktarı da GTIN'i de değişir, arşive düşmez. Koli
    GTIN'i olmayan malzemede ürün GTIN'i basılır."""
    enable_gs1(admin)
    planner, actor = make_user(PLANLAMA), make_user(DEPO)
    material = finished(case_gtin=CASE_GTIN)
    odd = finished_lot(material, "LOT 12")
    change_pack(planner, material, 24, NEW_CASE_GTIN)
    for label in (case_label(odd), pallet_label(services.create_pallet_label(actor, odd, 10))):
        assert content_gtins(label) == []
        assert [barcode.data for barcode in internal_barcodes(label)] == ["LOT:LOT 12"]
        assert CASE_GTIN in texts(label) and NEW_CASE_GTIN not in texts(label)

    legacy = finished(OTHER_GTIN, case_gtin="18690000000027")  # kontrol hanesi yanlış eski veri
    old = finished_lot(legacy, "D-261015-004")
    case = MaterialUnitConversion.objects.get(material=legacy)
    masterdata.update_record(planner, case, {"factor_to_base": Decimal(24)})  # kilitli değil
    assert case_gs1(old) is None and "GTIN" not in texts(case_label(old))
    masterdata.update_record(planner, case, {"gtin": "18690000000026"})  # düzeltme serbest
    assert not RetiredGtin.objects.filter(conversion=case).exists()
    assert case_gs1(old)[0] == ("01", "18690000000026")  # type: ignore[index]

    plain = finished_lot(finished("8690000000036"), "D-261015-005")
    assert case_gs1(plain)[0] == ("01", "08690000000036")  # type: ignore[index]


def test_lot_gs1_flag_matches_the_labels_after_a_pack_change(
    make_user, admin, client_for, invariants
) -> None:
    """`LotSerializer.gs1_label` (ön yüzün etiket ipucu) bugünkü koli GTIN'iyle hesaplanır; etiket
    lotun dönemindeki koli GTIN'ini basar. Arşivlenen koli GTIN'i her zaman geçerli olduğundan
    (yalnız kilitli, geçerli GTIN arşivlenir) ikisi aynı sonucu verir."""
    enable_gs1(admin)
    material = finished(case_gtin=CASE_GTIN)
    lots = [finished_lot(material, "D-261015-001"), finished_lot(material, "LOT 12")]
    change_pack(make_user(PLANLAMA), material, 24, NEW_CASE_GTIN)
    lots.append(finished_lot(material, "D-261015-002"))

    def gs1_on_labels(lot: Lot) -> bool:
        pallet = PalletLabel(sscc="0" * 18, lot=lot, case_count=10)  # kaydedilmez, yalnız çizilir
        printed = [content_gtins(case_label(lot)), content_gtins(pallet_label(pallet))]
        assert printed[0] == printed[1]
        return bool(printed[0])

    expected = {lot.pk: gs1_on_labels(lot) for lot in lots}
    assert list(expected.values()) == [True, False, True]
    rows = client_for(DEPO).get(LOTS).json()["results"]
    assert {row["id"]: row["gs1_label"] for row in rows} == expected
    for lot in lots:
        assert LotSerializer(Lot.objects.get(pk=lot.pk)).data["gs1_label"] is expected[lot.pk]
