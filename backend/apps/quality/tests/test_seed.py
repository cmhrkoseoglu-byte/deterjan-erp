from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.masterdata.models import Material
from apps.quality import services
from apps.quality.models import SampleStage, Specification


@override_settings(DEBUG=True)
def test_seed_demo_adds_approved_sample_specifications(roles):
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_quality_demo", stdout=StringIO())

    raw = Material.objects.filter(material_type="RAW", requires_incoming_qc=True)
    assert raw.count() == 14
    for material in raw:
        assert services.approved_specification(material, SampleStage.INCOMING) is not None
    dish = services.approved_specification(
        Material.objects.get(code="BULASIK-LIMON"), SampleStage.FINAL
    )
    assert dish is not None
    assert set(dish.lines.values_list("test__code", flat=True)) == {
        "PH",
        "VISK",
        "YOGUNLUK",
        "AKTIF_MADDE",
        "GORUNUS",
        "RENK",
        "KOKU",
    }
    # Tekrar çalıştırmak yeni sürüm açmaz.
    assert Specification.objects.count() == 16
    assert not Specification.objects.exclude(status="APPROVED").exists()


@pytest.mark.django_db
def test_seed_quality_demo_refuses_outside_debug():
    with pytest.raises(CommandError):
        call_command("seed_quality_demo", stdout=StringIO())
