"""Çıktıların doküman kontrol bandı uçtan uca (ISO 9001 md. 7.5).

Kayıtlı her çıktı gerçek üreticisiyle basılır: PDF'in her sayfasında, Excel'in her sayfasının
yazdırma alt bilgisinde bant olmalı ve belge kendi tarihinde yürürlükte olan revizyonla basılmalı.
Her çıktı grubunun geçmişiyle açılır (`banded`, `Timeline`): çoğunda ilk yayın 90 gün önce, Rev. 00
60 gün önce, Rev. 01 10 gün önce yürürlüğe girdi ve girildi; bant 75 gün önceden beri açık. Tarihli
belge (analiz sertifikası karar günü, sipariş tarihi, irsaliye sevk günü, stok karşılaştırması) 30
gün önce tarihlenir ve Rev. 00 ile basılır; tarihsiz çıktı (raporlar, listeler, şablonlar) bugünün
Rev. 01'iyle. Bordro dönemi sabit olduğundan personel çıktılarının geçmişi de sabit günlerdedir
(`PERSONNEL`): yalnız onay günü Rev. 00 verir. Burada denetlenmeyen kayıtlı çıktı
`test_every_registered_output_is_checked`'i kırar.
"""

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from typing import Any

import pytest
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from apps.core import pdf as core_pdf
from apps.core.coding import outputs, registry
from apps.core.coding.outputs import DocumentControl
from apps.core.models import OutputBandChange, OutputDocument, OutputDocumentRevision, User
from apps.core.roles import ADMIN, DEPO, LABORATUVAR, SEVKIYAT, YONETIM
from apps.golive import exports as golive_exports
from apps.golive import services as golive_services
from apps.golive.models import StockComparison
from apps.hse import selectors as hse_selectors
from apps.hse.exports import sds_gaps_xlsx
from apps.inventory.importers import build_template as opening_template
from apps.inventory.testing import assert_stock_invariants
from apps.inventory.tests.factories import stocked_lot, storage_location
from apps.masterdata.importers import SPECS, build_template, template_output
from apps.masterdata.tests.factories import MaterialFactory
from apps.personnel import exports as personnel_exports
from apps.personnel import pdf as personnel_pdf
from apps.personnel import selectors as personnel_selectors
from apps.personnel import services as personnel_services
from apps.personnel.models import AttendanceMonth, PayrollApproval
from apps.personnel.tests.factories import employee, parameter_set
from apps.purchasing.pdf import PURCHASE_ORDER_OUTPUT, purchase_order_pdf
from apps.purchasing.tests.factories import approved_order, raw_material
from apps.purchasing.tests.factories import line as order_line
from apps.quality import coa
from apps.quality.models import QualityDecision
from apps.quality.testing import pass_sample
from apps.quality.tests.factories import quarantined_raw_lot, sample_with_spec
from apps.recipes.importers import build_template as recipe_template
from apps.reporting import filters as report_filters
from apps.reporting import services as report_services
from apps.reporting.models import ReportJob
from apps.reporting.reports import REPORTS
from apps.sales import services as sales_services
from apps.sales.models import Shipment
from apps.sales.tests.factories import (
    confirmed_order,
    finished_lot,
    finished_product,
    shipping_location,
)
from apps.sales.waybill import WAYBILL_OUTPUT, waybill_pdf
from apps.traceability.exports import RECALL_OUTPUT, recall_pdf, recall_xlsx
from apps.traceability.selectors import recall_simulation

pytestmark = pytest.mark.django_db

ISSUED, REV_00, REV_01, BAND_ON, DOCUMENT = 90, 60, 10, 75, 30
PDF, XLSX = ReportJob.Format.PDF, ReportJob.Format.XLSX
# Bordro dönemi: brütten nete bordronun başlangıç ayı (Ekim 2026); onay ve ödeme günü.
PAYROLL_YEAR, PAYROLL_MONTH = 2026, 10
PAYROLL_APPROVED, PAYROLL_PAID = date(2026, 11, 5), date(2026, 11, 10)


