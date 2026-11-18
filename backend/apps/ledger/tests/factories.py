"""Cari testleri için kurulum: fiyatlı sipariş → sevk edilmiş sevkiyat, fiyatlı kaydedilmiş mal
kabul. Stok ve belgeler yalnızca servislerle."""

from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.models import User
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceipt
from apps.inventory.tests.factories import storage_location
from apps.masterdata.models import Customer, Location, Material, Supplier
from apps.masterdata.tests.factories import (
    CustomerFactory,
    MaterialFactory,
    SupplierFactory,
    unit,
)
from apps.sales import services as sales
from apps.sales.models import Shipment
from apps.sales.tests.factories import finished_lot, finished_product, shipping_location

D = Decimal

# (mamul, miktar, birim kodu, birim fiyat ya da None, para birimi)
OrderLine = tuple[Material, str, str, str | None, str]
# (malzeme, kg, birim fiyat ya da None, para birimi, kur ya da None)
ReceiptLine = tuple[Material, str, str | None, str, str | None]


def product(vat_rate: str = "20", **kwargs: Any) -> Material:
    """Mamul (ADET; 1 KOLI = 12 ADET) ve mamul deposunda bol serbest lotu."""
    material = finished_product(vat_rate=D(vat_rate), **kwargs)
    finished_lot(material, "100000")
    return material


def raw_material(vat_rate: str = "20") -> Material:
    return MaterialFactory.create(requires_incoming_qc=False, vat_rate=D(vat_rate))


def dispatched_shipment(
    shipper: User,
    picker: User,
    lines: list[OrderLine],
    *,
    customer: Customer | None = None,
) -> Shipment:
    """Siparişin tamamı sevk edilmiş sevkiyat."""
    if not Location.objects.filter(location_type=Location.Type.SHIPPING).exists():
        shipping_location(code="SEVK")
    order = sales.create_order(
        shipper,
        {
            "customer": customer or CustomerFactory.create(),
            "order_date": date.today(),
            "promised_date": date.today(),
        },
        [
            {
                "product": material,
                "quantity": D(quantity),
                "unit": unit(unit_code),
                "unit_price": D(price) if price is not None else None,
                "currency": currency if price is not None else "",
            }
            for material, quantity, unit_code, price, currency in lines
        ],
    )
    order = sales.confirm_order(shipper, order)
    shipment = sales.plan_shipment(
        shipper,
        order,
        {"planned_date": date.today(), "vehicle_plate": "34 A 1", "driver_name": "Ali"},
    )
    for line in order.lines.all():
        for reservation in line.reservations.all():
            sales.pick_lot(picker, shipment, reservation.lot)
    sales.mark_loaded(picker, shipment)
    return sales.dispatch_shipment(shipper, shipment)


def posted_receipt(
    actor: User,
    lines: list[ReceiptLine],
    *,
    supplier: Supplier | None = None,
    receipt_date: date | None = None,
) -> GoodsReceipt:
    """Kaydedilmiş mal kabul (birim KG)."""
    receipt = inventory.create_goods_receipt(
        actor,
        {
            "supplier": supplier or SupplierFactory.create(),
            "receipt_date": receipt_date or date.today(),
            "storage_location": storage_location(),
        },
        [
            {
                "material": material,
                "quantity": D(quantity),
                "unit": unit("KG"),
                "unit_price": D(price) if price is not None else None,
                "currency": currency,
                "exchange_rate": D(rate) if rate is not None else None,
            }
            for material, quantity, price, currency, rate in lines
        ],
    )
    return inventory.post_goods_receipt(actor, receipt)
