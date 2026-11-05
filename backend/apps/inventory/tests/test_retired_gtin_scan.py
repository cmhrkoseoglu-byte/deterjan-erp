"""Eski koli GTIN'inin okutulması (GS1, CUMHUR 2026-11-05 "Yeni koli GTIN'iyle"): lotu olan mamulde
koli içi miktar değişince koliye yeni GTIN verilir, eski GTIN eski miktarıyla arşivlenir
(`masterdata.RetiredGtin`). Depodaki eski koliler okutulmaya devam eder: (01), (02) ve çıplak GTIN
malzemeyi arşivden bulur (önce ürün, sonra güncel koli GTIN'i, sonra arşiv), koli içi miktar eski
koli düzenidir ve uyarı bunu söyler; (10) lotu üretim, dolum ve sevkiyatın ortak lot çözümünde
(`resolve_lot`) güncel koli GTIN'indeki gibi bulunur.

Arşiv satırları testte doğrudan yazılır (yazan servis `masterdata.services`'tedir)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.labels import gtin14
from apps.inventory import services
from apps.inventory.api.serializers import ScanResultSerializer
from apps.inventory.models import Lot
from apps.inventory.selectors import decode_scan, resolve_lot
from apps.masterdata.models import Material, MaterialUnitConversion, RetiredGtin
from apps.masterdata.tests.factories import MaterialFactory, unit

pytestmark = pytest.mark.usefixtures("invariants")

GS = "\x1d"
TODAY = date(2026, 11, 5)
GTIN = "8690000000012"  # ürün GTIN'i (GTIN-13)
NEW_CASE = "28690000000016"  # güncel koli GTIN'i: 1 koli = 12 ADET
OLD_CASE = "18690000000019"  # eski koli GTIN'i (arşivde): 1 koli = 6 ADET'ti
UNKNOWN = "48690000000010"  # geçerli GTIN, ne güncel ne arşivde
LOT_NO = "D-261015-001"
SCAN = "/api/v1/inventory/scan/"
LOTS = "/api/v1/inventory/lots/"


def warning(quantity: str, unit_code: str = "ADET") -> str:
    """Eski koli GTIN'i uyarısı (sözleşmedeki metin)."""
    return (
        "Eski koli GTIN'i okutuldu: koli düzeni değişti; "
        f"bu kolide 1 koli = {quantity} {unit_code}."
    )


OLD_WARNING = warning("6")


def finished_product(
    case_gtin: str, factor: str = "12", *, gtin: str = "", base_unit: str = "ADET"
) -> tuple[Material, MaterialUnitConversion]:
    """Mamul ve güncel koli GTIN'li KOLI dönüşümü (doğrudan, denetimsiz)."""
    material = MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit(base_unit), gtin=gtin
    )
    conversion = MaterialUnitConversion.objects.create(
        material=material, unit=unit("KOLI"), factor_to_base=Decimal(factor), gtin=case_gtin
    )
    return material, conversion


def retire(
    conversion: MaterialUnitConversion, gtin: str, factor: str, replaced_by: str
) -> RetiredGtin:
    """Arşiv satırı, servisin yazdığı gibi: 14 haneli normal biçim, eski koli içi miktar."""
    return RetiredGtin.objects.create(
        conversion=conversion,
        gtin=gtin14(gtin),
        factor_to_base=Decimal(factor),
        replaced_by=gtin14(replaced_by),
    )


def finished_lot(material: Material, lot_no: str = LOT_NO) -> Lot:
    """Koli düzeni değişmeden önce yapılmış lot (SKT 15.10.2028)."""
    return services.create_lot(
        None,
        material=material,
        source=Lot.Source.FILLING,
        lot_no=lot_no,
        manufactured_at=date(2026, 10, 15),
        expiry_date=date(2028, 10, 15),
    )


