import io
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.core.labels import gs1_check_digit
from apps.core.models import AuditLog
from apps.inventory import services as inventory
from apps.inventory.models import Lot
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Material, MaterialUnitConversion, RetiredGtin, Supplier
from apps.masterdata.tests.factories import (
    CustomerFactory,
    EquipmentFactory,
    LocationFactory,
    MaterialCategoryFactory,
    MaterialFactory,
    MaterialUnitConversionFactory,
    SupplierFactory,
    WarehouseFactory,
    unit,
)

pytestmark = pytest.mark.django_db

MATERIALS = reverse("masterdata:material-list")


def material_url(pk, action=None):
    if action:
        return reverse(f"masterdata:material-{action}", args=[pk])
    return reverse("masterdata:material-detail", args=[pk])


def xlsx_upload(rows, name="malzeme.xlsx"):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    buffer.name = name
    return buffer


# --- yetki -----------------------------------------------------------------------------------


def test_list_requires_login():
    assert APIClient().get(MATERIALS).status_code == 401


@pytest.mark.parametrize(
    "basename",
    [
        "unit",
        "category",
        "material",
        "conversion",
        "warehouse",
        "location",
        "equipment",
        "supplier",
        "customer",
    ],
)
def test_every_role_can_read(client_for, basename):
    response = client_for("depo").get(reverse(f"masterdata:{basename}-list"))

    assert response.status_code == 200
    assert "results" in response.json()


@pytest.mark.parametrize("role", ["depo", "uretim", "laboratuvar", "sevkiyat"])
def test_other_roles_cannot_write(client_for, role):
    client = client_for(role)
    material = MaterialFactory()

    payload = {"code": "X", "name": "x", "material_type": "RAW", "base_unit": unit("KG").pk}
    assert client.post(MATERIALS, payload, format="json").status_code == 403
    assert client.patch(material_url(material.pk), {"name": "y"}).status_code == 403
    assert client.post(material_url(material.pk, "deactivate")).status_code == 403


def test_units_are_admin_only_for_writing(client_for):
    payload = {"code": "TON", "name": "Ton", "kind": "MASS", "factor_to_kind_base": "1000"}
    url = reverse("masterdata:unit-list")

    assert client_for("planlama").post(url, payload).status_code == 403
    response = client_for("admin").post(url, payload)
    assert response.status_code == 201, response.json()
    assert response.json()["kind_display"] == "Kütle"


def test_delete_is_not_available(client_for):
    material = MaterialFactory()

    assert client_for("admin").delete(material_url(material.pk)).status_code == 405


# --- malzeme ---------------------------------------------------------------------------------


