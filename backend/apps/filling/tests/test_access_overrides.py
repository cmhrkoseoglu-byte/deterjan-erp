"""Kişiye özel ayarla dolum (docs/plan/kisi-yetkileri.md §10, 3. adım): kaldırılan yetki uç
noktada ve serviste düşer, okuma açık kalır. Tüketim raporları Dolum hattı'nın okumasıdır. Emrin
lot kararıyla kapanması ve numune açılması yetki denetimi olmayan sistem adımlarıdır."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, READ, VIEW
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess, can_read, has_access
from apps.filling import services
from apps.filling.access import ORDERS, PREP, RUNS, SPECS
from apps.filling.models import FillingOrder, PackagingSpec
from apps.filling.tests.factories import Line, approved_order, order_data, started_run
from apps.inventory import services as inventory
from apps.quality.access import SAMPLES
from apps.quality.models import Sample, SampleStage

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
Status = FillingOrder.Status


def url(name: str, *args: Any) -> str:
    return reverse(f"filling:{name}", args=args)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_removing_packaging_prep_stops_preparation_and_keeps_reads(
    line: Line, planner: User, depo: User
) -> None:
    order = approved_order(line, planner)
    row = order.requirements.select_related("material").get(material=line.bottle)
    lot = line.lots["bottle"]
    client = api(override(depo, PREP.key, CHANGE))

    assert client.get(url("order-detail", order.pk)).status_code == 200
    assert client.get(url("order-picks", order.pk)).status_code == 200
    suggestions = client.get(url("order-pick-suggestions", order.pk), {"requirement": str(row.pk)})
    assert suggestions.status_code == 200

    started = client.post(url("order-start-prep", order.pk))
    assert started.status_code == 403
    assert started.json()["required"] == [{"key": PREP.key, "level": CHANGE}]
    picked = client.post(
        url("order-picks", order.pk),
        {"requirement": row.pk, "lot": lot.pk, "quantity": "10"},
        format="json",
    )
    assert picked.status_code == 403
    assert client.post(url("order-mark-ready", order.pk)).status_code == 403
    assert client.head(url("order-picks", order.pk)).status_code == 403
    with pytest.raises(MissingAccess):
        services.pick_packaging(depo, order, row, lot, D("10"))


def test_removing_line_change_stops_runs_and_keeps_reports(
    line: Line, planner: User, depo: User, filler: User
) -> None:
    run = started_run(line, planner, depo, filler)
    client = api(override(filler, RUNS.key, CHANGE))

    assert client.get(url("run-detail", run.pk)).status_code == 200
    assert client.get(url("run-report", run.pk)).status_code == 200
    assert client.get(url("order-report", run.order_id)).status_code == 200
    refused = client.post(url("run-cancel", run.pk), {"reason": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": RUNS.key, "level": CHANGE}]
    finish = client.post(url("order-finish", run.order_id), {"note": ""}, format="json")
    assert finish.status_code == 403
    with pytest.raises(MissingAccess):
        services.consume_bulk(filler, run, line.lots["bulk"], D("10"))


def test_consumption_reports_follow_the_filling_line_section(
    line: Line, planner: User, depo: User, filler: User, make_user: Callable[..., User]
) -> None:
    """Plan §3.6: parti ve emir tüketim raporları Dolum hattı'nın açık okumasıdır. Açık kayıtlar
    ve Dolum hattı'nın Görür'ü kapatılınca emir ve parti okunur, raporlar okunmaz."""
    run = started_run(line, planner, depo, filler)
    viewer = override(make_user("yonetim"), "filling.open_records", READ)
    client = api(override(viewer, RUNS.key, VIEW))

    assert client.get(url("order-detail", run.order_id)).status_code == 200
    assert client.get(url("run-detail", run.pk)).status_code == 200
    report = client.get(url("order-report", run.order_id))
    assert report.status_code == 403
    assert report.json()["required"] == [
        {"key": RUNS.key, "level": VIEW},
        {"key": "filling.open_records", "level": READ},
    ]
    assert client.get(url("run-report", run.pk)).status_code == 403


def test_cancel_needs_change_for_a_draft_and_approve_afterwards(
    line: Line, planner: User, depo: User, make_user: Callable[..., User]
) -> None:
    draft = services.create_order(planner, order_data(line))
    other_draft = services.create_order(planner, order_data(line))
    approved = approved_order(line, planner)

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

    # Onaylar'ı kaldırılan kişi taslağı iptal eder; onaylı emri iptal edemez, emri onaylayamaz.
    editor_user = override(make_user("planlama"), ORDERS.key, APPROVE)
    editor = api(editor_user)
    refused = editor.post(url("order-cancel", approved.pk), {"reason": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": ORDERS.key, "level": APPROVE}]
    approve = editor.post(url("order-approve", other_draft.pk), {"note": ""}, format="json")
    assert approve.status_code == 403
    with pytest.raises(MissingAccess):
        services.approve_order(editor_user, other_draft)
    cancelled = editor.post(url("order-cancel", draft.pk), {"reason": "Yanlış"}, format="json")
    assert cancelled.status_code == 200, cancelled.json()
    assert cancelled.json()["status"] == Status.CANCELLED

    # Değiştirir'i kaldırılan kişi onaylı emri iptal eder; emir açamaz, taslağı düzenleyemez ve
    # iptal edemez.
    approver = override(make_user("planlama"), ORDERS.key, CHANGE)
    with pytest.raises(MissingAccess):
        services.create_order(approver, order_data(line))
    edit = api(approver).patch(url("order-detail", other_draft.pk), {"notes": "x"}, format="json")
    assert edit.status_code == 403
    kept = api(approver).post(url("order-cancel", other_draft.pk), {"reason": "x"}, format="json")
    assert kept.status_code == 403
    assert kept.json()["required"] == [{"key": ORDERS.key, "level": CHANGE}]
    done = api(approver).post(url("order-cancel", approved.pk), {"reason": "Plan"}, format="json")
    assert done.status_code == 200, done.json()
    other_draft.refresh_from_db()
    assert other_draft.status == Status.DRAFT


def test_spec_approval_follows_its_level(
    line: Line, planner: User, make_user: Callable[..., User]
) -> None:
    editor = override(make_user("planlama"), SPECS.key, APPROVE)
    client = api(editor)

    copied = client.post(url("packaging-spec-copy", line.spec.pk), {"note": "Koli"}, format="json")
    assert copied.status_code == 201, copied.json()
    draft = PackagingSpec.objects.get(pk=copied.json()["id"])
    refused = client.post(url("packaging-spec-approve", draft.pk), {"note": ""}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": SPECS.key, "level": APPROVE}]
    with pytest.raises(MissingAccess):
        services.approve_spec(editor, draft)

    approved = api(planner).post(
        url("packaging-spec-approve", draft.pk), {"note": ""}, format="json"
    )
    assert approved.status_code == 200, approved.json()


def test_lot_release_completes_the_filling_order_without_filling_rights(
    line: Line,
    planner: User,
    depo: User,
    filler: User,
    lab: User,
    commit: Callable[[], Any],
) -> None:
    """Emrin kapanması lot kararının sonucudur (sistem adımı, plan §5.4): kararı veren kişinin
    dolumda hiçbir yetkisi olmasa da emir tamamlanır."""
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("780"))
    with commit():
        services.finish_run(filler, run, 1000)
        order = services.finish_filling(filler, run.order)
    assert order.status == Status.QC_PENDING
    override(lab, "filling.open_records", READ)
    assert not can_read(lab, ORDERS, PREP, RUNS)
    assert not has_access(lab, RUNS, CHANGE)

    with commit():
        inventory.release_lot(lab, run.output_lot, "Analiz uygun", quality_decision=True)

    order.refresh_from_db()
    assert order.status == Status.COMPLETED


def test_finishing_a_run_opens_the_sample_without_quality_rights(
    line: Line, planner: User, depo: User, filler: User
) -> None:
    """Parti bitince numune açılması da sistem adımıdır (plan §5.4): partiyi bitiren kişi
    kaliteyi okuyamasa da dolum lotuna son kontrol numunesi açılır."""
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("780"))
    override(filler, "quality.open_records", READ)
    assert not can_read(filler, SAMPLES)

    services.finish_run(filler, run, 1000)

    assert Sample.objects.filter(lot=run.output_lot, stage=SampleStage.FINAL).exists()


def test_each_service_names_its_section_and_level(
    line: Line, planner: User, depo: User, filler: User, make_user: Callable[..., User]
) -> None:
    """Her servis denetimi planın §3.6 tablosundaki bölüme ve düzeye bağlıdır: rolü olmayan kişi
    her birinde, işin kurallarından önce, o yetkiyi söyleyen 403 alır. Paket denkliği testi aynı
    yetkinin bugünkü rollerle denkliğini kanıtlar."""
    spec = services.copy_spec(planner, line.spec, "Taslak")
    spec_line = spec.lines.first()
    assert spec_line is not None
    draft = services.create_order(planner, order_data(line))
    approved = approved_order(line, planner)
    row = approved.requirements.get(material=line.bottle)
    run = started_run(line, planner, depo, filler)
    nobody = make_user()
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        ("create_spec", lambda: services.create_spec(nobody, {}), (SPECS.key, CHANGE)),
        ("copy_spec", lambda: services.copy_spec(nobody, line.spec, "x"), (SPECS.key, CHANGE)),
        ("update_spec", lambda: services.update_spec(nobody, spec, {}), (SPECS.key, CHANGE)),
        ("add_spec_line", lambda: services.add_spec_line(nobody, spec, {}), (SPECS.key, CHANGE)),
        (
            "update_spec_line",
            lambda: services.update_spec_line(nobody, spec_line, {}),
            (SPECS.key, CHANGE),
        ),
        (
            "remove_spec_line",
            lambda: services.remove_spec_line(nobody, spec_line),
            (SPECS.key, CHANGE),
        ),
        ("approve_spec", lambda: services.approve_spec(nobody, spec), (SPECS.key, APPROVE)),
        (
            "create_order",
            lambda: services.create_order(nobody, order_data(line)),
            (ORDERS.key, CHANGE),
        ),
        ("update_order", lambda: services.update_order(nobody, draft, {}), (ORDERS.key, CHANGE)),
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
            "pick_packaging",
            lambda: services.pick_packaging(nobody, approved, row, line.lots["bottle"], D("1")),
            (PREP.key, CHANGE),
        ),
        (
            "mark_material_ready",
            lambda: services.mark_material_ready(nobody, approved),
            (PREP.key, CHANGE),
        ),
        ("start_run", lambda: services.start_run(nobody, run.order), (RUNS.key, CHANGE)),
        (
            "consume_bulk",
            lambda: services.consume_bulk(nobody, run, line.lots["bulk"], D("1")),
            (RUNS.key, CHANGE),
        ),
        (
            "scan_packaging_lot",
            lambda: services.scan_packaging_lot(nobody, run, line.lots["bottle"]),
            (RUNS.key, CHANGE),
        ),
        (
            "record_scrap",
            lambda: services.record_scrap(
                nobody, run, kind="FINISHED", quantity=D("1"), reason_code="OTHER"
            ),
            (RUNS.key, CHANGE),
        ),
        ("finish_run", lambda: services.finish_run(nobody, run, 1), (RUNS.key, CHANGE)),
        ("cancel_run", lambda: services.cancel_run(nobody, run, "x"), (RUNS.key, CHANGE)),
        (
            "finish_filling",
            lambda: services.finish_filling(nobody, run.order),
            (RUNS.key, CHANGE),
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
    assert draft.status == Status.DRAFT


def test_unrouted_methods_keep_todays_rule(
    line: Line, planner: User, depo: User, filler: User, make_user: Callable[..., User]
) -> None:
    """Görünümün karşılamadığı metotlar (sözleşme testinin dışında) bugünkü kararı verir: yazma
    metotlarında görünümün bugünkü yedek rolü (ambalaj reçetesi ve emirde planlama, partide dolum)
    denetlenir, sonra 405 döner; her GET okumadır."""
    run = started_run(line, planner, depo, filler)
    spec_line = line.spec.lines.first()
    assert spec_line is not None
    planning, warehouse, filling = api(planner), api(depo), api(filler)
    signed_in = api(make_user())

    assert planning.delete(url("packaging-spec-detail", line.spec.pk)).status_code == 405
    assert filling.delete(url("packaging-spec-detail", line.spec.pk)).status_code == 403
    assert planning.post(url("packaging-spec-line-detail", spec_line.pk), {}).status_code == 405
    assert filling.post(url("packaging-spec-line-detail", spec_line.pk), {}).status_code == 403
    assert planning.delete(url("order-detail", run.order_id)).status_code == 405
    assert warehouse.delete(url("order-detail", run.order_id)).status_code == 403
    assert planning.head(url("order-approve", run.order_id)).status_code == 405
    assert warehouse.head(url("order-approve", run.order_id)).status_code == 403
    assert filling.put(url("run-detail", run.pk), {}, format="json").status_code == 405
    assert planning.put(url("run-detail", run.pk), {}, format="json").status_code == 403
    assert warehouse.get(url("order-approve", run.order_id)).status_code == 405
    assert signed_in.get(url("run-finish", run.pk)).status_code == 405
    assert signed_in.get(url("packaging-spec-approve", line.spec.pk)).status_code == 405
    assert APIClient().get(url("run-finish", run.pk)).status_code == 401
    assert APIClient().put(url("run-detail", run.pk), {}, format="json").status_code == 401
