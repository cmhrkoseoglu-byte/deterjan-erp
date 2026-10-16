from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Customer
from apps.sales import selectors
from apps.sales.models import SalesOrder, Shipment

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_includes_sales(roles: None) -> None:
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())

    assert Customer.objects.get(code="M-ZINCIR").min_remaining_shelf_life_days == 180
    confirmed = SalesOrder.objects.get(customer_po_no="DEMO-1")
    assert confirmed.status == SalesOrder.Status.CONFIRMED
    lines = list(selectors.order_lines(confirmed))
    # 1 palet = 720 adet; zincir market 180 gün ister, 120 günlük lot atlanır.
    assert [(line.base_quantity, line.shortage_quantity) for line in lines] == [  # type: ignore[attr-defined]
        (Decimal(720), Decimal(0)),
        (Decimal(240), Decimal(0)),
    ]
    lot_nos = {r.lot.lot_no for r in selectors.order_reservations(confirmed)}
    assert lot_nos == {"ACILIS-BL750-2", "ACILIS-YC1000-1"}
    assert SalesOrder.objects.get(customer_po_no="DEMO-2").status == SalesOrder.Status.DRAFT
    assert [s.status for s in confirmed.shipments.all()] == [Shipment.Status.PLANNED]
    shipped = SalesOrder.objects.get(customer_po_no="DEMO-3")
    assert shipped.status == SalesOrder.Status.SHIPPED
    assert [s.status for s in shipped.shipments.all()] == [Shipment.Status.DISPATCHED]
    assert_stock_invariants()
