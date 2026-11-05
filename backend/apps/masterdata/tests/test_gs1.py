"""GS1 (Kodlama sistematiği, Paket 2, Adım 7): GS1 ayarları, GTIN kuralları, GTIN önerileri.

Lot ve palet etiketi gerektiren durumlar (GTIN kilidi, SSCC çakışması, koli ve palet etiketi)
`inventory/tests/test_gs1_labels.py` içindedir; kilidin kapsamı (yalnız mamul), koli içi miktar
değişikliği ve eski koli GTIN'leri (3. tur) `test_pack_change.py` içindedir.
"""

import threading
import time
from decimal import Decimal
from typing import Any

import pytest
from django.contrib import admin as django_admin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.labels import gs1_check_digit
from apps.core.models import AuditLog
from apps.core.roles import ADMIN, DEPO, DOLUM, PLANLAMA, URETIM
from apps.masterdata import services
from apps.masterdata.admin import MaterialUnitConversionInline
from apps.masterdata.models import LabelSettings, Material, MaterialUnitConversion, UnitOfMeasure
from apps.masterdata.tests.factories import MaterialFactory, MaterialUnitConversionFactory, unit

pytestmark = pytest.mark.django_db

GS1 = "/api/v1/masterdata/gs1-settings/"
SUGGEST = "/api/v1/masterdata/gtin-suggestion/"
LABEL_SETTINGS = "/api/v1/masterdata/label-settings/"
CONVERSIONS = "/api/v1/masterdata/conversions/"
PREFIX = "8691234"
GTIN = "8690000000012"
CASE_GTIN = "18690000000019"  # GTIN'in gösterge hanesi 1 ile koli GTIN'i
# Gövdesi ASCII olmayan rakam, kontrol hanesi ASCII "2" (869000000001 → 8690000000012): eski
# `str.isdigit` denetimi bunları kabul ederdi (int() bu rakamları da okur).
NON_ASCII_BODIES = [
    "869000000001".translate(str.maketrans("0123456789", digits)) + "2"
    for digits in ("٠١٢٣٤٥٦٧٨٩", "０１２３４５６７８９")  # Arapça-Hint, tam genişlik
]


@pytest.fixture
def admin(make_user):
    return make_user(ADMIN)


@pytest.fixture
def planner(make_user):
    return make_user(PLANLAMA)


def finished(code: str, **extra: Any) -> dict[str, Any]:
    return {
        "code": code,
        "name": f"Mamul {code}",
        "material_type": Material.Type.FINISHED,
        "base_unit": unit("ADET"),
        **extra,
    }


def add_conversion(actor, material, gtin: str = "", unit_code: str = "KOLI"):
    return services.create_record(
        actor,
        MaterialUnitConversion,
        {
            "material": material,
            "unit": unit(unit_code),
            "factor_to_base": Decimal(12),
            "gtin": gtin,
        },
    )


def gs1(actor, **changes: Any) -> LabelSettings:
    return services.update_gs1_settings(actor, note="GS1 üyeliği", **changes)


def rule_error(call, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(BusinessRuleError) as exc:
        call(*args, **kwargs)
    return exc.value.code


# --- GS1 ayarları ------------------------------------------------------------------------------


def test_gs1_settings_are_admin_only_and_need_a_note(admin, planner) -> None:
    for actor in (planner, None):
        with pytest.raises(PermissionDenied) as denied:
            services.update_gs1_settings(
                actor,  # type: ignore[arg-type]
                note="x",
                company_prefix=PREFIX,
            )
        assert str(denied.value) == "GS1 ayarlarını yalnızca sistem yöneticisi değiştirir."
    for note in ("", "   "):
        assert rule_error(
            services.update_gs1_settings, admin, note=note, company_prefix=PREFIX
        ) == ("note_required")
    assert services.get_label_settings().gs1_company_prefix == ""


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"company_prefix": "86912"}, "invalid_gs1_prefix"),
        ({"company_prefix": "8691234567890"}, "invalid_gs1_prefix"),
        ({"company_prefix": "86912A4"}, "invalid_gs1_prefix"),
        ({"company_prefix": "٨٦٩١٢٣٤"}, "invalid_gs1_prefix"),  # Arapça-Hint rakamları
        ({"extension_digit": 10}, "invalid_extension_digit"),
        ({"extension_digit": -1}, "invalid_extension_digit"),
        ({"next_item_reference": 5}, "invalid_item_reference"),  # önek yok
        ({"company_prefix": PREFIX, "next_item_reference": 100_000}, "invalid_item_reference"),
        ({"company_prefix": PREFIX, "next_item_reference": -1}, "invalid_item_reference"),
        ({"company_prefix": "869123456789", "next_item_reference": 1}, "invalid_item_reference"),
    ],
)
def test_gs1_settings_are_validated(admin, changes, code) -> None:
    assert rule_error(gs1, admin, **changes) == code
    row = services.get_label_settings()
    assert (row.gs1_company_prefix, row.sscc_extension_digit, row.next_item_reference) == (
        "",
        0,
        None,
    )


