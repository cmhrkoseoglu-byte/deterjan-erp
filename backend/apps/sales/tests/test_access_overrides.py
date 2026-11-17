"""Kişiye özel ayarla sevkiyat (docs/plan/kisi-yetkileri.md §10, 5. adım): kaldırılan yetki uç
noktada ve serviste düşer, okuma açık kalır. Lot serbest durumdan çıkınca rezervasyonların
bırakılması yetki denetimi olmayan bir sistem adımıdır."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess, can_read, has_access
from apps.core.records import can_view
from apps.inventory import services as inventory
from apps.inventory.models import StockReservation
from apps.masterdata.models import Location
from apps.sales import services
from apps.sales.access import ORDERS, PICKING, SHIPMENTS, SHIPPED_LOTS
from apps.sales.models import SalesOrder, Shipment
from apps.sales.tests.factories import (
    confirmed_order,
    draft_order,
    finished_lot,
    finished_product,
    shipping_location,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

D = Decimal
Status = SalesOrder.Status
Commit = Callable[[], AbstractContextManager[Any]]
ORDERS_URL = "/api/v1/sales/orders/"
SHIPMENTS_URL = "/api/v1/sales/shipments/"
SHIPPED_LOTS_URL = "/api/v1/sales/shipped-lots/"
VEHICLE = {"vehicle_plate": "34 ABC 123", "driver_name": "Ali Veli", "driver_id_no": "12345678901"}


def plan(order: SalesOrder) -> dict[str, Any]:
    return {**VEHICLE, "planned_date": timezone.localdate()}


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def dock() -> Location:
    return shipping_location(code="SEVK")


@pytest.fixture
def picker(make_user: Callable[..., User]) -> User:
    return make_user("depo")


def stocked_order(seller: User, quantity: str = "10") -> SalesOrder:
    product = finished_product()
    finished_lot(product, "100", expiry_date=timezone.localdate() + timedelta(days=300))
    return confirmed_order(seller, [(product, quantity, "ADET")])


def picked_shipment(seller: User, picker: User) -> Shipment:
    order = stocked_order(seller)
    shipment = services.plan_shipment(seller, order, plan(order))
    lot = order.lines.get().product.lots.get()
    services.pick_lot(picker, shipment, lot)
    return shipment


def test_removing_picking_change_stops_picking_and_keeps_reads(
    seller: User, picker: User, dock: Location
) -> None:
    """Depodan "Toplama ve yükleme: Değiştirir" kaldırılınca lot okutma, okutmayı geri alma ve
    yükleme 403 olur; sevkiyat okuması ve toplama önerisi açık kalır."""
    shipment = picked_shipment(seller, picker)
    pick = shipment.lines.get().picks.get()
    lot = pick.lot
    client = api(override(picker, PICKING.key, CHANGE))

    assert client.get(SHIPMENTS_URL).status_code == 200
    assert client.get(f"{SHIPMENTS_URL}{shipment.pk}/").status_code == 200
    assert client.get(f"{SHIPMENTS_URL}{shipment.pk}/suggestions/").status_code == 200

    picked = client.post(
        f"{SHIPMENTS_URL}{shipment.pk}/pick/", {"lot": lot.pk, "quantity": "1"}, format="json"
    )
    assert picked.status_code == 403
    assert picked.json()["required"] == [{"key": PICKING.key, "level": CHANGE}]
    undone = client.post(
        f"{SHIPMENTS_URL}{shipment.pk}/undo-pick/", {"pick": pick.pk}, format="json"
    )
    assert undone.status_code == 403
    assert client.post(f"{SHIPMENTS_URL}{shipment.pk}/load/", {}, format="json").status_code == 403
    with pytest.raises(MissingAccess):
        services.mark_loaded(picker, shipment)
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.PICKING


def test_granted_picking_change_lets_another_role_pick(
    seller: User, picker: User, dock: Location, make_user: Callable[..., User]
) -> None:
    order = stocked_order(seller)
    shipment = services.plan_shipment(seller, order, plan(order))
    lot = order.lines.get().product.lots.get()
    planner = override(make_user("planlama"), PICKING.key, CHANGE, effect="grant")

    picked = api(planner).post(
        f"{SHIPMENTS_URL}{shipment.pk}/pick/", {"lot": lot.pk}, format="json"
    )
    assert picked.status_code == 200, picked.json()
    assert picked.json()["status"] == Shipment.Status.PICKING


def test_order_cancel_needs_change_for_a_draft_and_approve_afterwards(
    seller: User, make_user: Callable[..., User]
) -> None:
    product = finished_product()
    finished_lot(product, "100")
    draft = draft_order(seller, [(product, "5", "ADET")])
    other_draft = draft_order(seller, [(product, "5", "ADET")])
    confirmed = confirmed_order(seller, [(product, "5", "ADET")])

    # İkisi de yoksa uç nokta reddeder: mesaj öteki denetimlerle aynı, iki yetki de listede.
    denied = api(make_user("planlama")).post(
        f"{ORDERS_URL}{draft.pk}/cancel/", {"reason": "x"}, format="json"
    )
    assert denied.status_code == 403
    assert denied.json() == {
        "code": "permission_denied",
        "detail": "Bu işlem için yetkiniz yok.",
        "required": [
            {"key": ORDERS.key, "level": CHANGE},
            {"key": ORDERS.key, "level": APPROVE},
        ],
    }

    # Onaylar'ı kaldırılan kişi taslağı iptal eder; onaylı siparişi iptal edemez, onaylayamaz.
    editor = api(override(make_user("sevkiyat"), ORDERS.key, APPROVE))
    refused = editor.post(f"{ORDERS_URL}{confirmed.pk}/cancel/", {"reason": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": ORDERS.key, "level": APPROVE}]
    confirm = editor.post(f"{ORDERS_URL}{other_draft.pk}/confirm/", {}, format="json")
    assert confirm.status_code == 403
    assert confirm.json()["required"] == [{"key": ORDERS.key, "level": APPROVE}]
    cancelled = editor.post(f"{ORDERS_URL}{draft.pk}/cancel/", {"reason": "Yanlış"}, format="json")
    assert cancelled.status_code == 200, cancelled.json()
    assert cancelled.json()["status"] == Status.CANCELLED

    # Değiştirir'i kaldırılan kişi onaylı siparişi iptal eder; sipariş açamaz, taslağı
    # düzenleyemez ve iptal edemez, rezervasyon yapamaz.
    approver_user = override(make_user("sevkiyat"), ORDERS.key, CHANGE)
    approver = api(approver_user)
    assert approver.post(ORDERS_URL, {}, format="json").status_code == 403
    edit = approver.patch(f"{ORDERS_URL}{other_draft.pk}/", {"notes": "x"}, format="json")
    assert edit.status_code == 403
    kept = approver.post(f"{ORDERS_URL}{other_draft.pk}/cancel/", {"reason": "x"}, format="json")
    assert kept.status_code == 403
    assert kept.json()["required"] == [{"key": ORDERS.key, "level": CHANGE}]
    assert approver.post(f"{ORDERS_URL}{confirmed.pk}/reserve-shortages/").status_code == 403
    with pytest.raises(MissingAccess):
        services.cancel_order(approver_user, other_draft, "x")
    done = approver.post(
        f"{ORDERS_URL}{confirmed.pk}/cancel/", {"reason": "Müşteri vazgeçti"}, format="json"
    )
    assert done.status_code == 200, done.json()
    assert done.json()["status"] == Status.CANCELLED
    other_draft.refresh_from_db()
    assert other_draft.status == Status.DRAFT


def test_removing_shipment_view_keeps_picking_reads_but_closes_the_waybill(
    seller: User, picker: User, dock: Location
) -> None:
    """Depodan "Sevkiyatlar ve irsaliye: Görür" kaldırılınca sevkiyatlar Toplama ve yükleme ile
    okunur; irsaliye (veri ve PDF) yalnız Sevkiyatlar ve irsaliye: Görür ile açılır."""
    shipment = picked_shipment(seller, picker)
    services.mark_loaded(picker, shipment)
    before = api(picker)
    assert before.get(f"{SHIPMENTS_URL}{shipment.pk}/waybill.pdf").status_code == 200

    client = api(override(picker, SHIPMENTS.key, VIEW))
    assert client.get(SHIPMENTS_URL).status_code == 200
    assert client.get(f"{SHIPMENTS_URL}{shipment.pk}/").status_code == 200
    assert client.get(f"{SHIPMENTS_URL}{shipment.pk}/suggestions/").status_code == 200
    for path in ("waybill/", "waybill.pdf"):
        refused = client.get(f"{SHIPMENTS_URL}{shipment.pk}/{path}")
        assert refused.status_code == 403, path
        assert refused.json()["required"] == [{"key": SHIPMENTS.key, "level": VIEW}]
    # Sipariş okuması ayrı bölümdür, açık kalır.
    assert client.get(ORDERS_URL).status_code == 200


def test_removing_shipment_approve_stops_dispatch_only(
    seller: User, picker: User, dock: Location
) -> None:
    shipment = picked_shipment(seller, picker)
    services.mark_loaded(picker, shipment)
    client = api(override(seller, SHIPMENTS.key, APPROVE))

    refused = client.post(f"{SHIPMENTS_URL}{shipment.pk}/dispatch/", {}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": SHIPMENTS.key, "level": APPROVE}]
    edited = client.patch(f"{SHIPMENTS_URL}{shipment.pk}/", {"notes": "Kapı 2"}, format="json")
    assert edited.status_code == 200, edited.json()
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.LOADED


def test_shipped_lots_follow_their_own_section(
    seller: User, make_user: Callable[..., User]
) -> None:
    order = stocked_order(seller)
    params = {"customer": str(order.customer_id)}

    revoked = api(override(make_user("yonetim"), SHIPPED_LOTS.key, VIEW))
    refused = revoked.get(SHIPPED_LOTS_URL, params)
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": SHIPPED_LOTS.key, "level": VIEW}]
    assert revoked.get(ORDERS_URL).status_code == 200

    granted = api(override(make_user("depo"), SHIPPED_LOTS.key, VIEW, effect="grant"))
    assert granted.get(SHIPPED_LOTS_URL, params).status_code == 200
    # Karşılanmayan metot da bölümü izler, sonra DRF 405 döner.
    assert granted.post(SHIPPED_LOTS_URL, {}, format="json").status_code == 405


def test_record_panel_follows_the_screens_read_rule(
    seller: User, picker: User, dock: Location, make_user: Callable[..., User]
) -> None:
    """Yorum, geçmiş ve ek, kaydın kendi ekranının okumasını izler (plan §5.8): sevkiyat iki
    bölümden biriyle, sipariş Satış siparişleri ile okunur."""
    shipment = picked_shipment(seller, picker)
    order = shipment.sales_order

    planner = make_user("planlama")
    assert can_view(planner, order) and can_view(planner, shipment)
    override(planner, ORDERS.key, VIEW)
    assert not can_view(planner, order)
    assert can_view(planner, shipment)

    override(picker, SHIPMENTS.key, VIEW)
    assert can_view(picker, shipment)  # Toplama ve yükleme ile
    override(picker, PICKING.key, VIEW)
    assert not can_view(picker, shipment)
    assert can_view(picker, order)

    assert not can_view(make_user("uretim"), order)


def test_lot_leaving_released_releases_reservations_without_sales_rights(
    seller: User, commit: Commit, make_user: Callable[..., User]
) -> None:
    """Rezervasyonun bırakılması lot kararının sistem adımıdır (plan §5.4): lotu bloke eden
    kişinin sevkiyatta hiçbir yetkisi olmasa da siparişteki rezervasyon bırakılır."""
    product = finished_product()
    lot = finished_lot(product, "100")
    order = draft_order(seller, [(product, "50", "ADET")])
    with commit():
        services.confirm_order(seller, order)
    lab = make_user("laboratuvar")
    assert not can_read(lab, ORDERS, SHIPMENTS, PICKING)
    assert not has_access(lab, ORDERS, CHANGE)

    with commit():
        inventory.block_lot(lab, lot, "Müşteri şikâyeti")

    assert not StockReservation.objects.filter(status=StockReservation.Status.ACTIVE).exists()


def test_each_service_names_its_section_and_level(
    seller: User, picker: User, dock: Location, make_user: Callable[..., User]
) -> None:
    """Her servis denetimi planın §3.7 tablosundaki bölüme ve düzeye bağlıdır: rolü olmayan kişi
    her birinde, işin kurallarından önce, o yetkiyi söyleyen 403 alır. Paket denkliği testi aynı
    yetkinin bugünkü rollerle denkliğini kanıtlar."""
    product = finished_product()
    lot = finished_lot(product, "100", expiry_date=timezone.localdate() + timedelta(days=300))
    draft = draft_order(seller, [(product, "5", "ADET")])
    confirmed = confirmed_order(seller, [(product, "10", "ADET")])
    line = confirmed.lines.get()
    reservation = StockReservation.objects.filter(
        status=StockReservation.Status.ACTIVE, sales_order_line=line
    ).first()
    assert reservation is not None
    shipment = services.plan_shipment(seller, confirmed, plan(confirmed))
    services.pick_lot(picker, shipment, lot)
    pick = shipment.lines.get().picks.get()
    nobody = make_user()
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        (
            "create_order",
            lambda: services.create_order(nobody, {"customer": draft.customer}),
            (ORDERS.key, CHANGE),
        ),
        ("update_order", lambda: services.update_order(nobody, draft, {}), (ORDERS.key, CHANGE)),
        ("confirm_order", lambda: services.confirm_order(nobody, draft), (ORDERS.key, APPROVE)),
        (
            "cancel_order taslak",
            lambda: services.cancel_order(nobody, draft, "x"),
            (ORDERS.key, CHANGE),
        ),
        (
            "cancel_order onaylı",
            lambda: services.cancel_order(nobody, confirmed, "x"),
            (ORDERS.key, APPROVE),
        ),
        ("close_order", lambda: services.close_order(nobody, confirmed), (ORDERS.key, CHANGE)),
        (
            "reserve_shortages",
            lambda: services.reserve_shortages(nobody, confirmed),
            (ORDERS.key, CHANGE),
        ),
        (
            "reserve_lot",
            lambda: services.reserve_lot(
                nobody, line, lot=lot, location=reservation.location, quantity=D("1")
            ),
            (ORDERS.key, CHANGE),
        ),
        (
            "release_line_reservation",
            lambda: services.release_line_reservation(nobody, reservation),
            (ORDERS.key, CHANGE),
        ),
        (
            "plan_shipment",
            lambda: services.plan_shipment(nobody, confirmed, plan(confirmed)),
            (SHIPMENTS.key, CHANGE),
        ),
        (
            "update_shipment",
            lambda: services.update_shipment(nobody, shipment, {}),
            (SHIPMENTS.key, CHANGE),
        ),
        ("pick_lot", lambda: services.pick_lot(nobody, shipment, lot), (PICKING.key, CHANGE)),
        ("undo_pick", lambda: services.undo_pick(nobody, pick), (PICKING.key, CHANGE)),
        ("mark_loaded", lambda: services.mark_loaded(nobody, shipment), (PICKING.key, CHANGE)),
        (
            "dispatch_shipment",
            lambda: services.dispatch_shipment(nobody, shipment),
            (SHIPMENTS.key, APPROVE),
        ),
        (
            "cancel_shipment",
            lambda: services.cancel_shipment(nobody, shipment, "x"),
            (SHIPMENTS.key, CHANGE),
        ),
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
    draft.refresh_from_db()
    shipment.refresh_from_db()
    assert draft.status == Status.DRAFT
    assert shipment.status == Shipment.Status.PICKING


def test_unrouted_methods_keep_todays_rule(
    seller: User, picker: User, dock: Location, make_user: Callable[..., User]
) -> None:
    """Görünümün karşılamadığı metotlar ve güvenli metotlar (sözleşme testinin bir kısmı dışında)
    bugünkü kararı verir. Siparişte HEAD ve OPTIONS okumadır, karşılanmayan yazma metodu
    Değiştirir ister; sevkiyatta yalnız GET okumadır, HEAD, OPTIONS ve karşılanmayan metot
    Sevkiyatlar ve irsaliye: Değiştirir ister; ikisinde de karşılanmayan GET okumadır."""
    shipment = picked_shipment(seller, picker)
    order = shipment.sales_order
    shipping, warehouse = api(seller), api(picker)
    manager, planning = api(make_user("yonetim")), api(make_user("planlama"))
    signed_in = api(make_user())

    # Sipariş: karşılanmayan yazma metodu Değiştirir, sonra 405.
    assert manager.delete(f"{ORDERS_URL}{order.pk}/").status_code == 405
    assert warehouse.delete(f"{ORDERS_URL}{order.pk}/").status_code == 403
    assert manager.put(ORDERS_URL, {}, format="json").status_code == 405
    assert planning.put(ORDERS_URL, {}, format="json").status_code == 403
    assert manager.post(f"{ORDERS_URL}{order.pk}/", {}, format="json").status_code == 405
    assert planning.post(f"{ORDERS_URL}{order.pk}/candidates/", {}).status_code == 403
    # Eylem yolunda HEAD karşılanmaz (yazma kuralı); GET okumadır; OPTIONS okumadır.
    assert manager.head(f"{ORDERS_URL}{order.pk}/confirm/").status_code == 405
    assert planning.head(f"{ORDERS_URL}{order.pk}/confirm/").status_code == 403
    assert planning.get(f"{ORDERS_URL}{order.pk}/confirm/").status_code == 405
    assert signed_in.get(f"{ORDERS_URL}{order.pk}/confirm/").status_code == 403
    assert planning.options(f"{ORDERS_URL}{order.pk}/confirm/").status_code == 200
    assert planning.head(ORDERS_URL).status_code == 200

    # Sevkiyat: HEAD ve OPTIONS yalnız Değiştirir ile (okutma yolunda da).
    detail = f"{SHIPMENTS_URL}{shipment.pk}/"
    assert warehouse.get(detail).status_code == 200
    assert warehouse.head(detail).status_code == 403
    assert shipping.head(detail).status_code == 200
    assert warehouse.head(f"{detail}waybill.pdf").status_code == 403
    assert warehouse.options(f"{detail}pick/").status_code == 403
    assert shipping.options(f"{detail}pick/").status_code == 200
    assert planning.options(SHIPMENTS_URL).status_code == 403
    # Karşılanmayan: GET okumadır; öteki metotlar Değiştirir, sonra 405.
    assert warehouse.get(f"{detail}pick/").status_code == 405
    assert signed_in.get(f"{detail}pick/").status_code == 403
    assert warehouse.head(f"{detail}pick/").status_code == 403
    assert shipping.head(f"{detail}pick/").status_code == 405
    assert warehouse.delete(detail).status_code == 403
    assert shipping.delete(detail).status_code == 405
    assert planning.put(f"{detail}waybill.pdf", {}).status_code == 403
    assert shipping.put(f"{detail}waybill.pdf", {}).status_code == 405

    # Müşteriye sevk edilen lotlar: karşılanmayan metot da bölümü ister.
    assert warehouse.post(SHIPPED_LOTS_URL, {}).status_code == 403
    assert shipping.post(SHIPPED_LOTS_URL, {}).status_code == 405
    assert manager.delete(SHIPPED_LOTS_URL).status_code == 405

    assert APIClient().get(f"{ORDERS_URL}{order.pk}/confirm/").status_code == 401
    assert APIClient().delete(detail).status_code == 401
