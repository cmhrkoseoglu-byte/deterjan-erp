"""Üretim testleri için kurulum: depo, lokasyonlar, tank, reçete ve stok (servislerle)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.inventory.models import Lot
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.models import Equipment, Location, Material, Warehouse
from apps.masterdata.tests.factories import (
    BulkMaterialFactory,
    EquipmentFactory,
    LocationFactory,
    MaterialFactory,
    WarehouseFactory,
    unit,
)
from apps.production import services
from apps.production.models import ProductionOrder, ProductionRequirement
from apps.recipes import services as recipes
from apps.recipes.models import RecipeVersion
from apps.recipes.tests.factories import RecipeFactory


@dataclass
class Plant:
    """Tek depolu küçük fabrika: depo/karantina/üretim lokasyonları, 1000 kg'lık iki tank ve
    1000 kg'lık reçete (LAS 600, SLES 300 kg, su 100 kg; tolerans %2)."""

    warehouse: Warehouse
    storage: Location
    quarantine: Location
    production: Location
    tank: Equipment
    tank2: Equipment
    product: Material
    las: Material
    sles: Material
    water: Material
    version: RecipeVersion
    lots: dict[str, Lot] = field(default_factory=dict)

    def requirement(self, order: ProductionOrder, material: Material) -> ProductionRequirement:
        return order.requirements.get(material=material)


def build_plant(planner: User, *, stock: bool = True) -> Plant:
    warehouse = WarehouseFactory.create()
    storage = LocationFactory.create(
        warehouse=warehouse, code="DEPO", location_type=Location.Type.STORAGE
    )
    quarantine = LocationFactory.create(
        warehouse=warehouse, code="KARANTINA", location_type=Location.Type.QUARANTINE
    )
    production = LocationFactory.create(
        warehouse=warehouse, code="URETIM", location_type=Location.Type.PRODUCTION
    )
    tanks = [
        EquipmentFactory.create(
            capacity=Decimal("1000"),
            location=LocationFactory.create(warehouse=warehouse, location_type=Location.Type.TANK),
        )
        for _ in range(2)
    ]
    product = BulkMaterialFactory.create(code="BULASIK", name="Bulaşık deterjanı")
    las = MaterialFactory.create(code="LAS", name="LAS %96")
    sles = MaterialFactory.create(code="SLES", name="SLES %70")
    water = MaterialFactory.create(code="SU", name="Şebeke suyu", requires_incoming_qc=False)
    recipe = RecipeFactory.create(product=product)
    kg = unit("KG")
    version = recipes.create_version(
        planner,
        recipe,
        batch_size=Decimal("1000"),
        batch_unit=kg,
        lines=[
            {
                "material": las,
                "quantity": Decimal("600"),
                "unit": kg,
                "tolerance_pct": Decimal("2"),
                "instruction": "Yavaşça ekle",
            },
            {
                "material": sles,
                "quantity": Decimal("300"),
                "unit": kg,
                "tolerance_pct": Decimal("2"),
            },
            {
                "material": water,
                "quantity": Decimal("100"),
                "unit": kg,
                "tolerance_pct": Decimal("5"),
                "is_water": True,
            },
        ],
    )
    recipes.approve_version(planner, version)
    plant = Plant(
        warehouse,
        storage,
        quarantine,
        production,
        tanks[0],
        tanks[1],
        product,
        las,
        sles,
        water,
        version,
    )
    if stock:
        plant.lots["las"] = stocked_lot("5000", material=las, location=storage)
        plant.lots["sles"] = stocked_lot("5000", material=sles, location=storage)
        plant.lots["water"] = stocked_lot("10000", material=water, location=storage)
    return plant


def order_data(plant: Plant, quantity: str = "1000", **extra: Any) -> dict[str, Any]:
    return {
        "recipe_version": plant.version,
        "planned_quantity": Decimal(quantity),
        "unit": unit("KG"),
        "planned_date": date(2026, 10, 20),
        "equipment": plant.tank,
        **extra,
    }


def approved_order(plant: Plant, planner: User, quantity: str = "1000") -> ProductionOrder:
    order = services.create_order(planner, order_data(plant, quantity))
    return services.approve_order(planner, order)


def pick_all(plant: Plant, order: ProductionOrder, depo: User) -> None:
    """Su dışındaki her ihtiyacı tam miktarıyla hazırlar."""
    for requirement in order.requirements.filter(is_water=False):
        lot = Lot.objects.filter(material=requirement.material, status=Lot.Status.RELEASED).first()
        assert lot is not None
        services.pick_material(depo, order, requirement, lot, requirement.required_quantity)


def ready_order(plant: Plant, planner: User, depo: User, quantity: str = "1000") -> ProductionOrder:
    order = approved_order(plant, planner, quantity)
    pick_all(plant, order, depo)
    return services.mark_material_ready(depo, order)


def weigh_all(plant: Plant, batch: Any, operator: User, factor: str = "1") -> None:
    """Şarjın her satırını planlanan miktarın `factor` katı kadar tartar."""
    order = batch.order
    for requirement in order.requirements.order_by("sequence"):
        lot = Lot.objects.filter(material=requirement.material, status=Lot.Status.RELEASED).first()
        assert lot is not None
        planned = services.batch_line_quantity(requirement, batch)
        services.record_consumption(
            operator, batch, requirement, lot, planned * Decimal(factor), note="test"
        )
