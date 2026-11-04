"""Çıktı doküman kodları (ISO 9001 md. 7.5): kayıt, doküman no, revizyonlar, bant, API."""

import dataclasses
import io
from datetime import date, timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.utils import timezone
from openpyxl import load_workbook
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.units import mm

from apps.core import pdf as core_pdf
from apps.core.coding import outputs, registry
from apps.core.coding.outputs import DOC_CODE_RE, DocumentControl, document_control
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, OutputDocument, OutputDocumentRevision
from apps.core.roles import ADMIN, PLANLAMA

pytestmark = pytest.mark.django_db

COA = "quality.coa"
RECALL = "traceability.recall"
BASE = "/api/v1/coding/outputs"


@pytest.fixture
def admin(make_user):
    return make_user(ADMIN)


def days_ago(n: int) -> date:
    return timezone.localdate() - timedelta(days=n)


def add_revision(actor, key=COA, *, effective: int, approved: int | None = None, **extra):
    return outputs.add_revision(
        actor,
        key,
        revision_date=days_ago(effective),
        change_note=f"{effective} gün önce yürürlüğe girdi",
        approved_by_name="Kalite Müdürü",
        approved_on=days_ago(effective if approved is None else approved),
        **extra,
    )


def configure(actor, key=COA, code="FR-KAL-001", *, issued=60, revisions=(60,), active=True):
    """Çıktıya doküman no, ilk yayın tarihi ve revizyonlar (gün önce) girer; bandı açar."""
    outputs.update_output(
        actor, key, note="Doküman listesi", doc_code=code, first_issue_date=days_ago(issued)
    )
    for effective in revisions:
        add_revision(actor, key, effective=effective)
    if active:
        outputs.update_output(actor, key, note="Bant açıldı", is_active=True)


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
        "purchasing.order",
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


# --- doküman no ve bant ------------------------------------------------------------------------


def test_update_output_rules(admin, make_user):
    with pytest.raises(PermissionDenied):
        outputs.update_output(make_user(PLANLAMA), COA, note="x", doc_code="FR-KAL-001")
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note=" ", doc_code="FR-KAL-001")
    assert error_code(excinfo) == "note_required"
    for bad in ("FR KAL 001", "-FR-001", "FR_KAL_001", "A" * 33):
        with pytest.raises(BusinessRuleError) as excinfo:
            outputs.update_output(admin, COA, note="x", doc_code=bad)
        assert error_code(excinfo) == "invalid_doc_code"
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", first_issue_date=days_ago(-1))
    assert error_code(excinfo) == "future_date"
    # Bant ancak doküman no, ilk yayın tarihi ve revizyon girilince açılır.
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", doc_code="FR-KAL-001", is_active=True)
    assert error_code(excinfo) == "output_not_ready"
    assert not OutputDocument.objects.filter(key=COA).exists()  # işlem geri alındı

    # Küçük harf büyüğe çevrilir; nokta ve eğik çizgi geçerlidir.
    row = outputs.update_output(admin, COA, note="Doküman listesi", doc_code="f.kal/01")
    assert row.doc_code == "F.KAL/01"
    audit = AuditLog.objects.filter(object_id=row.pk, action=AuditLog.Action.UPDATE).latest("id")
    assert audit.changes["doc_code"] == ["", "F.KAL/01"]
    assert audit.note == "Doküman listesi"
    # Doküman no çıktılar arasında tektir.
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, RECALL, note="x", doc_code="F.KAL/01")
    assert error_code(excinfo) == "output_code_taken"

    add_revision(admin, effective=30)
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", is_active=True)
    assert error_code(excinfo) == "output_not_ready"  # ilk yayın tarihi yok
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", first_issue_date=days_ago(10))
    assert error_code(excinfo) == "issue_after_revision"
    outputs.update_output(admin, COA, note="x", first_issue_date=days_ago(400), is_active=True)
    assert document_control(COA) == DocumentControl("F.KAL/01", days_ago(400), 0, days_ago(30))
    # Bant açıkken doküman no silinemez.
    with pytest.raises(BusinessRuleError) as excinfo:
        outputs.update_output(admin, COA, note="x", doc_code="")
    assert error_code(excinfo) == "output_not_ready"


def test_revision_numbering_and_rules(admin):
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
    audit = AuditLog.objects.filter(object_id=row.pk, action=AuditLog.Action.CUSTOM).latest("id")
    assert audit.changes == {"revision_no": [1, 2]}


def test_first_revision_number_follows_the_quality_system(admin):
    # Kalite sisteminde Rev. 03'te olan form sisteme 03 ile girilir; sonraki 04 olur.
    assert add_revision(admin, effective=30, revision_no=3).revision_no == 3
    assert add_revision(admin, effective=10).revision_no == 4
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, RECALL, effective=10, revision_no=100)
    assert error_code(excinfo) == "revision_no_invalid"
    # Revizyon ilk yayın tarihinden önce olamaz.
    outputs.update_output(admin, RECALL, note="x", first_issue_date=days_ago(5))
    with pytest.raises(BusinessRuleError) as excinfo:
        add_revision(admin, RECALL, effective=10)
    assert error_code(excinfo) == "revision_date_invalid"


def test_document_is_printed_with_the_revision_in_force_on_its_date(admin):
    configure(admin, issued=90, revisions=(60, 10))
    assert document_control(COA).revision_no == 1
    assert document_control(COA, on=days_ago(30)).revision_no == 0
    assert document_control(COA, on=days_ago(10)).revision_no == 1
    # İlk revizyondan önceki belge (bant yokken basılmıştı) bantsız basılır.
    assert document_control(COA, on=days_ago(70)) is None
    outputs.update_output(admin, COA, note="Bant kapatıldı", is_active=False)
    assert document_control(COA) is None


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
    assert planner.post(f"{BASE}/{COA}/revisions/", {}, format="json").status_code == 403


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
    saved = client.patch(
        f"{BASE}/{COA}/",
        {"doc_code": "FR-KAL-001", "first_issue_date": days_ago(30).isoformat(), "note": "Liste"},
        format="json",
    )
    assert saved.status_code == 200 and saved.data["doc_code"] == "FR-KAL-001"
    not_ready = client.patch(f"{BASE}/{COA}/", {"is_active": True, "note": "x"}, format="json")
    assert (not_ready.status_code, not_ready.data["code"]) == (400, "output_not_ready")

    revision = client.post(
        f"{BASE}/{COA}/revisions/",
        {
            "revision_date": days_ago(20).isoformat(),
            "change_note": "İlk yayın",
            "approved_by_name": "Kalite Müdürü",
            "approved_on": days_ago(21).isoformat(),
            "revision_no": 2,
        },
        format="json",
    )
    assert revision.status_code == 201
    assert (revision.data["revision_no"], revision.data["revision_date"]) == (
        2,
        days_ago(20).isoformat(),
    )
    [entry] = revision.data["revisions"]
    assert entry["change_note"] == "İlk yayın" and entry["created_by_name"]
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
