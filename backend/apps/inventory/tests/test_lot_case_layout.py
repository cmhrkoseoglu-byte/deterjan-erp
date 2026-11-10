"""Lotun koli düzeni (CUMHUR, 2026-11-05, "lotun koli düzeniyle"; Paket 2 incelemesi arka-2,
gs1-1, belge-1): mamul lotu açılırken KOLI dönüşümünün koli içi miktarı ve koli GTIN'i lota yazılır
(`Lot.case_factor`, `Lot.case_gtin`). Koli ve palet etiketi, lot API'si ve irsaliye bunu kullanır:
koli düzeni sonra nasıl değişirse değişsin (koli GTIN'i olmayan mamulde koli içi miktar, ilk kez
girilen koli GTIN'i, kilitli koli GTIN'inde yeni GTIN'le koli düzeni değişikliği, pasife alınan
KOLI dönüşümü) önceden açılmış lotunki değişmez. Var olan lotlar göçle doldurulur (inventory 0008).
Lot açılırken KOLI dönüşümü kilitlenir: var olan KOLI dönüşümündeki değişiklik açılmakta olan lotla
yarışmaz.
Koli düzeni değişiklikleri planlamanın API'siyle yapılır; irsaliye testleri
`sales/tests/test_shipments.py`'dedir."""

import importlib
import re
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.labels import gs1_check_digit
from apps.core.models import AuditLog, User
from apps.core.roles import ADMIN, DEPO, DOLUM, PLANLAMA
from apps.inventory import services
from apps.inventory.api.serializers import LotSerializer
from apps.inventory.models import Lot
from apps.inventory.selectors import RETIRED_CASE_WARNING, decode_scan
from apps.inventory.tests.test_gs1_labels import enable_gs1
from apps.masterdata import services as masterdata
from apps.masterdata.models import Material, MaterialUnitConversion, RetiredGtin, UnitOfMeasure
from apps.masterdata.tests.factories import MaterialFactory, unit
from apps.masterdata.tests.test_gs1 import _bound_lock_waits, _count_units

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

migration = importlib.import_module("apps.inventory.migrations.0008_lot_case_layout")

D = Decimal
LOTS = "/api/v1/inventory/lots/"
PALLETS = "/api/v1/inventory/pallet-labels/"
CONVERSIONS = "/api/v1/masterdata/conversions/"
GTIN = "8690000000012"  # ürün GTIN'i
ITEM = f"0{GTIN}"  # ürün GTIN'i 14 hane: koli GTIN'i yokken koli ve palet etiketine basılır
CASE_GTIN = "18690000000019"
NEW_CASE_GTIN = "28690000000016"
PACKAGING = Material.Type.PACKAGING  # tedarikçiden gelen ambalaj: lotuna koli düzeni yazılmaz
# Okutulan koli etiketi: (17) SKT 15.10.2028, (10) lot no.
CASE_BARCODE = "(01){gtin}(17)281015(10){lot_no}"


def gtin14(body: str) -> str:
    """13 haneli gövdeye kontrol hanesi: geçerli GTIN-14."""
    return body + gs1_check_digit(body)


def product(
    gtin: str = GTIN,
    *,
    case_gtin: str | None = "",
    factor: str = "12",
    base_unit: str = "ADET",
    active: bool = True,
    material_type: str = Material.Type.FINISHED,
) -> Material:
    """Malzeme ve (`case_gtin` None değilse) KOLI dönüşümü, 1 koli = `factor` temel birim
    (kurulum doğrudan; koli düzeni değişiklikleri testte servisle ya da API'yle)."""
    material = MaterialFactory.create(
        material_type=material_type, base_unit=unit(base_unit), gtin=gtin
    )
    if case_gtin is not None:
        MaterialUnitConversion.objects.create(
            material=material,
            unit=unit("KOLI"),
            factor_to_base=D(factor),
            gtin=case_gtin,
            is_active=active,
        )
    return material


def open_lot(material: Material, lot_no: str, actor: User | None = None) -> Lot:
    """Lot açılır (`create_lot`, tek yol): mamulde dolum lotu, ötekinde satın alma lotu."""
    finished = material.material_type == Material.Type.FINISHED
    return services.create_lot(
        actor,
        material=material,
        source=Lot.Source.FILLING if finished else Lot.Source.PURCHASE,
        lot_no=lot_no,
        manufactured_at=date(2026, 10, 15),
        expiry_date=date(2028, 10, 15),
    )


