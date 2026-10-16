from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.hse import selectors
from apps.hse.models import Incident, MaterialHazard, StorageLimit, WasteRecord
from apps.masterdata.models import Material

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_includes_hse(roles: None) -> None:
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())
    assert MaterialHazard.objects.count() == 4
    assert Material.objects.get(code="NAOH").is_hazardous is True
    gaps = {row.material_code: row.status for row in selectors.sds_gaps()}
    assert gaps["KORUYUCU"] == "MISSING"
    assert gaps["ALKOL"] == "NO_FILE"
    assert "LAS" in gaps  # demo GBF'lerinde PDF yok
    assert StorageLimit.objects.count() == 2
    assert all(not row.exceeded for row in selectors.storage_utilisation())
    assert WasteRecord.objects.count() == 1
    assert Incident.objects.count() == 1
