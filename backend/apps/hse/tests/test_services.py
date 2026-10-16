from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import Attachment, AuditLog, User
from apps.core.services import remove_attachment
from apps.hse import selectors, services
from apps.hse.models import Incident, MaterialHazard, SafetyDataSheet, WasteRecord
from apps.hse.state import incident_states, waste_record_states
from apps.hse.tests.factories import (
    contractor,
    hazardous_material,
    report,
    sds,
    statement,
    waste_data,
)
from apps.inventory import services as inventory
from apps.inventory.models import StockMovement
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.models import Material
from apps.masterdata.tests.factories import MaterialFactory, unit
from apps.workflow.models import Notification, Task

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate


# --- ayarlar ve ifadeler -----------------------------------------------------------------------


def test_settings_default_and_update(manager: User, depo: User) -> None:
    assert selectors.get_settings().sds_max_age_months == 36
    assert services.update_settings(manager, {"sds_max_age_months": 24}).sds_max_age_months == 24
    with pytest.raises(PermissionDenied):
        services.update_settings(depo, {"sds_max_age_months": 12})
    with pytest.raises(BusinessRuleError) as exc:
        services.update_settings(manager, {"sds_max_age_months": 0})
    assert exc.value.code == "invalid_months"


def test_seeded_statements_have_turkish_texts() -> None:
    assert statement("H290").text == "Metallere karşı aşındırıcı olabilir."
    assert statement("H314").text == "Ciddi cilt yanıklarına ve göz hasarına yol açar."
    assert statement("P305+P351+P338").kind == "P"
    assert statement("EUH208").kind == "EUH"


def test_statement_create_update_deactivate(lab: User, operator: User) -> None:
    created = services.create_statement(lab, {"code": "h 373", "kind": "H", "text": "Organ."})
    assert created.code == "H373"
    updated = services.update_statement(lab, created, {"text": "Uzun süreli maruziyette hasar."})
    assert updated.text.startswith("Uzun")
    assert services.set_statement_active(lab, created, False).is_active is False
    with pytest.raises(BusinessRuleError) as exc:
        services.create_statement(lab, {"code": "P999", "kind": "H", "text": "x"})
    assert exc.value.code == "invalid_statement_code"
    with pytest.raises(ValidationError):
        services.create_statement(lab, {"code": "H290", "kind": "H", "text": "tekrar"})
    with pytest.raises(PermissionDenied):
        services.create_statement(operator, {"code": "H999", "kind": "H", "text": "x"})


# --- tehlike bilgisi ---------------------------------------------------------------------------


def test_material_hazard_syncs_is_hazardous(lab: User) -> None:
    material = MaterialFactory.create()
    assert material.is_hazardous is False
    hazard = services.set_material_hazard(
        lab,
        material,
        {
            "pictograms": ["GHS07", "ghs05", "GHS05"],
            "signal_word": "DANGER",
            "statements": [statement("H314"), statement("P280")],
        },
    )
    assert hazard.pictograms == ["GHS05", "GHS07"]
    material.refresh_from_db()
    assert material.is_hazardous is True
    assert sorted(hazard.statements.values_list("code", flat=True)) == ["H314", "P280"]
    assert AuditLog.objects.filter(
        object_id=str(material.pk), changes__has_key="is_hazardous"
    ).exists()
    assert AuditLog.objects.filter(object_id=str(hazard.pk), changes__has_key="statements").exists()

    services.set_material_hazard(lab, material, {"pictograms": [], "signal_word": "DANGER"})
    material.refresh_from_db()
    hazard.refresh_from_db()
    assert material.is_hazardous is False
    assert hazard.signal_word == ""
    assert MaterialHazard.objects.filter(material=material).count() == 1