def layout(lot: Lot) -> tuple[Decimal | None, str]:
    """Lotun kayıtlı koli düzeni (veritabanından): (koli içi miktar, koli GTIN'i)."""
    return Lot.objects.values_list("case_factor", "case_gtin").get(pk=lot.pk)


def change_case(client: APIClient, case: MaterialUnitConversion, data: dict) -> None:
    """Planlama KOLI dönüşümünü değiştirir (API → `masterdata.services.update_record`)."""
    response = client.patch(f"{CONVERSIONS}{case.pk}/", data, format="json")
    assert response.status_code == 200, response.json()


def printed_gtins(client: APIClient, lot: Lot) -> list[str]:
    """Lotun API'den yeniden basılan koli ve palet etiketindeki GS1 içerik GTIN'leri: koli
    etiketinin (01) ve yeni palet etiketinin (02) alanı (ZPL)."""
    case = client.get(f"{LOTS}{lot.pk}/case-label/", {"output": "zpl"})
    created = client.post(PALLETS, {"lot": lot.pk, "case_count": 10})
    assert case.status_code == 200 and created.status_code == 201, created.json()
    pallet = client.get(f"{PALLETS}{created.json()['id']}/label/", {"output": "zpl"})
    zpl = case.content.decode() + pallet.content.decode()
    return re.findall(r"\^FD\((?:01|02)\)(\d{14})", zpl)


def api_layout(client: APIClient, lots: list[Lot]) -> list[tuple[str, str | None, bool]]:
    """Lot listesindeki (`material_case_gtin`, `case_units`, `gs1_label`); detay aynısını verir."""
    rows = {row["id"]: row for row in client.get(LOTS, {"page_size": 200}).json()["results"]}
    result = []
    for lot in lots:
        detail = client.get(f"{LOTS}{lot.pk}/").json()
        values = [
            (row["material_case_gtin"], row["case_units"], row["gs1_label"])
            for row in (rows[lot.pk], detail)
        ]
        assert values[0] == values[1], lot.lot_no
        result.append(values[0])
    return result


# --- lot açılırken --------------------------------------------------------------------------------


def test_create_lot_writes_the_case_layout_of_the_day(make_user) -> None:
    """Mamul lotu açılırken KOLI dönüşümünün koli içi miktarı (dönüşüm aktifse) ve koli GTIN'i
    (pasifse de: basılmış etiket okutulur) lota ve denetim günlüğüne yazılır; KOLI dönüşümü yoksa
    boş kalır. Mamul olmayan lota yazılmaz (tedarikçinin koli dönüşümü olsa da)."""
    actor = make_user(DOLUM)
    lot_type = ContentType.objects.get_for_model(Lot)
    cases = [
        (product(case_gtin=CASE_GTIN), (D(12), CASE_GTIN)),
        (product("8690000000029"), (D(12), "")),
        (product("8690000000036", case_gtin=None), (None, "")),
        (product("8690000000043", case_gtin=NEW_CASE_GTIN, active=False), (None, NEW_CASE_GTIN)),
        (
            product("", case_gtin="38690000000013", factor="1000", material_type=PACKAGING),
            (None, ""),
        ),
    ]
    for index, (material, expected) in enumerate(cases, start=1):
        lot = open_lot(material, f"L-{index}", actor)
        assert layout(lot) == expected, material.code
        log = AuditLog.objects.get(
            content_type=lot_type, object_id=lot.pk, action=AuditLog.Action.CREATE
        )
        factor, gtin = expected
        assert log.changes.get("case_factor") == (
            None if factor is None else [None, f"{factor:.6f}"]
        )
        assert log.changes.get("case_gtin") == ([None, gtin] if gtin else None)


# --- koli düzeni sonra değişince ------------------------------------------------------------------


