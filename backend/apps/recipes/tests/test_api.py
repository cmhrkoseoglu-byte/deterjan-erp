import pytest
from django.urls import reverse

from apps.core.models import AuditLog
from apps.masterdata.tests.factories import BulkMaterialFactory, MaterialFactory, unit
from apps.recipes.models import RecipeVersion
from apps.recipes.tests.factories import RecipeFactory, RecipeLineFactory, RecipeVersionFactory

pytestmark = pytest.mark.django_db

RECIPES = reverse("recipes:recipe-list")


def version_url(pk, action=None):
    name = f"recipes:version-{action}" if action else "recipes:version-detail"
    return reverse(name, args=[pk])


def draft_with_line():
    version = RecipeVersionFactory()
    RecipeLineFactory(version=version)
    return version


def test_create_recipe_and_first_version_with_lines(client_for):
    client = client_for("planlama")
    product = BulkMaterialFactory()
    las = MaterialFactory()

    recipe = client.post(RECIPES, {"code": "r-bul", "name": "Bulaşık", "product": product.pk})
    assert recipe.status_code == 201, recipe.json()
    assert recipe.json()["code"] == "R-BUL"
    assert recipe.json()["approved_version"] is None

    version = client.post(
        reverse("recipes:recipe-versions", args=[recipe.json()["id"]]),
        {
            "batch_size": "1000",
            "batch_unit": unit("KG").pk,
            "change_note": "İlk sürüm",
            "lines": [
                {
                    "material": las.pk,
                    "quantity": "120",
                    "unit": unit("KG").pk,
                    "instruction": "Yavaş",
                }
            ],
            "steps": [{"description": "Suyu ekle", "duration_min": 10}],
        },
        format="json",
    )

    assert version.status_code == 201, version.json()
    body = version.json()
    assert body["version_no"] == 1
    assert body["status"] == "DRAFT"
    assert body["status_display"] == "Taslak"
    assert body["lines"][0]["material_code"] == las.code
    assert body["lines"][0]["tolerance_pct"] == "2.00"
    assert body["steps"][0]["description"] == "Suyu ekle"
    assert body["can_edit"] is True
    assert body["can_approve"] is True


def test_recipe_list_shows_approved_and_latest_version(client_for):
    version = draft_with_line()
    planner = client_for("planlama")
    planner.post(version_url(version.pk, "approve"))
    planner.post(version_url(version.pk, "copy"))

    [row] = client_for("depo").get(RECIPES).json()["results"]

    assert row["approved_version"] == {"id": version.pk, "version_no": version.version_no}
    assert row["latest_version_no"] == version.version_no + 1


def test_versions_list_for_recipe(client_for):
    version = draft_with_line()

    response = client_for("uretim").get(
        reverse("recipes:recipe-versions", args=[version.recipe_id])
    )

    assert response.status_code == 200
    assert [v["version_no"] for v in response.json()] == [version.version_no]


def test_versions_endpoint_filters_approved(client_for):
    draft = draft_with_line()
    approved = draft_with_line()
    client_for("laboratuvar").post(version_url(approved.pk, "approve"))

    results = (
        client_for("uretim")
        .get(reverse("recipes:version-list"), {"status": "APPROVED"})
        .json()["results"]
    )

    assert [v["id"] for v in results] == [approved.pk]
    assert draft.pk not in [v["id"] for v in results]


def test_approve_copy_and_obsolete_flow(client_for):
    client = client_for("planlama")
    v1 = draft_with_line()

    approved = client.post(version_url(v1.pk, "approve"), {"note": "ok"})
    assert approved.status_code == 200, approved.json()
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["can_edit"] is False

    locked = client.patch(version_url(v1.pk), {"batch_size": "500"})
    assert locked.status_code == 400
    assert locked.json()["code"] == "version_locked"

    line_id = approved.json()["lines"][0]["id"]
    assert (
        client.patch(reverse("recipes:line-detail", args=[line_id]), {"quantity": "1"}).json()[
            "code"
        ]
        == "version_locked"
    )

    copy = client.post(version_url(v1.pk, "copy"), {"note": "Parfüm değişti"})
    assert copy.status_code == 201
    v2 = copy.json()
    assert v2["status"] == "DRAFT"
    assert v2["copied_from"] == v1.pk
    assert v2["change_note"] == "Parfüm değişti"

    new_line = client.patch(
        reverse("recipes:line-detail", args=[v2["lines"][0]["id"]]), {"quantity": "130"}
    )
    assert new_line.status_code == 200, new_line.json()

    client.post(version_url(v2["id"], "approve"))
    v1.refresh_from_db()
    assert v1.status == RecipeVersion.Status.OBSOLETE