def days_ago(days: int) -> date:
    return timezone.localdate() - timedelta(days=days)


def noon(day: date) -> datetime:
    """Günün öğlesi (yerel saat)."""
    return timezone.make_aware(datetime.combine(day, time(12)))


def doc_code(key: str) -> str:
    """Çıktının doküman no'su: kayıttaki öneri (çıktılar arasında tek)."""
    item = registry.output_type(key)
    assert item is not None, key
    return item.suggested_code


@dataclass(frozen=True)
class Timeline:
    """Çıktının doküman kontrol geçmişi: ilk yayın günü, bandın açıldığı gün, Rev. 00 ve Rev. 01'in
    yürürlüğe girdiği (ve sisteme girildiği) günler."""

    issued: date
    band_on: date
    revisions: tuple[date, date]

    def expected(self, key: str, revision: int) -> DocumentControl:
        """Bantta beklenen bilgi: belgenin tarihinde yürürlükte olan revizyon."""
        return DocumentControl(doc_code(key), self.issued, revision, self.revisions[revision])


def recent(band_on: int = BAND_ON) -> Timeline:
    """Bugüne göre geçmiş: 30 gün önceki belge Rev. 00, bugünkü (tarihsiz) çıktı Rev. 01 ile."""
    return Timeline(days_ago(ISSUED), days_ago(band_on), (days_ago(REV_00), days_ago(REV_01)))


# Personel çıktıları sabit bordro dönemine bağlı; geçmişleri de sabit günlerde. Böylece yanlış
# günle basan üretici bugün ne olursa olsun yakalanır: dönem sonu (31.10) bant açılmadan önce
# (bantsız), onay günü (05.11) Rev. 00, ödeme günü (10.11) ve bugün Rev. 01.
PERSONNEL = Timeline(date(2026, 11, 1), date(2026, 11, 1), (date(2026, 11, 4), date(2026, 11, 6)))


def banded(admin: User, key: str, timeline: Timeline) -> None:
    """Çıktıyı `timeline`'daki geçmişle açar. Servis bandı bugünden açar ve revizyonu bugün girer:
    geçmişte açılmış bant kaydı doğrudan yazılır, revizyonlar yürürlüğe girdikleri gün girilmiş
    sayılır (geç girilen revizyon önceki tarihli belgeye basılmaz)."""
    outputs.update_output(
        admin,
        key,
        note="Doküman listesi",
        doc_code=doc_code(key),
        first_issue_date=timeline.issued,
    )
    for effective in timeline.revisions:
        revision = outputs.add_revision(
            admin,
            key,
            revision_date=effective,
            change_note="Revizyon",
            approved_by_name="Kalite Müdürü",
            approved_on=effective,
        )
        OutputDocumentRevision.objects.filter(pk=revision.pk).update(created_at=noon(effective))
    outputs.update_output(admin, key, note="Bant açıldı", is_active=True)
    OutputBandChange.objects.create(
        output=OutputDocument.objects.get(key=key), is_active=True, effective_date=timeline.band_on
    )


@dataclass
class Recorder:
    """Çizilen bantlar (bilgi, sayfa, toplam) ve `document_control`'ün sorduğu çıktı anahtarları."""

    bands: list[tuple[DocumentControl, int | None, int | None]] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.bands.clear()
        self.keys.clear()


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    record = Recorder()

    def band(
        canvas: Any, control: DocumentControl, page: int | None, total: int | None, **kwargs: Any
    ) -> None:
        record.bands.append((control, page, total))

    # Personel PDF'leri draw_band'i adıyla alır: ikisi de yakalanır.
    monkeypatch.setattr(core_pdf, "draw_band", band)
    monkeypatch.setattr(personnel_pdf, "draw_band", band)
    # document_control bu adı çağrı anında arar; üreticiler document_control'ü adıyla aldığı için
    # anahtar burada yakalanır.
    lookup = outputs.output_type

    def recording(key: str) -> Any:
        record.keys.append(key)
        return lookup(key)

    monkeypatch.setattr(outputs, "output_type", recording)
    return record