def test_material_hazard_rules(lab: User, operator: User) -> None:
    material = MaterialFactory.create()
    with pytest.raises(BusinessRuleError) as exc:
        services.set_material_hazard(lab, material, {"pictograms": ["GHS05"]})
    assert exc.value.code == "signal_word_required"
    with pytest.raises(BusinessRuleError) as exc:
        services.set_material_hazard(
            lab, material, {"pictograms": ["GHS10"], "signal_word": "WARNING"}
        )
    assert exc.value.code == "invalid_pictogram"
    with pytest.raises(PermissionDenied):
        services.set_material_hazard(
            operator, material, {"pictograms": ["GHS05"], "signal_word": "DANGER"}
        )


# --- GBF ---------------------------------------------------------------------------------------


def test_new_sds_supersedes_current(manager: User) -> None:
    material = MaterialFactory.create()
    first = sds(manager, material, revision_date=TODAY() - timedelta(days=400))
    second = sds(manager, material, revision_no="2", revision_date=TODAY() - timedelta(days=5))
    first.refresh_from_db()
    assert first.superseded_at is not None and second.superseded_at is None
    assert selectors.current_sds(material) == second
    with pytest.raises(BusinessRuleError) as exc:
        sds(manager, material, revision_no="0", revision_date=TODAY() - timedelta(days=900))
    assert exc.value.code == "older_revision"
    assert SafetyDataSheet.objects.filter(material=material).count() == 2


def test_sds_rules(manager: User, depo: User) -> None:
    material = MaterialFactory.create()
    with pytest.raises(BusinessRuleError) as exc:
        sds(manager, material, revision_date=TODAY() + timedelta(days=1))
    assert exc.value.code == "future_revision_date"
    with pytest.raises(BusinessRuleError) as exc:
        sds(
            manager,
            material,
            revision_date=TODAY() - timedelta(days=5),
            valid_until=TODAY() - timedelta(days=10),
        )
    assert exc.value.code == "invalid_valid_until"
    with pytest.raises(PermissionDenied):
        sds(depo, material)


def test_update_sds(manager: User) -> None:
    sheet = sds(manager, MaterialFactory.create())
    updated = services.update_sds(manager, sheet, {"revision_no": "1.1", "note": "düzeltme"})
    assert updated.revision_no == "1.1"
    with pytest.raises(BusinessRuleError) as exc:
        services.update_sds(manager, sheet, {"revision_no": " "})
    assert exc.value.code == "revision_no_required"


def test_months_before_clamps_day() -> None:
    assert selectors.months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert selectors.months_before(date(2026, 1, 15), 36) == date(2023, 1, 15)


def test_sds_statuses_and_gaps(manager: User) -> None:
    today = TODAY()
    missing = MaterialFactory.create(code="A-MISSING")
    no_file = MaterialFactory.create(code="B-NOFILE")
    sds(manager, no_file, with_file=False)
    expired = MaterialFactory.create(code="C-EXPIRED")
    sds(
        manager,
        expired,
        revision_date=today - timedelta(days=100),
        valid_until=today - timedelta(days=1),
    )
    outdated = MaterialFactory.create(code="D-OUTDATED")
    sds(manager, outdated, revision_date=selectors.months_before(today, 37))
    ok = MaterialFactory.create(code="E-OK")
    sds(manager, ok)
    packaging = MaterialFactory.create(
        code="F-PACK", material_type=Material.Type.PACKAGING, base_unit=unit("ADET")
    )
    hazardous_bulk = hazardous_material(
        manager, code="G-BULK", material_type=Material.Type.BULK, density=Decimal("1.1")
    )

    assert selectors.sds_status(missing).status == selectors.SDS_MISSING
    assert selectors.sds_status(no_file).status == selectors.SDS_NO_FILE
    assert selectors.sds_status(expired).status == selectors.SDS_EXPIRED
    assert selectors.sds_status(outdated).status == selectors.SDS_OUTDATED
    assert selectors.sds_status(ok).status == selectors.SDS_OK
    gaps = {row.material_code: row for row in selectors.sds_gaps()}
    assert "E-OK" not in gaps and "F-PACK" not in gaps
    assert gaps["A-MISSING"].status_display == "GBF yok"
    assert gaps["B-NOFILE"].status_display == "Dosya yok"
    assert gaps["C-EXPIRED"].status_display == "Geçerliliği geçti"
    assert gaps["D-OUTDATED"].status_display == "Revizyonu eski"
    assert gaps["G-BULK"].status == selectors.SDS_MISSING
    assert packaging.pk not in {row.material_id for row in selectors.sds_gaps()}
    assert hazardous_bulk.is_hazardous

    # Ayardan yaş sınırı uzatılınca eski revizyon geçerli sayılır.
    services.update_settings(manager, {"sds_max_age_months": 48})
    assert selectors.sds_status(outdated).status == selectors.SDS_OK
    # Dosya kaldırılınca "Dosya yok".
    remove_attachment(manager, Attachment.objects.filter(object_id=ok.safety_sheets.get().pk)[0])
    assert selectors.sds_status(ok).status == selectors.SDS_NO_FILE


