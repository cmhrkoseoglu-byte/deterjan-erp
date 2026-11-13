"""Bordroda yarım gün (YG) kesintisi (2. adım; docs/DECISIONS.md "Puantajda günlük çalışma saati ve
yarım gün"): puantajdan hesaba köprü (takvim kuralı), kümülatif zincir, başlangıç öncesi ay, onay
kapısı, yeniden açma, çıktılar (pusula, bordro listesi, icmal, Excel), eski motorla onaylanmış ayın
çıktıları, mali müşavirdeki kişi ve API.

Bugün 20.01.2027 sayılır. Günlük çalışma saati 9, hafta tatili pazar. Örnek kişi: 45.000 TL brüt,
Eylül sonu devri girilmiş; yarım gün çalışılan her gün için 45.000 / 60 = 750,00 kesilir."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from django.utils import timezone
from openpyxl import load_workbook
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from rest_framework.test import APIClient

from apps.core.models import User
from apps.personnel import exports, payroll, pdf, selectors, services
from apps.personnel.models import (
    AttendanceMonth,
    AttendanceStatus,
    Employee,
    PayrollItemCategory,
    PayrollRun,
    PayrollSlip,
)
from apps.personnel.tests.factories import employee, parameter_set

pytestmark = pytest.mark.django_db
D = Decimal
C = PayrollItemCategory
S = AttendanceStatus
BASE = "/api/v1/personnel"
TODAY = date(2027, 1, 20)
SHORT = date(2026, 10, 5)  # pazartesi
SHORT_COLUMNS = (exports.SHORT_DAYS_HEADER, exports.SHORT_DAY_DEDUCTION_HEADER)
EXTERNAL_NOTE = "Puantajda 1 YG günü (yarım gün kesintisi mali müşavirce)"


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> date:
    original = timezone.localdate

    def fake(*args: Any, **kwargs: Any) -> date:
        return TODAY if not args and not kwargs else original(*args, **kwargs)

    monkeypatch.setattr(timezone, "localdate", fake)
    return TODAY


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    user = make_user("yonetim", username="yonetim")
    services.update_attendance_settings(user, [6], daily_hours=D("9"))
    parameter_set(user)
    return user


def _person(actor: User, name: str = "Ali Kaya", **extra: Any) -> Employee:
    person = employee(actor, full_name=name, employee_no=extra.pop("employee_no", "S-1"), **extra)
    services.add_wage(
        actor, {"employee": person, "gross_monthly": D("45000"), "valid_from": date(2020, 1, 1)}
    )
    services.set_opening_balance(actor, person, 2026, 10, tax_base=D("382500"), exemption_months=9)
    return person


def _short(actor: User, person: Employee, day: date = SHORT, hours: str = "4.5") -> None:
    services.set_attendance_day(
        actor, person, day, status=S.WORKED, worked_hours=D(hours), short_day=True
    )


def _line(year: int, month: int, person: Employee) -> payroll.Result:
    found = selectors.payroll_month(year, month)
    return next(row.line for row in found.rows if row.employee.pk == person.pk)


def _approve(actor: User, month: int = 10) -> PayrollRun:
    if not AttendanceMonth.objects.filter(
        year=2026, month=month, status=AttendanceMonth.Status.APPROVED
    ).exists():
        services.approve_attendance_month(actor, 2026, month)
    fingerprint = selectors.payroll_fingerprint(selectors.payroll_month(2026, month))
    return services.approve_payroll_month(
        actor, 2026, month, payment_date=date(2026, month + 1, 10), fingerprint=fingerprint
    )


def _gates() -> dict[str, str]:
    found = selectors.payroll_gates(selectors.payroll_month(2026, 10))
    return {gate.code: gate.level for gate in found}


def _bordro(month: selectors.PayrollMonth) -> tuple[list[str], list[tuple[Any, ...]], Any]:
    """Excel "Bordro" sayfası: başlık satırı, başlıktan sonraki satırlar ve sayfa."""
    sheet = load_workbook(BytesIO(exports.payroll_xlsx(month)))["Bordro"]
    rows = list(sheet.iter_rows(values_only=True))
    header = next(index for index, row in enumerate(rows) if row and row[0] == "Sicil no")
    return [str(value) for value in rows[header]], rows[header + 1 :], (sheet, header + 2)


def _number(value: Any) -> Decimal:
    return D(str(value))


# --- köprü: puantajdan hesaba ---------------------------------------------------------------------


def test_short_day_deducts_only_on_a_calendar_work_day(manager: User) -> None:
    """Kesintiye yalnızca takvimde iş günü olan "Çalıştı" günündeki YG girer: arife (yarım gün
    tatil) dahil. Hafta tatiline ya da tam gün tatile "Çalıştı" yazılmış günde YG yalnızca kayıttır
    (puantajda görünür, kesilmez)."""
    person = _person(manager)
    full = _line(2026, 10, person)
    arife, holiday, sunday = date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 11)
    services.add_holiday(manager, {"date": arife, "name": "Arife", "half_day": True})
    services.add_holiday(manager, {"date": holiday, "name": "Bayram"})
    _short(manager, person, holiday)
    _short(manager, person, sunday)
    cells = {
        cell.date: cell
        for cell in selectors.attendance_grid(2026, 10).rows[0].cells
        if cell.date in (holiday, sunday)
    }
    assert [cell.code for cell in cells.values()] == ["YG", "YG"]
    line = _line(2026, 10, person)
    assert (line.short_days, line.short_day_deduction) == (0, D(0))

    _short(manager, person)
    _short(manager, person, arife, hours="4")  # arife: günün çalışma saati 4,5
    line = _line(2026, 10, person)
    assert (line.short_days, line.short_day_deduction) == (2, D("1500.00"))
    assert line.gross_total == full.gross_total - D("1500.00")
    assert (line.salary, line.paid_days, line.sgk_days) == (full.salary, 30, 30)


def test_open_month_short_day_lowers_the_next_months_carry(manager: User) -> None:
    """Açık Ekim'deki YG Ekim'in GV matrahını, dolayısıyla Kasım'ın kümülatifini düşürür."""
    person = _person(manager)
    before = _line(2026, 11, person).cumulative_tax_base_before
    _short(manager, person)
    october = _line(2026, 10, person)
    november = _line(2026, 11, person)
    assert november.cumulative_tax_base_before == october.cumulative_tax_base_after < before