def test_old_lots_keep_their_case_layout_when_the_case_quantity_and_gtin_change(
    client_for, make_user
) -> None:
    """Koli GTIN'i olmayan mamulde (1 KOLI = 12 ADET) planlama koli içi miktarı 24'e çıkarır, sonra
    koli GTIN'ini ilk kez girer (API; koli GTIN'i kilitli değil, arşiv yazılmaz). Önceden açılmış
    lotların koli ve palet etiketi açıldıkları günkü gibi ürün GTIN'ini taşır, okutulunca koli
    birimi vermez (eskiden yeni koli GTIN'i basılır, 1 koli = 24 okunurdu); lot API'si o günkü koli
    içi adedi verir. Koli GTIN'iyle açılan lot koli GTIN'ini basar. Sonra koli GTIN'i kilitli
    düzende değişir (24 → 36, eski GTIN 24'lü arşivlenir): hiçbir lotun etiketi değişmez."""
    enable_gs1(make_user(ADMIN))
    planner, client = client_for(PLANLAMA), client_for(DOLUM)
    material = product()
    case = MaterialUnitConversion.objects.get(material=material)
    old = open_lot(material, "D-261015-001")
    change_case(planner, case, {"factor_to_base": "24"})
    resized = open_lot(material, "D-261015-002")
    change_case(planner, case, {"gtin": CASE_GTIN})
    assert not RetiredGtin.objects.exists()
    cased = open_lot(material, "D-261015-003")

    assert [layout(lot) for lot in (old, resized, cased)] == [
        (D(12), ""),
        (D(24), ""),
        (D(24), CASE_GTIN),
    ]
    for lot, gtin in ((old, ITEM), (resized, ITEM), (cased, CASE_GTIN)):
        assert printed_gtins(client, lot) == [gtin, gtin], lot.lot_no
    scanned = decode_scan(CASE_BARCODE.format(gtin=ITEM, lot_no=old.lot_no))
    assert (scanned.lots, scanned.unit, scanned.units_per_case) == ([old], "", None)
    assert api_layout(client, [old, resized, cased]) == [
        ("", "12.000000", True),
        ("", "24.000000", True),
        (CASE_GTIN, "24.000000", True),
    ]

    change_case(planner, case, {"factor_to_base": "36", "gtin": NEW_CASE_GTIN})
    assert RetiredGtin.objects.get().factor_to_base == D(24)
    for lot, gtin in ((old, ITEM), (resized, ITEM), (cased, CASE_GTIN)):
        assert printed_gtins(client, lot) == [gtin, gtin], lot.lot_no
    # Arşivdeki koli GTIN'i 24'lü düzenindir: yalnız o düzende açılan lotun kolisinde basılıdır.
    scanned = decode_scan(CASE_BARCODE.format(gtin=CASE_GTIN, lot_no=cased.lot_no))
    assert (scanned.lots, scanned.unit, scanned.units_per_case) == ([cased], "KOLI", D(24))
    assert [layout(lot) for lot in (old, resized, cased)] == [
        (D(12), ""),
        (D(24), ""),
        (D(24), CASE_GTIN),
    ]


def test_old_lot_keeps_its_case_gtin_after_a_pack_change_and_deactivation(
    client_for, make_user
) -> None:
    """Lotu olan mamulde koli GTIN'i kilitlidir: koli düzeni yeni koli GTIN'iyle değişir (12 → 36;
    masterdata eski GTIN'i eski miktarıyla arşivler), sonra KOLI dönüşümü pasife alınır (planlama,
    API). Önceden açılmış lot eski koli GTIN'ini ve koli içi adedini tutar; etiketindeki eski koli
    barkodu eski miktarla okunur. Değişiklikten sonra açılan lot yeni düzeni alır; dönüşüm pasife
    alındıktan sonra açılan lotta koli içi miktar yoktur (pasif dönüşümün koli GTIN'i basılır)."""
    enable_gs1(make_user(ADMIN))
    planner, client = client_for(PLANLAMA), client_for(DOLUM)
    material = product(case_gtin=CASE_GTIN)
    case = MaterialUnitConversion.objects.get(material=material)
    old = open_lot(material, "D-261015-001")  # lotu var: koli GTIN'i kilitli
    change_case(planner, case, {"factor_to_base": "36", "gtin": NEW_CASE_GTIN})
    retired = RetiredGtin.objects.get()
    assert (retired.gtin, retired.factor_to_base, retired.replaced_by) == (
        CASE_GTIN,
        D(12),
        NEW_CASE_GTIN,
    )
    new = open_lot(material, "D-261015-002")
    assert client_for(DEPO).post(f"{CONVERSIONS}{case.pk}/deactivate/").status_code == 403
    response = planner.post(f"{CONVERSIONS}{case.pk}/deactivate/")
    assert response.status_code == 200, response.json()
    late = open_lot(material, "D-261015-003")

    assert [layout(lot) for lot in (old, new, late)] == [
        (D(12), CASE_GTIN),
        (D(36), NEW_CASE_GTIN),
        (None, NEW_CASE_GTIN),
    ]
    for lot, gtin in ((old, CASE_GTIN), (new, NEW_CASE_GTIN), (late, NEW_CASE_GTIN)):
        assert printed_gtins(client, lot) == [gtin, gtin], lot.lot_no
    # Eski lotun kolisi eski koli GTIN'iyle okunur: arşivden, 1 koli = 12 (dönüşüm pasif olsa da).
    scanned = decode_scan(CASE_BARCODE.format(gtin=CASE_GTIN, lot_no=old.lot_no))
    assert (scanned.lots, scanned.unit, scanned.units_per_case) == ([old], "KOLI", D(12))
    assert scanned.warnings == [RETIRED_CASE_WARNING.format(quantity="12", unit="ADET")]
    assert api_layout(client, [old, new, late]) == [
        (CASE_GTIN, "12.000000", True),
        (NEW_CASE_GTIN, "36.000000", True),
        (NEW_CASE_GTIN, None, True),
    ]