# --- depolama limitleri ------------------------------------------------------------------------


def test_storage_limit_rules(manager: User, depo: User) -> None:
    location = storage_location()
    limit = services.create_storage_limit(
        manager, {"location": location, "hazard_class": "GHS02", "max_kg": Decimal("500")}
    )
    assert limit.is_active
    with pytest.raises(ValidationError):
        services.create_storage_limit(
            manager, {"location": location, "hazard_class": "GHS02", "max_kg": Decimal("1")}
        )
    with pytest.raises(BusinessRuleError) as exc:
        services.create_storage_limit(
            manager, {"location": location, "hazard_class": "GHS05", "max_kg": Decimal("0")}
        )
    assert exc.value.code == "invalid_limit"
    with pytest.raises(PermissionDenied):
        services.create_storage_limit(
            depo, {"location": location, "hazard_class": "GHS05", "max_kg": Decimal("10")}
        )
    updated = services.update_storage_limit(manager, limit, {"max_kg": Decimal("600")})
    assert updated.max_kg == Decimal("600")
    assert services.set_storage_limit_active(manager, limit, False).is_active is False
    assert selectors.storage_utilisation(location) == []


def test_storage_utilisation_converts_to_kg(manager: User, invariants: None) -> None:
    location = storage_location()
    services.create_storage_limit(
        manager, {"location": location, "hazard_class": "GHS05", "max_kg": Decimal("200")}
    )
    services.create_storage_limit(
        manager, {"location": location, "hazard_class": "GHS07", "max_kg": Decimal("1000")}
    )
    kg_material = hazardous_material(manager, ["GHS05", "GHS07"])
    lt_material = hazardous_material(
        manager, ["GHS05"], base_unit=unit("LT"), density=Decimal("1.2")
    )
    pieces = hazardous_material(manager, ["GHS05"], base_unit=unit("ADET"))
    stocked_lot("50", material=kg_material, location=location)
    stocked_lot("100", material=lt_material, location=location)
    stocked_lot("10", material=pieces, location=location)  # kg'a çevrilemez, atlanır
    stocked_lot("999", material=MaterialFactory.create(), location=location)  # tehlikesiz

    rows = {row.hazard_class: row for row in selectors.storage_utilisation()}
    assert rows["GHS05"].quantity_kg == Decimal("170.0000")
    assert rows["GHS05"].pct == Decimal("85.00") and rows["GHS05"].exceeded is False
    assert rows["GHS07"].quantity_kg == Decimal("50.0000")
    assert rows["GHS05"].hazard_class_display == "Aşındırıcı"


