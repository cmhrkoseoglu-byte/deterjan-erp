from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.filling import services
from apps.filling.models import PackagingSpec
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Equipment, Location, Material, UnitOfMeasure
from apps.masterdata.services import to_base_quantity
from apps.quality.models import SampleStage, Specification

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_includes_filling_and_supports_an_order(roles, django_user_model):
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())

    assert Material.objects.filter(material_type="PACKAGING").count() == 6
    finished = Material.objects.filter(material_type="FINISHED")
    assert finished.count() == 2
    assert PackagingSpec.objects.filter(status="APPROVED").count() == 2
    assert (
        Specification.objects.filter(
            material__in=finished, sample_stage=SampleStage.FINAL, status="APPROVED"
        ).count()
        == 2
    )
    product = finished.get(code="BULASIK-LIMON-750")
    assert to_base_quantity(product, Decimal("1"), UnitOfMeasure.objects.get(code="PALET")) == 720
    assert_stock_invariants()

    planner = django_user_model.objects.get(username="planlama")
    order = services.create_order(
        planner,
        {
            "finished_product": product,
            "planned_units": 1200,
            "filling_line": Equipment.objects.get(code="DH-01"),
            "output_location": Location.objects.get(code="MAMUL-DEPO"),
            "planned_date": "2026-10-21",
        },
    )
    services.approve_order(planner, order)
    assert order.requirements.get(material__code="KOLI-12").required_quantity == 101