# --- lot API'si -----------------------------------------------------------------------------------


def test_lot_api_gives_the_case_units_and_case_gtin_of_the_lot(
    client_for, make_user, django_assert_num_queries
) -> None:
    """Lot API'si (liste ve detay) koli düzenini lottan verir: `case_units` (koli ve palet
    etiketinde "Koli içi adet" varsayılanı) lotun açıldığı günkü koli içi miktar, yalnız temel
    birimi adet olan malzemede (temel birimi koli, palet ya da kg olanda ve koli dönüşümü yoksa
    null: etiket "adet" yazar); `material_case_gtin` lotun etiketlerinin bastığı koli GTIN'i
    (kontrol hanesi yanlışsa basılmaz: ""); `gs1_label` etiketlerin kuralıyla lotun koli
    GTIN'inden (geçersiz koli GTIN'iyle açılan lot, GTIN sonra düzeltilse de GS1'siz basılır).
    Liste satır başına sorgu yapmaz; giriş yapmamış istek reddedilir."""
    client = client_for(DEPO)
    counted = open_lot(product(case_gtin=CASE_GTIN), "D-261015-001")
    client.get(LOTS)  # ısınma
    with CaptureQueriesContext(connection) as one_row:
        assert client.get(LOTS).json()["count"] == 1
    by_kg = open_lot(product("8690000000029", factor="12.5", base_unit="KG"), "D-261015-002")
    no_case = open_lot(product("8690000000036", case_gtin=None), "D-261015-003")
    legacy = product("8690000000043", case_gtin="18690000000010")  # kontrol hanesi yanlış
    invalid = open_lot(legacy, "D-261015-004")
    masterdata.update_record(
        make_user(PLANLAMA),
        MaterialUnitConversion.objects.get(material=legacy),
        {"gtin": "28690000000023"},  # geçersiz koli GTIN'inin düzeltilmesi serbest
    )
    fixed = open_lot(legacy, "D-261015-005")
    supplied = open_lot(
        product("", case_gtin="38690000000013", factor="1000", material_type=PACKAGING),
        "H-261015-001",
    )
    # Stoku koliyle sayılan mamul: koli içi miktar 1 koli (adet değil).
    in_cases = open_lot(product("8690000000050", case_gtin=None, base_unit="KOLI"), "D-261015-006")
    # Stoku paletle sayılan mamul: 1 koli = 0,025 palet.
    in_pallets = open_lot(
        product("8690000000067", factor="0.025", base_unit="PALET"), "D-261015-007"
    )
    assert [layout(lot) for lot in (in_cases, in_pallets)] == [(D(1), ""), (D("0.025"), "")]
    expected = {
        counted.pk: (CASE_GTIN, "12.000000", True),
        by_kg.pk: ("", None, True),
        no_case.pk: ("", None, True),
        invalid.pk: ("", "12.000000", False),
        fixed.pk: ("28690000000023", "12.000000", True),
        supplied.pk: ("", None, False),
        in_cases.pk: ("", None, True),
        in_pallets.pk: ("", None, True),
    }
    with django_assert_num_queries(len(one_row)):
        rows = client.get(LOTS).json()["results"]
    assert {
        row["id"]: (row["material_case_gtin"], row["case_units"], row["gs1_label"]) for row in rows
    } == expected
    for pk, values in expected.items():
        detail = client.get(f"{LOTS}{pk}/").json()
        assert (detail["material_case_gtin"], detail["case_units"], detail["gs1_label"]) == values
        data = LotSerializer(Lot.objects.get(pk=pk)).data
        assert (data["material_case_gtin"], data["case_units"], data["gs1_label"]) == values
    assert APIClient().get(LOTS).status_code in (401, 403)