def test_gs1_settings_change_is_audited_with_its_note(admin, make_user) -> None:
    row = gs1(admin, company_prefix=f" {PREFIX} ", extension_digit=3, next_item_reference=12)
    assert (row.gs1_company_prefix, row.sscc_extension_digit, row.next_item_reference) == (
        PREFIX,
        3,
        12,
    )
    log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(LabelSettings), object_id=row.pk
    )
    assert log.note == "GS1 üyeliği" and log.actor == admin
    assert log.changes["gs1_company_prefix"] == ["", PREFIX]
    assert log.changes["sscc_extension_digit"] == [0, 3]
    assert log.changes["next_item_reference"] == [None, 12]

    state = services.get_gs1_settings()
    assert state.company_prefix == PREFIX and state.extension_digit == 3
    assert state.sscc_enabled and state.gtin_suggestion_enabled
    assert state.item_reference_digits == 5 and state.next_item_reference == 12
    assert state.updated_by_name == (admin.full_name or admin.username)
    assert state.updated_at == log.timestamp
    # SSCC sayacı (palet etiketi) son GS1 değişikliği sayılmaz.
    services.next_sscc(make_user(DOLUM))
    assert services.get_gs1_settings().updated_at == log.timestamp
    assert services.get_gs1_settings().updated_by_name == state.updated_by_name


def test_prefix_change_restarts_sscc_serial_and_clears_item_reference(admin) -> None:
    gs1(admin, company_prefix=PREFIX, next_item_reference=7)
    services.next_sscc(None)
    services.next_sscc(None)
    assert services.get_label_settings().next_sscc_serial == 3
    # Yeni önekte basılmış SSCC yok: 1'den başlar. Ürün referansı önekin numaralamasıdır, silinir.
    row = gs1(admin, company_prefix="8697777")
    assert row.next_sscc_serial == 1 and row.next_item_reference is None
    # Aynı istekte verilen referans korunur.
    row = gs1(admin, company_prefix=PREFIX, next_item_reference=9)
    assert row.next_item_reference == 9
    # Yalnız uzantı hanesi değişince de seri no yeniden hesaplanır; referans kalır.
    services.next_sscc(None)
    row = gs1(admin, extension_digit=4)
    assert row.next_sscc_serial == 1 and row.next_item_reference == 9
    # Önek silinince SSCC ve GTIN önerisi kapanır.
    row = gs1(admin, company_prefix="")
    assert row.next_item_reference is None and not services.sscc_enabled()
    assert services.get_gs1_settings().item_reference_digits is None


