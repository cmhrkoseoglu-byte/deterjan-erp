"""GS1 (Kodlama sistematiği, Paket 2, Adım 7, 3. tur; CUMHUR, 2026-11-05): GTIN kilidi yalnız
mamulde; lotu olan mamulde koli içi miktar yalnız yeni koli GTIN'iyle değişir, eski koli GTIN'i eski
miktarıyla arşivlenir (`RetiredGtin`) ve hiçbir ürüne ya da koliye bir daha verilmez.

Kilit lot ister: lotlar `inventory` servisiyle açılır (stok hareketi olmadan; testler sonunda stok
değişmezleri yine denetlenir). Lotun koli ve palet etiketleri `inventory/tests/test_gs1_labels.py`
içindedir.
"""

import io
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.contrib import admin as django_admin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.roles import ADMIN, DEPO, PLANLAMA, URETIM
from apps.inventory import services as inventory
from apps.inventory.models import Lot
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata import importers, services
from apps.masterdata.admin import MaterialAdmin
from apps.masterdata.models import Material, MaterialUnitConversion, RetiredGtin
from apps.masterdata.tests.factories import unit
from apps.masterdata.tests.test_gs1 import (
    _bound_lock_waits,
    _count_units,
    _waiting_for_gtin_lock,
    gtin13,
)

pytestmark = pytest.mark.django_db

CONVERSIONS = "/api/v1/masterdata/conversions/"
MATERIALS = "/api/v1/masterdata/materials/"
PREFIX = "8691234"
GTIN = "8690000000012"
OTHER_GTIN = "8690000000029"
CASE_GTIN = "18690000000019"  # GTIN'in gösterge hanesi 1 ile koli GTIN'i
NEW_CASE = "28690000000016"  # gösterge hanesi 2
THIRD_CASE = "38690000000013"  # gösterge hanesi 3
FOURTH_CASE = "48690000000010"  # gösterge hanesi 4
REQUIRED = (
    "Koli içi miktar değişince GS1 yeni koli GTIN'i ister: yeni koli GTIN'ini de girin. Eski GTIN "
    "eski miktarıyla arşivlenir; depodaki eski koliler okutulmaya devam eder."
)
BASE_UNITS: dict[str, str] = {
    Material.Type.RAW: "KG",
    Material.Type.PACKAGING: "ADET",
    Material.Type.BULK: "KG",
    Material.Type.FINISHED: "ADET",
}
NOT_FINISHED = [Material.Type.RAW, Material.Type.PACKAGING, Material.Type.BULK]


@pytest.fixture
def planner(make_user) -> User:
    return make_user(PLANLAMA)


@pytest.fixture
def invariants(db: None) -> Iterator[None]:
    """Test sonunda stok değişmezleri (CLAUDE.md §7): lot açan testler."""
    yield
    assert_stock_invariants()


def make_material(
    actor: User | None,
    code: str,
    material_type: str = Material.Type.FINISHED,
    gtin: str = GTIN,
) -> Material:
    return services.create_record(
        actor,
        Material,
        {
            "code": code,
            "name": f"Malzeme {code}",
            "material_type": material_type,
            "base_unit": unit(BASE_UNITS[material_type]),
            "gtin": gtin,
        },
    )


def add_case(
    actor: User | None, material: Material, gtin: str = CASE_GTIN, factor: str = "12"
) -> MaterialUnitConversion:
    return services.create_record(
        actor,
        MaterialUnitConversion,
        {
            "material": material,
            "unit": unit("KOLI"),
            "factor_to_base": Decimal(factor),
            "gtin": gtin,
        },
    )


def add_lot(material: Material, lot_no: str) -> Lot:
    """Lot (stok hareketi yok): GTIN kilidi için lotun var olması yeter."""
    finished = material.material_type == Material.Type.FINISHED
    source = Lot.Source.FILLING if finished else Lot.Source.PURCHASE
    return inventory.create_lot(None, material=material, source=source, lot_no=lot_no)


def locked_case(
    actor: User | None,
    code: str = "MM-1",
    gtin: str = GTIN,
    case_gtin: str = CASE_GTIN,
) -> MaterialUnitConversion:
    """Lotu olan mamul ve kilitli koli GTIN'li KOLI dönüşümü (1 koli = 12 adet)."""
    material = make_material(actor, code, gtin=gtin)
    case = add_case(actor, material, case_gtin)
    add_lot(material, f"D-{code}")
    assert services.case_gtin_locked(case)
    return case


def change_pack(
    actor: User | None, case: MaterialUnitConversion, factor: str, gtin: str, note: str = ""
) -> MaterialUnitConversion:
    """Koli içi miktar değişikliği: yeni miktar ve yeni koli GTIN'i aynı istekte."""
    return services.update_record(
        actor, case, {"factor_to_base": Decimal(factor), "gtin": gtin}, note=note
    )


