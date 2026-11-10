"""Kod göçü stoka dokunmaz: hareketler, bakiyeler, lotlar ve soy ağacı aynı kalır (CLAUDE.md §4)."""

from decimal import Decimal

import pytest

from apps.core.coding import migration
from apps.core.coding import services as coding
from apps.inventory.models import Lot, StockBalance, StockMovement
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.models import Material
from apps.recipes.models import Recipe
from apps.recipes.tests.factories import RecipeFactory

pytestmark = pytest.mark.usefixtures("invariants")


def test_recode_materials_keeps_stock(make_user):
    admin = make_user("admin")
    lot = stocked_lot(quantity=Decimal("125"))
    material = lot.material
    Material.objects.filter(pk=material.pk).update(code="ESKI-HM")
    movements = list(StockMovement.objects.values_list("pk", "quantity", "lot_id"))
    balances = list(StockBalance.objects.values_list("pk", "quantity"))
    coding.update_scheme(admin, "masterdata.material", is_active=True, note="Biçim")

    plan = migration.preview_recode("masterdata.material")
    migration.apply_recode(admin, "masterdata.material", checksum=plan["checksum"], note="Göç")

    material.refresh_from_db()
    assert material.code.startswith("MLZ-")
    assert list(StockMovement.objects.values_list("pk", "quantity", "lot_id")) == movements
    assert list(StockBalance.objects.values_list("pk", "quantity")) == balances
    assert Lot.objects.get(pk=lot.pk).lot_no == lot.lot_no


def test_recode_recipes_like_live_data(make_user):
    """Canlıdaki gibi: biçime uyan REC-0000001/2 kalır, eskiler oluşturulma sırasıyla 3, 4, 5."""
    admin = make_user("admin")
    old = [RecipeFactory(code=code) for code in ("DENEME-REÇETE-001", "DENEME", "3645")]
    kept = [RecipeFactory(code=code) for code in ("REC-0000001", "REC-0000002")]
    plan = migration.preview_recode("recipes.recipe")
    assert (plan["change_count"], plan["keep_count"]) == (3, 2)
    migration.apply_recode(admin, "recipes.recipe", checksum=plan["checksum"], note="Göç")
    assert [Recipe.objects.get(pk=r.pk).code for r in old] == [
        "REC-0000003",
        "REC-0000004",
        "REC-0000005",
    ]
    assert [Recipe.objects.get(pk=r.pk).code for r in kept] == ["REC-0000001", "REC-0000002"]