def test_label_settings_no_longer_change_gs1_fields(admin, client_for) -> None:
    for field, value in (("gs1_company_prefix", PREFIX), ("sscc_extension_digit", 2)):
        with pytest.raises(ValueError):
            services.update_label_settings(admin, {field: value})
    client = client_for(ADMIN)
    response = client.put(
        LABEL_SETTINGS,
        {"company_name": "Inncos", "gs1_company_prefix": PREFIX, "sscc_extension_digit": 2},
        format="json",
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["company_name"] == "Inncos"
    assert body["gs1_company_prefix"] == "" and body["sscc_extension_digit"] == 0


def test_gs1_settings_api(client_for, admin) -> None:
    assert APIClient().get(GS1).status_code == 401
    for role in (PLANLAMA, DEPO):
        client = client_for(role)
        assert client.get(GS1).status_code == 403
        denied = client.patch(GS1, {"company_prefix": PREFIX, "note": "x"}, format="json")
        assert denied.status_code == 403

    client = APIClient()
    client.force_authenticate(admin)
    initial = client.get(GS1).json()
    assert initial == {
        "company_prefix": "",
        "extension_digit": 0,
        "next_sscc_serial": 1,
        "next_item_reference": None,
        "sscc_enabled": False,
        "gtin_suggestion_enabled": False,
        "item_reference_digits": None,
        "updated_at": None,
        "updated_by_name": "",
    }
    missing_note = client.patch(GS1, {"company_prefix": PREFIX}, format="json")
    assert missing_note.status_code == 400 and missing_note.json()["code"] == "note_required"
    bad = client.patch(GS1, {"company_prefix": "86912", "note": "x"}, format="json")
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_gs1_prefix"
    assert bad.json()["detail"] == "GS1 firma öneki 6-12 haneli bir sayı olmalıdır."

    body = {"company_prefix": PREFIX, "extension_digit": 2, "next_item_reference": 12, "note": "x"}
    saved = client.patch(GS1, body, format="json")
    assert saved.status_code == 200, saved.json()
    data = saved.json()
    assert (data["company_prefix"], data["extension_digit"], data["next_item_reference"]) == (
        PREFIX,
        2,
        12,
    )
    assert data["sscc_enabled"] and data["gtin_suggestion_enabled"]
    assert data["item_reference_digits"] == 5 and data["next_sscc_serial"] == 1
    assert data["updated_at"] and data["updated_by_name"] == (admin.full_name or admin.username)
    # Verilmeyen alan değişmez; referans null ile silinir.
    cleared = client.patch(GS1, {"next_item_reference": None, "note": "kapat"}, format="json")
    assert cleared.status_code == 200
    assert cleared.json()["company_prefix"] == PREFIX and cleared.json()["extension_digit"] == 2
    assert cleared.json()["next_item_reference"] is None
    assert cleared.json()["gtin_suggestion_enabled"] is False


# --- GTIN kuralları ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gtin",
    [
        "8690000000013",  # kontrol hanesi yanlış
        "12345",
        "869000000001²",  # üst simge rakam
        "8690000000012".translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")),
        *NON_ASCII_BODIES,
        "869000000000120",  # 15 hane
    ],
)
def test_gtin_must_be_ascii_digits_with_a_valid_check_digit(planner, gtin) -> None:
    assert rule_error(services.create_record, planner, Material, finished("MM-1", gtin=gtin)) == (
        "invalid_gtin"
    )
    material = services.create_record(planner, Material, finished("MM-2"))
    assert rule_error(add_conversion, planner, material, gtin) == "invalid_gtin"


def test_gtin_is_unique_across_product_and_case_gtins(planner) -> None:
    first = services.create_record(planner, Material, finished("MM-1", gtin=GTIN))
    second = services.create_record(planner, Material, finished("MM-2", gtin="8690000000029"))
    case = add_conversion(planner, second, CASE_GTIN)
    assert case.gtin == CASE_GTIN

    # Ürün GTIN'i başka malzemenin koli GTIN'i olamaz; koli GTIN'i ürün GTIN'i olamaz (14 hane).
    taken = rule_error(services.create_record, planner, Material, finished("MM-3", gtin=CASE_GTIN))
    assert taken == "gtin_taken"
    third = services.create_record(planner, Material, finished("MM-3"))
    for value in (GTIN, "0" + GTIN):
        with pytest.raises(BusinessRuleError) as exc:
            add_conversion(planner, third, value)
        assert exc.value.code == "gtin_taken"
        assert exc.value.message == (
            f"Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: {first.code}."
        )
    with pytest.raises(BusinessRuleError) as exc:
        add_conversion(planner, third, CASE_GTIN)
    assert exc.value.message.endswith(f"{second.code} koli dönüşümü.")
    # Başka malzemenin koli GTIN'i ürün GTIN'i olamaz; malzemenin kendi ürün GTIN'i de koli GTIN'i
    # olamaz (koli ayrı ticari üründür; mesajı test_own_product_and_case_gtin_must_differ'da).
    assert rule_error(services.update_record, planner, third, {"gtin": CASE_GTIN}) == "gtin_taken"
    fourth = services.create_record(planner, Material, finished("MM-4", gtin="8690000000036"))
    assert rule_error(add_conversion, planner, fourth, "8690000000036") == "gtin_taken"

    # Pasif kaydın GTIN'i de ayrılmış kalır.
    services.set_active(planner, first, False)
    assert rule_error(
        services.create_record, planner, Material, finished("MM-5", gtin="0" + GTIN)
    ) == ("gtin_taken")
    # Kaydın kendi GTIN'i çakışma sayılmaz.
    services.update_record(planner, second, {"name": "Yeni ad"})
    services.update_record(planner, case, {"factor_to_base": Decimal(24)})
    case.refresh_from_db()
    assert case.gtin == CASE_GTIN and case.factor_to_base == Decimal(24)