@pytest.fixture
def product() -> Material:
    """Mamul (ADET), ürün GTIN'i; koli düzeni 1 koli = 6 ADET'ten 12 ADET'e değişti: güncel koli
    GTIN'i `NEW_CASE`, eski `OLD_CASE` arşivde."""
    material, conversion = finished_product(NEW_CASE, "12", gtin=GTIN)
    retire(conversion, OLD_CASE, "6", NEW_CASE)
    return material


def test_archived_case_gtin_scans_with_its_old_quantity(product: Material) -> None:
    lot = finished_lot(product)
    case = decode_scan(f"(01){OLD_CASE}(17)281015(10){LOT_NO}", today=TODAY)
    assert (case.kind, case.lots, case.material) == ("lot", [lot], product)
    assert (case.unit, case.units_per_case) == ("KOLI", Decimal("6"))
    assert (case.warnings, case.gs1_dates) == ([OLD_WARNING], {"17": "2028-10-15"})
    raw_case = decode_scan(f"]C101{OLD_CASE}17281015" + f"10{LOT_NO}", today=TODAY)
    assert (raw_case.lots, raw_case.unit, raw_case.units_per_case) == ([lot], "KOLI", Decimal("6"))
    assert raw_case.warnings == [OLD_WARNING]
    # Lotsuz eski koli barkodu, eski palet etiketinin (02)+(37) barkodu, çıplak GTIN (ITF-14).
    for code in (f"(01){OLD_CASE}", f"(02){OLD_CASE}(37)40", OLD_CASE):
        found = decode_scan(code)
        assert (found.kind, found.material, found.unit, found.units_per_case) == (
            "material",
            product,
            "KOLI",
            Decimal("6"),
        ), code
        assert found.warnings == [OLD_WARNING], code
    pallet = decode_scan(f"(02){OLD_CASE}(37)40(10){LOT_NO}")
    assert (pallet.kind, pallet.lots, pallet.units_per_case) == ("lot", [lot], Decimal("6"))
    # Güncel koli GTIN'i güncel miktarı verir; ürün GTIN'i koli birimi vermez (ikisi de uyarısız).
    current = decode_scan(f"(01){NEW_CASE}(10){LOT_NO}")
    assert (current.lots, current.unit, current.units_per_case) == ([lot], "KOLI", Decimal("12"))
    assert current.warnings == []
    item = decode_scan(f"(01)0{GTIN}(10){LOT_NO}")
    assert (item.lots, item.unit, item.units_per_case, item.warnings) == ([lot], "", None, [])
    # Malzemede olmayan lot eski koli barkoduyla da bulunmaz.
    with pytest.raises(BusinessRuleError) as error:
        decode_scan(f"(01){OLD_CASE}(10)YOK-1")
    assert (error.value.code, error.value.message) == (
        "scan_not_found",
        f"{product.code} malzemesinde YOK-1 lotu bulunamadı.",
    )


@pytest.mark.parametrize(
    ("factor", "text", "base_unit"),
    [("6", "6", "ADET"), ("2.5", "2,5", "KG"), ("120", "120", "ADET"), ("0.75", "0,75", "LT")],
)
def test_warning_gives_the_old_quantity_in_turkish(factor: str, text: str, base_unit: str) -> None:
    """Uyarıdaki miktar sondaki sıfırlar olmadan, ondalık virgülle; birim temel birimdir."""
    material, conversion = finished_product(NEW_CASE, "12", base_unit=base_unit)
    retire(conversion, OLD_CASE, factor, NEW_CASE)
    found = decode_scan(f"(01){OLD_CASE}")
    assert (found.material, found.units_per_case) == (material, Decimal(factor))
    assert found.warnings == [
        f"Eski koli GTIN'i okutuldu: koli düzeni değişti; bu kolide 1 koli = {text} {base_unit}."
    ]