def rule_error(call, *args: Any, **kwargs: Any) -> tuple[str, str]:
    with pytest.raises(BusinessRuleError) as exc:
        call(*args, **kwargs)
    return exc.value.code, exc.value.message


def updates(instance: Any, field: str) -> list[list[Any]]:
    """Kaydın denetim günlüğündeki güncellemelerde `field` değişiklikleri, sırayla."""
    logs = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(instance),
        object_id=instance.pk,
        action=AuditLog.Action.UPDATE,
    ).order_by("id")
    return [log.changes[field] for log in logs if field in log.changes]


def archived_message(code: str) -> str:
    return f"Bu GTIN {code} malzemesinin eski koli GTIN'i (arşivde); bir daha kullanılamaz."


def case_locked_message(code: str) -> str:
    return (
        f"{code}: lotu olan mamulün koli GTIN'i değiştirilemez ya da silinemez (basılmış koli ve "
        "palet etiketleri bu GTIN'i taşır). Koli içi miktar değiştiyse yeni miktarla birlikte "
        "yeni koli GTIN'i girin."
    )


# --- kilit yalnız mamulde ------------------------------------------------------------------------


@pytest.mark.parametrize("material_type", NOT_FINISHED)
def test_non_finished_materials_with_lots_correct_their_gtins(
    planner, invariants, material_type
) -> None:
    """Hammadde, ambalaj ve dökme ürün (tedarikçi) GTIN'ini ve koli GTIN'ini lotu olsa da
    değiştirir ve siler; değişiklik denetim günlüğüne düşer. Biçim ve tekillik kuralları kalır."""
    material = make_material(planner, "HM-1", material_type)
    case = add_case(planner, material)
    add_lot(material, "H-1")
    assert not services.gtin_locked(material) and not services.case_gtin_locked(case)

    services.update_record(planner, material, {"gtin": OTHER_GTIN})
    services.update_record(planner, material, {"gtin": ""})
    assert updates(material, "gtin") == [[GTIN, OTHER_GTIN], [OTHER_GTIN, ""]]
    services.update_record(planner, case, {"gtin": NEW_CASE})
    services.update_record(planner, case, {"gtin": ""})
    # Koli içi miktar da yeni GTIN'siz değişir; arşiv satırı yazılmaz.
    services.update_record(planner, case, {"gtin": THIRD_CASE, "factor_to_base": Decimal(24)})
    services.update_record(planner, case, {"factor_to_base": Decimal(30)})
    assert updates(case, "gtin") == [[CASE_GTIN, NEW_CASE], [NEW_CASE, ""], ["", THIRD_CASE]]
    assert updates(case, "factor_to_base") == [
        ["12.000000", "24.000000"],
        ["24.000000", "30.000000"],
    ]
    assert not RetiredGtin.objects.exists()

    # Biçim ve tekillik her türde denetlenir.
    assert rule_error(services.update_record, planner, material, {"gtin": "8690000000013"})[0] == (
        "invalid_gtin"
    )
    make_material(planner, "MM-9", gtin="8690000000036")
    assert rule_error(services.update_record, planner, material, {"gtin": "8690000000036"})[0] == (
        "gtin_taken"
    )


def test_finished_goods_with_lots_stay_locked(planner, invariants) -> None:
    case = locked_case(planner)
    material = case.material
    assert services.gtin_locked(material)
    message = (
        "MM-1: lotu olan mamulün GTIN'i değiştirilemez ya da silinemez (basılmış koli ve palet "
        "etiketleri bu GTIN'i taşır)."
    )
    for value in (OTHER_GTIN, ""):
        assert rule_error(services.update_record, planner, material, {"gtin": value}) == (
            "gtin_locked",
            message,
        )
    # Türü değiştirerek kilit kaldırılamaz: lotu olan malzemenin türü mamulden ya da mamule
    # değişmez (CUMHUR, 2026-11-05; aynı istekte ya da ayrı istekte).
    change = {"material_type": Material.Type.RAW, "gtin": OTHER_GTIN}
    assert rule_error(services.update_record, planner, material, change)[0] == (
        "material_type_locked"
    )
    material.refresh_from_db()
    assert (material.material_type, material.gtin) == (Material.Type.FINISHED, GTIN)

    raw = make_material(planner, "HM-1", Material.Type.RAW, gtin="8690000000036")
    add_lot(raw, "H-1")
    change = {"material_type": Material.Type.FINISHED, "gtin": "8690000000043"}
    assert rule_error(services.update_record, planner, raw, change)[0] == "material_type_locked"
    raw.refresh_from_db()
    assert (raw.material_type, raw.gtin) == (Material.Type.RAW, "8690000000036")
    change = {"material_type": Material.Type.FINISHED}
    assert rule_error(services.update_record, planner, raw, change)[0] == "material_type_locked"
    raw.refresh_from_db()
    assert raw.material_type == Material.Type.RAW and not services.gtin_locked(raw)