def test_own_product_and_case_gtin_must_differ(planner) -> None:
    """Koli ayrı bir ticari üründür: malzemenin koli GTIN'i kendi ürün GTIN'i olamaz, ürün GTIN'i
    de kendi koli GTIN'i olamaz. Kod `gtin_taken`; mesaj "başka bir malzemede" demez."""
    own_product = "Koli GTIN'i malzemenin kendi ürün GTIN'i olamaz; koli için ayrı bir GTIN girin."
    own_case = "Ürün GTIN'i bu malzemenin koli GTIN'iyle aynı olamaz; koli ayrı bir ticari üründür."

    def taken(call, *args: Any) -> tuple[str, str]:
        with pytest.raises(BusinessRuleError) as exc:
            call(*args)
        return exc.value.code, exc.value.message

    material = services.create_record(planner, Material, finished("MM-1", gtin=GTIN))
    for value in (GTIN, "0" + GTIN):  # 14 haneli normal biçimde aynı
        assert taken(add_conversion, planner, material, value) == ("gtin_taken", own_product)
    case = add_conversion(planner, material)
    assert taken(services.update_record, planner, case, {"gtin": GTIN}) == (
        "gtin_taken",
        own_product,
    )

    other = services.create_record(planner, Material, finished("MM-2"))
    add_conversion(planner, other, CASE_GTIN)
    assert taken(services.update_record, planner, other, {"gtin": CASE_GTIN}) == (
        "gtin_taken",
        own_case,
    )
    # Başka malzemenin GTIN'leri genel mesajı alır.
    assert taken(services.update_record, planner, other, {"gtin": GTIN}) == (
        "gtin_taken",
        f"Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: {material.code}.",
    )
    assert taken(services.update_record, planner, case, {"gtin": CASE_GTIN}) == (
        "gtin_taken",
        f"Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı: {other.code} koli dönüşümü.",
    )


def test_case_gtin_only_on_case_unit_conversion(planner) -> None:
    material = services.create_record(planner, Material, finished("MM-1", gtin=GTIN))
    with pytest.raises(BusinessRuleError) as exc:
        add_conversion(planner, material, CASE_GTIN, unit_code="PALET")
    assert exc.value.code == "case_gtin_not_allowed"
    assert "KOLI" in exc.value.message
    pallet = add_conversion(planner, material, unit_code="PALET")
    assert pallet.gtin == ""
    assert rule_error(services.update_record, planner, pallet, {"gtin": CASE_GTIN}) == (
        "case_gtin_not_allowed"
    )


def _gtin_lock_held() -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objsubid = 1 "
            "AND objid = %s AND pid = pg_backend_pid() AND granted",
            [services._GTIN_LOCK_ID],
        )
        return int(cursor.fetchone()[0])


def test_gtin_write_takes_the_gtin_lock_until_the_transaction_ends(planner) -> None:
    services.create_record(planner, Material, finished("MM-1"))  # GTIN'siz kayıt kilit almaz
    assert _gtin_lock_held() == 0
    services.create_record(planner, Material, finished("MM-2", gtin=GTIN))
    assert _gtin_lock_held() == 1  # test işlemi bitene kadar tutulur


def test_gtin_lock_is_taken_before_the_code_counter_lock(planner, monkeypatch) -> None:
    """Kodu boş yeni malzemeye kod verilirken kod sayacı kilitlenir (`assign_master_code`). GTIN
    kilidi ondan önce alınır: kodu elle yazılmış GTIN'li kayıt önce GTIN kilidini, sonra sayacı
    alır; sıra ters olsaydı iki kayıt birbirini beklerdi (deadlock)."""
    held: list[int] = []
    assign = services.coding.assign_master_code

    def spy(item: Any, instance: Any) -> None:
        held.append(_gtin_lock_held())
        assign(item, instance)

    monkeypatch.setattr(services.coding, "assign_master_code", spy)
    services.create_record(planner, Material, finished("MM-1"))  # GTIN'siz: kilit yok
    services.create_record(planner, Material, finished("MM-2", gtin=GTIN))
    assert held == [0, 1]


def _waiting_for_gtin_lock(timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            # pg_locks bütün veritabanlarını gösterir: yalnız bu test veritabanındaki bekleyiş.
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objsubid = 1 "
                "AND objid = %s AND NOT granted AND database = "
                "(SELECT oid FROM pg_database WHERE datname = current_database())",
                [services._GTIN_LOCK_ID],
            )
            if cursor.fetchone()[0]:
                return True
        time.sleep(0.02)
    return False


