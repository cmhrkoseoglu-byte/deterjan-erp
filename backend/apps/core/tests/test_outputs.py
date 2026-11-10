"""Çıktı doküman kodları (ISO 9001 md. 7.5): kayıt, doküman no, revizyonlar, bant, yeniden basım,
göç, API."""

import dataclasses
import importlib
import io
from datetime import date, timedelta

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.urls import path
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from openpyxl import load_workbook
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.units import mm

from apps.core import pdf as core_pdf
from apps.core.api import coding as coding_api
from apps.core.coding import outputs, registry
from apps.core.coding.outputs import DOC_CODE_RE, DocumentControl, document_control
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, OutputBandChange, OutputDocument, OutputDocumentRevision
from apps.core.roles import ADMIN, PLANLAMA

pytestmark = pytest.mark.django_db

COA = "quality.coa"
RECALL = "traceability.recall"
ORDER = "purchasing.order"
BASE = "/api/v1/coding/outputs"
NOTE_MESSAGE = "Değişiklik notu yazın (denetim günlüğüne yazılır)."

migration = importlib.import_module("apps.core.migrations.0008_cikti_yeniden_basim")


@pytest.fixture
def admin(make_user):
    return make_user(ADMIN)


def days_ago(n: int) -> date:
    return timezone.localdate() - timedelta(days=n)


def entered_on(revision: OutputDocumentRevision, days: int) -> None:
    """Revizyon `days` gün önce sisteme girilmiş sayılır (servis bugün girer)."""
    revision.created_at = timezone.now() - timedelta(days=days)
    OutputDocumentRevision.objects.filter(pk=revision.pk).update(created_at=revision.created_at)


def add_revision(
    actor,
    key=COA,
    *,
    effective: int,
    approved: int | None = None,
    entered: int | None = None,
    **extra,
):
    """Revizyon `effective` gün önce yürürlüğe girer ve o gün girilmiş sayılır (`entered`: kaç gün
    önce girildiği; 0, bugün geriye tarihli girilen revizyon)."""
    revision = outputs.add_revision(
        actor,
        key,
        revision_date=days_ago(effective),
        change_note=f"{effective} gün önce yürürlüğe girdi",
        approved_by_name="Kalite Müdürü",
        approved_on=days_ago(effective if approved is None else approved),
        **extra,
    )
    entered_on(revision, effective if entered is None else entered)
    return revision


def band_since(key: str, days: int) -> OutputBandChange:
    """Bandı `days` gün önceden beri açık sayar. Servis bandı bugünden açar; geçmişte açılmış bant
    kaydı doğrudan yazılır."""
    return OutputBandChange.objects.create(
        output=OutputDocument.objects.get(key=key), is_active=True, effective_date=days_ago(days)
    )


def configure(
    actor,
    key=COA,
    code="FR-KAL-001",
    *,
    issued=60,
    revisions=(60,),
    active=True,
    since: int | None = None,
):
    """Çıktıya doküman no, ilk yayın tarihi ve revizyonlar (gün önce yürürlüğe girdi ve girildi)
    girer; bandı bugün açar (`since`: bant o kadar gün önceden beri açık)."""
    outputs.update_output(
        actor, key, note="Doküman listesi", doc_code=code, first_issue_date=days_ago(issued)
    )
    for effective in revisions:
        add_revision(actor, key, effective=effective)
    if active:
        outputs.update_output(actor, key, note="Bant açıldı", is_active=True)
    if since is not None:
        band_since(key, since)


def row_logs(row: OutputDocument, action: str):
    """Çıktı kaydının denetim günlüğü."""
    return AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(OutputDocument),
        object_id=row.pk,
        action=action,
    )


def error_code(excinfo: pytest.ExceptionInfo[BusinessRuleError]) -> str:
    return excinfo.value.code


# --- kayıt ---------------------------------------------------------------------------------------


def test_registered_outputs_have_unique_keys_and_valid_suggestions():
    items = registry.output_types()
    keys = [item.key for item in items]
    assert len(keys) == len(set(keys))
    codes = [item.suggested_code for item in items]
    assert all(codes) and len(codes) == len(set(codes))
    assert all(DOC_CODE_RE.match(code) for code in codes)
    # Yalnızca irsaliye yasal belgedir (bandı açmadan önce mali müşavire danışılır).
    assert [item.key for item in items if item.legal] == ["sales.waybill"]
    assert {
        "sales.waybill",
        COA,
        ORDER,
        RECALL,
        "reporting.stock-status",
        "personnel.payroll",
        "personnel.payslip",
        "costing.personnel-cost",
        "hse.sds-gaps",
        "golive.comparison",
        "masterdata.template.materials",
        "recipes.template",
        "inventory.opening-template",
    } <= set(keys)


def test_band_is_off_until_configured_and_unknown_output_is_an_error(admin):
    assert document_control(COA) is None
    # Doküman no ve revizyon girildi ama bant açılmadı: çıktı bugünkü gibi basılır.
    configure(admin, active=False)
    assert document_control(COA) is None
    with pytest.raises(ImproperlyConfigured):
        document_control("yok.boyle-cikti")