def test_archived_quantity_holds_when_the_conversion_is_inactive(product: Material) -> None:
    """Dönüşüm sonradan pasif olsa da eski koli GTIN'i eski koli içi miktarını verir (geçmiş
    geçerlidir); "koli içi miktar önerilmez" uyarısı yalnızca güncel koli GTIN'indedir."""
    lot = finished_lot(product)
    MaterialUnitConversion.objects.filter(material=product).update(is_active=False)
    codes = [f"(01){OLD_CASE}(10){LOT_NO}", f"(01){OLD_CASE}", f"(02){OLD_CASE}(37)40", OLD_CASE]
    for code in codes:
        found = decode_scan(code)
        assert (found.material, found.unit, found.units_per_case) == (
            product,
            "KOLI",
            Decimal("6"),
        ), code
        assert found.warnings == [OLD_WARNING], code
    assert decode_scan(codes[0]).lots == [lot]
    current = decode_scan(f"(01){NEW_CASE}(10){LOT_NO}")
    assert (current.lots, current.unit, current.units_per_case) == ([lot], "", None)
    assert current.warnings == ["Bu koli GTIN'inin dönüşümü pasif; koli içi miktar önerilmez."]


def test_archived_gtin_13_scans_as_gtin_13_and_as_gtin_14() -> None:
    """Eski koli GTIN'i GTIN-13 olarak girilmişti (arşivde 14 haneli normal biçimi): EAN-13
    barkodu, ITF-14 / GTIN-14 hâli ve GS1 (01)/(02) alanı aynı arşiv kaydını bulur."""
    old_13 = "8690000000029"
    material, conversion = finished_product(NEW_CASE, "12")
    assert retire(conversion, old_13, "6", NEW_CASE).gtin == f"0{old_13}"
    lot = finished_lot(material)
    for code in (old_13, f"0{old_13}", f"(01)0{old_13}", f"]C1010{old_13}", f"(02)0{old_13}(37)40"):
        found = decode_scan(code)
        assert (found.kind, found.material, found.unit, found.units_per_case) == (
            "material",
            material,
            "KOLI",
            Decimal("6"),
        ), code
        assert found.warnings == [OLD_WARNING], code
    for code in (f"(01)0{old_13}(10){LOT_NO}", f"]C1010{old_13}10{LOT_NO}"):
        assert decode_scan(code).lots == [lot], code
        assert resolve_lot(code, materials=[material.pk]) == lot, code


def test_expiry_warning_comes_with_the_archived_gtin_warning(product: Material) -> None:
    """Barkoddaki SKT (17) lot kaydındakinden farklıysa iki uyarı birlikte: önce eski koli GTIN'i,
    sonra SKT."""
    lot = finished_lot(product)
    expiry = "Barkoddaki SKT (16.10.2028) lot kaydındaki SKT'den (15.10.2028) farklı."
    for code in (
        f"(01){OLD_CASE}(17)281016(10){LOT_NO}",
        f"]C101{OLD_CASE}17281016" + f"10{LOT_NO}",
    ):
        found = decode_scan(code, today=TODAY)
        assert (found.lots, found.units_per_case) == ([lot], Decimal("6")), code
        assert found.warnings == [OLD_WARNING, expiry], code
    assert decode_scan(f"(01){OLD_CASE}(17)281015(10){LOT_NO}").warnings == [OLD_WARNING]
    Lot.objects.filter(pk=lot.pk).update(expiry_date=None)
    assert decode_scan(f"(01){OLD_CASE}(17)281015(10){LOT_NO}").warnings == [
        OLD_WARNING,
        "Barkoddaki SKT (15.10.2028) lot kaydında yok.",
    ]


def test_two_pack_changes_each_archived_gtin_keeps_its_quantity() -> None:
    """Koli düzeni iki kez değişti (1 koli = 6 → 12 → 24 ADET): her eski GTIN kendi koli içi
    miktarını verir, güncel GTIN güncel miktarı (uyarısız)."""
    first, second, third = "18690000000026", "28690000000023", "38690000000020"
    material, conversion = finished_product(third, "24")
    retire(conversion, first, "6", second)
    retire(conversion, second, "12", third)
    lot = finished_lot(material)
    for gtin, quantity, warnings in (
        (first, "6", [warning("6")]),
        (second, "12", [warning("12")]),
        (third, "24", []),
    ):
        for code in (f"(01){gtin}(10){LOT_NO}", f"(02){gtin}(37)40(10){LOT_NO}"):
            found = decode_scan(code)
            assert (found.lots, found.unit, found.units_per_case) == (
                [lot],
                "KOLI",
                Decimal(quantity),
            ), code
            assert found.warnings == warnings, code
        bare = decode_scan(gtin)
        assert (bare.material, bare.units_per_case, bare.warnings) == (
            material,
            Decimal(quantity),
            warnings,
        ), gtin


