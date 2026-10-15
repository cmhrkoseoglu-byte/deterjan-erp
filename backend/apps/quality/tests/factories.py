"""Kalite test kurulumu: test tanımları (migration'dan), spesifikasyon ve numuneli lotlar."""

from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.inventory.models import Lot
from apps.inventory.tests.factories import quarantine_location, stocked_lot
from apps.masterdata.models import Location, Material
from apps.masterdata.tests.factories import BulkMaterialFactory, LocationFactory, MaterialFactory
from apps.quality import services
from apps.quality.models import Sample, SampleStage, Specification, TestDefinition

D = Decimal


def tdef(code: str) -> TestDefinition:
    """Migration'la gelen standart test (PH, VISK, RENK, GORUNUS, …)."""
    return TestDefinition.objects.get(code=code)


def raw_spec_lines() -> list[dict[str, Any]]:
    """pH 6–8 (zorunlu), görünüş "Berrak" (zorunlu), renk (isteğe bağlı)."""
    return [
        {"test": tdef("PH"), "min_value": D("6"), "max_value": D("8"), "target_value": D("7")},
        {"test": tdef("GORUNUS"), "text_expected": "Berrak"},
        {"test": tdef("RENK"), "is_mandatory": False},
    ]


def approved_spec(
    lab: User,
    material: Material,
    stage: str = SampleStage.INCOMING,
    lines: list[dict[str, Any]] | None = None,
) -> Specification:
    spec = services.create_specification(
        lab, material=material, sample_stage=stage, lines=lines or raw_spec_lines()
    )
    return services.approve_specification(lab, spec)


def quarantined_raw_lot(
    quantity: str = "100", *, material: Material | None = None
) -> tuple[Lot, Location]:
    """Karantinada stoklu hammadde lotu ve karantina lokasyonu."""
    location = quarantine_location()
    lot = stocked_lot(
        quantity,
        material=material or MaterialFactory.create(),
        location=location,
        status="QUARANTINE",
    )
    return lot, location


def bulk_lot_in_tank(quantity: str = "1000", *, material: Material | None = None) -> Lot:
    """Tankta karantinadaki bulk lot (şarj çıktısı gibi)."""
    tank = LocationFactory.create(location_type=Location.Type.TANK)
    return stocked_lot(
        quantity,
        material=material or BulkMaterialFactory.create(),
        location=tank,
        status=Lot.Status.QUARANTINE,
        source=Lot.Source.PRODUCTION,
    )


def sample_with_spec(
    lab: User, lot: Lot, stage: str = SampleStage.INCOMING, **spec_kwargs: Any
) -> Sample:
    """Onaylı spesifikasyonla açılmış numune."""
    approved_spec(lab, lot.material, stage, **spec_kwargs)
    return services.create_sample(lab, lot, stage)


def line(sample: Sample, code: str) -> Any:
    assert sample.specification is not None
    return sample.specification.lines.get(test__code=code)