def test_band_text():
    control = DocumentControl("FR-KAL-001", date(2026, 1, 10), 1, date(2026, 6, 1))
    assert control.band(1, 2) == (
        "Doküman no: FR-KAL-001 · Yayın tarihi: 10.01.2026 · Rev. no: 01 · "
        "Rev. tarihi: 01.06.2026 · Sayfa 1/2"
    )
    assert control.band() == (
        "Doküman no: FR-KAL-001 · Yayın tarihi: 10.01.2026 · Rev. no: 01 · Rev. tarihi: 01.06.2026"
    )
    assert control.short() == "FR-KAL-001 Rev.01"
    # Yıl her zaman dört hane: hatalı yazılmış yıl kâğıtta da görünür.
    assert outputs._day(date(26, 1, 10)) == "10.01.0026"
    assert outputs._day(None) == "—"


# --- doküman no ve bant ------------------------------------------------------------------------


def test_update_output_rules(admin, make_user):
    with pytest.raises(PermissionDenied):
        outputs.update_output(make_user(PLANLAMA), COA, note="x", doc_code="FR-KAL-001")
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note=" ", doc_code="FR-KAL-001")
    assert (error_code(excinfo), excinfo.value.message) == ("note_required", NOTE_MESSAGE)
    for bad in ("FR KAL 001", "-FR-001", "FR_KAL_001", "A" * 33):
        with pytest.raises(BusinessRuleError) as excinfo:
            outputs.update_output(admin, COA, note="x", doc_code=bad)
        assert error_code(excinfo) == "invalid_doc_code"
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", first_issue_date=days_ago(-1))
    assert error_code(excinfo) == "future_date"
    # İki haneli yıl (0026) ve 2000'den önceki tarih yazılmaz: revizyonlar değiştirilemez.
    for bad_day in (date(26, 1, 10), date(1999, 12, 31)):
        with pytest.raises(BusinessRuleError) as excinfo:
            outputs.update_output(admin, COA, note="x", first_issue_date=bad_day)
        assert (error_code(excinfo), excinfo.value.message) == (
            "invalid_date",
            "Tarih 01.01.2000'den önce olamaz.",
        )
    # Bant ancak doküman no, ilk yayın tarihi ve revizyon girilince açılır.
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", doc_code="FR-KAL-001", is_active=True)
    assert error_code(excinfo) == "output_not_ready"
    assert not OutputDocument.objects.filter(key=COA).exists()  # işlem geri alındı

    # Küçük harf büyüğe çevrilir; nokta ve eğik çizgi geçerlidir.
    row = outputs.update_output(admin, COA, note="Doküman listesi", doc_code="f.kal/01")
    assert row.doc_code == "F.KAL/01"
    audit = row_logs(row, AuditLog.Action.UPDATE).latest("id")
    assert audit.changes["doc_code"] == ["", "F.KAL/01"]
    assert audit.note == "Doküman listesi"
    # Doküman no çıktılar arasında tektir.
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, RECALL, note="x", doc_code="F.KAL/01")
    assert error_code(excinfo) == "output_code_taken"
    # İlk revizyondan önce doküman no ve ilk yayın tarihi serbestçe düzeltilir; 01.01.2000 geçerli.
    outputs.update_output(admin, COA, note="x", doc_code="", first_issue_date=date(2000, 1, 1))
    outputs.update_output(
        admin, COA, note="x", doc_code="FR-KAL-001", first_issue_date=days_ago(400)
    )
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", is_active=True)
    assert error_code(excinfo) == "output_not_ready"  # revizyon yok

    add_revision(admin, effective=30)
    outputs.update_output(admin, COA, note="x", is_active=True)
    assert document_control(COA) == DocumentControl("FR-KAL-001", days_ago(400), 0, days_ago(30))