# --- göç: var olan lotlar -------------------------------------------------------------------------


def test_migration_fills_the_case_layout_of_existing_lots() -> None:
    """Göç (inventory 0008) var olan mamul lotlarına lotun açıldığı günkü koli düzenini, alanlardan
    önceki kuralla (`masterdata.case_factor_at` / `case_gtin_at`, lotun açıldığı an) yazar: lot
    açıldıktan sonra arşivlenmiş en eski koli GTIN'i onun miktarını ve GTIN'ini verir (arşivlendiği
    an açılan lot için sonraki); yoksa bugünkü KOLI dönüşümü (miktar yalnız aktifse, GTIN pasifse
    de). Temel birimi koli olan mamulün lotunda koli içi miktar 1'dir. KOLI dönüşümü olmayan mamul
    lotu ve mamul olmayan lot boş kalır."""
    now = timezone.now()
    changed = product("8690000000050", case_gtin=gtin14("4869000000005"), factor="24")
    conversion = MaterialUnitConversion.objects.get(material=changed)
    first, second = gtin14("1869000000005"), gtin14("2869000000005")
    archived = {
        first: (D(6), second, now - timedelta(days=20)),
        second: (D(12), conversion.gtin, now - timedelta(days=10)),
    }
    for gtin, (factor, replaced_by, created_at) in archived.items():
        row = RetiredGtin.objects.create(
            conversion=conversion, gtin=gtin, factor_to_base=factor, replaced_by=replaced_by
        )
        RetiredGtin.objects.filter(pk=row.pk).update(created_at=created_at)
    materials = {
        "no_case": product(case_gtin=None),
        "active": product("8690000000029", case_gtin=CASE_GTIN),
        "blank": product("8690000000036"),
        "inactive": product("8690000000043", case_gtin=NEW_CASE_GTIN, active=False),
        "changed": changed,
        "packaging": product(
            "", case_gtin=gtin14("5869000000005"), factor="1000", material_type=PACKAGING
        ),
        "in_cases": product("8690000000067", case_gtin=None, base_unit="KOLI"),
    }
    opened = [
        ("no_case", 30),
        ("active", 30),
        ("blank", 30),
        ("inactive", 30),
        ("changed", 30),  # iki değişiklikten önce: ilk arşiv satırı
        ("changed", 20),  # ilk değişikliğin anında: sonraki arşiv satırı
        ("changed", 15),  # iki değişiklik arasında
        ("changed", 5),  # iki değişiklikten sonra: bugünkü dönüşüm
        ("packaging", 30),
        ("in_cases", 30),  # stoku koliyle sayılır: 1 KOLI = 1 KOLI
    ]
    lots = []
    for index, (key, days) in enumerate(opened, start=1):
        lot = open_lot(materials[key], f"L-{index}")
        # Göçten önceki lot: koli düzeni boş, açıldığı an geçmişte.
        Lot.objects.filter(pk=lot.pk).update(
            created_at=now - timedelta(days=days), case_factor=None, case_gtin=""
        )
        lots.append(lot)

    migration.snapshot_case_layout(django_apps, None)

    assert [layout(lot) for lot in lots] == [
        (None, ""),
        (D(12), CASE_GTIN),
        (D(12), ""),
        (None, NEW_CASE_GTIN),
        (D(6), first),
        (D(12), second),
        (D(12), second),
        (D(24), conversion.gtin),
        (None, ""),
        (D(1), ""),
    ]
    for lot in Lot.objects.filter(material__material_type=Material.Type.FINISHED):
        assert layout(lot) == (
            masterdata.case_factor_at(lot.material, lot.created_at),
            masterdata.case_gtin_at(lot.material, lot.created_at),
        ), lot.lot_no