def test_month_before_the_payroll_start(
    manager: User, client_for: Callable[..., APIClient]
) -> None:
    """Bordro başlangıcından önceki ay (Eylül 2026, personel maliyeti): kesinti brüte ve
    maliyete girer, net alanları boş."""
    person = _person(manager)
    full = _line(2026, 9, person)
    _short(manager, person, date(2026, 9, 7))
    month = selectors.payroll_month(2026, 9)
    assert not month.net
    line = month.rows[0].line
    assert (line.short_days, line.short_day_deduction) == (1, D("750.00"))
    assert line.gross_total == D("44250.00") and line.employer_cost < full.employer_cost
    body = client_for("yonetim").get(f"{BASE}/payroll/2026/9/").json()
    data = body["rows"][0]["line"]
    assert (data["short_days"], data["short_day_deduction"], data["gross_total"]) == (
        1,
        "750.00",
        "44250.00",
    )
    assert data["net_pay"] is None and data["payable"] is None
    assert body["totals"]["short_day_deduction"] == "750.00"


# --- onay kapısı ve yeniden açma ------------------------------------------------------------------


def test_short_day_can_make_the_payable_negative(manager: User) -> None:
    """YG neti düşürür: avans sonrası ödenecek eksiye düşerse onay durur (NEGATIVE_PAYABLE)."""
    person = _person(manager)
    net = _line(2026, 10, person).net_pay
    services.add_payroll_item(
        manager,
        {
            "employee": person,
            "year": 2026,
            "month": 10,
            "category": C.ADVANCE,
            "description": "Avans",
            "amount": net - D("100"),
        },
    )
    assert selectors.NEGATIVE_PAYABLE not in _gates()
    _short(manager, person)
    assert _line(2026, 10, person).payable < 0
    assert _gates()[selectors.NEGATIVE_PAYABLE] == "block"
    with pytest.raises(services.PayrollGateError):
        _approve(manager)