@dataclass(frozen=True)
class Printed:
    """Basılacak çıktı: anahtar, biçim, beklenen revizyon ve dosyayı üreten çağrı. `pages`: PDF'in
    en az sayfa sayısı (çok sayfalı belgede bandın her sayfada olduğu görülür)."""

    key: str
    kind: str
    revision: int
    make: Callable[[], bytes]
    pages: int = 1


def pdf_pages(content: bytes) -> int:
    return content.count(b"/Type /Page") - content.count(b"/Type /Pages")


def assert_pdf_band(
    recorder: Recorder,
    content: bytes,
    control: DocumentControl,
    *,
    numbered: bool,
    min_pages: int = 1,
) -> None:
    """Her sayfada bir bant; ortak çerçevede "Sayfa x/y" ile (personel PDF'inde sayfa bilgisi
    sağda ayrıca yazılıdır, bant sayfasızdır)."""
    assert content.startswith(b"%PDF")
    pages = pdf_pages(content)
    assert pages >= min_pages
    assert [drawn for drawn, _page, _total in recorder.bands] == [control] * pages
    numbers = [(page, total) for _drawn, page, total in recorder.bands]
    if numbered:
        assert numbers == [(number, pages) for number in range(1, pages + 1)]
    else:
        assert numbers == [(None, None)] * pages


def assert_xlsx_band(content: bytes, control: DocumentControl) -> None:
    """Her sayfanın yazdırma alt bilgisinde bant; dosya özelliklerinde doküman no ve revizyon."""
    book = load_workbook(io.BytesIO(content))
    assert book.worksheets
    for sheet in book.worksheets:
        assert sheet.oddFooter.left.text == control.band(), sheet.title
        assert sheet.oddFooter.right.text == "Sayfa &P/&N", sheet.title
    assert (book.properties.identifier, book.properties.version) == (
        control.doc_code,
        control.revision_text,
    )


def download(client: APIClient, url: str) -> bytes:
    response = client.get(url)
    assert response.status_code == 200, url
    return response.content


# --- çıktı grupları: belge kurulur, üretici çağrısı döner ----------------------------------------

Builder = Callable[[Callable[..., User], Callable[..., APIClient]], list[Printed]]


def quality_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Analiz sertifikası: lotu serbest bırakan kararın günü."""
    lab = make_user(LABORATUVAR)
    lot, _quarantine = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    decision = pass_sample(lab, sample, release_location=storage_location())
    QualityDecision.objects.filter(pk=decision.pk).update(
        decided_at=timezone.now() - timedelta(days=DOCUMENT)
    )
    return [Printed(coa.COA_OUTPUT, PDF, 0, partial(coa.coa_pdf, sample))]


def purchasing_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Satın alma siparişi: sipariş tarihi. 60 satır: iki sayfa."""
    material = raw_material()
    order = approved_order(
        make_user(YONETIM),
        [order_line(material, expected_date=days_ago(DOCUMENT - 5)) for _ in range(60)],
        order_date=days_ago(DOCUMENT),
    )
    return [Printed(PURCHASE_ORDER_OUTPUT, PDF, 0, partial(purchase_order_pdf, order), pages=2)]


