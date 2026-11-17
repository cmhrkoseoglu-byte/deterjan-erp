"""Paket B'nin elle denenen dört senaryosu, uçtan uca API ile (docs/plan/kisi-yetkileri.md §10,
9. adım): admin Yetkiler ekranından (`PUT /users/{pk}/access/`) kaydeder, kişi ilgili ekranlarda
sonucu görür."""

from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core import event_names, events
from apps.core.models import User
from apps.core.roles import ADMIN, DEPO, LABORATUVAR, PLANLAMA
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Customer, Supplier
from apps.masterdata.tests.factories import CustomerFactory, SupplierFactory
from apps.production.tests.factories import approved_order, build_plant
from apps.quality.tests.factories import quarantined_raw_lot, sample_with_spec
from apps.workflow.models import Notification

pytestmark = pytest.mark.django_db
MakeUser = Callable[..., User]


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def revoke(key: str, level: str) -> dict[str, str]:
    return {"key": key, "level": level, "effect": "revoke"}


def save(admin: APIClient, user: User, overrides: list[dict[str, str]], **extra: Any) -> Any:
    path = f"/api/v1/users/{user.pk}/access/"
    version = admin.get(path).json()["version"]
    response = admin.put(
        path,
        {"version": version, "overrides": overrides, "note": "Senaryo denemesi", **extra},
        format="json",
    )
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.fixture
def admin(make_user: MakeUser) -> APIClient:
    return api(make_user(ADMIN, username="yonetici"))


@pytest.fixture
def invariants() -> Iterator[None]:
    yield
    assert_stock_invariants()


@pytest.fixture
def published() -> list[events.Event]:
    received: list[events.Event] = []
    events.subscribe("*")(received.append)
    return received


def production(name: str, *args: Any) -> str:
    return reverse(f"production:{name}", args=args)


def task_titles(client: APIClient) -> list[str]:
    response = client.get("/api/v1/workflow/tasks/")
    assert response.status_code == 200
    return [item["title"] for item in response.json()["results"]]


@pytest.mark.usefixtures("invariants")
def test_scenario_admin_removes_prep_change_from_depo(
    admin: APIClient,
    make_user: MakeUser,
    published: list[events.Event],
    django_capture_on_commit_callbacks: Any,
) -> None:
    """Depodan "Malzeme hazırlama: Değiştirir" kaldırılır: düğmeler (uç noktalar) kapanır, emir
    okuması kalır, açık oturum yenilenir, hazırlık görevi ona düşmez, gerekçe geçmişte görünür."""
    planner = make_user(PLANLAMA)
    depo = make_user(DEPO, username="depo")
    colleague = make_user(DEPO, username="depo2")
    plant = build_plant(planner)
    order = approved_order(plant, planner)

    with django_capture_on_commit_callbacks(execute=True):
        save(
            admin,
            depo,
            [revoke("production.prep", "change")],
            note="Hazırlık yetkisi geçici olarak kaldırıldı",
        )

    client = api(User.objects.get(pk=depo.pk))
    started = client.post(production("order-start-prep", order.pk))
    assert started.status_code == 403
    assert started.json()["required"] == [{"key": "production.prep", "level": "change"}]
    assert client.post(production("order-mark-ready", order.pk)).status_code == 403
    assert client.get(production("order-list")).status_code == 200
    assert client.get(production("order-detail", order.pk)).status_code == 200
    assert client.get(production("order-picks", order.pk)).status_code == 200
    assert client.get("/api/v1/auth/me/").json()["access"]["production.prep"] == "rv"
    # Açık oturum yenilenir (access.changed) ve kişiye "Yetkileriniz güncellendi" bildirimi gider.
    changed = [event for event in published if event.name == event_names.ACCESS_CHANGED]
    assert [event.payload["user_id"] for event in changed] == [depo.pk]
    assert Notification.objects.filter(
        recipient=depo, event_name=event_names.ACCESS_UPDATED
    ).exists()

    with django_capture_on_commit_callbacks(execute=True):
        second = approved_order(plant, planner)
    prep = f"Malzeme hazırla: {second.number}"
    assert prep not in task_titles(client)
    assert prep in task_titles(api(colleague))

    history = admin.get(f"/api/v1/users/{depo.pk}/access/history/").json()["results"]
    assert history[0]["note"] == "Hazırlık yetkisi geçici olarak kaldırıldı"