def test_storage_limit_exceeded_notifies(
    manager: User,
    depo: User,
    published: list,
    commit: Callable,
    invariants: None,
) -> None:
    location = storage_location()
    services.create_storage_limit(
        manager, {"location": location, "hazard_class": "GHS05", "max_kg": Decimal("100")}
    )
    material = hazardous_material(manager, ["GHS05"])
    with commit():
        stocked_lot("80", material=material, location=location)
    assert not [e for e in published if e.name == ev.STORAGE_LIMIT_EXCEEDED]

    with commit():
        stocked_lot("30", material=material, location=location)
        stocked_lot("5", material=material, location=location)  # aynı işlemde tek denetim
    exceeded = [e for e in published if e.name == ev.STORAGE_LIMIT_EXCEEDED]
    assert len(exceeded) == 1
    payload = exceeded[0].payload
    assert payload["model"] == "masterdata.location" and payload["id"] == location.pk
    assert payload["location_code"] == location.code
    assert payload["hazard_class"] == "GHS05"
    assert payload["hazard_class_display"] == "Aşındırıcı"
    assert payload["quantity_kg"] == "115" and payload["limit_kg"] == "100"
    note = Notification.objects.get(rule_code="storage_limit_exceeded", recipient=depo)
    assert note.title == f"Depolama limiti aşıldı: {location.code} — Aşındırıcı"
    assert note.body == "115 kg / limit 100 kg"
    assert Notification.objects.filter(rule_code="storage_limit_exceeded", recipient=manager)


def test_storage_hook_ignores_outgoing_and_rolled_back(
    manager: User, published: list, commit: Callable, invariants: None
) -> None:
    location = storage_location()
    services.create_storage_limit(
        manager, {"location": location, "hazard_class": "GHS05", "max_kg": Decimal("10")}
    )
    material = hazardous_material(manager, ["GHS05"])
    with commit():
        lot = stocked_lot("50", material=material, location=location)
    published.clear()
    with commit():
        inventory.post_movement(
            None,
            material,
            lot,
            location,
            Decimal("-45"),
            StockMovement.Type.ADJUSTMENT,
            None,
        )
    assert not published
    with commit():
        try:
            from django.db import transaction

            with transaction.atomic():
                stocked_lot("50", material=material, location=location)
                raise RuntimeError
        except RuntimeError:
            pass
    assert not [e for e in published if e.name == ev.STORAGE_LIMIT_EXCEEDED]


# --- atık --------------------------------------------------------------------------------------


def test_waste_code_normalisation() -> None:
    assert services.normalize_waste_code("070601*") == "07 06 01*"
    assert services.normalize_waste_code(" 15-01-10 * ") == "15 01 10*"
    assert services.normalize_waste_code("15 01 02") == "15 01 02"
    for bad in ("0706", "07 06 01**", "AB 06 01", ""):
        with pytest.raises(BusinessRuleError) as exc:
            services.normalize_waste_code(bad)
        assert exc.value.code == "invalid_waste_code"


def test_record_waste(manager: User, depo: User, published: list, commit: Callable) -> None:
    firm = contractor(manager)
    with commit():
        record = services.record_waste(manager, waste_data(firm, waste_code="070601*"))
    assert record.number.startswith("AT-") and record.status == WasteRecord.Status.RECORDED
    assert record.waste_code == "07 06 01*" and record.is_hazardous is True
    assert "waste_record.created" in [e.name for e in published]
    plain = services.record_waste(
        manager, waste_data(firm, waste_code="150102", is_hazardous=False)
    )
    assert plain.is_hazardous is False
    with pytest.raises(PermissionDenied):
        services.record_waste(depo, waste_data(firm))


def test_waste_rejected_for_expired_or_inactive_contractor(manager: User) -> None:
    expired = contractor(manager, valid_until=TODAY() - timedelta(days=1))
    with pytest.raises(BusinessRuleError) as exc:
        services.record_waste(manager, waste_data(expired))
    assert exc.value.code == "contractor_license_expired"
    # Teslim lisans süresi içindeyse kaydedilir.
    old = services.record_waste(
        manager, waste_data(expired, delivered_on=TODAY() - timedelta(days=2))
    )
    assert old.pk
    firm = contractor(manager)
    firm = services.set_contractor_active(manager, firm, False)
    with pytest.raises(BusinessRuleError) as exc:
        services.record_waste(manager, waste_data(firm))
    assert exc.value.code == "inactive_reference"
    with pytest.raises(BusinessRuleError) as exc:
        services.record_waste(manager, waste_data(contractor(manager), quantity_kg=Decimal(0)))
    assert exc.value.code == "invalid_quantity"