def test_first_revision_needs_doc_no_and_first_issue_date(admin):
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, effective=30)
    assert (error_code(excinfo), excinfo.value.message) == (
        "revision_needs_doc",
        "İlk revizyon için doküman no ve ilk yayın tarihi girilmelidir.",
    )
    assert not OutputDocument.objects.filter(key=COA).exists()  # işlem geri alındı
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, effective=30, doc_code="FR-KAL-001")
    assert error_code(excinfo) == "revision_needs_doc"
    outputs.update_output(admin, COA, note="Liste", doc_code="FR-KAL-001")
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, effective=30)
    assert error_code(excinfo) == "revision_needs_doc"
    # Revizyonda doküman no boş olamaz; tarih denetimleri update_output'taki gibidir.
    for extra, code in (
        ({"doc_code": " ", "first_issue_date": days_ago(40)}, "invalid_doc_code"),
        ({"first_issue_date": days_ago(-1)}, "future_date"),
        ({"first_issue_date": date(26, 1, 10)}, "invalid_date"),
        ({"first_issue_date": days_ago(20)}, "revision_date_invalid"),  # revizyondan sonra
    ):
        with pytest.raises(BusinessRuleError) as excinfo:
            add_revision(admin, effective=30, **extra)
        assert error_code(excinfo) == code, extra

    # Kayıtlı doküman no ve bu çağrıda verilen ilk yayın tarihiyle ilk revizyon girilir.
    revision = add_revision(admin, effective=30, first_issue_date=days_ago(40))
    assert (revision.doc_code, revision.first_issue_date) == ("FR-KAL-001", days_ago(40))
    row = OutputDocument.objects.get(key=COA)
    assert row.first_issue_date == days_ago(40)
    audit = row_logs(row, AuditLog.Action.UPDATE).latest("id")
    assert audit.changes == {"first_issue_date": [None, days_ago(40).isoformat()]}
    assert audit.note == "Yeni revizyon 00: 30 gün önce yürürlüğe girdi"

    # İkisi birden ilk revizyonla verilebilir; numara başka bir çıktıda kullanılıyorsa reddedilir.
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(
            admin, RECALL, effective=30, doc_code="fr-kal-001", first_issue_date=days_ago(40)
        )
    assert error_code(excinfo) == "output_code_taken"
    first = add_revision(
        admin, RECALL, effective=30, doc_code="fr-kal-002", first_issue_date=days_ago(40)
    )
    assert (first.doc_code, first.first_issue_date) == ("FR-KAL-002", days_ago(40))
    recall = OutputDocument.objects.get(key=RECALL)
    assert (recall.doc_code, recall.first_issue_date) == ("FR-KAL-002", days_ago(40))


def test_doc_no_and_first_issue_date_change_only_with_a_new_revision(admin):
    configure(admin, issued=90, revisions=(60,))
    row = OutputDocument.objects.get(key=COA)
    for changes in (
        {"doc_code": "FR-KAL-002"},
        {"doc_code": ""},
        {"first_issue_date": days_ago(80)},
    ):
        with pytest.raises(BusinessRuleError) as excinfo:
            outputs.update_output(admin, COA, note="x", **changes)
        assert (error_code(excinfo), excinfo.value.message) == (
            "output_doc_locked",
            "Doküman no ve ilk yayın tarihi ilk revizyondan sonra yalnız yeni revizyonla değişir.",
        ), changes
    # Aynı değeri göndermek değişiklik sayılmaz (ekran bütün alanları gönderir).
    logs = AuditLog.objects.count()
    outputs.update_output(
        admin, COA, note="x", doc_code="fr-kal-001", first_issue_date=days_ago(90), is_active=True
    )
    assert AuditLog.objects.count() == logs

    # Yeni numara yeni revizyonla verilir: çıktı kaydına değişiklik açıklamasıyla yazılır.
    renumbered = add_revision(admin, effective=10, doc_code="fr-kal-099")
    assert (renumbered.revision_no, renumbered.doc_code) == (1, "FR-KAL-099")
    row.refresh_from_db()
    assert (row.doc_code, row.first_issue_date) == ("FR-KAL-099", days_ago(90))
    audit = row_logs(row, AuditLog.Action.UPDATE).latest("id")
    assert audit.changes == {"doc_code": ["FR-KAL-001", "FR-KAL-099"]}
    assert audit.note == "Yeni revizyon 01: 10 gün önce yürürlüğe girdi"
    assert OutputDocumentRevision.objects.get(output=row, revision_no=0).doc_code == "FR-KAL-001"
    # İlk yayın tarihi düzeltmesi de yeni revizyonla; ilk revizyondan sonra olamaz.
    for extra, code in (
        ({"first_issue_date": days_ago(50)}, "issue_after_revision"),
        ({"first_issue_date": days_ago(-1)}, "future_date"),
        ({"first_issue_date": date(1999, 12, 31)}, "invalid_date"),
        ({"doc_code": "FR KAL"}, "invalid_doc_code"),
    ):
        with pytest.raises(BusinessRuleError) as excinfo:
            add_revision(admin, effective=5, **extra)
        assert error_code(excinfo) == code, extra
    corrected = add_revision(admin, effective=5, first_issue_date=days_ago(80))
    assert (corrected.doc_code, corrected.first_issue_date) == ("FR-KAL-099", days_ago(80))


def test_band_changes_are_dated_and_cannot_be_changed(admin):
    configure(admin, active=False)
    assert not OutputBandChange.objects.exists()
    outputs.update_output(admin, COA, note="Bant açıldı", is_active=True)
    outputs.update_output(admin, COA, note="Yine açık", is_active=True)  # değişiklik değil
    outputs.update_output(admin, COA, note="Bant kapatıldı", is_active=False)
    changes = list(OutputBandChange.objects.order_by("id"))
    assert [(c.is_active, c.effective_date, c.created_by) for c in changes] == [
        (True, days_ago(0), admin),
        (False, days_ago(0), admin),
    ]
    # Aynı gün açılıp kapandı: bugünkü belge son duruma göre bantsız basılır.
    assert document_control(COA) is None
    changes[0].is_active = False
    with pytest.raises(ValueError):
        changes[0].save()
    with pytest.raises(ValueError):
        changes[0].delete()


