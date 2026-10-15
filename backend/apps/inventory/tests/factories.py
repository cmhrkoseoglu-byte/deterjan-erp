"""Stok testleri için yardımcılar. Stok yalnızca servislerle oluşturulur (hareket defteri)."""

from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.inventory import services
from apps.inventory.models import Lot, StockMovement
from apps.masterdata.models import Location, Material
from apps.masterdata.tests.factories import LocationFactory, MaterialFactory

MOVEMENT_FOR_SOURCE: dict[str, str] = {
    Lot.Source.PURCHASE: StockMovement.Type.RECEIPT,
    Lot.Source.PRODUCTION: StockMovement.Type.PRODUCTION_OUTPUT,
    Lot.Source.FILLING: StockMovement.Type.PRODUCTION_OUTPUT,
}


def storage_location(**kwargs: Any) -> Location:
    return LocationFactory.create(location_type=Location.Type.STORAGE, **kwargs)


def quarantine_location(**kwargs: Any) -> Location:
    return LocationFactory.create(location_type=Location.Type.QUARANTINE, **kwargs)


def stocked_lot(
    quantity: str | Decimal = "100",
    *,
    material: Material | None = None,
    location: Location | None = None,
    status: str = Lot.Status.RELEASED,
    source: str = Lot.Source.PURCHASE,
    expiry_date: date | None = None,
    actor: User | None = None,
) -> Lot:
    """Stoklu bir lot: `create_lot` + `RECEIPT` hareketi (servislerle)."""
    material = material or MaterialFactory.create()
    location = location or storage_location()
    assert material is not None
    lot = services.create_lot(
        actor, material=material, source=source, status=status, expiry_date=expiry_date
    )
    services.post_movement(
        actor,
        material,
        lot,
        location,
        Decimal(quantity),
        MOVEMENT_FOR_SOURCE[source],
        None,
    )
    return lot
