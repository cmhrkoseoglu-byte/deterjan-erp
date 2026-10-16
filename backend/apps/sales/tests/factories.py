"""Satış testleri için yardımcılar: adet, koli ve palet birimli mamul ve stoklu mamul lotu."""

from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.inventory.models import Lot
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.models import Location, Material, MaterialUnitConversion
from apps.masterdata.tests.factories import CustomerFactory, LocationFactory, MaterialFactory, unit
from apps.sales import services
from apps.sales.models import SalesOrder

UNITS_PER_CASE = Decimal(12)
CASES_PER_PALLET = Decimal(40)


def finished_product(**kwargs: Any) -> Material:
    """Mamul: temel birim ADET, 1 KOLI = 12 ADET, 1 PALET = 480 ADET."""
    product = MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), **kwargs
    )
    MaterialUnitConversion.objects.create(
        material=product, unit=unit("KOLI"), factor_to_base=UNITS_PER_CASE
    )
    MaterialUnitConversion.objects.create(
        material=product, unit=unit("PALET"), factor_to_base=UNITS_PER_CASE * CASES_PER_PALLET
    )
    return product


def finished_lot(
    product: Material,
    quantity: str | Decimal = "120",
    *,
    location: Location | None = None,
    expiry_date: date | None = None,
    status: str = Lot.Status.RELEASED,
) -> Lot:
    """Mamul deposunda stoklu, serbest (varsayılan) dolum lotu."""
    return stocked_lot(
        quantity,
        material=product,
        location=location or storage_location(),
        status=status,
        source=Lot.Source.FILLING,
        expiry_date=expiry_date,
    )


def draft_order(
    actor: User,
    lines: list[tuple[Material, str, str]],
    *,
    customer: Any = None,
    **data: Any,
) -> SalesOrder:
    """Taslak sipariş: `lines` = [(mamul, miktar, birim kodu), ...]."""
    values = {"customer": customer or CustomerFactory.create(), "order_date": date.today(), **data}
    return services.create_order(
        actor,
        values,
        [
            {"product": product, "quantity": Decimal(quantity), "unit": unit(code)}
            for product, quantity, code in lines
        ],
    )


def shipping_location(**kwargs: Any) -> Location:
    """Sevk alanı (`SHIPPING` türü lokasyon)."""
    return LocationFactory.create(location_type=Location.Type.SHIPPING, **kwargs)


def confirmed_order(
    actor: User, lines: list[tuple[Material, str, str]], **kwargs: Any
) -> SalesOrder:
    """Onaylı (FEFO ile rezerve edilmiş) sipariş."""
    order = draft_order(actor, lines, **kwargs)
    return services.confirm_order(actor, order)
