from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.maintenance import selectors
from apps.maintenance.models import ChangeoverRule, MaintenancePlan

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_includes_maintenance(roles: None) -> None:
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())
    statuses = {row.equipment.code: row.status for row in selectors.calibration_status()}
    assert statuses == {"TR-01": selectors.CAL_OK, "TR-02": selectors.CAL_DUE_SOON}
    assert MaintenancePlan.objects.filter(interval_runs=20).count() == 1
    assert ChangeoverRule.objects.count() == 1