def test_revision_numbering_and_rules(admin):
    outputs.update_output(
        admin, COA, note="Liste", doc_code="FR-KAL-001", first_issue_date=days_ago(90)
    )
    first = add_revision(admin, effective=60)
    assert first.revision_no == 0
    assert add_revision(admin, effective=30).revision_no == 1
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, effective=20, revision_no=5)
    assert error_code(excinfo) == "revision_no_invalid"
    assert add_revision(admin, effective=20, revision_no=2).revision_no == 2
    for kwargs, code in (
        ({"effective": 40}, "revision_date_invalid"),  # bir öncekinden önce
        ({"effective": -1}, "future_date"),
        ({"effective": 10, "approved": 5}, "approval_after_effective"),
    ):
        with pytest.raises(BusinessRuleError) as excinfo:
            add_revision(admin, **kwargs)
        assert error_code(excinfo) == code, kwargs
    # İki haneli yıl (0026) ve 2000'den önceki tarih: revizyon değiştirilemediği için düzeltilemez.
    for revision_day, approval_day in (
        (date(26, 10, 1), date(26, 10, 1)),
        (days_ago(1), date(1999, 12, 31)),
    ):
        with pytest.raises(BusinessRuleError) as excinfo:
            outputs.add_revision(
                admin,
                COA,
                revision_date=revision_day,
                change_note="Yeni alan",
                approved_by_name="Kalite Müdürü",
                approved_on=approval_day,
            )
        assert (error_code(excinfo), excinfo.value.message) == (
            "invalid_date",
            "Tarih 01.01.2000'den önce olamaz.",
        )
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.add_revision(
            admin,
            COA,
            revision_date=days_ago(1),
            change_note=" ",
            approved_by_name="Kalite Müdürü",
            approved_on=days_ago(1),
        )
    assert error_code(excinfo) == "change_note_required"
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.add_revision(
            admin,
            COA,
            revision_date=days_ago(1),
            change_note="Yeni alan",
            approved_by_name="",
            approved_on=days_ago(1),
        )
    assert error_code(excinfo) == "approver_required"
    # Revizyonlar değiştirilemez ve silinemez; ekleme denetim günlüğüne yazılır.
    first.change_note = "değişti"
    with pytest.raises(ValueError):
        first.save()
    with pytest.raises(ValueError):
        first.delete()
    row = OutputDocument.objects.get(key=COA)
    audit = row_logs(row, AuditLog.Action.CUSTOM).latest("id")
    assert audit.changes == {"revision_no": [1, 2]}
    # Her revizyon girildiği andaki doküman no ve ilk yayın tarihini saklar.
    assert set(OutputDocumentRevision.objects.values_list("doc_code", "first_issue_date")) == {
        ("FR-KAL-001", days_ago(90))
    }


def test_first_revision_number_follows_the_quality_system(admin):
    outputs.update_output(
        admin, COA, note="Liste", doc_code="FR-KAL-001", first_issue_date=days_ago(90)
    )
    # Kalite sisteminde Rev. 03'te olan form sisteme 03 ile girilir; sonraki 04 olur.
    assert add_revision(admin, effective=30, revision_no=3).revision_no == 3
    assert add_revision(admin, effective=10).revision_no == 4
    outputs.update_output(
        admin, RECALL, note="Liste", doc_code="FR-KAL-002", first_issue_date=days_ago(30)
    )
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, RECALL, effective=10, revision_no=100)
    assert error_code(excinfo) == "revision_no_invalid"
    # Revizyon ilk yayın tarihinden önce olamaz.
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, RECALL, effective=40)
    assert error_code(excinfo) == "revision_date_invalid"


def test_document_is_printed_with_the_revision_in_force_on_its_date(admin):
    configure(admin, issued=90, revisions=(60, 10), since=90)
    assert document_control(COA).revision_no == 1
    assert document_control(COA, on=days_ago(30)).revision_no == 0
    assert document_control(COA, on=days_ago(10)).revision_no == 1
    # İlk revizyondan önceki belge (bant yokken basılmıştı) bantsız basılır.
    assert document_control(COA, on=days_ago(70)) is None
    outputs.update_output(admin, COA, note="Bant kapatıldı", is_active=False)
    assert document_control(COA) is None


# --- yeniden basım ilk basımdaki gibi (CUMHUR, 2026-11-05) --------------------------------------


def test_document_dated_before_the_band_was_turned_on_prints_no_band(admin):
    configure(admin, issued=90, revisions=(60,))  # bant bugün açıldı
    assert document_control(COA, on=days_ago(30)) is None
    assert document_control(COA, on=days_ago(1)) is None
    assert document_control(COA) == DocumentControl("FR-KAL-001", days_ago(90), 0, days_ago(60))


