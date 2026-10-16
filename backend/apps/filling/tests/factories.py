"""Dolum testleri için kurulum: depo, dolum hattı, mamul deposu, bulk lotu, ambalaj stoku ve onaylı
ambalaj reçetesi (servislerle)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.filling import services
from apps.filling.models import FillingOrder, FillingRequirement, FillingRun, PackagingSpec
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

D = Decimal


@dataclass
class Line:
    """Dolum hattı DH-01 (hat başı lokasyonu), mamul deposu, tank lokasyonu; 750 ml'lik mamul
    (bulk yoğunluğu 1,04 → adet başına 0,78 kg) ve ambalajı: şişe, kapak, etiket (1'er), koli
    (1/12)."""

    warehouse: Warehouse
    storage: Location
    tank: Location
    line_location: Location
    finished_store: Location
    filling_line: Equipment
    bulk: Material
    finished: Material
    bottle: Material
    cap: Material
    label: Material
    case: Material
    spec: PackagingSpec
    lots: dict[str, Lot] = field(default_factory=dict)

    @property
    def packaging(self) -> list[Material]:
        return [self.bottle, self.cap, self.label, self.case]


def packaging_material(code: str, name: str) -> Material:
    return MaterialFactory.create(
        code=code,
        name=name,
        material_type=Material.Type.PACKAGING,
        base_unit=unit("ADET"),
        requires_incoming_qc=False,
    )


def build_line(
    planner: User,
    *,
    stock: bool = True,
    bulk: Material | None = None,
    warehouse: Warehouse | None = None,
    tank: Location | None = None,
) -> Line:
    """`bulk` verilirse o bulk ürün (ör. üretim tesisinin) kullanılır; yoğunluğu 1,04 yapılır."""
    warehouse = warehouse or WarehouseFactory.create()
    storage = LocationFactory.create(
        warehouse=warehouse, code="AMB-DEPO", location_type=Location.Type.STORAGE
    )
    tank = tank or LocationFactory.create(
        warehouse=warehouse, code="TANK-9", location_type=Location.Type.TANK
    )
    line_location = LocationFactory.create(
        warehouse=warehouse, code="DOLUM-1", location_type=Location.Type.PRODUCTION
    )
    finished_store = LocationFactory.create(
        warehouse=warehouse, code="MAMUL", location_type=Location.Type.STORAGE
    )
    filling_line = EquipmentFactory.create(
        code="DH-01",
        name="Dolum hattı 1",
        equipment_type=Equipment.Type.FILLING_LINE,
        capacity=None,
        capacity_unit=None,
        location=line_location,
    )
    bulk_given = bulk is not None
    if bulk is None:
        bulk = BulkMaterialFactory.create(code="BULASIK", name="Bulaşık deterjanı")
    bulk.density = D("1.04")
    bulk.save(update_fields=["density"])
    finished = MaterialFactory.create(
        code="BULASIK-750",
        name="Bulaşık deterjanı 750 ml",
        material_type=Material.Type.FINISHED,
        base_unit=unit("ADET"),
        shelf_life_days=730,
        requires_incoming_qc=False,
    )
    bottle = packaging_material("SISE-750", "Şişe 750 ml")
    cap = packaging_material("KAPAK-28", "Kapak 28 mm")
    label = packaging_material("ETIKET-750", "Ön etiket 750 ml")
    case = packaging_material("KOLI-12", "Koli 12'li")
    spec = services.create_spec(
        planner,
        {
            "finished_product": finished,
            "bulk_product": bulk,
            "fill_quantity": D("750"),
            "fill_unit": unit("ML"),
            "fill_tolerance_pct": D("2"),
            "units_per_case": 12,
            "cases_per_pallet": 60,
            "lines": [
                {"material": bottle, "quantity_per_unit": D("1"), "scrap_allowance_pct": D("2")},
                {"material": cap, "quantity_per_unit": D("1"), "scrap_allowance_pct": D("2")},
                {"material": label, "quantity_per_unit": D("1"), "scrap_allowance_pct": D("3")},
                {
                    "material": case,
                    "quantity_per_unit": D("0.083333"),
                    "scrap_allowance_pct": D("2"),
                },
            ],
        },
    )
    spec = services.approve_spec(planner, spec)
    line = Line(
        warehouse,
        storage,
        tank,
        line_location,
        finished_store,
        filling_line,
        bulk,
        finished,
        bottle,
        cap,
        label,
        case,
        spec,
    )
    if stock:
        for key, material in zip(("bottle", "cap", "label", "case"), line.packaging, strict=True):
            line.lots[key] = stocked_lot("5000", material=material, location=storage)
    if stock and not bulk_given:
        line.lots["bulk"] = stocked_lot(
            "1000", material=bulk, location=tank, source=Lot.Source.PRODUCTION
        )
    return line


def order_data(line: Line, units: int = 1000, **extra: Any) -> dict[str, Any]:
    return {
        "finished_product": line.finished,
        "planned_units": units,
        "filling_line": line.filling_line,
        "output_location": line.finished_store,
        "planned_date": date(2026, 10, 21),
        **extra,
    }


def approved_order(line: Line, planner: User, units: int = 1000) -> FillingOrder:
    order = services.create_order(planner, order_data(line, units))
    return services.approve_order(planner, order)


def requirement(order: FillingOrder, material: Material) -> FillingRequirement:
    return order.requirements.get(material=material)


def pick_all(line: Line, order: FillingOrder, depo: User) -> None:
    """Her ambalaj satırını fire payı dahil ihtiyacıyla hazırlar."""
    for row in order.requirements.select_related("material"):
        lot = Lot.objects.filter(material=row.material, status=Lot.Status.RELEASED).first()
        assert lot is not None
        services.pick_packaging(depo, order, row, lot, row.required_quantity)


def ready_order(line: Line, planner: User, depo: User, units: int = 1000) -> FillingOrder:
    order = approved_order(line, planner, units)
    pick_all(line, order, depo)
    return services.mark_material_ready(depo, order)


def started_run(line: Line, planner: User, depo: User, filler: User) -> FillingRun:
    order = ready_order(line, planner, depo)
    return services.start_run(filler, order)
