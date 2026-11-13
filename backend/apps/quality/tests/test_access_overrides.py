"""Kişiye özel ayarla kalite (docs/plan/kisi-yetkileri.md §10, 4. adım): karar Onaylar, öteki
numune işleri Değiştirir ister; şartlı kabulü öneren onaylayamaz (admin dahil); açık kayıtlar
kapatılınca lot sayfasının kalite bölümü ve analiz sertifikası Lotlar okumasıyla açık kalır."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, READ
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.inventory.tests.factories import storage_location
from apps.quality import services
from apps.quality.access import CONDITIONAL, SAMPLES, SPECS
from apps.quality.models import QualityDecision, Sample, SampleStage
from apps.quality.tests.factories import line, quarantined_raw_lot, sample_with_spec, tdef

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
Decision = QualityDecision.Decision


def url(name: str, *args: Any) -> str:
    return reverse(f"quality:{name}", args=args)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _tested(lab: User) -> Sample:
    """Sonuçları girilmiş, şartlı kabule uygun (pH sınır dışı) giriş numunesi."""
    lot, _location = quarantined_raw_lot("10")
    sample = sample_with_spec(lab, lot)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("8.2"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Berrak")
    return sample


def test_proposer_cannot_approve_own_conditional_acceptance_admin_included(
    lab: User, manager: User, make_user: Callable[..., User]
) -> None:
    """Plan §5.11 (karar 10): öneren onaylayamaz, admin dahil; reddetmek değişmez; başka bir
    yönetici onaylar."""
    both = make_user("laboratuvar", "yonetim")
    own = services.decide(
        both,
        _tested(lab),
        Decision.CONDITIONAL_RELEASE,
        "Sınırda",
        release_location=storage_location(),
    )
    refused = api(both).post(url("decision-review", own.pk), {"approve": True}, format="json")
    assert refused.status_code == 400
    assert refused.json()["code"] == "conditional_same_person"
    own.refresh_from_db()
    assert own.approval_status == QualityDecision.Approval.PENDING
    other = api(manager).post(url("decision-review", own.pk), {"approve": True}, format="json")
    assert other.status_code == 200, other.json()
    own.refresh_from_db()
    assert own.approval_status == QualityDecision.Approval.APPROVED

    admin = make_user("admin")
    mine = services.decide(
        admin,
        _tested(lab),
        Decision.CONDITIONAL_RELEASE,
        "Sınırda",
        release_location=storage_location(),
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.review_conditional_release(admin, mine, approve=True)
    assert exc.value.code == "conditional_same_person"
    services.review_conditional_release(admin, mine, approve=False, note="Yeniden bakılsın")
    mine.refresh_from_db()
    assert mine.approval_status == QualityDecision.Approval.REFUSED


def test_decision_needs_approve_while_results_need_change(lab: User) -> None:
    sample = sample_with_spec(lab, quarantined_raw_lot("10")[0])
    client = api(override(lab, SAMPLES.key, APPROVE))

    entered = client.post(
        url("sample-results", sample.pk),
        {"spec_line": line(sample, "PH").pk, "numeric_value": "7"},
        format="json",
    )
    assert entered.status_code in (200, 201), entered.json()
    refused = client.post(url("sample-decide", sample.pk), {"decision": "RELEASE"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": SAMPLES.key, "level": APPROVE}]
    with pytest.raises(MissingAccess):
        services.decide(lab, sample, Decision.RELEASE)


def test_conditional_approval_follows_its_section(
    lab: User, make_user: Callable[..., User]
) -> None:
    decision = services.decide(
        lab,
        _tested(lab),
        Decision.CONDITIONAL_RELEASE,
        "Sınırda",
        release_location=storage_location(),
    )
    manager = override(make_user("yonetim"), CONDITIONAL.key, APPROVE)
    refused = api(manager).post(url("decision-review", decision.pk), {"approve": True})
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": CONDITIONAL.key, "level": APPROVE}]

    planner = override(make_user("planlama"), CONDITIONAL.key, APPROVE, effect="grant")
    approved = api(planner).post(
        url("decision-review", decision.pk), {"approve": True}, format="json"
    )
    assert approved.status_code == 200, approved.json()


def test_closed_quality_records_keep_the_lot_page_section(
    lab: User, make_user: Callable[..., User]
) -> None:
    """Plan §5.3: açık kayıtlar kapatılınca lotsuz liste, kuyruk, numune ve kararlar kapanır; lot
    verilen liste ve analiz sertifikası Lotlar okumasını izler."""
    sample = sample_with_spec(lab, quarantined_raw_lot("10")[0])
    closed = api(override(make_user("depo"), "quality.open_records", READ))

    by_lot = closed.get(url("sample-list"), {"lot": str(sample.lot_id)})
    assert by_lot.status_code == 200
    assert [row["id"] for row in by_lot.json()["results"]] == [sample.pk]
    assert closed.get(url("sample-list")).status_code == 403
    assert closed.get(url("sample-list"), {"lot": ""}).status_code == 403
    assert closed.get(url("sample-queue"), {"lot": str(sample.lot_id)}).status_code == 403
    assert closed.get(url("sample-detail", sample.pk)).status_code == 403
    assert closed.get(url("decision-list")).status_code == 403
    # Sertifika Lotlar okumasıyla açılır; karar yokken iş kuralı 400 verir (403 değil).
    assert closed.get(url("sample-coa", sample.pk)).status_code == 400


def test_test_definitions_follow_quality_specs_not_master_data_cards(
    lab: User, make_user: Callable[..., User]
) -> None:
    payload = {"code": "YENI", "name": "Yeni test", "result_type": "NUMERIC", "unit": "pH"}
    # Ana veri kartlarını yazan depo test tanımı yazamaz (bugünkü gibi yalnız laboratuvar).
    assert api(make_user("depo")).post(url("test-list"), payload, format="json").status_code == 403
    revoked = api(override(lab, SPECS.key, CHANGE))
    refused = revoked.post(url("test-list"), payload, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": SPECS.key, "level": CHANGE}]
    assert revoked.get(url("test-list")).status_code == 200


def test_unrouted_methods_keep_todays_rule(
    lab: User, manager: User, make_user: Callable[..., User]
) -> None:
    """Kalitede yalnız liste, kayıt, kuyruk ve sertifika okumadır: karşılanmayan her metot (GET
    dahil) bugünkü gibi laboratuvarın yazma yetkisini ister, sonra 405 döner."""
    decision = services.decide(
        lab,
        _tested(lab),
        Decision.CONDITIONAL_RELEASE,
        "Sınırda",
        release_location=storage_location(),
    )
    sample = decision.sample
    lab_client, manager_client, warehouse = api(lab), api(manager), api(make_user("depo"))

    assert lab_client.get(url("sample-results", sample.pk)).status_code == 405
    assert warehouse.get(url("sample-results", sample.pk)).status_code == 403
    assert lab_client.delete(url("sample-detail", sample.pk)).status_code == 405
    assert warehouse.delete(url("sample-detail", sample.pk)).status_code == 403
    # Onay yolunda GET onay kuralı değil, laboratuvarın kuralıdır.
    assert lab_client.get(url("decision-review", decision.pk)).status_code == 405
    assert manager_client.get(url("decision-review", decision.pk)).status_code == 403
    assert lab_client.delete(url("specification-detail", sample.specification_id)).status_code == (
        405
    )
    assert warehouse.head(url("specification-approve", sample.specification_id)).status_code == (
        403
    )
    assert APIClient().delete(url("sample-detail", sample.pk)).status_code == 401


def test_each_service_names_its_section_and_level(
    lab: User, make_user: Callable[..., User]
) -> None:
    """Her servis denetimi plan §3.5'teki bölüme ve düzeye bağlıdır; numune açılması (open_sample)
    sistem adımıdır, denetimsizdir (plan §5.4)."""
    lot, _location = quarantined_raw_lot("10")
    sample = sample_with_spec(lab, lot)
    spec = sample.specification
    assert spec is not None
    draft = services.copy_specification(lab, spec, "Taslak")
    draft_line = draft.lines.first()
    assert draft_line is not None
    test = tdef("PH")
    pending = services.decide(
        lab,
        _tested(lab),
        Decision.CONDITIONAL_RELEASE,
        "Sınırda",
        release_location=storage_location(),
    )
    nobody = make_user()
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        (
            "create_test_definition",
            lambda: services.create_test_definition(nobody, {}),
            (SPECS.key, CHANGE),
        ),
        (
            "update_test_definition",
            lambda: services.update_test_definition(nobody, test, {}),
            (SPECS.key, CHANGE),
        ),
        (
            "set_test_active",
            lambda: services.set_test_active(nobody, test, False),
            (SPECS.key, CHANGE),
        ),
        (
            "create_specification",
            lambda: services.create_specification(
                nobody, material=lot.material, sample_stage=SampleStage.INCOMING
            ),
            (SPECS.key, CHANGE),
        ),
        (
            "copy_specification",
            lambda: services.copy_specification(nobody, spec, "x"),
            (SPECS.key, CHANGE),
        ),
        (
            "update_specification",
            lambda: services.update_specification(nobody, draft, {}),
            (SPECS.key, CHANGE),
        ),
        (
            "approve_specification",
            lambda: services.approve_specification(nobody, draft),
            (SPECS.key, APPROVE),
        ),
        ("add_spec_line", lambda: services.add_spec_line(nobody, draft, {}), (SPECS.key, CHANGE)),
        (
            "update_spec_line",
            lambda: services.update_spec_line(nobody, draft_line, {}),
            (SPECS.key, CHANGE),
        ),
        (
            "remove_spec_line",
            lambda: services.remove_spec_line(nobody, draft_line),
            (SPECS.key, CHANGE),
        ),
        (
            "create_sample",
            lambda: services.create_sample(nobody, lot, SampleStage.INCOMING),
            (SAMPLES.key, CHANGE),
        ),
        (
            "update_sample",
            lambda: services.update_sample(nobody, sample, {}),
            (SAMPLES.key, CHANGE),
        ),
        (
            "assign_specification",
            lambda: services.assign_specification(nobody, sample, spec),
            (SAMPLES.key, CHANGE),
        ),
        (
            "cancel_sample",
            lambda: services.cancel_sample(nobody, sample, "x"),
            (SAMPLES.key, CHANGE),
        ),
        (
            "record_result",
            lambda: services.record_result(
                nobody, sample, line(sample, "PH"), numeric_value=D("7")
            ),
            (SAMPLES.key, CHANGE),
        ),
        (
            "decide",
            lambda: services.decide(nobody, sample, Decision.RELEASE),
            (SAMPLES.key, APPROVE),
        ),
        (
            "review_conditional_release",
            lambda: services.review_conditional_release(nobody, pending, approve=True),
            (CONDITIONAL.key, APPROVE),
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
    # Numune açılması denetimsiz sistem adımı: kaliteyi okuyamayan kişiyle de açılır.
    closed = override(make_user("depo"), "quality.open_records", READ)
    other, _q = quarantined_raw_lot("5")
    assert services.open_sample(closed, other, SampleStage.INCOMING).pk is not None
