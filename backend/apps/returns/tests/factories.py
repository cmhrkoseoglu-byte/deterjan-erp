"""İade testleri için kurulum: mamul ürün, mamul deposu, karantina, müşteri ve müşteriye "sevk
edilmiş" (SHIPMENT hareketiyle çıkmış) serbest bir mamul lotu. Stok yalnızca servislerle."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockMovement
from apps.inventory.tests.factories import quarantine_location, stocked_lot, storage_location
from apps.masterdata.models import Customer, Location, Material
from apps.masterdata.tests.factories import CustomerFactory, MaterialFactory, unit
from apps.returns import services
from apps.returns.models import CustomerReturn

D = Decimal


@dataclass
class Setup:
    product: Material
    store: Location
    quarantine: Location
    customer: Customer
    lot: Lot


def finished_product(**kwargs: Any) -> Material:
    return MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), **kwargs
    )


def shipped_lot(
    product: Material, store: Location, *, stock: str = "100", shipped: str = "40"
) -> Lot:
    """Mamul deposunda `stock` adet serbest lot; `shipped` adedi SHIPMENT hareketiyle çıkmış."""
    lot = stocked_lot(stock, material=product, location=store, source=Lot.Source.FILLING)
    inventory.post_movement(
        None, product, lot, store, -D(shipped), StockMovement.Type.SHIPMENT, None
    )
    return lot


def build_setup() -> Setup:
    product = finished_product()
    store = storage_location(code="MAMUL-DEPO")
    return Setup(
        product=product,
        store=store,
        quarantine=quarantine_location(code="IADE-KRNT"),
        customer=CustomerFactory.create(),
        lot=shipped_lot(product, store),
    )


def draft_return(
    actor: User, setup: Setup, quantity: str = "12", lot: Lot | None = None
) -> CustomerReturn:
    lot = lot or setup.lot
    return services.create_return(
        actor,
        {
            "customer": setup.customer,
            "return_date": "2026-10-16",
            "reason": "Müşteri şikâyeti: koku farklı",
            "quarantine_location": setup.quarantine,
        },
        [{"product": lot.material, "lot": lot, "quantity": D(quantity), "unit": unit("ADET")}],
    )
