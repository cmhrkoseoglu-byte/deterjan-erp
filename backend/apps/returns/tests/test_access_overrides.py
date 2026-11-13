"""Kişiye özel ayarla iadeler (docs/plan/kisi-yetkileri.md §10, 4. adım): iade kayıtları ve
teslim alma ayrı bölümlerdir; iade formunun sevkiyat seçimi iadelerin kendi uç noktasıdır ve
İade kayıtları: Değiştirir ister (plan §5.4). İade sonucu ve numune açılması sistem adımıdır."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import CHANGE, READ
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.inventory import services as inventory
from apps.inventory.tests.factories import storage_location
from apps.quality.models import Sample, SampleStage
from apps.returns import services
from apps.returns.access import RECEIVING, RETURNS
from apps.returns.models import CustomerReturnLine
from apps.returns.tests.factories import Setup, draft_return
from apps.sales import services as sales
from apps.sales.models import Shipment
from apps.sales.tests.factories import (
    confirmed_order,
    finished_lot,
    finished_product,
    shipping_location,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]
D = Decimal
Commit = Callable[[], AbstractContextManager[Any]]


def url(name: str, *args: Any) -> str:
    return reverse(f"returns:{name}", args=args)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def dispatched(shipper: User, make_user: Callable[..., User]) -> Shipment:
    """Müşteriye 30 adet sevk edilmiş sevkiyat."""
    picker = make_user("depo")
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


def test_shipment_selection_is_the_returns_own_endpoint(
    shipper: User, depo: User, dispatched: Shipment
) -> None:
    customer = dispatched.sales_order.customer_id
    listing = api(shipper).get(url("return-shipments"), {"customer": str(customer)})
    assert listing.status_code == 200, listing.json()
    [row] = listing.json()["results"]
    assert row == {
        "id": dispatched.pk,
        "number": dispatched.number,
        "order_number": dispatched.sales_order.number,
        "planned_date": dispatched.planned_date.isoformat(),
    }
    other = api(shipper).get(url("return-shipments"), {"customer": str(customer + 999)})
    assert other.json()["results"] == []
    assert api(shipper).get(url("return-shipments")).status_code == 400
    assert api(shipper).get(url("return-shipments"), {"customer": "²"}).status_code == 400

    refused = api(depo).get(url("return-shipments"), {"customer": str(customer)})
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": RETURNS.key, "level": CHANGE}]
    revoked = api(override(shipper, RETURNS.key, CHANGE))
    assert revoked.get(url("return-shipments"), {"customer": str(customer)}).status_code == 403
    assert revoked.get(url("return-list")).status_code == 200


def test_removing_receiving_stops_receipt_and_keeps_reads(
    shipper: User, depo: User, setup: Setup
) -> None:
    document = draft_return(shipper, setup)
    client = api(override(depo, RECEIVING.key, CHANGE))

    assert client.get(url("return-detail", document.pk)).status_code == 200
    refused = client.post(url("return-receive", document.pk))
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": RECEIVING.key, "level": CHANGE}]
    with pytest.raises(MissingAccess):
        services.receive_return(depo, document)


def test_receipt_opens_the_sample_and_the_decision_settles_lines_without_their_rights(
    shipper: User, depo: User, lab: User, setup: Setup, commit: Commit
) -> None:
    """Numune açılması ve iade sonucu sistem adımıdır (plan §5.4): teslim alan kalite kayıtlarını,
    kararı veren iade kayıtlarını okuyamasa da işler."""
    document = draft_return(shipper, setup)
    override(depo, "quality.open_records", READ)
    with commit():
        services.receive_return(depo, document)
    line = document.lines.get()
    assert Sample.objects.filter(lot=line.lot, stage=SampleStage.RETURN).exists()

    override(lab, "returns.open_records", READ)
    with commit():
        inventory.release_lot(
            lab, line.lot, "Analiz uygun", storage_location(), quality_decision=True
        )
    line.refresh_from_db()
    assert line.disposition == CustomerReturnLine.Disposition.RESTOCK


def test_unrouted_methods_keep_todays_rule(
    shipper: User, depo: User, lab: User, setup: Setup
) -> None:
    """Bugün yalnız liste ve kayıt okumadır: karşılanmayan metot (GET dahil, teslim alma yolunda
    da) iade yazma yetkisini ister, sonra 405 döner."""
    document = draft_return(shipper, setup)

    assert api(shipper).get(url("return-receive", document.pk)).status_code == 405
    assert api(depo).get(url("return-receive", document.pk)).status_code == 403
    assert api(shipper).delete(url("return-detail", document.pk)).status_code == 405
    assert api(lab).delete(url("return-detail", document.pk)).status_code == 403
    assert APIClient().delete(url("return-detail", document.pk)).status_code == 401


def test_each_service_names_its_section_and_level(
    shipper: User, setup: Setup, make_user: Callable[..., User], commit: Commit
) -> None:
    draft = draft_return(shipper, setup)
    with commit():
        received = services.receive_return(shipper, draft_return(shipper, setup, quantity="1"))
    line = received.lines.get()
    nobody = make_user()
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        ("create_return", lambda: services.create_return(nobody, {}, []), (RETURNS.key, CHANGE)),
        (
            "update_return",
            lambda: services.update_return(nobody, draft, {}, None),
            (RETURNS.key, CHANGE),
        ),
        (
            "cancel_return",
            lambda: services.cancel_return(nobody, draft, "x"),
            (RETURNS.key, CHANGE),
        ),
        ("receive_return", lambda: services.receive_return(nobody, draft), (RECEIVING.key, CHANGE)),
        ("scrap_line", lambda: services.scrap_line(nobody, line, "x"), (RECEIVING.key, CHANGE)),
    ]
    wrong: list[str] = []
    for name, call, required in calls:
        try:
            call()
        except MissingAccess as error:
            if error.required != (required,):
                wrong.append(f"{name}: {error.required} != {(required,)}")
        else:
            wrong.append(f"{name}: reddedilmedi")
    assert not wrong, "\n".join(wrong)
