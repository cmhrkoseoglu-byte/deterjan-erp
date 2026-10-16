"""İadenin sevkiyata bağlanması (Adım 3.2): sevk edilmiş sevkiyat, aynı müşteri, o sevkiyatta
sevk edilen lot ve "sevk edilenden fazla iade edilemez" kuralı."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.roles import DEPO
from apps.inventory.tests.factories import quarantine_location
from apps.masterdata.tests.factories import CustomerFactory, unit
from apps.returns import services
from apps.returns.models import CustomerReturn
from apps.sales import services as sales
from apps.sales.models import Shipment
from apps.sales.tests.factories import (
    confirmed_order,
    finished_lot,
    finished_product,
    shipping_location,
)

D = Decimal
Commit = Callable[[], AbstractContextManager[Any]]

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]


@pytest.fixture
def dispatched(shipper: User, make_user: Callable[..., User]) -> Shipment:
    """Müşteriye 30 adet sevk edilmiş sevkiyat."""
    picker = make_user(DEPO)
    shipping_location(code="SEVK")
    product = finished_product()
    finished_lot(product, "100")
    order = confirmed_order(shipper, [(product, "30", "ADET")])
    shipment = sales.plan_shipment(
        shipper,
        order,
        {"planned_date": date.today(), "vehicle_plate": "34 A 1", "driver_name": "Ali"},
    )
    lot = order.lines.get().reservations.get().lot
    sales.pick_lot(picker, shipment, lot)
    sales.mark_loaded(picker, shipment)
    return sales.dispatch_shipment(shipper, shipment)


def make_return(actor: User, shipment: Shipment, quantity: str, **header: Any) -> CustomerReturn:
    pick = shipment.lines.get().picks.get()
    data = {
        "customer": shipment.sales_order.customer,
        "shipment": shipment,
        "return_date": "2026-10-16",
        "reason": "Hasarlı koli",
        "quarantine_location": quarantine_location(),
        **header,
    }
    return services.create_return(
        actor,
        data,
        [
            {
                "product": pick.lot.material,
                "lot": pick.lot,
                "quantity": D(quantity),
                "unit": unit("ADET"),
            }
        ],
    )


def test_return_limited_to_shipped_quantity(
    shipper: User, dispatched: Shipment, commit: Commit
) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        make_return(shipper, dispatched, "31")
    assert exc.value.code == "return_exceeds_shipped"

    with commit():
        first = services.receive_return(shipper, make_return(shipper, dispatched, "20"))
    assert first.shipment == dispatched
    # İlk iade düşülür: aynı sevkiyattan en çok 10 adet daha.
    second = make_return(shipper, dispatched, "10")
    services.update_return(
        shipper,
        second,
        {},
        [
            {
                "id": second.lines.get().pk,
                "product": second.lines.get().product,
                "lot": second.lines.get().lot,
                "quantity": D("10"),
                "unit": unit("ADET"),
            }
        ],
    )
    with pytest.raises(BusinessRuleError) as exc:
        make_return(shipper, dispatched, "11")
    assert exc.value.code == "return_exceeds_shipped"


def test_return_shipment_must_match(shipper: User, dispatched: Shipment) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        make_return(shipper, dispatched, "1", customer=CustomerFactory.create())
    assert exc.value.code == "shipment_customer_mismatch"

    other = finished_product()
    stranger = finished_lot(other, "5")
    with pytest.raises(BusinessRuleError) as exc:
        services.create_return(
            shipper,
            {
                "customer": dispatched.sales_order.customer,
                "shipment": dispatched,
                "return_date": "2026-10-16",
                "reason": "Yanlış ürün",
                "quarantine_location": quarantine_location(),
            },
            [{"product": other, "lot": stranger, "quantity": D(1), "unit": unit("ADET")}],
        )
    assert exc.value.code == "lot_not_in_shipment"


def test_return_needs_dispatched_shipment(shipper: User) -> None:
    shipping_location(code="SEVK")
    product = finished_product()
    lot = finished_lot(product, "10")
    order = confirmed_order(shipper, [(product, "5", "ADET")])
    planned = sales.plan_shipment(shipper, order, {"planned_date": date.today()})
    with pytest.raises(BusinessRuleError) as exc:
        services.create_return(
            shipper,
            {
                "customer": order.customer,
                "shipment": planned,
                "return_date": "2026-10-16",
                "reason": "Hasarlı",
                "quarantine_location": quarantine_location(),
            },
            [{"product": product, "lot": lot, "quantity": D(1), "unit": unit("ADET")}],
        )
    assert exc.value.code == "shipment_not_dispatched"


def test_receive_locks_shipment_so_parallel_returns_are_checked_in_turn(
    shipper: User, dispatched: Shipment
) -> None:
    """Aynı sevkiyata bağlı iki taslak aynı anda teslim alınırsa ikincisi birincinin miktarını
    görsün diye sınır denetimi sevkiyat satırını kilitler."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    draft = make_return(shipper, dispatched, "30")
    with CaptureQueriesContext(connection) as queries:
        services.receive_return(shipper, draft)
    assert any(
        'FROM "sales_shipment"' in q["sql"] and "FOR UPDATE" in q["sql"]
        for q in queries.captured_queries
    )


def test_reversed_shipment_cannot_be_returned(shipper: User, dispatched: Shipment) -> None:
    from apps.inventory import services as inventory
    from apps.inventory.models import StockMovement

    movement = StockMovement.objects.get(movement_type=StockMovement.Type.SHIPMENT)
    inventory.reverse_movement(shipper, movement, "Yanlış sevk kaydı")

    with pytest.raises(BusinessRuleError) as exc:
        make_return(shipper, dispatched, "1")
    assert exc.value.code == "lot_not_in_shipment"
