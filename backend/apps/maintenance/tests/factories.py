"""Bakım testleri için yardımcılar (kayıtlar servislerle oluşturulur)."""

from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.maintenance import services
from apps.maintenance.models import MaintenanceKind, MaintenancePlan
from apps.masterdata.models import Equipment, Material
from apps.masterdata.tests.factories import BulkMaterialFactory, EquipmentFactory, unit
from apps.production import services as production
from apps.production.models import ProductionBatch
from apps.production.tests.factories import Plant, ready_order, weigh_all
from apps.recipes import services as recipes
from apps.recipes.models import RecipeVersion
from apps.recipes.tests.factories import RecipeFactory


def scale(**kwargs: Any) -> Equipment:
    return EquipmentFactory.create(
        equipment_type=Equipment.Type.SCALE,
        capacity=None,
        capacity_unit=None,
        location=None,
        **kwargs,
    )


def plan(actor: User, equipment: Equipment, **data: Any) -> MaintenancePlan:
    values: dict[str, Any] = {
        "equipment": equipment,
        "kind": MaintenanceKind.PERIODIC,
        "title": "Aylık bakım",
        "interval_days": 30,
        "checklist": ["Conta kontrolü", "Yağlama"],
        **data,
    }
    return services.create_plan(actor, values)


def second_product(plant: Plant, planner: User, code: str = "CAMASIR") -> RecipeVersion:
    """Aynı hammaddelerle ikinci dökme ürün ve onaylı reçetesi."""
    product: Material = BulkMaterialFactory.create(code=code, name=f"{code} deterjanı")
    recipe = RecipeFactory.create(product=product)
    kg = unit("KG")
    version = recipes.create_version(
        planner,
        recipe,
        batch_size=Decimal("1000"),
        batch_unit=kg,
        lines=[
            {"material": plant.las, "quantity": Decimal("500"), "unit": kg, "tolerance_pct": 2},
            {"material": plant.sles, "quantity": Decimal("400"), "unit": kg, "tolerance_pct": 2},
            {
                "material": plant.water,
                "quantity": Decimal("100"),
                "unit": kg,
                "tolerance_pct": 5,
                "is_water": True,
            },
        ],
    )
    return recipes.approve_version(planner, version)


def run_batch(
    plant: Plant,
    planner: User,
    depo: User,
    operator: User,
    version: RecipeVersion | None = None,
) -> ProductionBatch:
    """Tankta (plant.tank) bir şarjı baştan sona yapar."""
    if version is not None and version.pk != plant.version.pk:
        original = plant.version
        plant.version = version
        try:
            order = ready_order(plant, planner, depo)
        finally:
            plant.version = original
    else:
        order = ready_order(plant, planner, depo)
    batch = production.start_batch(operator, order, plant.tank)
    weigh_all(plant, batch, operator)
    return production.finish_batch(operator, batch, Decimal("1000"))
