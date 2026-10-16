"""Satın alma testleri için yardımcılar (kayıtlar servislerle oluşturulur)."""

from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.inventory.tests.factories import quarantine_location, storage_location
from apps.masterdata.models import Location, Material, Supplier
from apps.masterdata.tests.factories import MaterialFactory, SupplierFactory, unit
from apps.purchasing import services
from apps.purchasing.models import PurchaseOrder

ORDER_DATE = date(2026, 10, 16)


def raw_material(**kwargs: Any) -> Material:
    return MaterialFactory.create(**kwargs)


def line(
    material: Material, quantity: str = "1000", price: str = "10", **extra: Any
) -> dict[str, Any]:
    return {
        "material": material,
        "quantity": Decimal(quantity),
        "unit": unit("KG"),
        "unit_price": Decimal(price),
        "expected_date": date(2026, 10, 20),
        **extra,
    }


def draft_order(
    actor: User,
    lines: list[dict[str, Any]],
    *,
    supplier: Supplier | None = None,
    **data: Any,
) -> PurchaseOrder:
    return services.create_order(
        actor,
        {"supplier": supplier or SupplierFactory.create(), "order_date": ORDER_DATE, **data},
        lines,
    )


def approved_order(manager: User, lines: list[dict[str, Any]], **data: Any) -> PurchaseOrder:
    return services.approve_order(manager, draft_order(manager, lines, **data))


def receipt_locations() -> dict[str, Location]:
    return {"quarantine_location": quarantine_location(), "storage_location": storage_location()}
