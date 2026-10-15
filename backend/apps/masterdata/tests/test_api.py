import io

import pytest
from django.urls import reverse
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.masterdata.models import Material, Supplier
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