def test_gtin_neither_current_nor_archived_is_not_found(product: Material) -> None:
    """Ne güncel ne arşivde olan GTIN önceki gibi bulunmaz (`scan_not_found`, aynı mesajlar);
    yanındaki eski koli GTIN'i arşivden bulunur."""
    finished_lot(product)
    assert decode_scan(f"(01){OLD_CASE}(10){LOT_NO}").units_per_case == Decimal("6")
    messages = {
        f"(01){UNKNOWN}": f"Bu GTIN ile kayıtlı malzeme yok: {UNKNOWN}.",
        f"(02){UNKNOWN}(37)40": f"Bu GTIN ile kayıtlı malzeme yok: {UNKNOWN}.",
        f"(01){UNKNOWN}(10){LOT_NO}": f"Bu GTIN ile kayıtlı malzeme yok: {UNKNOWN}.",
        UNKNOWN: f"Okutulan kod tanınmadı: {UNKNOWN}.",
    }
    for code, message in messages.items():
        with pytest.raises(BusinessRuleError) as error:
            decode_scan(code)
        assert (error.value.code, error.value.message) == ("scan_not_found", message), code
        assert resolve_lot(code) is None, code


def test_current_owner_comes_before_the_archive() -> None:
    """Sıra: ürün GTIN'i, güncel koli GTIN'i, sonra arşiv ((02)'de önce güncel koli GTIN'i).
    Servisler arşivdeki GTIN'i bir daha vermez; tutarsız eski veride güncel sahip kazanır."""
    item_gtin, case_gtin = "8690000000036", "38690000000013"
    material, conversion = finished_product(NEW_CASE, "12")
    item = MaterialFactory.create(material_type=Material.Type.FINISHED, gtin=item_gtin)
    boxed, _ = finished_product(case_gtin, "24")
    retire(conversion, item_gtin, "6", NEW_CASE)
    retire(conversion, case_gtin, "8", NEW_CASE)
    retire(conversion, OLD_CASE, "10", NEW_CASE)
    for code in (f"(01)0{item_gtin}", f"(02)0{item_gtin}(37)40", item_gtin):
        found = decode_scan(code)
        assert (found.material, found.unit, found.warnings) == (item, "", []), code
    for code in (f"(01){case_gtin}", f"(02){case_gtin}(37)40", case_gtin):
        found = decode_scan(code)
        assert (found.material, found.units_per_case, found.warnings) == (
            boxed,
            Decimal("24"),
            [],
        ), code
    # Yalnızca arşivde olan GTIN arşivden çözülür.
    archived = decode_scan(f"(01){OLD_CASE}")
    assert (archived.material, archived.units_per_case) == (material, Decimal("10"))
    assert archived.warnings == [warning("10")]