def test_api_gtin_locked_follows_the_lock_scope(client_for, planner, invariants) -> None:
    raw = make_material(planner, "HM-1", Material.Type.RAW, gtin=OTHER_GTIN)
    raw_case = add_case(planner, raw, NEW_CASE)
    add_lot(raw, "H-1")
    finished = locked_case(planner).material
    no_lots = make_material(planner, "MM-2", gtin="8690000000036")
    add_case(planner, no_lots, THIRD_CASE)

    client = client_for(DEPO)
    listed = {row["code"]: row["gtin_locked"] for row in client.get(MATERIALS).json()["results"]}
    assert listed == {"HM-1": False, "MM-1": True, "MM-2": False}
    for material, flag in ((raw, False), (finished, True), (no_lots, False)):
        detail = client.get(f"{MATERIALS}{material.pk}/").json()
        assert detail["gtin_locked"] is flag
        assert [row["gtin_locked"] for row in detail["conversions"]] == [flag]
    rows = client.get(CONVERSIONS).json()["results"]
    assert {row["material_code"]: row["gtin_locked"] for row in rows} == listed

    # Hammaddenin (tedarikçi) GTIN'i API'den de düzeltilir.
    writer = client_for(PLANLAMA)
    saved = writer.patch(f"{MATERIALS}{raw.pk}/", {"gtin": "8690000000043"}, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["gtin"] == "8690000000043" and saved.json()["gtin_locked"] is False
    patched = writer.patch(f"{CONVERSIONS}{raw_case.pk}/", {"gtin": ""}, format="json")
    assert patched.status_code == 200, patched.json()
    assert patched.json()["gtin"] == "" and patched.json()["retired_gtins"] == []


# --- koli içi miktar değişikliği -----------------------------------------------------------------


def test_case_quantity_changes_only_with_a_new_case_gtin(planner, invariants) -> None:
    case = locked_case(planner)
    # Miktar aynı, koli GTIN'i değişiyor ya da siliniyor: kilit (miktar değiştiyse ne yapılacağını
    # da söyler).
    for value in (NEW_CASE, ""):
        assert rule_error(services.update_record, planner, case, {"gtin": value}) == (
            "gtin_locked",
            case_locked_message("MM-1"),
        )
    # Miktar değişiyor, koli GTIN'i aynı (verilmedi, aynı yazıldı) ya da siliniyor.
    for change in (
        {"factor_to_base": Decimal(24)},
        {"factor_to_base": Decimal(24), "gtin": CASE_GTIN},
        {"factor_to_base": Decimal(24), "gtin": f" {CASE_GTIN} "},
        {"factor_to_base": Decimal(24), "gtin": ""},
    ):
        assert rule_error(services.update_record, planner, case, change) == (
            "case_gtin_required",
            REQUIRED,
        )
    # Yeni koli GTIN'i de biçim ve tekillik kurallarından geçer.
    assert rule_error(change_pack, planner, case, "24", "28690000000017")[0] == "invalid_gtin"
    make_material(planner, "MM-2", gtin=OTHER_GTIN)
    assert rule_error(change_pack, planner, case, "24", OTHER_GTIN) == (
        "gtin_taken",
        "Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: MM-2.",
    )
    assert rule_error(change_pack, planner, case, "24", GTIN)[0] == "gtin_taken"  # kendi ürünü
    case.refresh_from_db()
    assert (case.factor_to_base, case.gtin) == (Decimal(12), CASE_GTIN)
    assert not RetiredGtin.objects.exists()

    saved = change_pack(planner, case, "24", NEW_CASE)
    saved.refresh_from_db()
    assert (saved.factor_to_base, saved.gtin) == (Decimal(24), NEW_CASE)
    retired = RetiredGtin.objects.get()
    assert (retired.conversion, retired.gtin, retired.factor_to_base, retired.replaced_by) == (
        case,
        CASE_GTIN,
        Decimal(12),
        NEW_CASE,
    )
    # Yeni koli GTIN'i de kilitli: miktar yine yalnız yeni GTIN'le değişir.
    assert services.case_gtin_locked(saved)
    assert rule_error(services.update_record, planner, saved, {"factor_to_base": Decimal(12)}) == (
        "case_gtin_required",
        REQUIRED,
    )


def test_pack_change_archives_the_old_case_gtin_with_audit(planner, invariants) -> None:
    case = locked_case(planner)
    change_pack(planner, case, "24", NEW_CASE, note="Yeni koli düzeni")
    retired = RetiredGtin.objects.get()
    assert retired.created_by == planner and retired.updated_by == planner
    log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(RetiredGtin), object_id=retired.pk
    )
    assert (log.action, log.actor, log.note) == (
        AuditLog.Action.CREATE,
        planner,
        "Yeni koli düzeni",
    )
    assert log.changes == {
        "conversion": [None, case.pk],
        "gtin": [None, CASE_GTIN],
        "factor_to_base": [None, "12.000000"],
        "replaced_by": [None, NEW_CASE],
    }
    change = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(MaterialUnitConversion),
        object_id=case.pk,
        action=AuditLog.Action.UPDATE,
    ).get()
    assert change.note == "Yeni koli düzeni" and change.actor == planner
    assert change.changes == {
        "factor_to_base": ["12.000000", "24.000000"],
        "gtin": [CASE_GTIN, NEW_CASE],
    }