def test_contractor_rules(manager: User, depo: User) -> None:
    firm = contractor(manager)
    renewed = services.update_contractor(
        manager, firm, {"license_valid_until": TODAY() + timedelta(days=700)}
    )
    assert renewed.license_valid_until > TODAY()
    with pytest.raises(BusinessRuleError) as exc:
        contractor(manager, license_no=" ")
    assert exc.value.code == "license_no_required"
    with pytest.raises(PermissionDenied):
        contractor(depo)


def test_waste_cancel_and_summary(manager: User) -> None:
    firm = contractor(manager)
    first = services.record_waste(manager, waste_data(firm))
    services.record_waste(manager, waste_data(firm, quantity_kg=Decimal("100.5")))
    services.record_waste(manager, waste_data(firm, waste_code="15 01 02", description="Plastik"))
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_waste_record(manager, first, " ")
    assert exc.value.code == "cancel_reason_required"
    cancelled = services.cancel_waste_record(manager, first, "Mükerrer kayıt")
    assert cancelled.status == WasteRecord.Status.CANCELLED
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_waste_record(manager, cancelled, "tekrar")
    assert exc.value.code == "invalid_transition"
    rows = {row.waste_code: row for row in selectors.waste_summary(TODAY(), TODAY())}
    assert rows["07 06 01*"].count == 1 and rows["07 06 01*"].quantity_kg == Decimal("100.5")
    assert rows["07 06 01*"].is_hazardous is True
    assert rows["15 01 02"].is_hazardous is False
    assert selectors.waste_summary(TODAY() - timedelta(days=9), TODAY() - timedelta(days=1)) == []


def test_waste_state_machine() -> None:
    assert waste_record_states.initial == "RECORDED"
    assert waste_record_states.can_transition("RECORDED", "CANCELLED")
    assert not waste_record_states.can_transition("CANCELLED", "RECORDED")


# --- olay / kaza -------------------------------------------------------------------------------


def test_report_incident_opens_review_task(
    operator: User, manager: User, published: list, commit: Callable
) -> None:
    with commit():
        incident = report(operator)
    assert incident.number.startswith("OL-") and incident.status == Incident.Status.OPEN
    event = next(e for e in published if e.name == ev.INCIDENT_CREATED)
    assert event.payload["incident_type_display"] == "Ramak kala"
    assert event.payload["injury"] is False and event.payload["severity"] == "LOW"
    assert event.payload["occurred_at"] == (
        f"{timezone.localtime(incident.occurred_at):%d.%m.%Y %H:%M}"
    )
    task = Task.objects.get(rule_code="incident_review")
    assert task.title == f"Olay kaydı: {incident.number} — Ramak kala"
    assert task.description.startswith("Hammadde deposu, ")
    assert not Notification.objects.filter(rule_code="incident_injury").exists()


def test_injury_incident_warns_management(operator: User, manager: User, commit: Callable) -> None:
    with commit():
        incident = report(
            operator,
            incident_type=Incident.Type.WORK_ACCIDENT,
            injury=True,
            injured_person="A. Yılmaz",
            severity=Incident.Severity.HIGH,
        )
    note = Notification.objects.get(rule_code="incident_injury", recipient=manager)
    assert note.title == f"Yaralanmalı olay: {incident.number}"
    assert note.level == "WARNING"


def test_report_incident_rules(operator: User) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        report(operator, occurred_at=timezone.now() + timedelta(hours=1))
    assert exc.value.code == "future_occurred_at"
    with pytest.raises(BusinessRuleError) as exc:
        report(operator, place="")
    assert exc.value.code == "place_required"
    with pytest.raises(BusinessRuleError) as exc:
        report(operator, description=" ")
    assert exc.value.code == "description_required"
    assert report(operator, injured_person="x").injured_person == ""  # yaralanma yoksa boş