def test_resolve_lot_finds_the_lot_of_an_archived_case(product: Material) -> None:
    """Üretim, dolum ve sevkiyatın ortak lot çözümü eski koli barkodundaki lotu güncel koli
    GTIN'indeki gibi bulur: GTIN malzemeyi belirler, aynı lot no başka malzemede olsa da."""
    lot = finished_lot(product)
    other_material = MaterialFactory.create()
    services.create_lot(None, material=other_material, source=Lot.Source.PURCHASE, lot_no=LOT_NO)
    both = [product.pk, other_material.pk]
    codes = [
        f"(01){OLD_CASE}(10){LOT_NO}",
        f"(01){OLD_CASE}(17)281015(10){LOT_NO.lower()}",
        f"]C101{OLD_CASE}10{LOT_NO}{GS}17281015",
        f"01{OLD_CASE}10{LOT_NO}",  # AIM'siz, GS'siz ham veri
        f"{GS}01{OLD_CASE}10{LOT_NO}",
        f"\xa0(01){OLD_CASE}(10){LOT_NO}\x1e",
        f"(02){OLD_CASE}(37)40(10){LOT_NO}",
    ]
    for code in codes:
        assert resolve_lot(code) == lot, code
        # Üretim: yalnızca ihtiyacın malzemesindeki lot.
        assert resolve_lot(code, materials=[product.pk]) == lot, code
        assert resolve_lot(code, materials=[other_material.pk]) is None, code
        # Dolum: verilen malzemelerde yoksa o lot döner (servis "yanlış malzeme" der).
        assert resolve_lot(code, materials=[other_material.pk], restrict=False) == lot, code
        # Sevkiyat: iki üründe aynı lot no olsa da GTIN ürünü belirler (`ambiguous_lot` yok).
        assert resolve_lot(code, materials=both, restrict=False, unique=True) == lot, code
    # Lot no tek başına iki malzemede belirsizdir; lotsuz koli barkodu ve bilinmeyen lot lot değil.
    with pytest.raises(BusinessRuleError) as error:
        resolve_lot(LOT_NO, materials=both, restrict=False, unique=True)
    assert error.value.code == "ambiguous_lot"
    for code in (f"(01){OLD_CASE}", OLD_CASE, f"(01){OLD_CASE}(10)YOK-1"):
        assert resolve_lot(code, materials=[product.pk]) is None, code


def test_scan_api_returns_the_old_case_quantity(client_for, product: Material) -> None:
    """Okutma yanıtı: eski koli içi miktar (`units_per_case`), koli birimi ve uyarı; lotun
    `material_case_gtin`'i güncel koli GTIN'i kalır."""
    lot = finished_lot(product)
    client = client_for("depo")
    response = client.get(SCAN, {"code": f"(01){OLD_CASE}(17)281015(10){LOT_NO}"})
    assert response.status_code == 200, response.json()
    body = response.json()
    assert (body["kind"], [row["id"] for row in body["lots"]]) == ("lot", [lot.pk])
    assert (body["unit"], body["units_per_case"], body["warnings"]) == (
        "KOLI",
        "6.0000",
        [OLD_WARNING],
    )
    assert body["material"]["base_unit_code"] == "ADET"
    case = client.get(SCAN, {"code": OLD_CASE}).json()
    assert (case["kind"], case["unit"], case["units_per_case"]) == ("material", "KOLI", "6.0000")
    current = client.get(SCAN, {"code": f"(01){NEW_CASE}(10){LOT_NO}"}).json()
    assert (current["unit"], current["units_per_case"], current["warnings"]) == (
        "KOLI",
        "12.0000",
        [],
    )
    missing = client.get(SCAN, {"code": f"(01){UNKNOWN}"})
    assert (missing.status_code, missing.json()["code"]) == (400, "scan_not_found")
    assert client.get(f"{LOTS}{lot.pk}/").json()["material_case_gtin"] == NEW_CASE
    assert APIClient().get(SCAN, {"code": OLD_CASE}).status_code in (401, 403)


def test_archived_case_scan_serializes_without_queries(
    product: Material, django_assert_num_queries
) -> None:
    """Eski koli GTIN'inin malzemesi temel birimiyle yüklenir: yanıt sorgusuz seri hale gelir."""
    finished_lot(product)
    codes = [
        f"(01){OLD_CASE}",
        f"(02){OLD_CASE}(37)40",
        OLD_CASE,
        f"(01){OLD_CASE}(10){LOT_NO}",
        f"]C101{OLD_CASE}10{LOT_NO}",
    ]
    for code in codes:
        result = decode_scan(code)
        with django_assert_num_queries(0):
            data = ScanResultSerializer(result).data
        assert (data["material"]["base_unit_code"], data["unit"]) == ("ADET", "KOLI"), code