def test_turning_the_band_off_keeps_it_on_documents_dated_while_it_was_on(admin):
    configure(admin, issued=90, revisions=(60,), since=40)
    old = DocumentControl("FR-KAL-001", days_ago(90), 0, days_ago(60))
    assert document_control(COA, on=days_ago(30)) == old
    assert document_control(COA, on=days_ago(45)) is None  # bant henüz açılmamıştı
    outputs.update_output(admin, COA, note="Bant kapatıldı", is_active=False)
    assert document_control(COA) is None
    assert document_control(COA, on=days_ago(30)) == old  # kapatılsa da açıkken tarihlenen belge
    outputs.update_output(admin, COA, note="Bant yeniden açıldı", is_active=True)
    assert document_control(COA) == old


def test_renumbering_keeps_the_old_doc_no_on_documents_dated_before_it(admin):
    configure(admin, issued=90, revisions=(60,), since=90)
    add_revision(admin, effective=10, doc_code="FR-KAL-099")
    assert document_control(COA, on=days_ago(30)) == DocumentControl(
        "FR-KAL-001", days_ago(90), 0, days_ago(60)
    )
    assert document_control(COA, on=days_ago(10)) == DocumentControl(
        "FR-KAL-099", days_ago(90), 1, days_ago(10)
    )
    assert document_control(COA) == document_control(COA, on=days_ago(10))


def test_first_issue_date_correction_applies_from_its_revision(admin):
    configure(admin, issued=90, revisions=(60,), since=90)
    add_revision(admin, effective=10, first_issue_date=days_ago(80))
    assert document_control(COA, on=days_ago(30)).first_issue_date == days_ago(90)
    assert document_control(COA, on=days_ago(10)).first_issue_date == days_ago(80)
    assert document_control(COA).band() == (
        f"Doküman no: FR-KAL-001 · Yayın tarihi: {days_ago(80):%d.%m.%Y} · Rev. no: 01 · "
        f"Rev. tarihi: {days_ago(10):%d.%m.%Y}"
    )


def test_revision_entered_late_does_not_change_documents_dated_before_it_was_entered(admin):
    """Bugün girilen, 30 gün önceden yürürlükte revizyon (yeni doküman no ve ilk yayın tarihi
    düzeltmesiyle): girildiği günden önceki tarihli belge ilk basımdaki gibi basılır, bugünkü belge
    yeni revizyonla."""
    configure(admin, issued=90, revisions=(60,), since=90)
    printed = DocumentControl("FR-KAL-001", days_ago(90), 0, days_ago(60))
    assert document_control(COA, on=days_ago(20)) == printed
    add_revision(
        admin, effective=30, entered=0, doc_code="FR-KAL-099", first_issue_date=days_ago(70)
    )
    for day in (30, 20, 1):
        assert document_control(COA, on=days_ago(day)) == printed, day
    assert document_control(COA) == DocumentControl("FR-KAL-099", days_ago(70), 1, days_ago(30))


def test_printed_doc_no_is_never_given_to_another_output(admin):
    configure(admin, issued=90, revisions=(60,))
    add_revision(admin, effective=10, doc_code="FR-KAL-099")  # FR-KAL-001 artık boşta görünür
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, RECALL, note="x", doc_code="fr-kal-001")
    assert error_code(excinfo) == "output_code_taken"
    assert "revizyonlarında kullanıldı" in excinfo.value.message
    outputs.update_output(
        admin, RECALL, note="Liste", doc_code="FR-KAL-002", first_issue_date=days_ago(30)
    )
    add_revision(admin, RECALL, effective=20)
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, RECALL, effective=5, doc_code="FR-KAL-001")
    assert error_code(excinfo) == "output_code_taken"
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, RECALL, effective=5, doc_code="FR-KAL-099")  # bugünkü numarası
    assert error_code(excinfo) == "output_code_taken"
    assert OutputDocument.objects.get(key=RECALL).doc_code == "FR-KAL-002"
    # Çıktı kendi eski numarasına yeni revizyonla döner (yanlış numaralandırma geri alınır);
    # bıraktığı numara başka çıktıya yine verilmez.
    back = add_revision(admin, effective=5, doc_code="fr-kal-001")
    assert (back.revision_no, back.doc_code) == (2, "FR-KAL-001")
    assert OutputDocument.objects.get(key=COA).doc_code == "FR-KAL-001"
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, RECALL, effective=5, doc_code="FR-KAL-099")
    assert error_code(excinfo) == "output_code_taken"
    assert "revizyonlarında kullanıldı" in excinfo.value.message