def test_approve_forbidden_for_other_roles(client_for):
    version = draft_with_line()

    response = client_for("depo").post(version_url(version.pk, "approve"))

    assert response.status_code == 403
    version.refresh_from_db()
    assert version.status == RecipeVersion.Status.DRAFT


@pytest.mark.parametrize("role", ["depo", "uretim", "dolum"])
def test_write_endpoints_forbidden_for_other_roles(client_for, role):
    client = client_for(role)
    version = draft_with_line()
    line = version.lines.get()

    assert client.post(RECIPES, {}).status_code == 403
    assert (
        client.post(reverse("recipes:recipe-versions", args=[version.recipe_id]), {}).status_code
        == 403
    )
    assert client.post(version_url(version.pk, "copy")).status_code == 403
    assert client.post(version_url(version.pk, "lines"), {}).status_code == 403
    assert client.delete(reverse("recipes:line-detail", args=[line.pk])).status_code == 403


def test_add_and_remove_draft_line(client_for):
    client = client_for("laboratuvar")
    version = RecipeVersionFactory()
    material = MaterialFactory()

    added = client.post(
        version_url(version.pk, "lines"),
        {"material": material.pk, "quantity": "5", "unit": unit("G").pk},
    )
    assert added.status_code == 201, added.json()
    assert added.json()["sequence"] == 1

    removed = client.delete(reverse("recipes:line-detail", args=[added.json()["id"]]))
    assert removed.status_code == 204
    assert not version.lines.exists()
    assert AuditLog.objects.filter(object_id=version.pk, note__contains="silindi").exists()


def test_line_validation_error_from_service(client_for):
    version = RecipeVersionFactory()
    packaging = MaterialFactory(material_type="PACKAGING")

    response = client_for("planlama").post(
        version_url(version.pk, "lines"),
        {"material": packaging.pk, "quantity": "5", "unit": unit("KG").pk},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_ingredient"


def test_duplicate_line_sequence_is_rejected(client_for):
    version = RecipeVersionFactory()
    RecipeLineFactory(version=version, sequence=1)

    response = client_for("planlama").post(
        version_url(version.pk, "lines"),
        {"sequence": 1, "material": MaterialFactory().pk, "quantity": "5", "unit": unit("KG").pk},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


def test_add_step(client_for):
    version = RecipeVersionFactory()

    response = client_for("planlama").post(
        version_url(version.pk, "steps"),
        {"description": "Isıt", "temperature_c": "45.5", "mixer_rpm": 300},
    )

    assert response.status_code == 201, response.json()
    assert response.json()["sequence"] == 1


def test_scale_endpoint(client_for):
    version = RecipeVersionFactory()
    RecipeLineFactory(version=version, quantity="120")

    response = client_for("uretim").get(
        version_url(version.pk, "scale"), {"qty": "2500", "unit": "kg"}
    )

    assert response.status_code == 200, response.json()
    [row] = response.json()
    assert row["quantity"] == "300.0000"
    assert row["unit_code"] == "KG"


def test_scale_endpoint_validates_query(client_for):
    version = RecipeVersionFactory()
    url = version_url(version.pk, "scale")
    client = client_for("uretim")

    assert client.get(url, {"qty": "0", "unit": "KG"}).json()["code"] == "validation_error"
    assert client.get(url, {"qty": "1", "unit": "XYZ"}).json()["errors"]["unit"]


def test_recipe_requires_bulk_product_via_api(client_for):
    response = client_for("planlama").post(
        RECIPES, {"code": "R", "name": "x", "product": MaterialFactory().pk}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "recipe_product_not_bulk"


def test_recipe_deactivate(client_for):
    recipe = RecipeFactory()

    response = client_for("planlama").post(reverse("recipes:recipe-deactivate", args=[recipe.pk]))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