def _count_units() -> UnitOfMeasure:
    """ADET ve KOLI birimleri; KOLI'yi döner. İşlemli testler veritabanını boşaltır, göçle gelen
    birimler olmayabilir."""
    UnitOfMeasure.objects.get_or_create(
        code="ADET", defaults={"name": "Adet", "kind": "COUNT", "factor_to_kind_base": 1}
    )
    koli, _ = UnitOfMeasure.objects.get_or_create(
        code="KOLI", defaults={"name": "Koli", "kind": "COUNT"}
    )
    return koli


def _bound_lock_waits() -> None:
    """İş parçacığındaki işlem kilit beklerken sonsuza dek takılmasın (test asla asılı kalmaz)."""
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '15s'")


@pytest.mark.django_db(transaction=True)
def test_concurrent_product_and_case_gtin_writes_are_serialized(make_user) -> None:
    """İki tabloda ortak DB kısıtı yoktur: aynı GTIN'i biri ürün, biri koli GTIN'i olarak yazan
    ikinci işlem GTIN kilidinde bekler, ilki bitince `gtin_taken` alır."""
    actor = make_user(PLANLAMA)
    koli = _count_units()
    other = services.create_record(actor, Material, finished("MM-2"))
    locked, release = threading.Event(), threading.Event()
    outcome: dict[str, str] = {}

    def hold_product_gtin() -> None:
        try:
            with transaction.atomic():
                services.create_record(actor, Material, finished("MM-1", gtin=GTIN))
                locked.set()
                release.wait(10)
        finally:
            connection.close()

    def write_case_gtin() -> None:
        try:
            services.create_record(
                actor,
                MaterialUnitConversion,
                {"material": other, "unit": koli, "factor_to_base": Decimal(12), "gtin": GTIN},
            )
            outcome["case"] = "ok"
        except BusinessRuleError as exc:
            outcome["case"] = exc.code
        finally:
            connection.close()

    holder = threading.Thread(target=hold_product_gtin)
    holder.start()
    writer = None
    try:
        assert locked.wait(10)
        writer = threading.Thread(target=write_case_gtin)
        writer.start()
        assert _waiting_for_gtin_lock(), "koli GTIN'i yazımı GTIN kilidinde beklemedi"
    finally:
        release.set()
        holder.join()
        if writer is not None:
            writer.join()
    assert outcome == {"case": "gtin_taken"}
    assert Material.objects.filter(gtin=GTIN).count() == 1
    assert not MaterialUnitConversion.objects.filter(gtin=GTIN).exists()


@pytest.mark.django_db(transaction=True)
def test_gtin_update_waits_for_the_gtin_lock_before_locking_the_material(make_user) -> None:
    """Aynı malzemede biri koli GTIN'li dönüşüm açar (GTIN kilidini tutar; commit'te yabancı anahtar
    denetimi malzeme satırını ister), öteki malzemenin GTIN'ini değiştirir. Güncelleme GTIN
    kilidini malzeme satırını kilitlemeden önce alır: iki işlem de biter. Sıra ters olsaydı
    PostgreSQL birini "deadlock detected" ile keserdi."""
    actor = make_user(PLANLAMA)
    koli = _count_units()
    material = services.create_record(actor, Material, finished("MM-1"))
    case_written, release = threading.Event(), threading.Event()
    outcome: dict[str, str] = {}

    def write_case_gtin() -> None:
        try:
            with transaction.atomic():
                _bound_lock_waits()
                services.create_record(
                    actor,
                    MaterialUnitConversion,
                    {
                        "material": material,
                        "unit": koli,
                        "factor_to_base": Decimal(12),
                        "gtin": CASE_GTIN,
                    },
                )
                case_written.set()
                release.wait(10)
            outcome["case"] = "ok"
        except Exception as exc:  # deadlock: OperationalError
            outcome["case"] = f"{type(exc).__name__}: {exc}"
        finally:
            case_written.set()
            connection.close()

    def write_product_gtin() -> None:
        try:
            with transaction.atomic():
                _bound_lock_waits()
                services.update_record(actor, material, {"gtin": GTIN})
            outcome["product"] = "ok"
        except Exception as exc:
            outcome["product"] = f"{type(exc).__name__}: {exc}"
        finally:
            connection.close()

    case_writer = threading.Thread(target=write_case_gtin)
    case_writer.start()
    product_writer = None
    try:
        assert case_written.wait(10)
        product_writer = threading.Thread(target=write_product_gtin)
        product_writer.start()
        assert _waiting_for_gtin_lock(), "GTIN güncellemesi GTIN kilidinde beklemedi"
    finally:
        release.set()
        case_writer.join(30)
        if product_writer is not None:
            product_writer.join(30)
    assert not case_writer.is_alive()
    assert product_writer is not None and not product_writer.is_alive()
    assert outcome == {"case": "ok", "product": "ok"}
    material.refresh_from_db()
    assert material.gtin == GTIN
    assert MaterialUnitConversion.objects.get(material=material).gtin == CASE_GTIN