def test_migration_backfills_revision_snapshots_and_band(admin):
    """core 0008: var olan revizyonlara çıktının doküman no ve ilk yayın tarihi; bugün bandı açık
    çıktıya ilk revizyonundan (yoksa kaydın açıldığı günden) beri açık bant kaydı."""

    def revision(row, number, effective, **extra):
        created = OutputDocumentRevision.objects.create(
            output=row,
            revision_no=number,
            revision_date=days_ago(effective),
            change_note="Eski kayıt",
            approved_by_name="Kalite Müdürü",
            approved_on=days_ago(effective),
            **extra,
        )
        entered_on(created, effective)  # yürürlüğe girdiği gün girilmiş
        return created

    # Göçten önceki kayıtlar doğrudan yazılır (servis bugün bu durumu üretmez).
    coa = OutputDocument.objects.create(
        key=COA, doc_code="FR-KAL-001", first_issue_date=days_ago(90), is_active=True
    )
    revision(coa, 0, 60)
    revision(coa, 1, 10)
    order = OutputDocument.objects.create(
        key=ORDER, doc_code="FR-SAT-001", first_issue_date=days_ago(90)
    )
    revision(order, 0, 30)
    revision(order, 1, 20, doc_code="FR-SAT-000", first_issue_date=days_ago(95))
    recall = OutputDocument.objects.create(key=RECALL, doc_code="FR-KAL-002", is_active=True)
    OutputDocument.objects.filter(pk=recall.pk).update(created_at=timezone.now() - timedelta(7))
    banded = OutputDocument.objects.create(
        key="hse.sds-gaps", doc_code="LS-ISG-001", first_issue_date=days_ago(9), is_active=True
    )
    revision(banded, 0, 9)
    OutputBandChange.objects.create(output=banded, is_active=True, effective_date=days_ago(3))

    migration.backfill_snapshots_and_band(django_apps, None)

    snapshots = OutputDocumentRevision.objects.order_by("output__key", "revision_no")
    assert [(r.output.key, r.revision_no, r.doc_code, r.first_issue_date) for r in snapshots] == [
        ("hse.sds-gaps", 0, "LS-ISG-001", days_ago(9)),
        (ORDER, 0, "FR-SAT-001", days_ago(90)),
        (ORDER, 1, "FR-SAT-000", days_ago(95)),  # saklanmış bilgi ezilmez
        (COA, 0, "FR-KAL-001", days_ago(90)),
        (COA, 1, "FR-KAL-001", days_ago(90)),
    ]
    bands = OutputBandChange.objects.order_by("output__key", "id")
    assert [(b.output.key, b.is_active, b.effective_date, b.created_by) for b in bands] == [
        ("hse.sds-gaps", True, days_ago(3), None),  # kaydı olan çıktıya eklenmez
        (COA, True, days_ago(60), None),
        (RECALL, True, days_ago(7), None),
    ]
    # Göçten sonra yeniden basım, belgenin tarihindeki revizyonla.
    assert document_control(COA, on=days_ago(30)) == DocumentControl(
        "FR-KAL-001", days_ago(90), 0, days_ago(60)
    )
    assert document_control(ORDER) is None  # bant kapalıydı
    # İkinci çalıştırma bir şey yazmaz.
    migration.backfill_snapshots_and_band(django_apps, None)
    assert OutputBandChange.objects.count() == 3


def test_template_change_asks_for_a_new_revision(admin, monkeypatch):
    configure(admin)
    item = registry.output_type(COA)
    assert item is not None
    assert outputs.describe_output(item)["template_changed"] is False
    changed = dataclasses.replace(item, template_version=item.template_version + 1)
    monkeypatch.setitem(registry._OUTPUTS, COA, changed)
    assert outputs.describe_output(changed)["template_changed"] is True
    add_revision(admin, effective=0)
    row = outputs.describe_output(changed)
    assert row["template_changed"] is False
    assert [r["revision_no"] for r in row["revisions"]] == [1, 0]
    assert OutputDocumentRevision.objects.get(revision_no=1).template_version == 2


# --- çıktılar ------------------------------------------------------------------------------------


def test_excel_gets_print_footer_and_properties_without_changing_cells(admin):
    from apps.masterdata.importers import build_template, template_output

    plain = load_workbook(io.BytesIO(build_template("materials")))
    assert not plain.worksheets[0].oddFooter.left.text
    assert not plain.properties.identifier

    configure(admin, template_output("materials"), "FR-SIS-001")
    book = load_workbook(io.BytesIO(build_template("materials")))
    control = document_control(template_output("materials"))
    assert control is not None
    for sheet in book.worksheets:
        assert sheet.oddFooter.left.text == control.band()
        assert sheet.oddFooter.right.text == "Sayfa &P/&N"
    assert (book.properties.identifier, book.properties.version) == ("FR-SIS-001", "00")
    # Hücreler aynı: şablon yine içe aktarılır.
    assert [cell.value for cell in book.worksheets[0][1]] == [
        cell.value for cell in plain.worksheets[0][1]
    ]


def test_pdf_band_is_drawn_on_every_page(monkeypatch):
    from apps.reporting.exports import to_pdf
    from apps.reporting.reports import Column

    calls: list[tuple[str, int | None, int | None]] = []

    def spy(canvas, control, page, total, **kwargs):
        calls.append((control.doc_code, page, total))

    monkeypatch.setattr(core_pdf, "draw_band", spy)
    control = DocumentControl("LS-RAP-001", date(2026, 1, 10), 0, date(2026, 1, 10))
    rows = [{"name": f"Satır {number}"} for number in range(150)]
    columns = [Column("name", "Ad", width=30)]
    assert to_pdf("Deneme", columns, rows, control=control).startswith(b"%PDF")
    total = calls[0][2]
    assert total is not None and total >= 2
    assert calls == [("LS-RAP-001", page, total) for page in range(1, total + 1)]

    calls.clear()
    assert to_pdf("Deneme", columns, rows).startswith(b"%PDF")
    assert calls == []  # bant kapalı: düz canvas