def test_case_quantity_is_compared_as_a_decimal(client_for, planner, invariants) -> None:
    """12 ile 12.000000 aynı miktardır: değişiklik sayılmaz (GTIN'siz kayıt geçer, yeni GTIN'le
    kayıt kilit hatası alır); 12.000001 değişikliktir."""
    case = locked_case(planner)
    for same in (Decimal("12.000000"), Decimal("12.0"), Decimal(12), 12, "12.00"):
        services.update_record(planner, case, {"factor_to_base": same, "gtin": CASE_GTIN})
        change = {"factor_to_base": same, "gtin": NEW_CASE}
        assert rule_error(services.update_record, planner, case, change)[0] == "gtin_locked"
    change = {"factor_to_base": Decimal("12.000001")}
    assert rule_error(services.update_record, planner, case, change)[0] == "case_gtin_required"
    client = client_for(PLANLAMA)
    url = f"{CONVERSIONS}{case.pk}/"
    same = client.patch(url, {"factor_to_base": "12.000000", "gtin": CASE_GTIN}, format="json")
    assert same.status_code == 200, same.json()
    assert not RetiredGtin.objects.exists()
    assert updates(case, "factor_to_base") == []


def test_unlocked_conversions_change_their_case_quantity_as_today(planner, invariants) -> None:
    """Lotu olmayan mamulde, koli GTIN'i boş ya da geçersiz (okutulamayan eski veri) dönüşümde ve
    KOLI dışı birimde miktar yeni GTIN'siz değişir; arşiv satırı yazılmaz."""
    no_lots = add_case(planner, make_material(planner, "MM-1"))
    services.update_record(planner, no_lots, {"factor_to_base": Decimal(24)})
    change_pack(planner, no_lots, "6", NEW_CASE)

    with_lots = make_material(planner, "MM-2", gtin=OTHER_GTIN)
    add_lot(with_lots, "D-2")
    blank = add_case(planner, with_lots, "")
    pallet = services.create_record(
        planner,
        MaterialUnitConversion,
        {"material": with_lots, "unit": unit("PALET"), "factor_to_base": Decimal(480)},
    )
    services.update_record(planner, blank, {"factor_to_base": Decimal(24)})
    services.update_record(planner, pallet, {"factor_to_base": Decimal(960)})
    services.update_record(planner, blank, {"gtin": "28690000000023"})  # ilk kez girilir

    legacy = make_material(planner, "MM-3", gtin="8690000000036")
    add_lot(legacy, "D-3")
    # Eski veri: denetimsiz girilmiş, kontrol hanesi yanlış koli GTIN'i (okutulamaz, kilitlenmez).
    bad = MaterialUnitConversion.objects.create(
        material=legacy, unit=unit("KOLI"), factor_to_base=Decimal(12), gtin="18690000000010"
    )
    assert not services.case_gtin_locked(bad)
    services.update_record(planner, bad, {"factor_to_base": Decimal(24)})
    change_pack(planner, bad, "36", THIRD_CASE)  # düzeltme serbest; geçersiz GTIN arşivlenmez
    assert not RetiredGtin.objects.exists()


# --- eski koli GTIN'i bir daha verilmez ----------------------------------------------------------


def test_archived_case_gtin_is_never_given_again(planner, invariants) -> None:
    case = locked_case(planner, gtin="")  # ürün GTIN'i yok: kendi ürün GTIN'i de denenir
    material = case.material
    change_pack(planner, case, "24", NEW_CASE)
    message = ("gtin_taken", archived_message("MM-1"))
    # Kendi malzemesine de (eski miktarıyla koliye, ürün GTIN'i olarak) geri verilmez.
    assert rule_error(change_pack, planner, case, "12", CASE_GTIN) == message
    assert rule_error(services.update_record, planner, material, {"gtin": CASE_GTIN}) == message
    # Başka malzemeye: yeni malzemede, ürün GTIN'i ya da koli GTIN'i olarak.
    assert rule_error(make_material, planner, "MM-2", gtin=CASE_GTIN) == message
    other = make_material(planner, "MM-3", gtin=OTHER_GTIN)
    assert rule_error(services.update_record, planner, other, {"gtin": CASE_GTIN}) == message
    assert rule_error(add_case, planner, other, CASE_GTIN) == message
    other_case = add_case(planner, other, "18690000000026")
    assert rule_error(services.update_record, planner, other_case, {"gtin": CASE_GTIN}) == message
    raw = make_material(planner, "HM-1", Material.Type.RAW, gtin="")
    assert rule_error(services.update_record, planner, raw, {"gtin": CASE_GTIN}) == message
    case.refresh_from_db()
    assert case.gtin == NEW_CASE and RetiredGtin.objects.count() == 1


