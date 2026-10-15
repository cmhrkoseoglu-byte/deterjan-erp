from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.inventory.models import StockBalance
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Equipment, Material, Supplier
from apps.production import services
from apps.recipes.models import RecipeVersion

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_is_repeatable_and_usable(roles):
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())

    assert Material.objects.filter(material_type="RAW").count() == 15
    assert Material.objects.filter(material_type="BULK").count() == 2
    assert Equipment.objects.filter(equipment_type="MIXING_TANK").count() == 2
    assert Supplier.objects.count() == 3
    approved = RecipeVersion.objects.filter(status="APPROVED")
    assert approved.count() == 2
    for version in approved:
        assert version.lines.filter(is_water=True).count() == 1
    assert StockBalance.objects.filter(quantity__gt=0, material__material_type="RAW").count() == 15
    assert_stock_invariants()


@override_settings(DEBUG=True)
def test_seed_demo_supports_a_production_order(roles, django_user_model):
    call_command("seed_demo", stdout=StringIO())
    planner = django_user_model.objects.get(username="planlama")
    version = RecipeVersion.objects.get(recipe__code="REC-BULASIK", status="APPROVED")
    order = services.create_order(
        planner,
        {
            "recipe_version": version,
            "planned_quantity": Decimal("3000"),
            "unit": version.batch_unit,
            "planned_date": "2026-10-20",
            "equipment": Equipment.objects.get(code="KT-01"),
        },
    )
    services.approve_order(planner, order)
    assert order.production_location.code == "URETIM-1"
    assert services.suggested_batch_quantity(order) == 2000


@override_settings(DEBUG=False)
def test_seed_demo_refuses_outside_debug(roles):
    with pytest.raises(Exception, match="geliştirme"):
        call_command("seed_demo", stdout=StringIO())