def sales_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """İrsaliye: sevk günü."""
    seller, picker = make_user(SEVKIYAT), make_user(DEPO)
    shipping_location(code="SEVK")
    product = finished_product()
    lot = finished_lot(product, "10")
    order = confirmed_order(seller, [(product, "10", "ADET")])
    shipment = sales_services.plan_shipment(
        seller,
        order,
        {
            "planned_date": timezone.localdate(),
            "vehicle_plate": "34 abc 123",
            "driver_name": "Ali Veli",
            "driver_id_no": "12345678901",
        },
    )
    sales_services.pick_lot(picker, shipment, lot)
    sales_services.mark_loaded(picker, shipment)
    sales_services.dispatch_shipment(seller, shipment)
    Shipment.objects.filter(pk=shipment.pk).update(
        dispatched_at=timezone.now() - timedelta(days=DOCUMENT)
    )
    shipment.refresh_from_db()
    return [Printed(WAYBILL_OUTPUT, PDF, 0, partial(waybill_pdf, shipment))]


def personnel_keys() -> set[str]:
    return {
        personnel_pdf.PAYROLL_OUTPUT,
        personnel_pdf.EMPLOYER_COST_OUTPUT,
        personnel_pdf.PAYSLIP_OUTPUT,
        personnel_pdf.ATTENDANCE_OUTPUT,
    }


def personnel_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Bordro listesi (PDF, Excel), işveren maliyeti, pusula: bordro onay günü; puantaj: puantaj
    onay günü (`PERSONNEL` geçmişiyle Rev. 00)."""
    manager = make_user(YONETIM)
    parameter_set(manager)
    person = employee(
        manager,
        full_name="Ali Kaya",
        department="Üretim",
        hire_date=date(2020, 1, 1),
        national_id="10000000146",
        employee_no="S-1",
    )
    personnel_services.add_wage(
        manager,
        {"employee": person, "gross_monthly": Decimal("50000"), "valid_from": date(2020, 1, 1)},
    )
    personnel_services.set_opening_balance(
        manager, person, PAYROLL_YEAR, PAYROLL_MONTH, tax_base=Decimal("382500"), exemption_months=9
    )
    personnel_services.approve_attendance_month(manager, PAYROLL_YEAR, PAYROLL_MONTH)
    computed = personnel_selectors.payroll_month(PAYROLL_YEAR, PAYROLL_MONTH)
    personnel_services.approve_payroll_month(
        manager,
        PAYROLL_YEAR,
        PAYROLL_MONTH,
        payment_date=PAYROLL_PAID,
        fingerprint=personnel_selectors.payroll_fingerprint(computed),
    )
    approved_at = noon(PAYROLL_APPROVED)
    PayrollApproval.objects.update(approved_at=approved_at)
    AttendanceMonth.objects.update(approved_at=approved_at)
    month = personnel_selectors.payroll_month(PAYROLL_YEAR, PAYROLL_MONTH)
    assert month.approval is not None
    grid = personnel_selectors.attendance_grid(PAYROLL_YEAR, PAYROLL_MONTH)
    # Yanlış gün başka bant verir: dönem sonu bantsız, ödeme günü Rev. 01; yalnız onay günü
    # Rev. 00.
    period_end = date(PAYROLL_YEAR, PAYROLL_MONTH, 31)
    for key in personnel_keys():
        assert outputs.document_control(key, on=period_end) is None, key
        assert outputs.document_control(key, on=PAYROLL_PAID) == PERSONNEL.expected(key, 1), key
    return [
        # Bordro listesi ve icmal sayfası: iki sayfa.
        Printed(
            personnel_pdf.PAYROLL_OUTPUT,
            PDF,
            0,
            partial(personnel_pdf.register_pdf, month),
            pages=2,
        ),
        Printed(
            personnel_pdf.PAYROLL_OUTPUT, XLSX, 0, partial(personnel_exports.payroll_xlsx, month)
        ),
        Printed(
            personnel_pdf.EMPLOYER_COST_OUTPUT,
            PDF,
            0,
            partial(personnel_pdf.employer_cost_pdf, month),
        ),
        Printed(personnel_pdf.PAYSLIP_OUTPUT, PDF, 0, partial(personnel_pdf.payslips_pdf, month)),
        Printed(
            personnel_pdf.ATTENDANCE_OUTPUT,
            XLSX,
            0,
            partial(personnel_exports.attendance_xlsx, grid),
        ),
    ]


def golive_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Stok karşılaştırması: karşılaştırmanın yapıldığı gün."""
    material = MaterialFactory.create(code="HM-LAS")
    stocked_lot("100", material=material, location=storage_location(code="A-01"))
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Malzeme kodu", "Lot no", "Lokasyon kodu", "Miktar", "Birim"])
    sheet.append(["HM-LAS", None, None, 90, None])
    upload = io.BytesIO()
    workbook.save(upload)
    upload.seek(0)
    comparison = golive_services.create_stock_comparison(
        make_user(DEPO), upload=upload, filename="stok.xlsx"
    )
    StockComparison.objects.filter(pk=comparison.pk).update(
        created_at=timezone.now() - timedelta(days=DOCUMENT)
    )
    comparison.refresh_from_db()
    return [
        Printed("golive.comparison", XLSX, 0, partial(golive_exports.comparison_xlsx, comparison))
    ]


