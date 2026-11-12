"""Kişiye özel ayarla üretim (docs/plan/kisi-yetkileri.md §10, 3. adım): kaldırılan yetki uç
noktada ve serviste düşer, emir okuması açık kalır. Emrin lot kararıyla kapanması yetki denetimi
olmayan bir sistem adımıdır."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, READ
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess, can_read, has_access
from apps.inventory import services as inventory
from apps.production import services
from apps.production.access import BATCHES, ORDERS, PREP
from apps.production.models import ProductionOrder
from apps.production.tests.factories import (
    Plant,
    approved_order,
    order_data,
    ready_order,
    weigh_all,
)
from apps.quality.access import SAMPLES
from apps.quality.models import Sample, SampleStage

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
Status = ProductionOrder.Status


def url(name: str, *args: Any) -> str:
    return reverse(f"production:{name}", args=args)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_removing_prep_change_stops_preparation_and_keeps_reads(
    plant: Plant, planner: User, depo: User
) -> None:
    """Plan §10'un örneği: depodan "Malzeme hazırlama: Değiştirir" kaldırılınca hazırlık
    başlatma, okutma ve hazır bildirme 403 olur; emir okuması açık kalır."""
    order = approved_order(plant, planner)
    requirement = plant.requirement(order, plant.las)
    client = api(override(depo, PREP.key, CHANGE))

    assert client.get(url("order-list")).status_code == 200
    assert client.get(url("order-detail", order.pk)).status_code == 200
    assert client.get(url("order-picks", order.pk)).status_code == 200
    suggestions = client.get(
        url("order-pick-suggestions", order.pk), {"requirement": str(requirement.pk)}
    )
    assert suggestions.status_code == 200

    started = client.post(url("order-start-prep", order.pk))
    assert started.status_code == 403
    assert started.json()["required"] == [{"key": PREP.key, "level": CHANGE}]
    picked = client.post(
        url("order-picks", order.pk),
        {"requirement": requirement.pk, "lot": plant.lots["las"].pk, "quantity": "600"},
        format="json",
    )
    assert picked.status_code == 403
    assert client.post(url("order-mark-ready", order.pk)).status_code == 403
    # HEAD bugünkü gibi okutma yetkisiyle denetlenir.
    assert client.head(url("order-picks", order.pk)).status_code == 403
    with pytest.raises(MissingAccess):
        services.pick_material(depo, order, requirement, plant.lots["las"], D("600"))
    order.refresh_from_db()
    assert order.status == Status.APPROVED


def test_granted_prep_change_lets_another_role_prepare(
    plant: Plant, planner: User, operator: User
) -> None:
    order = approved_order(plant, planner)
    client = api(override(operator, PREP.key, CHANGE, effect="grant"))

    started = client.post(url("order-start-prep", order.pk))
    assert started.status_code == 200, started.json()
    assert started.json()["status"] == Status.MATERIAL_PREP


def test_cancel_needs_change_for_a_draft_and_approve_afterwards(
    plant: Plant, planner: User, depo: User, make_user: Callable[..., User]
) -> None:
    draft = services.create_order(planner, order_data(plant))
    other_draft = services.create_order(planner, order_data(plant))
    approved = approved_order(plant, planner)

    # İkisi de yoksa uç nokta reddeder: mesaj öteki denetimlerle aynı, iki yetki de listede.
    denied = api(depo).post(url("order-cancel", draft.pk), {"reason": "x"}, format="json")
    assert denied.status_code == 403
    assert denied.json() == {
        "code": "permission_denied",
        "detail": "Bu işlem için yetkiniz yok.",
        "required": [
            {"key": ORDERS.key, "level": CHANGE},
            {"key": ORDERS.key, "level": APPROVE},
        ],
    }

    # Onaylar'ı kaldırılan kişi taslağı iptal eder; onaylı emri iptal edemez, onaylayamaz.
    editor = api(override(make_user("planlama"), ORDERS.key, APPROVE))
    refused = editor.post(url("order-cancel", approved.pk), {"reason": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": ORDERS.key, "level": APPROVE}]
    assert editor.post(url("order-approve", draft.pk), {"note": ""}, format="json").status_code == (
        403
    )
    cancelled = editor.post(url("order-cancel", draft.pk), {"reason": "Yanlış"}, format="json")
    assert cancelled.status_code == 200, cancelled.json()
    assert cancelled.json()["status"] == Status.CANCELLED

    # Değiştirir'i kaldırılan kişi onaylı emri iptal eder; emir açamaz, taslağı düzenleyemez ve
    # iptal edemez, elle tamamlayamaz.
    approver_user = override(make_user("planlama"), ORDERS.key, CHANGE)
    approver = api(approver_user)
    assert approver.post(url("order-list"), {}, format="json").status_code == 403
    edit = approver.patch(url("order-detail", other_draft.pk), {"notes": "x"}, format="json")
    assert edit.status_code == 403
    kept = approver.post(url("order-cancel", other_draft.pk), {"reason": "x"}, format="json")
    assert kept.status_code == 403
    assert kept.json()["required"] == [{"key": ORDERS.key, "level": CHANGE}]
    assert approver.post(url("order-complete", approved.pk)).status_code == 403
    with pytest.raises(MissingAccess):
        services.create_order(approver_user, order_data(plant))
    done = approver.post(
        url("order-cancel", approved.pk), {"reason": "Plan değişti"}, format="json"
    )
    assert done.status_code == 200, done.json()
    assert done.json()["status"] == Status.CANCELLED
    other_draft.refresh_from_db()
    assert other_draft.status == Status.DRAFT


def test_removing_batch_change_stops_batches_and_keeps_reads(
    plant: Plant, planner: User, depo: User, operator: User
) -> None:
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    client = api(override(operator, BATCHES.key, CHANGE))

    assert client.get(url("batch-list")).status_code == 200
    assert client.get(url("batch-detail", batch.pk)).status_code == 200
    refused = client.post(url("batch-cancel", batch.pk), {"reason": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": BATCHES.key, "level": CHANGE}]
    assert client.post(url("batch-list"), {"order": order.pk}, format="json").status_code == 403
    with pytest.raises(MissingAccess):
        services.cancel_batch(operator, batch, "Yanlış tank")


def test_closing_open_records_closes_reads_for_people_outside_production(
    plant: Plant, planner: User, depo: User, lab: User
) -> None:
    order = approved_order(plant, planner)
    closed = api(override(lab, "production.open_records", READ))

    listing = closed.get(url("order-list"))
    assert listing.status_code == 403
    assert {"key": "production.open_records", "level": READ} in listing.json()["required"]
    assert closed.get(url("order-picks", order.pk)).status_code == 403
    assert closed.get(url("batch-list")).status_code == 403
    # Her GET okumadır: karşılanmayan yoldaki GET de okuma kuralıyla denetlenir.
    assert closed.get(url("order-approve", order.pk)).status_code == 403

    # Bölümünde Görür'ü olan kişi açık kayıtlar kapatılsa da okur.
    member = api(override(depo, "production.open_records", READ))
    assert member.get(url("order-list")).status_code == 200
    assert member.get(url("order-approve", order.pk)).status_code == 405


def test_lot_release_completes_the_order_without_production_rights(
    plant: Plant,
    planner: User,
    depo: User,
    operator: User,
    lab: User,
    commit: Callable[[], Any],
) -> None:
    """Emrin kapanması lot kararının sonucudur (sistem adımı, plan §5.4): kararı veren kişinin
    üretimde hiçbir yetkisi olmasa da emir tamamlanır."""
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    weigh_all(plant, batch, operator)
    services.finish_batch(operator, batch, D("1000"))
    override(lab, "production.open_records", READ)
    assert not can_read(lab, ORDERS, PREP, BATCHES)
    assert not has_access(lab, ORDERS, CHANGE)

    with commit():
        inventory.release_lot(lab, batch.output_lot, "Analiz uygun", quality_decision=True)

    order.refresh_from_db()
    assert order.status == Status.COMPLETED


def test_finishing_a_batch_opens_the_sample_without_quality_rights(
    plant: Plant,
    planner: User,
    depo: User,
    operator: User,
    commit: Callable[[], Any],
) -> None:
    """Şarj bitince numune açılması da sistem adımıdır (plan §5.4): şarjı bitiren kişi kaliteyi
    okuyamasa da çıktı lotuna son kontrol numunesi açılır."""
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    weigh_all(plant, batch, operator)
    override(operator, "quality.open_records", READ)
    assert not can_read(operator, SAMPLES)

    with commit():
        services.finish_batch(operator, batch, D("1000"))

    assert Sample.objects.filter(lot=batch.output_lot, stage=SampleStage.FINAL).exists()


def test_each_service_names_its_section_and_level(
    plant: Plant, planner: User, depo: User, operator: User, make_user: Callable[..., User]
) -> None:
    """Her servis denetimi planın §3.4 tablosundaki bölüme ve düzeye bağlıdır: rolü olmayan kişi
    her birinde, işin kurallarından önce, o yetkiyi söyleyen 403 alır. Paket denkliği testi aynı
    yetkinin bugünkü rollerle denkliğini kanıtlar."""
    draft = services.create_order(planner, order_data(plant))
    approved = approved_order(plant, planner)
    ready = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, ready)
    requirement = plant.requirement(approved, plant.las)
    lot = plant.lots["las"]
    nobody = make_user()
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        (
            "create_order",
            lambda: services.create_order(nobody, order_data(plant)),
            (ORDERS.key, CHANGE),
        ),
        ("update_order", lambda: services.update_order(nobody, draft, {}), (ORDERS.key, CHANGE)),
        (
            "set_rework_additions",
            lambda: services.set_rework_additions(nobody, draft, []),
            (ORDERS.key, CHANGE),
        ),
        ("approve_order", lambda: services.approve_order(nobody, draft), (ORDERS.key, APPROVE)),
        (
            "cancel_order taslak",
            lambda: services.cancel_order(nobody, draft, "x"),
            (ORDERS.key, CHANGE),
        ),
        (
            "cancel_order onaylı",
            lambda: services.cancel_order(nobody, approved, "x"),
            (ORDERS.key, APPROVE),
        ),
        (
            "start_material_prep",
            lambda: services.start_material_prep(nobody, approved),
            (PREP.key, CHANGE),
        ),
        (
            "pick_material",
            lambda: services.pick_material(nobody, approved, requirement, lot, D("1")),
            (PREP.key, CHANGE),
        ),
        (
            "mark_material_ready",
            lambda: services.mark_material_ready(nobody, approved),
            (PREP.key, CHANGE),
        ),
        ("start_batch", lambda: services.start_batch(nobody, ready), (BATCHES.key, CHANGE)),
        (
            "record_consumption",
            lambda: services.record_consumption(
                nobody, batch, plant.requirement(ready, plant.las), lot, D("1"), "x"
            ),
            (BATCHES.key, CHANGE),
        ),
        (
            "finish_batch",
            lambda: services.finish_batch(nobody, batch, D("1")),
            (BATCHES.key, CHANGE),
        ),
        ("cancel_batch", lambda: services.cancel_batch(nobody, batch, "x"), (BATCHES.key, CHANGE)),
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
    assert draft.status == Status.DRAFT


def test_unrouted_methods_keep_todays_rule(
    plant: Plant, planner: User, depo: User, operator: User, make_user: Callable[..., User]
) -> None:
    """Görünümün karşılamadığı metotlar (sözleşme testinin dışında) bugünkü kararı verir: yazma
    metotlarında bugünkü yedek kural (emir yazma yetkisi; şarjlarda da) denetlenir, sonra 405
    döner; her GET okumadır."""
    order = approved_order(plant, planner)
    batch = services.start_batch(operator, ready_order(plant, planner, depo))
    planning, warehouse, production = api(planner), api(depo), api(operator)
    signed_in = api(make_user())

    assert planning.delete(url("order-detail", order.pk)).status_code == 405
    assert warehouse.delete(url("order-detail", order.pk)).status_code == 403
    assert planning.delete(url("batch-detail", batch.pk)).status_code == 405
    assert production.delete(url("batch-detail", batch.pk)).status_code == 403
    assert planning.head(url("order-approve", order.pk)).status_code == 405
    assert warehouse.head(url("order-approve", order.pk)).status_code == 403
    assert planning.put(url("batch-cancel", batch.pk), {}, format="json").status_code == 405
    assert production.put(url("batch-cancel", batch.pk), {}, format="json").status_code == 403
    assert warehouse.get(url("order-approve", order.pk)).status_code == 405
    assert signed_in.get(url("batch-finish", batch.pk)).status_code == 405
    assert APIClient().get(url("order-approve", order.pk)).status_code == 401
    assert APIClient().delete(url("order-detail", order.pk)).status_code == 401