def test_archived_gtin_is_checked_in_its_14_digit_form(planner, invariants) -> None:
    """GTIN-13 koli GTIN'i arşivde 14 haneli normal biçimde durur; iki yazımı da reddedilir."""
    case = locked_case(planner, case_gtin=OTHER_GTIN)  # koli GTIN'i GTIN-13
    # Aynı GTIN'i 14 hane yazmak yeni GTIN sayılmaz.
    change = {"factor_to_base": Decimal(24), "gtin": "0" + OTHER_GTIN}
    assert rule_error(services.update_record, planner, case, change)[0] == "case_gtin_required"
    change_pack(planner, case, "24", "8690000000036")  # yeni koli GTIN'i de GTIN-13
    retired = RetiredGtin.objects.get()
    assert (retired.gtin, retired.replaced_by) == ("0" + OTHER_GTIN, "08690000000036")
    for value in (OTHER_GTIN, "0" + OTHER_GTIN):
        assert rule_error(make_material, planner, "MM-2", gtin=value) == (
            "gtin_taken",
            archived_message("MM-1"),
        )


def test_second_pack_change_chains_two_archived_gtins(planner, invariants) -> None:
    case = locked_case(planner)
    material = case.material
    first = timezone.now()
    change_pack(planner, case, "24", NEW_CASE)
    between = timezone.now()
    change_pack(planner, case, "36", THIRD_CASE)
    rows = list(RetiredGtin.objects.values_list("gtin", "factor_to_base", "replaced_by"))
    assert rows == [(CASE_GTIN, Decimal(12), NEW_CASE), (NEW_CASE, Decimal(24), THIRD_CASE)]
    case.refresh_from_db()
    assert (case.factor_to_base, case.gtin) == (Decimal(36), THIRD_CASE)
    for value in (CASE_GTIN, NEW_CASE):
        assert rule_error(change_pack, planner, case, "48", value)[0] == "gtin_taken"
        assert rule_error(make_material, planner, f"MM-X{value[0]}", gtin=value)[0] == "gtin_taken"
    # Yürürlükteki koli GTIN'i: değişiklikten önce, arada ve sonra.
    assert services.case_gtin_at(material, first) == CASE_GTIN
    assert services.case_gtin_at(material, between) == NEW_CASE
    assert services.case_gtin_at(material, timezone.now()) == THIRD_CASE
    assert services.case_gtin_at(material, None) == THIRD_CASE
    # Öneri iki eski GTIN'i ve bugünkünü atlar.
    assert services.case_gtin_suggestion(material).gtin == FOURTH_CASE


def test_suggestions_skip_archived_gtins(make_user, planner, invariants) -> None:
    services.update_gs1_settings(
        make_user(ADMIN), note="GS1 üyeliği", company_prefix=PREFIX, next_item_reference=1
    )
    # Firma önekli GTIN-13 koli GTIN'i (ürün referansı 1) arşive düşer.
    case = locked_case(planner, case_gtin=gtin13(1))
    assert services.get_label_settings().next_item_reference == 2
    assert services.case_gtin_suggestion(case.material).gtin == CASE_GTIN
    change_pack(planner, case, "24", CASE_GTIN)
    assert "0" + gtin13(1) in services.used_gtin14s(start="0" + PREFIX)
    assert services.used_gtin14s(among=["0" + gtin13(1), "0" + gtin13(2)]) == {"0" + gtin13(1)}
    # Sayaç geri alınsa da arşivdeki GTIN önerilmez; koli önerisi kullanılanı atlar.
    services.update_gs1_settings(make_user(ADMIN), note="Sayaç", next_item_reference=1)
    assert services.gtin_suggestion().gtin == gtin13(2)
    assert services.case_gtin_suggestion(case.material).gtin == NEW_CASE
    change_pack(planner, case, "36", NEW_CASE)
    assert services.case_gtin_suggestion(case.material).gtin == THIRD_CASE  # 1 arşivde, 2 güncel


def test_case_gtin_at(planner, invariants) -> None:
    """Yürürlükteki koli GTIN'i: o andan sonra arşivlenmiş en eski GTIN, yoksa bugünkü."""
    no_case = make_material(planner, "MM-9", gtin="")
    assert services.case_gtin_at(no_case, timezone.now()) == ""  # KOLI dönüşümü yok
    case = locked_case(planner)
    material = case.material
    assert services.case_gtin_at(material, timezone.now() - timedelta(days=1)) == CASE_GTIN
    change_pack(planner, case, "24", NEW_CASE)
    retired = RetiredGtin.objects.get()
    assert services.case_gtin_at(material, retired.created_at - timedelta(microseconds=1)) == (
        CASE_GTIN
    )
    assert services.case_gtin_at(material, retired.created_at) == NEW_CASE  # değiştiği an: yeni
    # Pasif KOLI dönüşümü de sayılır (basılmış etiketler aynı GTIN'le okunur).
    services.set_active(planner, case, False)
    assert services.case_gtin_at(material, retired.created_at) == NEW_CASE
    assert services.case_gtin_at(material, retired.created_at - timedelta(days=1)) == CASE_GTIN