def test_incident_investigate_and_close(operator: User, manager: User, commit: Callable) -> None:
    with commit():
        incident = report(operator)
    with pytest.raises(PermissionDenied):
        services.start_investigation(operator, incident)
    with pytest.raises(BusinessRuleError) as exc:
        services.close_incident(manager, incident, {"root_cause": "x", "corrective_action": "y"})
    assert exc.value.code == "invalid_transition"  # OPEN → CLOSED yok
    incident = services.start_investigation(manager, incident, {"severity": "MEDIUM"})
    assert incident.status == Incident.Status.INVESTIGATING and incident.severity == "MEDIUM"
    incident = services.update_investigation(manager, incident, {"root_cause": "Dar koridor"})
    with pytest.raises(BusinessRuleError) as exc:
        services.close_incident(manager, incident, {"root_cause": ""})
    assert exc.value.code == "root_cause_required"
    with pytest.raises(BusinessRuleError) as exc:
        services.close_incident(manager, incident, {})
    assert exc.value.code == "corrective_action_required"
    with commit():
        closed = services.close_incident(
            manager,
            incident,
            {
                "corrective_action": "Raf koruyucu takıldı",
                "action_owner": "Depo şefi",
                "action_due": TODAY() + timedelta(days=7),
                "closed_note": "Tamam",
            },
        )
    assert closed.status == Incident.Status.CLOSED and closed.root_cause == "Dar koridor"
    assert Task.objects.get(rule_code="incident_review").status == Task.Status.DONE
    assert AuditLog.objects.filter(
        object_id=str(closed.pk), changes__has_key="corrective_action"
    ).exists()
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_incident(manager, closed, "geç")
    assert exc.value.code == "invalid_transition"
    with pytest.raises(BusinessRuleError) as exc:
        services.update_investigation(manager, closed, {"root_cause": "x"})
    assert exc.value.code == "incident_not_open"


def test_incident_cancel_from_open_and_investigating(
    operator: User, manager: User, commit: Callable
) -> None:
    with commit():
        first = report(operator)
        second = report(operator)
    with pytest.raises(PermissionDenied):
        services.cancel_incident(operator, first, "mükerrer")
    with commit():
        assert services.cancel_incident(manager, first, "Mükerrer").status == "CANCELLED"
        services.start_investigation(manager, second)
        assert services.cancel_incident(manager, second, "Hatalı kayıt").status == "CANCELLED"
    assert set(Task.objects.values_list("status", flat=True)) == {Task.Status.DONE}


def test_incident_state_machine() -> None:
    allowed = {
        ("OPEN", "INVESTIGATING"),
        ("OPEN", "CANCELLED"),
        ("INVESTIGATING", "CLOSED"),
        ("INVESTIGATING", "CANCELLED"),
    }
    for source in incident_states.states:
        for target in incident_states.states:
            assert incident_states.can_transition(source, target) == ((source, target) in allowed)


def test_incident_summary(operator: User, manager: User) -> None:
    report(operator)
    report(operator, incident_type=Incident.Type.WORK_ACCIDENT, injury=True, severity="HIGH")
    closed = services.start_investigation(manager, report(operator))
    services.close_incident(manager, closed, {"root_cause": "a", "corrective_action": "b"})
    services.cancel_incident(manager, report(operator), "mükerrer")
    report(operator, occurred_at=timezone.now() - timedelta(days=40))
    summary = selectors.incident_summary(TODAY() - timedelta(days=7), TODAY())
    assert summary.total == 3 and summary.injury_count == 1 and summary.open_count == 2
    by_type = {row.code: row.count for row in summary.by_type}
    assert by_type == {
        "WORK_ACCIDENT": 1,
        "NEAR_MISS": 2,
        "ENVIRONMENTAL": 0,
        "FIRE": 0,
        "OTHER": 0,
    }
    assert {row.code: row.count for row in summary.by_severity}["HIGH"] == 1