def _report(data: report_services.ReportData, kind: str) -> bytes:
    return report_services.render(data, kind).content


def reporting_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Raporlar (tarihsiz): her rapor PDF ve Excel olarak, `reporting.services.render` ile."""
    admin = make_user(ADMIN)
    printed = []
    for definition in REPORTS.values():
        values = report_filters.parse_filters(definition, {})
        data = report_services.report_data(definition, admin, values)
        key = report_services.output_key(definition)
        printed += [Printed(key, kind, 1, partial(_report, data, kind)) for kind in (PDF, XLSX)]
    return printed


def traceability_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Geri çağırma raporu (tarihsiz): PDF ve Excel."""
    result = recall_simulation([stocked_lot("10")])
    return [
        Printed(RECALL_OUTPUT, PDF, 1, partial(recall_pdf, result)),
        Printed(RECALL_OUTPUT, XLSX, 1, partial(recall_xlsx, result)),
    ]


COSTING_REPORTS = {
    "cost-trend": "costing.cost-trend",
    "batch-variance": "costing.batch-variance",
    "scrap-cost": "costing.scrap-cost",
    "top-materials": "costing.top-materials",
    "stock-value": "costing.stock-value",
}
PERSONNEL_COST = "costing.personnel-cost"


def costing_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Maliyet Excel'leri (tarihsiz): çıktı anahtarı uç noktada verilir, API'den indirilir."""
    client = client_for(ADMIN)
    printed = [
        Printed(key, XLSX, 1, partial(download, client, f"/api/v1/costing/reports/{name}/xlsx/"))
        for name, key in COSTING_REPORTS.items()
    ]
    url = f"/api/v1/costing/personnel-costs/{PAYROLL_YEAR}/{PAYROLL_MONTH}/xlsx/"
    printed.append(Printed(PERSONNEL_COST, XLSX, 1, partial(download, client, url)))
    return printed


def hse_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """Eksik GBF listesi (tarihsiz)."""
    return [Printed("hse.sds-gaps", XLSX, 1, lambda: sds_gaps_xlsx(hse_selectors.sds_gaps()))]


TEMPLATES = {
    "recipes.template": recipe_template,
    "inventory.opening-template": opening_template,
    "golive.comparison-template": golive_exports.comparison_template,
}


def template_outputs(make_user: Callable[..., User], client_for: Any) -> list[Printed]:
    """İçe aktarma şablonları (tarihsiz)."""
    printed = [
        Printed(template_output(kind), XLSX, 1, partial(build_template, kind)) for kind in SPECS
    ]
    printed += [Printed(key, XLSX, 1, make) for key, make in TEMPLATES.items()]
    return printed


@dataclass(frozen=True)
class Group:
    """Çıktı grubu: kurulum (belgeleri hazırlar, üretici çağrılarını döner), çıktı anahtarları ve
    çıktıların doküman kontrol geçmişi."""

    build: Builder
    output_keys: Callable[[], set[str]]
    timeline: Callable[[], Timeline] = recent


# Anahtarlar burada yazılıdır: kayda yeni çıktı eklenince `test_every_registered_output_is_checked`
# onu bir gruba eklemeyi ister.
GROUPS: dict[str, Group] = {
    "quality": Group(quality_outputs, lambda: {coa.COA_OUTPUT}),
    "purchasing": Group(purchasing_outputs, lambda: {PURCHASE_ORDER_OUTPUT}),
    "sales": Group(sales_outputs, lambda: {WAYBILL_OUTPUT}),
    "personnel": Group(personnel_outputs, personnel_keys, lambda: PERSONNEL),
    "golive": Group(golive_outputs, lambda: {"golive.comparison"}),
    "reporting": Group(
        reporting_outputs,
        lambda: {report_services.output_key(definition) for definition in REPORTS.values()},
    ),
    "traceability": Group(traceability_outputs, lambda: {RECALL_OUTPUT}),
    "costing": Group(costing_outputs, lambda: {*COSTING_REPORTS.values(), PERSONNEL_COST}),
    "hse": Group(hse_outputs, lambda: {"hse.sds-gaps"}),
    "templates": Group(
        template_outputs,
        lambda: {template_output(kind) for kind in SPECS} | set(TEMPLATES),
    ),
}


def test_every_registered_output_is_checked() -> None:
    declared = [key for group in GROUPS.values() for key in group.output_keys()]
    assert len(declared) == len(set(declared))
    assert set(declared) == {item.key for item in registry.output_types()}


@pytest.mark.parametrize("group", list(GROUPS))
def test_outputs_print_the_band_of_their_document_date(
    group: str,
    make_user: Callable[..., User],
    client_for: Callable[..., APIClient],
    recorder: Recorder,
) -> None:
    checked = GROUPS[group]
    timeline = checked.timeline()
    admin = make_user(ADMIN)
    for key in sorted(checked.output_keys()):
        banded(admin, key, timeline)
    printed = checked.build(make_user, client_for)
    assert {item.key for item in printed} == checked.output_keys()
    for item in printed:
        recorder.clear()
        content = item.make()
        # Üretici kendi çıktısının doküman kontrol bilgisini sordu.
        assert set(recorder.keys) == {item.key}, (item.key, item.kind, recorder.keys)
        control = timeline.expected(item.key, item.revision)
        if item.kind == PDF:
            numbered = not item.key.startswith("personnel.")
            assert_pdf_band(recorder, content, control, numbered=numbered, min_pages=item.pages)
        else:
            assert recorder.bands == []
            assert_xlsx_band(content, control)
    assert_stock_invariants()


def test_dated_output_before_the_band_was_turned_on_prints_no_band(
    make_user: Callable[..., User], recorder: Recorder
) -> None:
    """Rev. 00 60 gün önce yürürlükte, bant 40 gün önce açıldı: 45 gün önceki sipariş bantsız,
    30 gün önceki Rev. 00 ile basılır."""
    timeline = recent(band_on=40)
    banded(make_user(ADMIN), PURCHASE_ORDER_OUTPUT, timeline)
    manager = make_user(YONETIM)
    before = approved_order(
        manager, [order_line(raw_material(), expected_date=days_ago(40))], order_date=days_ago(45)
    )
    after = approved_order(
        manager,
        [order_line(raw_material(), expected_date=days_ago(DOCUMENT - 5))],
        order_date=days_ago(DOCUMENT),
    )
    recorder.clear()
    assert purchase_order_pdf(before).startswith(b"%PDF")
    assert recorder.bands == [] and recorder.keys == [PURCHASE_ORDER_OUTPUT]
    recorder.clear()
    content = purchase_order_pdf(after)
    assert_pdf_band(recorder, content, timeline.expected(PURCHASE_ORDER_OUTPUT, 0), numbered=True)