def _approve_with_the_old_engine(manager: User, monkeypatch: pytest.MonkeyPatch) -> PayrollRun:
    """Ekim'i 2026.2 motoruyla onaylar: hesap YG'yi bilmez, saklı satırda yarım gün alanları yoktur
    (2. adımdan önce onaylanmış ay gibi)."""
    original = selectors._month_input

    def old_input(*args: Any, **kwargs: Any) -> payroll.MonthInput:
        found = original(*args, **kwargs)
        return replace(found, days=tuple(replace(day, short_day=False) for day in found.days))

    with monkeypatch.context() as patch:
        patch.setattr(payroll, "ENGINE_VERSION", "2026.2")
        patch.setattr(selectors, "_month_input", old_input)
        run = _approve(manager)
    for slip in PayrollSlip.objects.filter(approval__run=run):
        line = {
            key: value
            for key, value in slip.line.items()
            if key not in ("short_days", "short_day_deduction")
        }
        PayrollSlip.objects.filter(pk=slip.pk).update(line=line)
    return run


def test_month_approved_with_the_old_engine_keeps_its_outputs(
    manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026.2 ile onaylanmış ay değişmez: saklı satırda kesinti yok; pusula, liste, icmal ve Excel
    yeni satır ya da sütun içermez. Yeniden açılınca canlı hesap kesintiyi alır."""
    person = _person(manager)
    _short(manager, person)
    run = _approve_with_the_old_engine(manager, monkeypatch)
    month = selectors.payroll_month(2026, 10)
    assert month.approved and month.approval is not None
    assert month.approval.engine_version == "2026.2"
    row = month.rows[0]
    assert (row.line.short_days, row.line.short_day_deduction) == (0, D(0))
    assert row.line.gross_total == D("45000.00")
    assert pdf.payslip_lines(row)["earnings"] == [
        ("Normal ücret", "30 gün", "45.000,00"),
        ("Brüt toplam", "", "45.000,00"),
    ]
    assert not any("Yarım gün" in label for label, _ in pdf.payslip_days(row))
    assert pdf.register_rows(month)[0][1][2] == "Normal 45.000,00"
    assert not any("Yarım gün" in label for label, _ in pdf.summary_rows(month)[0][1])
    columns, rows, _ = _bordro(month)
    assert columns == exports.payroll_columns(short=False)
    assert not set(SHORT_COLUMNS) & set(columns)
    assert len(columns) == len(exports.payroll_columns()) - 2
    # Değişiklik öncesi sıra: gün sütunlarından sonra aylık brüt, normal ücretten sonra fazla mesai.
    assert columns[columns.index("Fiilen çalışılan gün") + 1] == "Aylık brüt ücret (TL)"
    assert columns[columns.index("Normal ücret (TL)") + 1] == "Fazla mesai iş günü (TL)"
    # Veri satırları da başlık kadar geniştir (kişi ve Genel toplam).
    filled = [row for row in rows if row and row[1]]
    assert len(filled) >= 2 and all(len(row) == len(columns) for row in filled)
    data = dict(zip(columns, filled[0], strict=False))
    assert _number(data["Normal ücret (TL)"]) == D("45000.00")

    services.reopen_payroll_month(manager, run, "yarım gün")
    line = _line(2026, 10, person)
    assert (line.short_days, line.short_day_deduction) == (1, D("750.00"))
    assert line.gross_total == D("44250.00")
    assert set(SHORT_COLUMNS) <= set(_bordro(selectors.payroll_month(2026, 10))[0])


def test_engine_version_comparison() -> None:
    """Sürümler sayısal karşılaştırılır ("2026.10" > "2026.3")."""
    assert exports._engine_version("2026.10") > exports._engine_version("2026.3")
    assert exports._engine_version("2026.2") < exports.SHORT_DAY_ENGINE
    assert exports._engine_version(payroll.ENGINE_VERSION) == exports.SHORT_DAY_ENGINE
    assert exports._engine_version("bozuk") == ()


# --- çıktılar -------------------------------------------------------------------------------------


def test_outputs_of_a_month_with_a_short_day(
    manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pusulada gün ve kesinti satırı, listede kısa satır (açıklaması işaretlerde), icmalde sayı ve
    tutar; YG'siz kişide satır yok. Onaylı (2026.3) ayın çıktıları aynıdır."""
    person = _person(manager)
    other = _person(manager, "Can Ak", employee_no="S-2")
    _short(manager, person)
    run = _approve(manager)
    assert run.current is not None and run.current.engine_version == "2026.3"
    month = selectors.payroll_month(2026, 10)
    rows = {row.employee.pk: row for row in month.rows}
    row = rows[person.pk]
    earnings = pdf.payslip_lines(row)["earnings"]
    assert earnings[:2] == [
        ("Normal ücret", "30 gün", "45.000,00"),
        ("Yarım gün kesintisi", "1 gün", "−750,00"),
    ]
    assert earnings[-1] == ("Brüt toplam", "", "44.250,00")
    days = pdf.payslip_days(row)
    assert days[2:4] == [
        ("Fiilen çalışılan gün", str(row.line.worked_days)),
        ("Yarım gün çalışılan (YG)", "1 gün"),
    ]
    assert ("SGK gün", "30") in days and ("Ücretli gün (30 gün usulü)", "30") in days
    plain = rows[other.pk]
    assert [label for label, _, _ in pdf.payslip_lines(plain)["earnings"]] == [
        "Normal ücret",
        "Brüt toplam",
    ]
    assert not any("Yarım gün" in label for label, _ in pdf.payslip_days(plain))

    register = {cells[0].split("\n")[0]: cells for _, cells in pdf.register_rows(month)}
    assert register["Ali Kaya"][2] == "Normal 45.000,00\nYG −750,00"
    assert register["Can Ak"][2] == "Normal 45.000,00"
    assert register["Genel toplam"][2] == "Normal 90.000,00\nYG −750,00"
    assert register["Genel toplam"][3] == "89.250,00"
    summary = pdf.summary_rows(month)[0][1]
    labels = [label for label, _ in summary]
    assert labels[1:5] == [
        "SGK gün toplamı",
        "Yarım gün çalışılan (YG) toplamı",
        "Normal ücret",
        "Yarım gün kesintisi",
    ]
    assert dict(summary)["Yarım gün kesintisi"] == "−750,00"
    assert dict(summary)["Yarım gün çalışılan (YG) toplamı"] == "1"

    texts: list[str] = []
    real = pdf.Paragraph

    def spy(text: str, *args: Any, **kwargs: Any) -> Any:
        texts.append(text)
        return real(text, *args, **kwargs)

    monkeypatch.setattr(pdf, "Paragraph", spy)
    pdf.register_pdf(month)
    assert any("YG: yarım gün kesintisi" in text for text in texts)
    texts.clear()
    content = pdf.payslips_pdf(month, employee_id=person.pk)
    assert content.count(b"/Type /Page") - content.count(b"/Type /Pages") == 1
    assert any("Yarım gün kesintisi" in text for text in texts)


def test_register_cell_fits_the_short_form() -> None:
    """Liste PDF'inin Kazançlar hücresi 29 mm: kalın toplam satırında "YG −123.456,78" sığar."""
    pdf.register_fonts()
    assert pdf.REGISTER_WIDTHS[2] == 29
    text = f"YG −{pdf._money(D('123456.78'))}"
    assert text == "YG −123.456,78"
    assert stringWidth(text, pdf.FONT_BOLD, 6.5) <= 29 * mm - 4


def test_payroll_excel_columns_with_a_short_day(manager: User) -> None:
    """Excel Bordro sayfası: YG sayısı "Fiilen çalışılan gün" yanında (para biçimi yok, genel
    toplamda toplanır), kesinti normal ücretin ardından eksi; kazanç sütunlarının yatay toplamı
    brüt toplamdır."""
    person = _person(manager)
    _person(manager, "Can Ak", employee_no="S-2")
    _short(manager, person)
    services.set_attendance_day(
        manager, person, date(2026, 10, 6), status=S.WORKED, overtime_hours=D("2")
    )
    services.add_payroll_item(
        manager,
        {
            "employee": person,
            "year": 2026,
            "month": 10,
            "category": C.PREMIUM,
            "description": "",
            "amount": D("1000"),
        },
    )
    columns, rows, (sheet, first) = _bordro(selectors.payroll_month(2026, 10))
    assert columns == exports.payroll_columns()
    worked = columns.index("Fiilen çalışılan gün")
    assert columns[worked + 1 : worked + 3] == [exports.SHORT_DAYS_HEADER, "Aylık brüt ücret (TL)"]
    normal = columns.index("Normal ücret (TL)")
    assert columns[normal + 1] == exports.SHORT_DAY_DEDUCTION_HEADER
    data = {row[1]: dict(zip(columns, row, strict=True)) for row in rows if row and row[1]}
    mine, total = data["Ali Kaya"], data["Genel toplam"]
    assert mine[exports.SHORT_DAYS_HEADER] == 1 and total[exports.SHORT_DAYS_HEADER] == 1
    assert data["Can Ak"][exports.SHORT_DAYS_HEADER] == 0
    assert _number(mine[exports.SHORT_DAY_DEDUCTION_HEADER]) == D("-750")
    assert _number(total[exports.SHORT_DAY_DEDUCTION_HEADER]) == D("-750")
    assert _number(data["Can Ak"][exports.SHORT_DAY_DEDUCTION_HEADER]) == 0
    gross = columns.index("Brüt toplam (TL)")
    for values in (mine, total):
        earnings = sum((_number(values[name] or 0) for name in columns[normal:gross]), D(0))
        assert earnings == _number(values["Brüt toplam (TL)"])
    count = sheet.cell(row=first, column=worked + 2)
    deduction = sheet.cell(row=first, column=normal + 2)
    assert count.number_format != exports.MONEY_FORMAT
    assert deduction.number_format == exports.MONEY_FORMAT


# --- mali müşavirdeki kişi ve API -----------------------------------------------------------------


def test_external_person_shows_only_the_count_in_the_register_note(
    manager: User, client_for: Callable[..., APIClient]
) -> None:
    """Bordrosu mali müşavirde olan kişide ERP kesinti tutarı göstermez: liste PDF'inin mali
    müşavir bölümünde yalnızca YG sayısı notu; toplamlara ve Excel Bordro sayfasına girmez."""
    person = _person(manager)
    external = employee(manager, employee_no="S-2", full_name="Can Kaya", payroll_external=True)
    services.set_external_payroll(
        manager, external, 2026, 10, gross_total=D("40000"), employer_cost=D("48000")
    )
    _short(manager, external)
    month = selectors.payroll_month(2026, 10)
    assert pdf.external_rows(month) == [
        ["Can Kaya\nS-2 · Dolum", "40.000,00", "48.000,00", EXTERNAL_NOTE]
    ]
    assert month.total("short_day_deduction") == D(0)
    _, rows, _ = _bordro(month)
    assert not any(row and row[1] == "Can Kaya" for row in rows)

    _short(manager, person)
    body = client_for("yonetim").get(f"{BASE}/payroll/2026/10/").json()
    line = next(row["line"] for row in body["rows"] if row["employee"]["id"] == person.pk)
    assert (line["salary"], line["short_days"], line["short_day_deduction"]) == (
        "45000.00",
        1,
        "750.00",
    )
    assert line["gross_total"] == "44250.00"
    totals = body["totals"]
    assert (totals["salary"], totals["short_day_deduction"]) == ("45000.00", "750.00")
    assert totals["computed_gross_total"] == "44250.00"
    assert totals["gross_total"] == "84250.00"  # mali müşavir rakamı dahil