def test_migration_takes_the_generic_case_factor_without_an_active_case_conversion() -> None:
    """KOLI biriminin genel katsayısı varsa (1 KOLI = 6 ADET) göç, aktif KOLI dönüşümü olmayan
    mamul lotuna onu yazar (`masterdata.unit_factor_to_base`: aktif KOLI dönüşümü genel katsayıdan
    önce gelir; pasif dönüşümün koli GTIN'i yine yazılır). Türü uymayan temel birimde (kg) koli içi
    miktar boş kalır."""
    UnitOfMeasure.objects.filter(code="KOLI").update(factor_to_kind_base=D(6))
    materials = [
        product(case_gtin=None),
        product("8690000000029", case_gtin=CASE_GTIN),
        product("8690000000036", case_gtin=NEW_CASE_GTIN, active=False),
        product("8690000000043", case_gtin=None, base_unit="KG"),
    ]
    now = timezone.now()
    lots = []
    for index, material in enumerate(materials, start=1):
        lot = open_lot(material, f"L-{index}")
        # Göçten önceki lot: koli düzeni boş, açıldığı an geçmişte.
        Lot.objects.filter(pk=lot.pk).update(
            created_at=now - timedelta(days=30), case_factor=None, case_gtin=""
        )
        lots.append(lot)

    migration.snapshot_case_layout(django_apps, None)

    assert [layout(lot) for lot in lots] == [
        (D(6), ""),
        (D(12), CASE_GTIN),
        (D(6), NEW_CASE_GTIN),
        (None, ""),
    ]
    for lot in Lot.objects.select_related("material__base_unit"):
        assert layout(lot) == (
            masterdata.case_factor_at(lot.material, lot.created_at),
            masterdata.case_gtin_at(lot.material, lot.created_at),
        ), lot.lot_no


# --- eşzamanlılık: lot açılırken koli düzeni değişirse --------------------------------------------

# Kilitli koli GTIN'inde koli düzeni değişikliği: yeni koli içi miktar yeni koli GTIN'iyle.
PACK_CHANGE = {"factor_to_base": D(24), "gtin": NEW_CASE_GTIN}


def _waits_for_lock(thread: threading.Thread, timeout: float = 10) -> bool:
    """İş parçacığının işlemi bu test veritabanında bir kilidi bekliyor mu? Bekleyiş görülene ya da
    iş parçacığı bitene kadar bakılır."""
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        with connection.cursor() as cursor:
            # pg_locks bütün veritabanlarını gösterir: yalnız bu test veritabanındaki bekleyiş.
            cursor.execute(
                "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                "WHERE NOT l.granted AND a.datname = current_database()"
            )
            if cursor.fetchone()[0]:
                return True
        thread.join(0.02)
    return False