# --- GTIN önerisi ------------------------------------------------------------------------------


def gtin13(reference: int, prefix: str = PREFIX) -> str:
    body = prefix + f"{reference:0{12 - len(prefix)}d}"
    return body + gs1_check_digit(body)


def test_gtin_suggestion_is_off_until_prefix_and_item_reference(admin) -> None:
    off = services.gtin_suggestion()
    assert (off.active, off.gtin) == (False, None)
    assert off.reason == (
        "GS1 firma öneki ve sıradaki ürün referansı Sistem > Kodlama sistematiği > GS1'de "
        "girilmemiş."
    )
    gs1(admin, company_prefix=PREFIX)
    no_reference = services.gtin_suggestion()
    assert not no_reference.active and "Sıradaki ürün referansı" in no_reference.reason
    gs1(admin, next_item_reference=12)
    on = services.gtin_suggestion()
    assert on.active and on.gtin == gtin13(12) == "8691234000120"
    assert on.reason == (
        "Sıradaki boş GTIN-13: firma öneki 8691234, ürün referansı 00012, kontrol hanesi 0."
    )
    # Öneri yalnızca mamul için.
    raw = services.gtin_suggestion(Material.Type.RAW)
    assert (raw.active, raw.gtin) == (False, None) and "mamul" in raw.reason
    assert services.gtin_suggestion(Material.Type.FINISHED).gtin == gtin13(12)


def test_gtin_suggestion_skips_used_product_and_case_gtins(admin) -> None:
    gs1(admin, company_prefix=PREFIX, next_item_reference=1)
    # Elle girilmiş (ya da eski) kayıtlar: 14 haneli normal biçimde karşılaştırılır.
    MaterialFactory.create(gtin=gtin13(1))
    MaterialUnitConversionFactory.create(gtin="0" + gtin13(2))
    MaterialFactory.create(gtin="0" + gtin13(3), is_active=False)
    assert services.gtin_suggestion().gtin == gtin13(4)


def test_saving_a_suggested_gtin_advances_the_item_reference(admin, planner) -> None:
    gs1(admin, company_prefix=PREFIX, next_item_reference=10)
    suggested = services.gtin_suggestion().gtin
    assert suggested == gtin13(10)
    services.create_record(planner, Material, finished("MM-1", gtin=suggested))
    assert services.get_label_settings().next_item_reference == 11
    assert services.gtin_suggestion().gtin == gtin13(11)
    # Sayaçtan en çok 10 ileri yazılan GTIN de sayacı ilerletir; daha ilerisi ilerletmez.
    services.create_record(planner, Material, finished("MM-2", gtin=gtin13(21)))
    assert services.get_label_settings().next_item_reference == 22
    services.create_record(planner, Material, finished("MM-3", gtin=gtin13(40)))
    assert services.get_label_settings().next_item_reference == 22
    # Başka önekli GTIN ve sayacın gerisindeki GTIN ilerletmez.
    services.create_record(planner, Material, finished("MM-4", gtin=GTIN))
    services.create_record(planner, Material, finished("MM-5", gtin=gtin13(15)))
    assert services.get_label_settings().next_item_reference == 22
    # GTIN'i değişmeyen kayıt sayacı ilerletmez.
    material = Material.objects.get(code="MM-1")
    services.update_record(planner, material, {"name": "Yeni ad"})
    assert services.get_label_settings().next_item_reference == 22
    # Firma önekli GTIN-13 koli GTIN'i de bir ürün referansı kullanır.
    add_conversion(planner, material, gtin13(22))
    assert services.get_label_settings().next_item_reference == 23
    # Sayaç ilerlemesi denetim günlüğüne yazılmaz ve son GS1 değişikliği sayılmaz (SSCC gibi).
    assert services.get_gs1_settings().updated_by_name == (admin.full_name or admin.username)