def test_planner_creates_material(client_for):
    response = client_for("planlama").post(
        MATERIALS,
        {
            "code": "hm-naoh",
            "name": "Kostik",
            "material_type": "RAW",
            "base_unit": unit("KG").pk,
            "density": "2.1300",
            "is_hazardous": True,
        },
        format="json",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["code"] == "HM-NAOH"
    assert body["base_unit_code"] == "KG"
    assert body["material_type_display"] == "Hammadde"
    assert body["requires_incoming_qc"] is True
    assert body["is_active"] is True


def test_duplicate_code_returns_validation_error(client_for):
    MaterialFactory(code="HM-1")

    response = client_for("planlama").post(
        MATERIALS,
        {"code": "hm-1", "name": "x", "material_type": "RAW", "base_unit": unit("KG").pk},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert "code" in response.json()["errors"]


def test_business_rule_error_shape(client_for):
    passive = MaterialCategoryFactory(is_active=False)
    response = client_for("planlama").post(
        MATERIALS,
        {
            "code": "X",
            "name": "x",
            "material_type": "RAW",
            "base_unit": unit("KG").pk,
            "category": passive.pk,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "inactive_reference"


def test_patch_material_and_audit(client_for):
    material = MaterialFactory(name="Eski")

    response = client_for("planlama").patch(material_url(material.pk), {"name": "Yeni"})

    assert response.status_code == 200
    assert response.json()["name"] == "Yeni"
    assert AuditLog.objects.filter(action="update", object_id=material.pk).exists()


def test_deactivate_and_activate(client_for):
    client = client_for("planlama")
    material = MaterialFactory()

    assert client.post(material_url(material.pk, "deactivate")).json()["is_active"] is False
    assert client.post(material_url(material.pk, "activate")).json()["is_active"] is True


def test_material_filters_and_search(client_for):
    MaterialFactory(code="HM-LAS", name="LAS")
    MaterialFactory(code="AMB-1", name="Şişe", material_type="PACKAGING", base_unit=unit("ADET"))
    MaterialFactory(code="HM-OLD", is_active=False)
    client = client_for("depo")

    by_type = client.get(MATERIALS, {"material_type": "PACKAGING"}).json()["results"]
    active = client.get(MATERIALS, {"is_active": "true"}).json()["results"]
    search = client.get(MATERIALS, {"search": "las"}).json()["results"]

    assert [m["code"] for m in by_type] == ["AMB-1"]
    assert "HM-OLD" not in [m["code"] for m in active]
    assert [m["code"] for m in search] == ["HM-LAS"]


def test_material_detail_includes_conversions(client_for):
    conversion = MaterialUnitConversionFactory()

    body = client_for("depo").get(material_url(conversion.material.pk)).json()

    assert body["conversions"][0]["unit_code"] == "KOLI"
    assert body["conversions"][0]["factor_to_base"] == "12.000000"


def test_create_conversion(client_for):
    material = MaterialFactory(material_type=Material.Type.PACKAGING, base_unit=unit("ADET"))

    response = client_for("planlama").post(
        reverse("masterdata:conversion-list"),
        {"material": material.pk, "unit": unit("KOLI").pk, "factor_to_base": "24"},
    )

    assert response.status_code == 201, response.json()
    assert response.json()["base_unit_code"] == "ADET"
    assert response.json()["retired_gtins"] == []


# --- eski koli GTIN'leri (koli içi miktar değişikliği; kurallar test_pack_change.py) -----------

ISTANBUL = ZoneInfo("Europe/Istanbul")


def case_gtin(n: int) -> str:
    body = f"1869{n:09d}"
    return body + gs1_check_digit(body)


def product_gtin(n: int) -> str:
    body = f"869{n:09d}"
    return body + gs1_check_digit(body)


def locked_conversion(gtin: str, product: str) -> MaterialUnitConversion:
    """Lotu olan mamulün geçerli koli GTIN'li KOLI dönüşümü: malzemenin ve dönüşümün
    `gtin_locked`'ı true; kilit lot sorgusu ister (sorgu ekleri `has_lots`, `material_has_lots`)."""
    material = MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), gtin=product
    )
    inventory.create_lot(
        None, material=material, source=Lot.Source.FILLING, lot_no=f"D-{material.code}"
    )
    return MaterialUnitConversionFactory.create(material=material, gtin=gtin)


def retire(conversion, gtin, factor, replaced_by, user=None, at=None):
    """Eski koli GTIN'i satırı (doğrudan); `at` verilirse değiştiği an."""
    row = RetiredGtin.objects.create(
        conversion=conversion,
        gtin=gtin,
        factor_to_base=Decimal(factor),
        replaced_by=replaced_by,
        created_by=user,
    )
    if at is not None:
        RetiredGtin.objects.filter(pk=row.pk).update(created_at=at)
    return row


def test_conversion_shows_retired_case_gtins_newest_first(client_for, make_user):
    conversion = MaterialUnitConversionFactory(gtin=case_gtin(3))
    planner = make_user("planlama", full_name="Ayşe Planlama")
    # Önce yazılan satır daha yeni: sıralama değiştiği ana göredir, kayıt sırasına göre değil.
    retire(
        conversion,
        case_gtin(2),
        "24",
        case_gtin(3),
        planner,
        datetime(2026, 11, 5, 10, 0, tzinfo=ISTANBUL),
    )
    retire(
        conversion,
        case_gtin(1),
        "12",
        case_gtin(2),
        None,
        datetime(2026, 10, 1, 9, 30, tzinfo=ISTANBUL),
    )
    expected = [
        {
            "gtin": case_gtin(2),
            "factor_to_base": "24.000000",
            "replaced_by": case_gtin(3),
            "retired_at": "2026-11-05T10:00:00+03:00",
            "retired_by_name": "Ayşe Planlama",
        },
        {
            "gtin": case_gtin(1),
            "factor_to_base": "12.000000",
            "replaced_by": case_gtin(2),
            "retired_at": "2026-10-01T09:30:00+03:00",
            "retired_by_name": "",  # sistem işlemi
        },
    ]
    client = client_for("depo")
    listed = client.get(reverse("masterdata:conversion-list")).json()["results"]
    assert listed[0]["retired_gtins"] == expected
    detail = client.get(reverse("masterdata:conversion-detail", args=[conversion.pk])).json()
    assert detail["retired_gtins"] == expected
    material = client.get(material_url(conversion.material.pk)).json()
    assert material["conversions"][0]["retired_gtins"] == expected


def test_retired_case_gtins_and_gtin_locks_add_no_per_row_queries(
    client_for, make_user, django_assert_num_queries
):
    """Eski koli GTIN'leri ve GTIN kilidi satır başına sorgu yapmaz. Ölçü: az satırlı listeler ve
    kilidi hiç sorgulanmayan ambalaj malzemesinin detayı; lotu olan mamuller (kilitli GTIN'ler) ve
    eski koli GTIN'leri eklenince sorgu sayısı değişmez. Sorgu eki düşerse her kilitli satır lot
    sorgusu yapar."""
    users = [make_user(full_name=f"Kullanıcı {n}") for n in range(3)]
    plain = MaterialUnitConversionFactory(gtin=case_gtin(300))  # ambalaj: kilit sorgulanmaz
    retire(plain, case_gtin(301), "6", case_gtin(300), users[0])
    first = locked_conversion(case_gtin(100), product_gtin(1))
    retire(first, case_gtin(101), "6", case_gtin(100), users[0])
    client = client_for("depo")
    conversions = reverse("masterdata:conversion-list")

    def count(url: str) -> int:
        with CaptureQueriesContext(connection) as queries:
            assert client.get(url).status_code == 200
        return len(queries)

    for url in (conversions, MATERIALS, material_url(plain.material.pk)):
        client.get(url)  # ısınma
    list_count, materials_count = count(conversions), count(MATERIALS)
    detail_count = count(material_url(plain.material.pk))

    pallet = MaterialUnitConversionFactory(material=first.material, unit=unit("PALET"))
    retire(pallet, case_gtin(102), "480", case_gtin(103), users[1])
    for n in range(2):
        other = locked_conversion(case_gtin(200 + n * 10), product_gtin(2 + n))
        for index, user in enumerate(users):
            retire(other, case_gtin(201 + n * 10 + index), "12", case_gtin(200 + n * 10), user)
    with django_assert_num_queries(list_count):
        rows = client.get(conversions).json()["results"]
    assert sorted((len(row["retired_gtins"]), row["gtin_locked"]) for row in rows) == [
        (1, False),
        (1, False),
        (1, True),
        (3, True),
        (3, True),
    ]
    with django_assert_num_queries(materials_count):
        listed = client.get(MATERIALS).json()["results"]
    assert sorted(row["gtin_locked"] for row in listed) == [False, True, True, True]
    # Lotu olan mamulün detayı (kilitli ürün ve koli GTIN'i, iki dönüşüm) ambalaj malzemesininki
    # kadar sorgu yapar.
    with django_assert_num_queries(detail_count):
        body = client.get(material_url(first.material.pk)).json()
    assert body["gtin_locked"] is True
    assert [(len(row["retired_gtins"]), row["gtin_locked"]) for row in body["conversions"]] == [
        (1, True),
        (1, False),
    ]
    assert_stock_invariants()


# --- depo, lokasyon, ekipman, tedarikçi, müşteri ---------------------------------------------


def test_create_location_and_tank(client_for):
    client = client_for("planlama")
    warehouse = WarehouseFactory()
    location = client.post(
        reverse("masterdata:location-list"),
        {"warehouse": warehouse.pk, "code": "tk-01", "name": "Tank 1", "location_type": "TANK"},
    )
    assert location.status_code == 201, location.json()

    tank = client.post(
        reverse("masterdata:equipment-list"),
        {
            "code": "KT-01",
            "name": "Karıştırma tankı",
            "equipment_type": "MIXING_TANK",
            "capacity": "5000",
            "capacity_unit": unit("KG").pk,
            "location": location.json()["id"],
        },
    )

    assert tank.status_code == 201, tank.json()
    assert tank.json()["location_code"] == "TK-01"


def test_tank_without_location_is_rejected(client_for):
    response = client_for("planlama").post(
        reverse("masterdata:equipment-list"),
        {"code": "KT", "name": "Tank", "equipment_type": "MIXING_TANK"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "tank_location_required"


def test_location_filters(client_for):
    LocationFactory(location_type="QUARANTINE", code="KAR")
    LocationFactory(location_type="STORAGE", code="RAF")
    EquipmentFactory()

    results = (
        client_for("depo")
        .get(reverse("masterdata:location-list"), {"location_type": "QUARANTINE"})
        .json()["results"]
    )

    assert [r["code"] for r in results] == ["KAR"]


def test_supplier_and_customer_crud(client_for):
    client = client_for("planlama")
    SupplierFactory(name="B Kimya")
    CustomerFactory()

    created = client.post(
        reverse("masterdata:supplier-list"),
        {"code": "t-9", "name": "A Kimya", "tax_number": "1234567890", "email": "a@b.com"},
    )
    listed = client.get(reverse("masterdata:supplier-list")).json()["results"]

    assert created.status_code == 201, created.json()
    assert [s["name"] for s in listed] == ["A Kimya", "B Kimya"]
    assert client.get(reverse("masterdata:customer-list")).json()["count"] == 1


# --- içe aktarma -----------------------------------------------------------------------------


def import_url(kind="materials"):
    return reverse("masterdata:import", args=[kind])


def test_import_preview_then_confirm(client_for):
    client = client_for("planlama")
    rows = [["Kod", "Ad", "Tür", "Temel birim"], ["HM-LAS", "LAS", "Hammadde", "KG"]]

    preview = client.post(import_url(), {"file": xlsx_upload(rows)}, format="multipart")
    assert preview.status_code == 200, preview.json()
    assert preview.json()["imported"] is False
    assert preview.json()["to_create"] == 1
    assert Material.objects.count() == 0

    confirm = client.post(
        import_url(), {"file": xlsx_upload(rows), "confirm": "true"}, format="multipart"
    )
    assert confirm.status_code == 200, confirm.json()
    assert confirm.json()["imported"] is True
    assert Material.objects.get().code == "HM-LAS"


def test_import_confirm_with_errors_returns_report(client_for):
    rows = [["Kod", "Ad", "Tür", "Temel birim"], ["HM-1", "", "RAW", "KG"]]

    response = client_for("planlama").post(
        import_url(), {"file": xlsx_upload(rows), "confirm": "true"}, format="multipart"
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "import_has_errors"
    assert body["report"]["rows"][0]["errors"][0]["column"] == "Ad"
    assert Material.objects.count() == 0


def test_import_suppliers_csv(client_for):
    upload = io.BytesIO("Kod,Ünvan\nT1,Tedarikçi\n".encode())
    upload.name = "t.csv"

    response = client_for("planlama").post(
        import_url("suppliers"), {"file": upload, "confirm": "true"}, format="multipart"
    )

    assert response.status_code == 200, response.json()
    assert Supplier.objects.get().code == "T1"


def test_import_requires_write_role(client_for):
    response = client_for("depo").post(
        import_url(), {"file": xlsx_upload([["Kod"]])}, format="multipart"
    )

    assert response.status_code == 403


def test_import_unknown_kind(client_for):
    response = client_for("planlama").post(
        import_url("lots"), {"file": xlsx_upload([["Kod"]])}, format="multipart"
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unknown_import_kind"


def test_template_download(client_for):
    response = client_for("planlama").get(reverse("masterdata:import-template", args=["materials"]))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert 'filename="sablon-materials.xlsx"' in response["Content-Disposition"]
    assert (
        client_for("depo")
        .get(reverse("masterdata:import-template", args=["materials"]))
        .status_code
        == 403
    )