def _open_while(
    second: Callable[[], object],
    material: Material,
    monkeypatch: pytest.MonkeyPatch,
    pause: str = "opened",
) -> tuple[bool, dict[str, str]]:
    """Lot açan işlem (dolum başlangıcı, mal kabul, açılış stoku içe aktarması gibi) sürerken ikinci
    işlemde `second` çalışır. Lot açan işlem lot açılınca (`pause="opened"`: lot yazıldı, işlem
    kaydedilmedi) ya da lot açılırken koli içi miktar okununca, lot yazılmadan
    (`pause="factor_read"`; koli GTIN'i ondan önce, kilitli satırdan okunur) durur; ikinci işlem bir
    kilidi bekleyince ya da bitince devam edip kaydedilir. Döner: (ikinci işlem bekledi mi,
    {"open": sonuç, "second": sonuç}); sonuç "ok" ya da iş kuralı hatasının kodu."""
    paused, release = threading.Event(), threading.Event()
    outcome: dict[str, str] = {}

    def hold() -> None:
        paused.set()
        release.wait(10)

    if pause == "factor_read":
        read_factor = masterdata.case_factor_at

        def factor_then_hold(*args: Any) -> Decimal | None:
            factor = read_factor(*args)
            if threading.current_thread().name == "open":
                hold()
            return factor

        monkeypatch.setattr(masterdata, "case_factor_at", factor_then_hold)

    def run(name: str, step: Callable[[], object]) -> None:
        try:
            with transaction.atomic():
                _bound_lock_waits()
                step()
                if name == "open" and pause == "opened":
                    hold()
            outcome[name] = "ok"
        except BusinessRuleError as exc:
            outcome[name] = exc.code
        except Exception as exc:
            outcome[name] = f"{type(exc).__name__}: {exc}"
        finally:
            paused.set()
            connection.close()

    opener = threading.Thread(
        target=run, args=("open", lambda: open_lot(material, "D-261015-001")), name="open"
    )
    other = threading.Thread(target=run, args=("second", second), name="second")
    blocked = False
    opener.start()
    try:
        assert paused.wait(10)
        other.start()
        blocked = _waits_for_lock(other)
    finally:
        release.set()
        opener.join(30)
        if other.ident is not None:
            other.join(30)
    return blocked, outcome


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("pause", "change", "result", "case_layout", "archived"),
    [
        # Kilitsiz kaydedilirdi (lot görünmez, koli GTIN'i kilitsiz; yeni GTIN ve arşiv olmadan):
        # lotun kolisindeki koli GTIN'i 24 okunurdu, irsaliye 12 sayardı.
        ("opened", {"factor_to_base": D(24)}, "case_gtin_required", (D(12), CASE_GTIN), []),
        # Kilitsiz eski koli GTIN'i arşivlenmezdi: lotun kolisi okutulamazdı.
        ("opened", PACK_CHANGE, "ok", (D(24), NEW_CASE_GTIN), [(CASE_GTIN, D(12), NEW_CASE_GTIN)]),
        # Kilitsiz lot eski koli içi miktarı ve yeni koli GTIN'ini alırdı (24 okunan GTIN, 12 sayan
        # irsaliye).
        (
            "factor_read",
            PACK_CHANGE,
            "ok",
            (D(24), NEW_CASE_GTIN),
            [(CASE_GTIN, D(12), NEW_CASE_GTIN)],
        ),
    ],
    ids=["miktar", "koli-duzeni", "okumalar-arasinda"],
)
def test_case_layout_change_waits_for_the_lot_being_opened(
    make_user, monkeypatch, pause, change, result, case_layout, archived
) -> None:
    """Lot açılırken KOLI dönüşümü işlem sonuna kadar kilitlenir. Lot açan işlem sürerken
    planlamanın koli düzeni değişikliği işlemin bitmesini bekler, sonra açılan lotu görür: koli
    GTIN'i kilitlidir, koli içi miktar tek başına değişemez (`case_gtin_required`); yeni koli
    GTIN'iyle değişirse eski GTIN eski miktarıyla arşivlenir. Lot o günkü koli düzenini tutar, koli
    içi miktar ve koli GTIN'i aynı düzenden okunur: lotun kolisindeki koli GTIN'i lotun koli içi
    miktarıyla okunur."""
    _count_units()  # işlemli test: göçle gelen birimler silinmiş olabilir
    planner = make_user(PLANLAMA)
    material = product(case_gtin=CASE_GTIN)
    case = MaterialUnitConversion.objects.get(material=material)

    blocked, outcome = _open_while(
        lambda: masterdata.update_record(planner, case, change), material, monkeypatch, pause
    )

    assert (blocked, outcome) == (True, {"open": "ok", "second": result})
    lot = Lot.objects.get(material=material)
    assert layout(lot) == (D(12), CASE_GTIN)
    assert (
        MaterialUnitConversion.objects.values_list("factor_to_base", "gtin").get(pk=case.pk)
        == case_layout
    )
    assert (
        list(RetiredGtin.objects.values_list("gtin", "factor_to_base", "replaced_by")) == archived
    )
    scanned = decode_scan(CASE_BARCODE.format(gtin=CASE_GTIN, lot_no=lot.lot_no))
    assert (scanned.lots, scanned.units_per_case) == ([lot], D(12))


@pytest.mark.django_db(transaction=True)
def test_case_conversion_opened_while_a_lot_opens_does_not_give_the_lot_half_a_layout(
    make_user, monkeypatch
) -> None:
    """Mamulün KOLI dönüşümü yokken lot açılır (kilitlenecek satır yok) ve o sırada planlama koli
    GTIN'li KOLI dönüşümü açar. Koli GTIN'i kilitli satırdan, koli içi miktardan önce okunur: lot
    koli düzeni olmadan açılır, hiç var olmamış bir düzenle (koli içi miktarsız koli GTIN'i:
    etikette koli GTIN'i, irsaliyede koli sayısı yok) değil. Sonra açılan lot yeni düzeni alır."""
    _count_units()  # işlemli test: göçle gelen birimler silinmiş olabilir
    planner = make_user(PLANLAMA)
    material = product(case_gtin=None)
    case = {"material": material, "unit": unit("KOLI"), "factor_to_base": D(12), "gtin": CASE_GTIN}

    blocked, outcome = _open_while(
        lambda: masterdata.create_record(planner, MaterialUnitConversion, case),
        material,
        monkeypatch,
        "factor_read",
    )

    assert (blocked, outcome) == (False, {"open": "ok", "second": "ok"})
    assert layout(Lot.objects.get(material=material)) == (None, "")
    assert layout(open_lot(material, "D-261015-002")) == (D(12), CASE_GTIN)