def test_item_reference_window_starts_at_the_suggestion(admin, planner) -> None:
    """Eski ya da elle girilmiş GTIN'ler sayacın önünü pencereden (10) uzun doldurmuşsa pencere
    önerilen referanstan (sayaçtan itibaren ilk boş referans) ölçülür; kodlama sayacındaki gibi."""
    gs1(admin, company_prefix=PREFIX, next_item_reference=1)
    for reference in range(1, 13):  # 1-12 kullanılmış (eski veri)
        MaterialFactory.create(gtin=gtin13(reference))
    for reference in (13, 14, 15):
        suggested = services.gtin_suggestion().gtin
        assert suggested == gtin13(reference)
        services.create_record(planner, Material, finished(f"MM-{reference}", gtin=suggested))
        assert services.get_label_settings().next_item_reference == reference + 1
    # Sayaç geride kalmış (1-15 kullanılmış, öneri 16): öneriden en çok 10 ileri GTIN sayacı
    # ilerletir, daha ilerisi ilerletmez.
    gs1(admin, next_item_reference=1)
    assert services.gtin_suggestion().gtin == gtin13(16)
    services.create_record(planner, Material, finished("MM-27", gtin=gtin13(27)))
    assert services.get_label_settings().next_item_reference == 1
    services.create_record(planner, Material, finished("MM-26", gtin=gtin13(26)))
    assert services.get_label_settings().next_item_reference == 27


def test_window_of_a_free_counter_ends_ten_past_the_counter(admin, planner) -> None:
    """Sayaç boşsa öneri sayaçtır: sayaç + 10 sayacı ilerletir, sayaç + 11 ilerletmez (öneri
    aradaki boş referansları atlamasın)."""
    gs1(admin, company_prefix=PREFIX, next_item_reference=5)
    services.create_record(planner, Material, finished("MM-16", gtin=gtin13(16)))
    assert services.get_label_settings().next_item_reference == 5
    assert services.gtin_suggestion().gtin == gtin13(5)
    services.create_record(planner, Material, finished("MM-15", gtin=gtin13(15)))
    assert services.get_label_settings().next_item_reference == 16


def test_saving_the_last_free_item_reference_moves_the_counter_to_the_end(admin, planner) -> None:
    """Pencere ölçülürken kaydedilen GTIN dolu sayılmaz: aralığın son boş referansı (öneri)
    kaydedilince de sayaç ilerler ve öneri "kullanılmış" der."""
    prefix = "8691234567"  # 10 haneli önek: ürün referansı 2 hane (0-99)
    gs1(admin, company_prefix=prefix, next_item_reference=85)
    for reference in range(85, 99):  # 85-98 kullanılmış: öneri 99, sayacın 10'dan fazla ilerisi
        MaterialFactory.create(gtin=gtin13(reference, prefix))
    suggested = services.gtin_suggestion().gtin
    assert suggested == gtin13(99, prefix)
    services.create_record(planner, Material, finished("MM-99", gtin=suggested))
    assert services.get_label_settings().next_item_reference == 100
    exhausted = services.gtin_suggestion()
    assert exhausted.active and exhausted.gtin is None and "kullanılmış" in exhausted.reason


def test_gtin_suggestion_reports_exhausted_item_references(admin, planner) -> None:
    prefix = "869123456789"  # 12 haneli önek: tek ürün referansı (0)
    gs1(admin, company_prefix=prefix, next_item_reference=0)
    only = services.gtin_suggestion()
    assert only.gtin == prefix + gs1_check_digit(prefix)
    services.create_record(planner, Material, finished("MM-1", gtin=only.gtin))
    exhausted = services.gtin_suggestion()
    assert exhausted.active and exhausted.gtin is None
    assert "kullanılmış" in exhausted.reason
    # Sayaç aralığın sonunda (1): öteki GS1 alanları yine değiştirilebilir; elle girilemez.
    assert gs1(admin, extension_digit=5).next_item_reference == 1
    assert rule_error(gs1, admin, next_item_reference=1) == "invalid_item_reference"


def test_gtin_suggestion_api(client_for, admin) -> None:
    gs1(admin, company_prefix=PREFIX, next_item_reference=12)
    assert APIClient().get(SUGGEST).status_code == 401
    for role in (DEPO, URETIM, DOLUM):
        assert client_for(role).get(SUGGEST).status_code == 403
    for role in (PLANLAMA, ADMIN):
        response = client_for(role).get(SUGGEST)
        assert response.status_code == 200
        assert response.json() == {
            "active": True,
            "gtin": gtin13(12),
            "reason": services.gtin_suggestion().reason,
        }
    raw = client_for(PLANLAMA).get(SUGGEST, {"material_type": "RAW"}).json()
    assert raw["active"] is False and raw["gtin"] is None