@pytest.mark.parametrize(("pagesize", "baseline"), [(landscape(A4), 9.5), (portrait(A4), 13)])
def test_personnel_pdf_band_sits_above_the_footer(monkeypatch, pagesize, baseline):
    from apps.personnel import pdf as personnel_pdf

    calls: list[tuple[int | None, int | None, float, float]] = []

    def spy(canvas, control, page, total, *, left, baseline):
        calls.append((page, total, left, baseline))

    monkeypatch.setattr(personnel_pdf, "draw_band", spy)
    control = DocumentControl("FR-IK-002", date(2026, 1, 10), 0, date(2026, 1, 10))
    for chrome in (
        personnel_pdf._Chrome("Bordro", "", control=control),
        personnel_pdf._Chrome("Bordro", ""),
    ):
        canvas = chrome.canvas_maker()(io.BytesIO(), pagesize=pagesize)
        canvas.showPage()
        canvas.save()
    # Sayfa bilgisi sağda zaten yazılı: bant sayfasız, notun üstünde; bantsız çıktıda çizilmez.
    assert calls == [(None, None, 10 * mm, baseline * mm)]


# --- API -----------------------------------------------------------------------------------------


def test_api_requires_admin(client_for, api_client):
    assert api_client.get(f"{BASE}/").status_code == 401
    planner = client_for(PLANLAMA)
    assert planner.get(f"{BASE}/").status_code == 403
    assert planner.patch(f"{BASE}/{COA}/", {"note": "x"}, format="json").status_code == 403
    revision = {
        "revision_date": days_ago(1).isoformat(),
        "change_note": "Yeni alan",
        "approved_by_name": "Kalite Müdürü",
        "approved_on": days_ago(1).isoformat(),
        "doc_code": "FR-KAL-001",
        "first_issue_date": days_ago(1).isoformat(),
    }
    assert planner.post(f"{BASE}/{COA}/revisions/", revision, format="json").status_code == 403
    assert not OutputDocument.objects.exists()


def test_api_list_update_and_revisions(client_for):
    client = client_for(ADMIN)
    listing = client.get(f"{BASE}/")
    assert listing.status_code == 200
    assert listing.data["count"] == len(registry.output_types())
    row = next(item for item in listing.data["results"] if item["key"] == COA)
    assert row | {"revisions": []} == {
        "key": COA,
        "label": "Analiz sertifikası",
        "group": "Kalite",
        "formats": ["PDF"],
        "legal": False,
        "suggested_code": "FR-KAL-001",
        "doc_code": "",
        "first_issue_date": None,
        "doc_locked": False,
        "is_active": False,
        "revision_no": None,
        "revision_date": None,
        "template_version": 1,
        "template_changed": False,
        "revisions": [],
    }
    assert client.get(f"{BASE}/yok.boyle/").status_code == 404

    missing_note = client.patch(f"{BASE}/{COA}/", {"doc_code": "FR-KAL-001"}, format="json")
    assert (missing_note.status_code, missing_note.data["code"]) == (400, "note_required")
    assert missing_note.data["detail"] == NOTE_MESSAGE
    too_old = client.patch(
        f"{BASE}/{COA}/", {"first_issue_date": "0001-01-01", "note": "x"}, format="json"
    )
    assert (too_old.status_code, too_old.data["code"]) == (400, "invalid_date")
    saved = client.patch(
        f"{BASE}/{COA}/",
        {"doc_code": "FR-KAL-001", "first_issue_date": days_ago(30).isoformat(), "note": "Liste"},
        format="json",
    )
    assert saved.status_code == 200 and saved.data["doc_code"] == "FR-KAL-001"
    assert saved.data["doc_locked"] is False
    not_ready = client.patch(f"{BASE}/{COA}/", {"is_active": True, "note": "x"}, format="json")
    assert (not_ready.status_code, not_ready.data["code"]) == (400, "output_not_ready")

    first = {
        "revision_date": days_ago(20).isoformat(),
        "change_note": "İlk yayın",
        "approved_by_name": "Kalite Müdürü",
        "approved_on": days_ago(21).isoformat(),
        "revision_no": 2,
    }
    old_day = client.post(
        f"{BASE}/{COA}/revisions/", first | {"approved_on": "1999-12-31"}, format="json"
    )
    assert (old_day.status_code, old_day.data["code"]) == (400, "invalid_date")
    revision = client.post(f"{BASE}/{COA}/revisions/", first, format="json")
    assert revision.status_code == 201
    assert (revision.data["revision_no"], revision.data["revision_date"]) == (
        2,
        days_ago(20).isoformat(),
    )
    assert revision.data["doc_locked"] is True
    [entry] = revision.data["revisions"]
    assert entry["change_note"] == "İlk yayın" and entry["created_by_name"]
    assert (entry["doc_code"], entry["first_issue_date"]) == (
        "FR-KAL-001",
        days_ago(30).isoformat(),
    )
    bad = client.post(
        f"{BASE}/{COA}/revisions/",
        {
            "revision_date": days_ago(10).isoformat(),
            "change_note": "Yeni alan",
            "approved_by_name": "Kalite Müdürü",
            "approved_on": days_ago(5).isoformat(),
        },
        format="json",
    )
    assert (bad.status_code, bad.data["code"]) == (400, "approval_after_effective")
    active = client.patch(f"{BASE}/{COA}/", {"is_active": True, "note": "Bant"}, format="json")
    assert active.status_code == 200 and active.data["is_active"] is True
    assert client.get(f"{BASE}/{COA}/").data["is_active"] is True

    # İlk revizyondan sonra doküman no yalnız yeni revizyonla değişir.
    locked = client.patch(f"{BASE}/{COA}/", {"doc_code": "FR-KAL-009", "note": "x"}, format="json")
    assert (locked.status_code, locked.data["code"]) == (400, "output_doc_locked")
    same = client.patch(
        f"{BASE}/{COA}/",
        {"doc_code": "FR-KAL-001", "first_issue_date": days_ago(30).isoformat(), "note": "x"},
        format="json",
    )
    assert same.status_code == 200
    renumbered = client.post(
        f"{BASE}/{COA}/revisions/",
        {
            "revision_date": days_ago(5).isoformat(),
            "change_note": "Doküman listesinde yeni numara",
            "approved_by_name": "Kalite Müdürü",
            "approved_on": days_ago(5).isoformat(),
            "doc_code": "fr-kal-009",
            "first_issue_date": days_ago(25).isoformat(),
        },
        format="json",
    )
    assert renumbered.status_code == 201
    assert (renumbered.data["doc_code"], renumbered.data["first_issue_date"]) == (
        "FR-KAL-009",
        days_ago(25).isoformat(),
    )
    assert [
        (entry["revision_no"], entry["doc_code"], entry["first_issue_date"])
        for entry in renumbered.data["revisions"]
    ] == [
        (3, "FR-KAL-009", days_ago(25).isoformat()),
        (2, "FR-KAL-001", days_ago(30).isoformat()),
    ]