def test_case_gtin_at_reads_the_current_gtin_before_the_archive(
    planner, invariants, monkeypatch
) -> None:
    """Koli düzeni iki okuma arasında değişse de eski lot eski GTIN'ini alır: önce bugünkü GTIN,
    sonra arşiv okunur (yeni GTIN ve arşiv satırı birlikte yazılır). Ters sırada okunursa açılmış
    lotun etiketine yeni koli GTIN'i basılırdı."""
    case = locked_case(planner)
    lot_time = timezone.now()
    original = services.case_gtin
    changed: list[bool] = []

    def change_then_read(material: Material) -> str:
        if not changed:
            changed.append(True)
            change_pack(planner, case, "24", NEW_CASE)  # tam okuma sırasında koli düzeni değişir
        return original(material)

    monkeypatch.setattr(services, "case_gtin", change_then_read)
    assert services.case_gtin_at(case.material, lot_time) == CASE_GTIN
    assert changed == [True]


def test_case_factor_at(planner, invariants) -> None:
    """Yürürlükteki koli içi miktar: o andan sonra arşivlenmiş en eski GTIN'in miktarı, yoksa
    bugünkü aktif KOLI dönüşümünün katsayısı; koli dönüşümü yoksa None (irsaliyede koli sayısı)."""
    no_case = make_material(planner, "MM-9", gtin="")
    assert services.case_factor_at(no_case, timezone.now()) is None
    case = locked_case(planner)
    material = case.material
    before = timezone.now()
    change_pack(planner, case, "24", NEW_CASE)
    between = timezone.now()
    change_pack(planner, case, "36", THIRD_CASE)
    assert services.case_factor_at(material, before) == Decimal(12)
    assert services.case_factor_at(material, between) == Decimal(24)
    assert services.case_factor_at(material, timezone.now()) == Decimal(36)
    assert services.case_factor_at(material, None) == Decimal(36)


def test_non_positive_case_quantity_gets_the_field_error(planner, invariants) -> None:
    """Sıfır ya da eksi koli içi miktarı alan doğrulaması reddeder; koli GTIN'i kuralları yanıltıcı
    hata (case_gtin_required, gtin_locked) vermez ve arşiv satırı yazılmaz."""
    case = locked_case(planner)
    for factor, gtin in (("-12", ""), ("0", CASE_GTIN), ("-24", NEW_CASE)):
        with pytest.raises(ValidationError) as exc:
            services.update_record(planner, case, {"factor_to_base": Decimal(factor), "gtin": gtin})
        assert "sıfırdan büyük" in str(exc.value)
    case.refresh_from_db()
    assert (case.factor_to_base, case.gtin) == (Decimal(12), CASE_GTIN)
    assert not RetiredGtin.objects.exists()