def test_case_gtin_suggestion(planner) -> None:
    material = services.create_record(planner, Material, finished("MM-1", gtin=GTIN))
    suggestion = services.case_gtin_suggestion(material)
    assert suggestion.gtin == CASE_GTIN and "gösterge hanesi 1" in suggestion.reason
    # Kullanılmış koli GTIN'i atlanır: sıradaki gösterge hanesi.
    MaterialUnitConversionFactory.create(gtin=CASE_GTIN)
    second = "2" + GTIN[:12] + gs1_check_digit("2" + GTIN[:12])
    assert services.case_gtin_suggestion(material).gtin == second
    # GTIN-12 ve GTIN-14'ten de türetilir (14 haneli biçimin ortadaki 12 hanesi).
    upc = MaterialFactory.create(gtin="614141000036")
    base = "061414100003"
    assert services.case_gtin_suggestion(upc).gtin == "1" + base + gs1_check_digit("1" + base)
    # Ürün GTIN'i yoksa ya da GTIN-8 ise öneri yok.
    assert services.case_gtin_suggestion(MaterialFactory.create()).gtin is None
    gtin8 = services.case_gtin_suggestion(MaterialFactory.create(gtin="96385074"))
    assert gtin8.gtin is None and "elle girin" in gtin8.reason


def test_case_gtin_suggestion_when_all_indicators_are_used(planner) -> None:
    material = services.create_record(planner, Material, finished("MM-1", gtin=GTIN))
    for indicator in "12345678":
        body = indicator + GTIN[:12]
        MaterialUnitConversionFactory.create(gtin=body + gs1_check_digit(body))
    suggestion = services.case_gtin_suggestion(material)
    assert suggestion.gtin is None and "1-8" in suggestion.reason


def test_case_gtin_suggestion_api(client_for, planner) -> None:
    material = services.create_record(planner, Material, finished("MM-1", gtin=GTIN))
    url = f"/api/v1/masterdata/materials/{material.pk}/case-gtin-suggestion/"
    assert client_for(DEPO).get(url).status_code == 403
    response = client_for(PLANLAMA).get(url)
    assert response.status_code == 200
    assert response.json()["gtin"] == CASE_GTIN and response.json()["reason"]


# --- API alanları ve yönetim paneli ------------------------------------------------------------


def test_conversion_api_writes_case_gtin(client_for, planner) -> None:
    material = services.create_record(planner, Material, finished("MM-1", gtin=GTIN))
    client = client_for(PLANLAMA)
    payload = {"material": material.pk, "unit": unit("KOLI").pk, "factor_to_base": "12"}
    created = client.post(CONVERSIONS, {**payload, "gtin": CASE_GTIN}, format="json")
    assert created.status_code == 201, created.json()
    assert created.json()["gtin"] == CASE_GTIN and created.json()["gtin_locked"] is False
    listed = client.get(CONVERSIONS, {"material": material.pk}).json()
    assert listed["count"] == 1 and listed["results"][0]["gtin_locked"] is False
    pallet = client.post(
        CONVERSIONS, {**payload, "unit": unit("PALET").pk, "gtin": "28690000000016"}, format="json"
    )
    assert pallet.status_code == 400 and pallet.json()["code"] == "case_gtin_not_allowed"
    long_value = client.patch(
        f"{CONVERSIONS}{created.json()['id']}/", {"gtin": "1" * 20}, format="json"
    )
    assert long_value.status_code == 400 and long_value.json()["code"] == "invalid_gtin"
    assert client_for(DEPO).post(CONVERSIONS, payload, format="json").status_code == 403

    detail = client.get(f"/api/v1/masterdata/materials/{material.pk}/").json()
    assert detail["gtin_locked"] is False
    assert detail["conversions"][0]["gtin"] == CASE_GTIN
    assert client.get("/api/v1/masterdata/materials/").json()["results"][0]["gtin_locked"] is False


def test_admin_panel_cannot_edit_gtins(admin) -> None:
    request = RequestFactory().get("/")
    request.user = admin
    material = MaterialFactory.create(gtin=GTIN)
    material_admin = django_admin.site._registry[Material]
    assert "gtin" in material_admin.get_readonly_fields(request, material)
    inline = MaterialUnitConversionInline(Material, django_admin.site)
    assert "gtin" in inline.get_readonly_fields(request, material)
    assert not inline.has_change_permission(request, material)