@pytest.mark.usefixtures("invariants")
def test_scenario_production_view_removed_then_records_closed(
    admin: APIClient, make_user: MakeUser
) -> None:
    """Üretimin üç bölümünde Görür kaldırılır: menüden Üretim düşer, emir okuması açık kalır.
    Sonra "Açık kayıtlar" da kapatılır: emir okuması kapanır."""
    planner = make_user(PLANLAMA)
    depo = make_user(DEPO, username="depo")
    plant = build_plant(planner)
    order = approved_order(plant, planner)
    views = [
        revoke("production.orders", "view"),
        revoke("production.prep", "view"),
        revoke("production.batches", "view"),
    ]

    body = save(admin, depo, views)

    letters = body["matrix"]["effective"]
    assert not any("v" in letters.get(key, "") for key in ("production.orders", "production.prep"))
    client = api(User.objects.get(pk=depo.pk))
    me = client.get("/api/v1/auth/me/").json()["access"]
    assert all("v" not in text for key, text in me.items() if key.startswith("production."))
    assert client.post(production("order-start-prep", order.pk)).status_code == 403
    assert client.get(production("order-detail", order.pk)).status_code == 200

    save(admin, depo, [*views, revoke("production.open_records", "read")])

    client = api(User.objects.get(pk=depo.pk))
    listing = client.get(production("order-list"))
    assert listing.status_code == 403
    assert {"key": "production.open_records", "level": "read"} in listing.json()["required"]
    assert client.get(production("order-detail", order.pk)).status_code == 403
    closed = client.get("/api/v1/auth/me/access/").json()["revoked"]
    assert {"key": "production.open_records", "level": "read", "roles": []} in closed


def test_scenario_quality_records_closed_keeps_the_lot_section(
    admin: APIClient, make_user: MakeUser
) -> None:
    """Kalite kayıtları kapatılır: lotsuz numune listesi ve numune sayfası kapanır, lot sayfasının
    kalite bölümü (lot verilen liste) açık kalır."""
    lab = make_user(LABORATUVAR)
    sample = sample_with_spec(lab, quarantined_raw_lot("10")[0])
    depo = make_user(DEPO, username="depo")

    save(admin, depo, [revoke("quality.open_records", "read")])

    client = api(User.objects.get(pk=depo.pk))
    samples = reverse("quality:sample-list")
    assert client.get(samples).status_code == 403
    assert client.get(reverse("quality:sample-detail", args=[sample.pk])).status_code == 403
    by_lot = client.get(samples, {"lot": str(sample.lot_id)})
    assert by_lot.status_code == 200
    assert [row["id"] for row in by_lot.json()["results"]] == [sample.pk]
    assert_stock_invariants()


CONTACT = {
    "tax_office": "Kadıköy",
    "tax_number": "1234567890",
    "address": "Moda Cad. 1",
    "phone": "0216 000 00 00",
    "email": "satis@ornek.com.tr",
    "contact_person": "Ayşe Yılmaz",
}


def test_scenario_masterdata_records_closed_gives_a_plain_supplier_card(
    admin: APIClient, make_user: MakeUser
) -> None:
    """Ana veri kayıtları kapatılır: deneme hesabı etkilenen ekranları söyler; kayıttan sonra
    tedarikçi kartı sade görünür, seçim listesi çalışır; Satış siparişleri: Görür'ü olan depo
    müşteri kartını tam görür."""
    supplier = cast(Supplier, SupplierFactory(**CONTACT))
    customer = cast(Customer, CustomerFactory(**CONTACT))
    depo = make_user(DEPO, username="depo")
    closed = [revoke("masterdata.open_records", "read")]

    preview = save(admin, depo, closed, dry_run=True, note="")

    assert preview["saved"] is False
    [warning] = [item for item in preview["warnings"] if item["code"] == "open_records_closed"]
    assert "müşteri ve tedarikçi kartları" in warning["text"]

    save(admin, depo, closed)

    client = api(User.objects.get(pk=depo.pk))
    card = client.get(reverse("masterdata:supplier-detail", args=[supplier.pk])).json()
    assert card["name"] == supplier.name
    assert all(card[name] == "" for name in CONTACT)
    choices = client.get(reverse("masterdata:supplier-list"), {"is_active": "true"})
    assert choices.status_code == 200
    assert supplier.pk in [row["id"] for row in choices.json()["results"]]
    full = client.get(reverse("masterdata:customer-detail", args=[customer.pk])).json()
    assert full["tax_number"] == "1234567890"