@pytest.mark.django_db(transaction=True)
def test_lot_opening_locks_only_the_case_conversion_of_its_product(monkeypatch) -> None:
    """Lot açan işlem yalnız kendi mamulünün KOLI dönüşümünü kilitler: başka mamulün lotu onu
    beklemez (KOLI biriminin satırı da kilitlenseydi bütün mamullerin lot açışı sıraya girerdi)."""
    _count_units()  # işlemli test: göçle gelen birimler silinmiş olabilir
    material = product(case_gtin=CASE_GTIN)
    other = product("8690000000029", case_gtin=NEW_CASE_GTIN)

    blocked, outcome = _open_while(lambda: open_lot(other, "D-261015-002"), material, monkeypatch)

    assert (blocked, outcome) == (False, {"open": "ok", "second": "ok"})
    assert [layout(lot) for lot in Lot.objects.order_by("lot_no")] == [
        (D(12), CASE_GTIN),
        (D(12), NEW_CASE_GTIN),
    ]


def _open_during(
    change: Callable[[], object], material: Material, *, roll_back: bool
) -> tuple[bool, dict[str, str]]:
    """Planlamanın koli düzeni değişikliği (`change`) önce çalışır ve kaydedilmeden durur; bu sırada
    aynı mamulün lotu (`D-261015-002`) ikinci işlemde açılır. Lot açan işlem bir kilidi bekleyince
    değişiklik kaydedilir (`roll_back`: geri alınır). Döner: (lot açan işlem bekledi mi,
    {"change": sonuç, "open": sonuç})."""
    held, release = threading.Event(), threading.Event()
    outcome: dict[str, str] = {}

    def run(name: str, step: Callable[[], object]) -> None:
        try:
            with transaction.atomic():
                _bound_lock_waits()
                step()
                if name == "change":
                    held.set()
                    release.wait(10)
                    if roll_back:
                        raise RuntimeError("geri alındı")
            outcome[name] = "ok"
        except BusinessRuleError as exc:
            outcome[name] = exc.code
        except Exception as exc:
            outcome[name] = f"{type(exc).__name__}: {exc}"
        finally:
            held.set()
            connection.close()

    planner = threading.Thread(target=run, args=("change", change), name="change")
    opener = threading.Thread(
        target=run, args=("open", lambda: open_lot(material, "D-261015-002")), name="open"
    )
    blocked = False
    planner.start()
    try:
        assert held.wait(10)
        opener.start()
        blocked = _waits_for_lock(opener)
    finally:
        release.set()
        planner.join(30)
        if opener.ident is not None:
            opener.join(30)
    return blocked, outcome


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("roll_back", "change_result", "case_layout"),
    [
        (False, "ok", (D(24), NEW_CASE_GTIN)),
        (True, "RuntimeError: geri alındı", (D(12), CASE_GTIN)),
    ],
    ids=["kaydedildi", "geri-alindi"],
)
def test_lot_opened_during_a_case_layout_change_waits_and_takes_its_result(
    make_user, roll_back, change_result, case_layout
) -> None:
    """Planlamanın koli düzeni değişikliği sürerken açılan lot KOLI dönüşümünün kilidini bekler ve
    değişikliğin sonucunu alır: kaydedilirse yeni koli içi miktarı yeni koli GTIN'iyle, geri
    alınırsa eski düzeni. Koli GTIN'i kilidi bekleyen sorgunun döndürdüğü satırdan okunur; kilitten
    önce okunsaydı lot yeni miktarla eski (arşivde 12 okunan) koli GTIN'ini alırdı."""
    _count_units()  # işlemli test: göçle gelen birimler silinmiş olabilir
    planner = make_user(PLANLAMA)
    material = product(case_gtin=CASE_GTIN)
    open_lot(material, "D-261015-001")  # koli GTIN'i kilitli
    case = MaterialUnitConversion.objects.get(material=material)

    blocked, outcome = _open_during(
        lambda: masterdata.update_record(planner, case, PACK_CHANGE), material, roll_back=roll_back
    )

    assert (blocked, outcome) == (True, {"change": change_result, "open": "ok"})
    assert layout(Lot.objects.get(material=material, lot_no="D-261015-002")) == case_layout
