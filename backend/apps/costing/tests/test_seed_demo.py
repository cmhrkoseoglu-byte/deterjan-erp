from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.costing import selectors
from apps.costing.models import CostRate, CostStage, EmployeeWage, LotCost, StandardCost
from apps.inventory.models import Lot
from apps.inventory.testing import assert_stock_invariants

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_includes_costing(roles: None) -> None:
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())

    assert StandardCost.objects.filter(material__code="LAS").exists()
    assert CostRate.objects.count() == 6
    las = Lot.objects.get(lot_no="ACILIS-LAS")
    cost = LotCost.objects.get(lot=las, is_current=True)
    assert cost.is_estimated and str(cost.unit_cost) == "48.0000"
    # Her demo lotunun tek maliyet sürümü vardır (tekrar çalıştırmak yeni sürüm açmaz).
    assert LotCost.objects.filter(version__gt=1).count() == 0
    assert not Lot.objects.filter(unit_cost__isnull=True, source="OPENING").exists()
    # Personel ücretleri ve birim eşleştirmesi; tekrar çalıştırmak ücret eklemez.
    assert EmployeeWage.objects.filter(employee__employee_no="S-0012").count() in (1, 2)
    assert EmployeeWage.objects.values("employee").distinct().count() == 14
    centers = {row["department"]: row["stage"] for row in selectors.cost_centers()}
    assert centers["Üretim"] == CostStage.PRODUCTION and centers["Dolum"] == CostStage.FILLING
    assert not [row for row in selectors.wage_summary() if row["current_wage"] is None]
    assert_stock_invariants()