def test_type_of_a_material_with_lots_does_not_change_to_or_from_finished(
    client_for, planner, invariants
) -> None:
    """Lotu olan malzemenin türü mamulden ya da mamule değişmez (CUMHUR, 2026-11-05): ayrı bir
    istekte tür değiştirilerek GTIN kilidi, koli içi miktar kuralı ve eski koli GTIN'i arşivi
    atlanamaz. Mamul olmayan türler arasında ve lotsuz malzemede değişiklik serbest."""
    finished = locked_case(planner).material
    code, message = rule_error(
        services.update_record, planner, finished, {"material_type": Material.Type.RAW}
    )
    assert code == "material_type_locked"
    assert message == (
        "MM-1: lotu olan malzemenin türü mamulden ya da mamule değiştirilemez (GTIN kilidi, koli "
        "içi miktar kuralı ve eski koli GTIN'leri mamule bağlıdır)."
    )
    raw = make_material(planner, "HM-1", Material.Type.RAW, gtin=OTHER_GTIN)
    add_lot(raw, "H-1")
    assert (
        rule_error(services.update_record, planner, raw, {"material_type": Material.Type.FINISHED})[
            0
        ]
        == "material_type_locked"
    )
    changed = services.update_record(planner, raw, {"material_type": Material.Type.PACKAGING})
    assert changed.material_type == Material.Type.PACKAGING
    fresh = make_material(planner, "MM-5", gtin="")
    assert services.update_record(
        planner, fresh, {"material_type": Material.Type.RAW}
    ).material_type
    response = client_for(PLANLAMA).patch(
        f"{MATERIALS}{finished.pk}/", {"material_type": "RAW"}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "material_type_locked"
    finished.refresh_from_db()
    assert finished.material_type == Material.Type.FINISHED

    # Excel içe aktarma da aynı kuralla: güncelleme satırı hata olur, hiçbir şey yazılmaz.
    def upload() -> io.BytesIO:
        buffer = io.BytesIO("Kod,Ad,Tür,Temel birim\nMM-1,Malzeme MM-1,Hammadde,ADET\n".encode())
        buffer.name = "malzeme.csv"
        return buffer

    report = importers.preview_import("materials", upload(), "malzeme.csv")
    assert [error["message"] for error in report.rows[0].errors] == [message]
    finished.refresh_from_db()
    assert finished.material_type == Material.Type.FINISHED


def test_admin_keeps_the_type_of_a_material_with_lots(planner, invariants, rf) -> None:
    """Yönetim panelinde lotu olan malzemenin türü salt okunurdur (panel kaydı servisleri atlar)."""
    model_admin = MaterialAdmin(Material, django_admin.site)
    request = rf.get("/admin/")
    with_lots = locked_case(planner).material
    without_lots = make_material(planner, "MM-5", gtin="")
    assert "material_type" in model_admin.get_readonly_fields(request, with_lots)
    assert "material_type" not in model_admin.get_readonly_fields(request, without_lots)
    assert "material_type" not in model_admin.get_readonly_fields(request, None)


def test_case_gtin_at_reads_only_the_materials_own_archive(planner, invariants) -> None:
    """Yürürlükteki koli GTIN'i yalnız malzemenin kendi KOLI dönüşümünün arşivinden okunur: bir
    mamulün koli içi miktar değişikliği, ondan önceki bir anda başka malzemenin koli GTIN'ini (koli
    GTIN'i yoksa boş sonucu) değiştirmez; iki malzemenin arşivi ayrı zincirdir."""
    case = locked_case(planner)
    other = locked_case(planner, "MM-2", gtin=OTHER_GTIN, case_gtin="18690000000026")
    no_case = make_material(planner, "MM-3", gtin="8690000000036")  # KOLI dönüşümü yok
    add_lot(no_case, "D-MM-3")
    before = timezone.now()
    change_pack(planner, case, "24", NEW_CASE)
    assert services.case_gtin_at(case.material, before) == CASE_GTIN
    assert services.case_gtin_at(other.material, before) == "18690000000026"
    assert services.case_gtin_at(no_case, before) == ""
    # İkinci malzemenin kendi değişikliği yalnız kendi zincirine düşer.
    between = timezone.now()
    change_pack(planner, other, "6", "28690000000023")
    for when in (before, between):
        assert services.case_gtin_at(other.material, when) == "18690000000026"
        assert services.case_gtin_at(no_case, when) == ""
    assert services.case_gtin_at(case.material, between) == NEW_CASE
    assert services.case_gtin_at(other.material, timezone.now()) == "28690000000023"
    assert list(RetiredGtin.objects.values_list("conversion", "gtin")) == [
        (case.pk, CASE_GTIN),
        (other.pk, "18690000000026"),
    ]


# --- API -----------------------------------------------------------------------------------------


def test_pack_change_api(client_for, make_user, invariants) -> None:
    planner = make_user(PLANLAMA, full_name="Ayşe Planlama")
    case = locked_case(planner)
    url = f"{CONVERSIONS}{case.pk}/"
    for role in (DEPO, URETIM):
        denied = client_for(role).patch(url, {"factor_to_base": "24", "gtin": NEW_CASE})
        assert denied.status_code == 403
    client = APIClient()
    client.force_authenticate(planner)
    required = client.patch(url, {"factor_to_base": "24"}, format="json")
    assert required.status_code == 400
    assert required.json() == {"code": "case_gtin_required", "detail": REQUIRED}
    locked = client.patch(url, {"gtin": NEW_CASE}, format="json")
    assert locked.status_code == 400
    assert locked.json() == {"code": "gtin_locked", "detail": case_locked_message("MM-1")}
    assert not RetiredGtin.objects.exists()

    saved = client.patch(url, {"factor_to_base": "24", "gtin": NEW_CASE}, format="json")
    assert saved.status_code == 200, saved.json()
    body = saved.json()
    assert (body["factor_to_base"], body["gtin"], body["gtin_locked"]) == (
        "24.000000",
        NEW_CASE,
        True,
    )
    retired = RetiredGtin.objects.get()
    first = {
        "gtin": CASE_GTIN,
        "factor_to_base": "12.000000",
        "replaced_by": NEW_CASE,
        "retired_at": timezone.localtime(retired.created_at).isoformat(),
        "retired_by_name": "Ayşe Planlama",
    }
    assert body["retired_gtins"] == [first]

    admin = client_for(ADMIN)
    again = admin.put(
        url,
        {"material": case.material_id, "unit": case.unit_id, "factor_to_base": "6", "gtin": ""},
        format="json",
    )
    assert again.status_code == 400 and again.json()["code"] == "case_gtin_required"
    again = admin.patch(url, {"factor_to_base": "6", "gtin": THIRD_CASE}, format="json")
    assert again.status_code == 200, again.json()
    gtins = [row["gtin"] for row in again.json()["retired_gtins"]]
    assert gtins == [NEW_CASE, CASE_GTIN]  # en yeniden eskiye
    assert admin.get(url).json()["retired_gtins"] == again.json()["retired_gtins"]
    detail = admin.get(f"{MATERIALS}{case.material_id}/").json()
    assert detail["conversions"][0]["retired_gtins"] == again.json()["retired_gtins"]


def test_retired_gtin_time_is_shown_in_turkish_time(client_for, planner, invariants) -> None:
    case = locked_case(planner)
    change_pack(planner, case, "24", NEW_CASE)
    moment = datetime(2026, 11, 5, 10, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
    RetiredGtin.objects.update(created_at=moment)
    row = client_for(DEPO).get(f"{CONVERSIONS}{case.pk}/").json()["retired_gtins"][0]
    assert row["retired_at"] == "2026-11-05T10:00:00+03:00"


def test_conversion_import_cannot_change_a_locked_case_quantity(planner, invariants) -> None:
    """İçe aktarmada koli GTIN'i sütunu yok: kilitli koli GTIN'inde miktar değişikliği satır hatası
    olur, hiçbir şey yazılmaz."""
    case = locked_case(planner)
    unlocked = add_case(planner, make_material(planner, "MM-2", gtin=OTHER_GTIN), NEW_CASE)

    def upload(rows: str) -> io.BytesIO:
        buffer = io.BytesIO(f"Malzeme kodu,Birim,Temel birim karşılığı\n{rows}".encode())
        buffer.name = "donusum.csv"
        return buffer

    rows = "MM-1,KOLI,24\nMM-2,KOLI,24\n"
    report = importers.preview_import("conversions", upload(rows), "donusum.csv")
    assert [row.errors for row in report.rows] == [[{"column": "", "message": REQUIRED}], []]
    with pytest.raises(importers.ImportHasErrors):
        importers.run_import(planner, "conversions", upload(rows), "donusum.csv")
    case.refresh_from_db()
    unlocked.refresh_from_db()
    assert case.factor_to_base == unlocked.factor_to_base == Decimal(12)
    report = importers.run_import(planner, "conversions", upload("MM-2,KOLI,24\n"), "donusum.csv")
    unlocked.refresh_from_db()
    assert unlocked.factor_to_base == Decimal(24) and not RetiredGtin.objects.exists()


# --- eşzamanlılık --------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reusing_a_case_gtin_being_archived_waits_for_the_pack_change(make_user) -> None:
    """Koli içi miktar değişikliği GTIN kilidini işlem sonuna kadar tutar: eski koli GTIN'ini aynı
    anda başka bir malzemeye yazan işlem kilidi bekler, arşiv satırı yazılıp işlem bitince
    `gtin_taken` (arşivde) alır. Kilitsiz ya da arşiv denetimi olmadan eski GTIN boşta görünür ve
    yeniden verilirdi."""
    actor = make_user(PLANLAMA)
    case_unit = _count_units()
    material = make_material(actor, "MM-1")
    case = services.create_record(
        actor,
        MaterialUnitConversion,
        {"material": material, "unit": case_unit, "factor_to_base": Decimal(12), "gtin": CASE_GTIN},
    )
    add_lot(material, "D-1")
    changed, release = threading.Event(), threading.Event()
    outcome: dict[str, str] = {}

    def change() -> None:
        try:
            with transaction.atomic():
                _bound_lock_waits()
                change_pack(actor, case, "24", NEW_CASE)
                changed.set()
                release.wait(10)
            outcome["pack"] = "ok"
        except Exception as exc:
            outcome["pack"] = f"{type(exc).__name__}: {exc}"
        finally:
            changed.set()
            connection.close()

    def reuse() -> None:
        try:
            with transaction.atomic():
                _bound_lock_waits()
                make_material(actor, "MM-2", gtin=CASE_GTIN)
            outcome["reuse"] = "ok"
        except BusinessRuleError as exc:
            outcome["reuse"] = exc.message
        except Exception as exc:
            outcome["reuse"] = f"{type(exc).__name__}: {exc}"
        finally:
            connection.close()

    changer = threading.Thread(target=change)
    changer.start()
    reuser = None
    try:
        assert changed.wait(10)
        reuser = threading.Thread(target=reuse)
        reuser.start()
        assert _waiting_for_gtin_lock(), "eski koli GTIN'ini yazan işlem GTIN kilidinde beklemedi"
    finally:
        release.set()
        changer.join(30)
        if reuser is not None:
            reuser.join(30)
    assert outcome == {"pack": "ok", "reuse": archived_message("MM-1")}
    assert not Material.objects.filter(code="MM-2").exists()
    assert RetiredGtin.objects.get().gtin == CASE_GTIN
    assert_stock_invariants()
