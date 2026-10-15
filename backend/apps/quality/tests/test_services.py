"""Kalite servisleri: spesifikasyon sürümleri, numune, sonuç, karar ve lot durumuna etkisi."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.inventory.models import Lot
from apps.inventory.services import block_lot, current_balance
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.models import Material
from apps.masterdata.tests.factories import MaterialFactory
from apps.quality import services
from apps.quality.models import QualityDecision, Sample, SampleStage, Specification, TestResult
from apps.quality.state import sample_states, specification_states
from apps.quality.tests.factories import (
    approved_spec,
    bulk_lot_in_tank,
    line,
    quarantined_raw_lot,
    raw_spec_lines,
    sample_with_spec,
    tdef,
)
from apps.workflow.models import Task

pytestmark = pytest.mark.django_db
D = Decimal
Decision = QualityDecision.Decision


def fill_passing(lab, sample):
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("7.2"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="berrak ")


# --- test tanımı -----------------------------------------------------------------------------


def test_standard_tests_are_seeded():
    """Karar D-7: standart deterjan testleri migration ile gelir."""
    assert {
        "PH",
        "VISK",
        "YOGUNLUK",
        "AKTIF_MADDE",
        "RENK",
        "KOKU",
        "GORUNUS",
        "KATI_MADDE",
    } <= set(services.TestDefinition.objects.values_list("code", flat=True))


def test_test_definition_crud_and_type_lock(lab, make_user):
    test = services.create_test_definition(
        lab, {"code": "tuz", "name": "Tuz", "result_type": "NUMERIC", "unit": "%"}
    )
    assert test.code == "TUZ"
    with pytest.raises(PermissionDenied):
        services.create_test_definition(make_user("depo"), {"code": "X", "name": "X"})
    test = services.update_test_definition(lab, test, {"result_type": "TEXT"})
    spec = services.create_specification(
        lab,
        material=MaterialFactory(),
        sample_stage=SampleStage.INCOMING,
        lines=[{"test": test, "text_expected": "Yok"}],
    )
    assert spec.lines.count() == 1
    with pytest.raises(BusinessRuleError) as exc:
        services.update_test_definition(lab, test, {"result_type": "NUMERIC"})
    assert exc.value.code == "test_in_use"
    other = services.create_test_definition(
        lab, {"code": "SERTLIK", "name": "Sertlik", "result_type": "TEXT"}
    )
    other = services.set_test_active(lab, other, False)
    with pytest.raises(BusinessRuleError) as exc:
        services.add_spec_line(lab, spec, {"test": other, "text_expected": "x"})
    assert exc.value.code == "inactive_reference"


# --- spesifikasyon ---------------------------------------------------------------------------


def test_specification_versions_single_approved(lab, published, commit):
    material = MaterialFactory()
    with commit():
        first = approved_spec(lab, material)
    assert first.status == Specification.Status.APPROVED and first.version_no == 1
    with commit():
        second = services.copy_specification(lab, first, "pH alt sınırı 6,5")
        services.update_spec_line(lab, second.lines.get(test__code="PH"), {"min_value": D("6.5")})
        services.approve_specification(lab, second)
    first.refresh_from_db()
    assert first.status == Specification.Status.OBSOLETE and first.obsoleted_at is not None
    assert second.version_no == 2 and second.copied_from == first
    assert services.approved_specification(material, SampleStage.INCOMING) == second
    # Başka aşamanın sürümü ayrı sayılır.
    final = approved_spec(lab, material, SampleStage.FINAL)
    assert final.version_no == 1
    names = [e.name for e in published]
    assert names.count(ev.SPECIFICATION_APPROVED) == 2
    assert ev.SPECIFICATION_OBSOLETE in names


def test_approved_specification_is_locked(lab):
    spec = approved_spec(lab, MaterialFactory())
    ph = spec.lines.get(test__code="PH")
    for call in (
        lambda: services.add_spec_line(lab, spec, {"test": tdef("VISK"), "max_value": D("1")}),
        lambda: services.update_spec_line(lab, ph, {"max_value": D("9")}),
        lambda: services.remove_spec_line(lab, ph),
        lambda: services.update_specification(lab, spec, {"change_note": "x"}),
    ):
        with pytest.raises(BusinessRuleError) as exc:
            call()
        assert exc.value.code == "specification_locked"


def test_draft_line_removal_is_audited(lab):
    spec = services.create_specification(
        lab, material=MaterialFactory(), sample_stage=SampleStage.FINAL, lines=raw_spec_lines()
    )
    services.remove_spec_line(lab, spec.lines.get(test__code="RENK"))
    assert list(spec.lines.values_list("test__code", flat=True)) == ["PH", "GORUNUS"]
    assert AuditLog.objects.filter(object_id=spec.pk, changes__has_key="line").exists()


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({"test": "PH"}, "spec_limits_required"),
        ({"test": "PH", "max_value": D("8"), "text_expected": "x"}, "spec_text_not_allowed"),
        ({"test": "RENK", "min_value": D("1")}, "spec_limits_not_allowed"),
    ],
)
def test_spec_line_validation(lab, data, code):
    spec = services.create_specification(
        lab, material=MaterialFactory(), sample_stage=SampleStage.INCOMING
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.add_spec_line(lab, spec, {**data, "test": tdef(data["test"])})
    assert exc.value.code == code


def test_spec_rules(lab, make_user):
    spec = services.create_specification(
        lab, material=MaterialFactory(), sample_stage=SampleStage.INCOMING
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.approve_specification(lab, spec)
    assert exc.value.code == "specification_has_no_lines"
    with pytest.raises(PermissionDenied):
        services.approve_specification(make_user("planlama"), spec)
    with pytest.raises(BusinessRuleError) as exc:
        services.create_specification(
            lab,
            material=MaterialFactory(material_type=Material.Type.SERVICE)
            if hasattr(Material.Type, "SERVICE")
            else MaterialFactory(is_active=False),
            sample_stage=SampleStage.INCOMING,
        )
    assert exc.value.code in ("invalid_spec_material", "inactive_reference")


def test_specification_state_machine():
    assert specification_states.allowed_transitions("DRAFT") == ["APPROVED"]
    assert specification_states.allowed_transitions("APPROVED") == ["OBSOLETE"]
    with pytest.raises(BusinessRuleError):
        specification_states.assert_can_transition("OBSOLETE", "APPROVED")


# --- numune ----------------------------------------------------------------------------------


def test_sample_pins_current_approved_spec(lab, published, commit):
    lot, _q = quarantined_raw_lot()
    spec = approved_spec(lab, lot.material)
    with commit():
        sample = services.create_sample(lab, lot, SampleStage.INCOMING)
    assert sample.number.startswith("NM-")
    assert sample.status == Sample.Status.PENDING
    assert sample.specification == spec
    assert sample.taken_by == lab and sample.taken_at is not None
    [created] = [e for e in published if e.name == ev.SAMPLE_CREATED]
    assert created.payload["lot_no"] == lot.lot_no
    assert created.payload["stage"] == "INCOMING"
    assert created.payload["lot"]["id"] == lot.pk
    # Yeni sürüm onaylansa da açık numune kendi sürümüyle kalır.
    services.approve_specification(lab, services.copy_specification(lab, spec))
    sample.refresh_from_db()
    assert sample.specification == spec


def test_sample_rules(lab, make_user):
    lot, _q = quarantined_raw_lot()
    services.create_sample(lab, lot, SampleStage.INCOMING)
    with pytest.raises(BusinessRuleError) as exc:
        services.create_sample(lab, lot, SampleStage.INCOMING)
    assert exc.value.code == "sample_already_open"
    released = stocked_lot("5")
    with pytest.raises(BusinessRuleError) as exc:
        services.create_sample(lab, released, SampleStage.INCOMING)
    assert exc.value.code == "lot_not_sampleable"
    with pytest.raises(PermissionDenied):
        services.create_sample(make_user("depo"), lot, SampleStage.FINAL)


def test_sample_without_spec_needs_assignment_before_results(lab):
    lot, _q = quarantined_raw_lot()
    sample = services.create_sample(lab, lot, SampleStage.INCOMING)
    assert sample.specification is None
    with pytest.raises(BusinessRuleError) as exc:
        services.decide(lab, sample, Decision.RELEASE)
    assert exc.value.code == "sample_has_no_specification"
    other = approved_spec(lab, MaterialFactory())
    with pytest.raises(BusinessRuleError) as exc:
        services.assign_specification(lab, sample, other)
    assert exc.value.code == "specification_mismatch"
    spec = approved_spec(lab, lot.material)
    services.assign_specification(lab, sample, spec)
    sample.refresh_from_db()
    assert sample.specification == spec


def test_cancel_sample(lab, commit, published):
    lot, _q = quarantined_raw_lot()
    sample = services.create_sample(lab, lot, SampleStage.INCOMING)
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_sample(lab, sample, " ")
    assert exc.value.code == "cancel_reason_required"
    with commit():
        services.cancel_sample(lab, sample, "Yanlış lot")
    sample.refresh_from_db()
    assert sample.status == Sample.Status.CANCELLED
    assert ev.SAMPLE_CANCELLED in [e.name for e in published]
    # İptalden sonra aynı aşamaya yeni numune açılabilir.
    services.create_sample(lab, lot, SampleStage.INCOMING)


def test_sample_state_machine_transitions():
    allowed = {
        "PENDING": ["AWAITING_APPROVAL", "CANCELLED", "DECIDED", "IN_TEST"],
        "IN_TEST": ["AWAITING_APPROVAL", "CANCELLED", "DECIDED"],
        "AWAITING_APPROVAL": ["DECIDED", "IN_TEST"],
        "DECIDED": [],
        "CANCELLED": [],
    }
    for state, targets in allowed.items():
        assert sample_states.allowed_transitions(state) == targets
    with pytest.raises(BusinessRuleError):
        sample_states.assert_can_transition("DECIDED", "IN_TEST")


# --- sonuç -----------------------------------------------------------------------------------


def test_results_evaluate_against_spec(lab, commit, published):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    with commit():
        ph = services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("8.5"))
    assert ph.is_within_spec is False
    sample.refresh_from_db()
    assert sample.status == Sample.Status.IN_TEST
    assert ev.SAMPLE_IN_TEST in [e.name for e in published]
    assert sample.taken_by == lab and sample.taken_at is not None
    look = services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="  BERRAK")
    assert look.is_within_spec is True and look.text_value == "BERRAK"
    color = services.record_result(lab, sample, line(sample, "RENK"), passed=False)
    assert color.is_within_spec is False
    with pytest.raises(BusinessRuleError) as exc:
        services.record_result(lab, sample, line(sample, "PH"), numeric_value=None, note="x")
    assert exc.value.code == "result_value_required"


@pytest.mark.parametrize(
    ("value", "within"), [("6", True), ("8", True), ("5.99", False), ("8.01", False)]
)
def test_numeric_limits_are_inclusive(lab, value, within):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    result = services.record_result(lab, sample, line(sample, "PH"), numeric_value=D(value))
    assert result.is_within_spec is within


def test_result_correction_keeps_history(lab):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    first = services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("9"))
    with pytest.raises(BusinessRuleError) as exc:
        services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("7"))
    assert exc.value.code == "correction_reason_required"
    second = services.record_result(
        lab, sample, line(sample, "PH"), numeric_value=D("7"), note="Kalibrasyon hatası"
    )
    first.refresh_from_db()
    assert first.superseded_by == second
    assert second.superseded_by is None and second.is_within_spec
    assert TestResult.objects.filter(sample=sample).count() == 2
    assert [r.pk for r in services.current_results(sample)] == [second.pk]
    third = services.record_result(
        lab, sample, line(sample, "PH"), numeric_value=D("7.1"), note="Tekrar"
    )
    second.refresh_from_db()
    assert second.superseded_by == third
    assert AuditLog.objects.filter(object_id=first.pk, changes__has_key="superseded_by").exists()


def test_result_line_must_belong_to_sample_spec(lab):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    other_lot, _ = quarantined_raw_lot()
    other = sample_with_spec(lab, other_lot)
    with pytest.raises(BusinessRuleError) as exc:
        services.record_result(lab, sample, line(other, "PH"), numeric_value=D("7"))
    assert exc.value.code == "spec_line_not_in_sample"


def test_only_lab_records_results(lab, make_user):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    with pytest.raises(PermissionDenied):
        services.record_result(
            make_user("uretim"), sample, line(sample, "PH"), numeric_value=D("7")
        )


# --- karar -----------------------------------------------------------------------------------


def test_decision_requires_all_mandatory_tests(lab):
    """Kabul kriteri: zorunlu test eksikken karar verilemiyor."""
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("7"))
    for decision in Decision.values:
        with pytest.raises(BusinessRuleError) as exc:
            services.decide(lab, sample, decision, "gerekçe")
        assert exc.value.code == "mandatory_tests_missing"
        assert "GORUNUS" in exc.value.message
    # İsteğe bağlı test (renk) eksik olabilir.
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Berrak")
    services.decide(lab, sample, Decision.RELEASE, release_location=storage_location())


def test_out_of_spec_result_blocks_release(lab):
    """Kabul kriteri: spec dışı sonuçla RELEASE verilemiyor."""
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("8.6"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Berrak")
    services.record_result(lab, sample, line(sample, "RENK"), passed=False)
    with pytest.raises(BusinessRuleError) as exc:
        services.decide(lab, sample, Decision.RELEASE, release_location=storage_location())
    assert exc.value.code == "out_of_spec_release"
    assert "PH" in exc.value.message and "RENK" in exc.value.message
    lot.refresh_from_db()
    assert lot.status == Lot.Status.QUARANTINE


def test_release_moves_stock_to_receipt_storage_by_default(lab, commit, published):
    lot, quarantine = quarantined_raw_lot("40")
    target = storage_location()
    sample = sample_with_spec(lab, lot)
    fill_passing(lab, sample)
    with pytest.raises(BusinessRuleError) as exc:
        services.decide(lab, sample, Decision.RELEASE)
    assert exc.value.code == "release_location_required"
    with commit():
        decision = services.decide(lab, sample, Decision.RELEASE, release_location=target)
    lot.refresh_from_db()
    sample.refresh_from_db()
    assert lot.status == Lot.Status.RELEASED and lot.released_by == lab
    assert lot.status_note == f"{sample.number}: Serbest"
    assert current_balance(lot, quarantine) == 0 and current_balance(lot, target) == D("40")
    assert sample.status == Sample.Status.DECIDED and sample.decided_at is not None
    assert decision.approval_status == QualityDecision.Approval.NOT_REQUIRED
    assert services.effective_decision(sample) == decision
    [decided] = [e for e in published if e.name == ev.SAMPLE_DECIDED]
    assert decided.payload["decision"] == "RELEASE"
    assert ev.LOT_RELEASED in [e.name for e in published]
    with pytest.raises(BusinessRuleError) as exc:
        services.decide(lab, sample, Decision.REJECT, "x")
    assert exc.value.code == "sample_not_open"


def test_reject_decision(lab, commit, published):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("3"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Bulanık")
    with pytest.raises(BusinessRuleError) as exc:
        services.decide(lab, sample, Decision.REJECT)
    assert exc.value.code == "decision_reason_required"
    with commit():
        services.decide(lab, sample, Decision.REJECT, "pH çok düşük")
    lot.refresh_from_db()
    assert lot.status == Lot.Status.REJECTED
    assert lot.status_note == f"{sample.number}: Ret. pH çok düşük"
    assert ev.LOT_REJECTED in [e.name for e in published]


def test_rework_decision_blocks_bulk_lot_and_opens_planning_task(lab, planner, commit):
    lot = bulk_lot_in_tank()
    sample = sample_with_spec(lab, lot, SampleStage.FINAL)
    fill_passing(lab, sample)
    with commit():
        services.decide(lab, sample, Decision.REWORK, "Viskozite düşük, tuz eklenecek")
    lot.refresh_from_db()
    assert lot.status == Lot.Status.BLOCKED
    task = Task.objects.get(rule_code="rework_order")
    assert task.title == f"Yeniden işleme emri aç: {lot.lot_no}"
    assert task.related_object_id == lot.pk
    assert task.assigned_role.name == "planlama"


def test_rework_only_for_bulk(lab):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    fill_passing(lab, sample)
    with pytest.raises(BusinessRuleError) as exc:
        services.decide(lab, sample, Decision.REWORK, "x")
    assert exc.value.code == "rework_not_allowed"


def test_conditional_release_needs_management_approval(lab, manager, commit, published):
    lot, _q = quarantined_raw_lot("10")
    target = storage_location()
    sample = sample_with_spec(lab, lot)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("8.2"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Berrak")
    with commit():
        decision = services.decide(
            lab,
            sample,
            Decision.CONDITIONAL_RELEASE,
            "pH sınırda, müşteri onayı var",
            release_location=target,
        )
    sample.refresh_from_db()
    lot.refresh_from_db()
    assert sample.status == Sample.Status.AWAITING_APPROVAL
    assert decision.approval_status == QualityDecision.Approval.PENDING
    assert lot.status == Lot.Status.QUARANTINE
    task = Task.objects.get(rule_code="conditional_release_approval")
    assert task.assigned_role.name == "yonetim" and task.related_object_id == sample.pk
    with pytest.raises(PermissionDenied):
        services.review_conditional_release(lab, decision, approve=True)
    with commit():
        services.review_conditional_release(manager, decision, approve=True, note="Uygun")
    decision.refresh_from_db()
    sample.refresh_from_db()
    lot.refresh_from_db()
    assert decision.approval_status == QualityDecision.Approval.APPROVED
    assert decision.approved_by == manager
    assert sample.status == Sample.Status.DECIDED
    assert lot.status == Lot.Status.RELEASED
    assert current_balance(lot, target) == D("10")
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    with pytest.raises(BusinessRuleError) as exc:
        services.review_conditional_release(manager, decision, approve=True)
    assert exc.value.code == "decision_not_pending"


def test_refused_conditional_release_returns_sample_to_lab(lab, manager, commit):
    lot = bulk_lot_in_tank()
    sample = sample_with_spec(lab, lot, SampleStage.FINAL)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("9"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Berrak")
    with commit():
        decision = services.decide(lab, sample, Decision.CONDITIONAL_RELEASE, "Sınırda")
    with pytest.raises(BusinessRuleError) as exc:
        services.review_conditional_release(manager, decision, approve=False)
    assert exc.value.code == "note_required"
    with commit():
        services.review_conditional_release(manager, decision, approve=False, note="Kabul edilmez")
    sample.refresh_from_db()
    lot.refresh_from_db()
    assert sample.status == Sample.Status.IN_TEST
    assert lot.status == Lot.Status.QUARANTINE
    assert services.effective_decision(sample) is None
    assert Task.objects.get(rule_code="conditional_release_approval").status == Task.Status.DONE
    # Laboratuvar yeniden karar verir.
    with commit():
        services.decide(lab, sample, Decision.REWORK, "Yönetim reddetti")
    lot.refresh_from_db()
    assert lot.status == Lot.Status.BLOCKED


def test_in_process_sample_does_not_change_lot(lab, commit):
    lot = bulk_lot_in_tank()
    sample = sample_with_spec(lab, lot, SampleStage.IN_PROCESS)
    fill_passing(lab, sample)
    with pytest.raises(BusinessRuleError) as exc:
        services.decide(lab, sample, Decision.REWORK, "x")
    assert exc.value.code == "invalid_in_process_decision"
    with commit():
        services.decide(lab, sample, Decision.REJECT, "pH yüksek, düzeltme yapılacak")
    lot.refresh_from_db()
    assert lot.status == Lot.Status.QUARANTINE


def test_blocked_lot_can_be_re_released_with_new_sample(lab):
    lot = stocked_lot("5")
    block_lot(lab, lot, "Müşteri şikâyeti")
    sample = sample_with_spec(lab, lot, SampleStage.FINAL)
    fill_passing(lab, sample)
    services.decide(lab, sample, Decision.RELEASE)
    lot.refresh_from_db()
    assert lot.status == Lot.Status.RELEASED


def test_decision_permission(lab, make_user):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    fill_passing(lab, sample)
    for role in ("depo", "uretim", "yonetim", "planlama"):
        with pytest.raises(PermissionDenied):
            services.decide(make_user(role), sample, Decision.RELEASE)


def test_auto_sample_gets_taker_from_first_result(lab):
    lot, _q = quarantined_raw_lot()
    approved_spec(lab, lot.material)
    sample = services.open_sample(
        None, lot, SampleStage.INCOMING, origin=Sample.Origin.GOODS_RECEIPT
    )
    assert sample.taken_by is None and sample.taken_at is None
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("7"))
    sample.refresh_from_db()
    assert sample.taken_by == lab and sample.taken_at is not None