def test_api_outputs_list_runs_a_fixed_number_of_queries(
    client_for, make_user, django_assert_max_num_queries
):
    """Liste her çıktı için ayrı sorgu çalıştırmaz: kayıtlar ve revizyonları birer sorgu (kaydı
    olmayan çıktı yeniden sorulmaz)."""
    client = client_for(ADMIN)
    assert client.get(f"{BASE}/", {"page_size": 200}).status_code == 200  # rol önbelleği dolar
    with django_assert_max_num_queries(2):
        assert client.get(f"{BASE}/", {"page_size": 200}).data["count"] == len(
            registry.output_types()
        )
    user = make_user(ADMIN)
    for number, item in enumerate(registry.output_types(), start=1):
        row = OutputDocument.objects.create(
            key=item.key, doc_code=f"FR-DNM-{number:03d}", first_issue_date=days_ago(90)
        )
        OutputDocumentRevision.objects.bulk_create(
            OutputDocumentRevision(
                output=row,
                revision_no=revision_no,
                revision_date=days_ago(60 - 50 * revision_no),
                doc_code=row.doc_code,
                first_issue_date=row.first_issue_date,
                change_note="Revizyon",
                approved_by_name="Kalite Müdürü",
                approved_on=days_ago(60 - 50 * revision_no),
                created_by=user,
            )
            for revision_no in (0, 1)
        )
    with django_assert_max_num_queries(2):
        response = client.get(f"{BASE}/", {"page_size": 200})
    assert response.status_code == 200
    assert response.data["count"] == len(registry.output_types())
    assert all(len(row["revisions"]) == 2 and row["doc_locked"] for row in response.data["results"])
    assert {row["revisions"][0]["created_by_name"] for row in response.data["results"]} == {
        user.full_name or user.username
    }


def test_api_outputs_list_schema_is_paginated():
    """OpenAPI şeması gerçek yanıtı anlatır: sayfalı nesne (count, results), page ve page_size."""
    schema = SchemaGenerator(
        patterns=[path("api/v1/coding/outputs/", coding_api.OutputDocumentListView.as_view())]
    ).get_schema(request=None, public=True)
    operation = schema["paths"]["/api/v1/coding/outputs/"]["get"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {"page", "page_size"}
    body = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/PaginatedOutputDocumentList"}
    page = schema["components"]["schemas"]["PaginatedOutputDocumentList"]
    assert {"count", "next", "previous", "results"} <= set(page["properties"])
    output = schema["components"]["schemas"]["OutputDocument"]["properties"]
    assert output["doc_locked"]["type"] == "boolean"
    revision = schema["components"]["schemas"]["OutputRevision"]["properties"]
    assert {"doc_code", "first_issue_date"} <= set(revision)
