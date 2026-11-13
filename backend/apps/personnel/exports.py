"""Personel Excel çıktıları (openpyxl): puantaj (aylık tablo ve toplamlar, günlük fazla mesai,
günlük çalışma saatleri, kodlar) ve ön bordro (bordro, işveren maliyeti, karşılaştırma, eksik gün,
parametreler)."""

import io
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from apps.core.coding.outputs import document_control
from apps.core.xlsx import apply_document_control
from apps.personnel import selectors
from apps.personnel.models import (
    ATTENDANCE_CODES,
    DEDUCTION_CATEGORIES,
    EXTRA_CATEGORIES,
    SHORT_DAY_CODE,
    AttendanceStatus,
    PayrollItemCategory,
    PayrollItemKind,
)
from apps.personnel.pdf import (
    ATTENDANCE_OUTPUT,
    DRAFT,
    PAYROLL_OUTPUT,
    PRELIMINARY_NOTE,
    SUPERSEDED,
    document_date,
    parameter_line,
    row_order,
    status_line,
)
from apps.personnel.selectors import (
    AttendanceCell,
    AttendanceDay,
    AttendanceGrid,
    PayrollMonth,
    PayrollRow,
)

WEEKDAYS = ("Pt", "Sa", "Ça", "Pe", "Cu", "Ct", "Pz")
PERSON_HEADERS = ("Sicil no", "Ad soyad", "Birim")
REST_FILL = PatternFill("solid", fgColor="EEEEEE")
HOLIDAY_FILL = PatternFill("solid", fgColor="FDE2E1")
OVERTIME_HEADERS = (
    (AttendanceStatus.WORKED, "FM iş günü"),
    (AttendanceStatus.WEEKLY_REST, "FM hafta tatili"),
    (AttendanceStatus.PUBLIC_HOLIDAY, "FM resmi tatil"),
)


HALF_HOLIDAY_CODE = "Ç½"
WORKED_HOURS_HEADER = "Çalışılan saat (FM hariç)"
SHORT_DAY_LEGEND = (
    "Yarım gün çalıştı (yönetimce yarım gün sayıldı). Ç toplamına girmez; çalışılan gün = Ç + YG. "
    "ERP ön bordrosunda bu günler için kesinti henüz hesaplanmaz."
)
WORKED_HOURS_LEGEND = (
    "Fazla mesai hariçtir. Saat girilmeyen gün günün çalışma saatiyle, yarım gün tatilde öğleden "
    "sonra da çalışılan gün günlük çalışma saatinin tamamıyla sayılır."
)


def _cell_code(cell: AttendanceCell, day: AttendanceDay) -> str:
    """Günün kodu; yarım gün tatilde öğleden sonra da çalışılan gün "Ç½", yarım gün çalışılan gün
    "YG" (`cell.code`)."""
    if cell.holiday_half_worked and day.half_day:
        return HALF_HOLIDAY_CODE
    return cell.code


def _daily_hours_legend(grid: AttendanceGrid) -> str:
    """Ayın günlük çalışma saati, "Kodlar" sayfası için: "9 saat (yarım gün tatilde 4,5)"."""
    daily = grid.daily_hours
    if daily is None:
        return "bu ay onaylanırken kayıtlı değildi" if grid.approved else "belirlenmedi"
    half = selectors.half_holiday_hours(daily)
    return (
        f"{selectors.format_hours(daily)} saat (yarım gün tatilde {selectors.format_hours(half)})"
    )


def _title(grid: AttendanceGrid) -> str:
    if grid.approved and grid.record is not None:
        return f"Puantaj — {grid.label} (onaylı, {grid.record.number})"
    return f"Puantaj — {grid.label} (taslak)"


def _day_header(day: AttendanceDay) -> str:
    return f"{day.date.day} {WEEKDAYS[day.weekday]}"


def _fill(day: AttendanceDay) -> PatternFill | None:
    if day.holiday is not None:
        return HOLIDAY_FILL
    return REST_FILL if day.rest else None


def _sheet(ws: Worksheet, grid: AttendanceGrid, headers: Sequence[str]) -> None:
    """Başlık satırı, sütun genişlikleri ve tatil sütunlarının rengi (veri eklendikten sonra)."""
    for cell in ws[2]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    first_day = len(PERSON_HEADERS) + 1
    for index, header in enumerate(headers, start=1):
        width = 5 if first_day <= index < first_day + len(grid.days) else max(10, len(header) + 2)
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.column_dimensions["B"].width = 26
    for offset, day in enumerate(grid.days):
        fill = _fill(day)
        if fill is None:
            continue
        for (cell,) in ws.iter_rows(
            min_row=2, min_col=first_day + offset, max_col=first_day + offset
        ):
            cell.fill = fill
    ws.freeze_panes = ws.cell(row=3, column=first_day)


def attendance_xlsx(grid: AttendanceGrid) -> bytes:
    """Aylık puantaj: "Puantaj" (günlük kodlar ve toplamlar), "Fazla mesai" (günlük saat),
    "Çalışma saatleri" (günlük çalışılan saat, fazla mesai hariç) ve "Kodlar" (kod açıklamaları,
    ayın günlük çalışma saati ve tatilleri)."""
    workbook = Workbook()
    ws = workbook.active
    assert ws is not None
    ws.title = "Puantaj"
    statuses = list(AttendanceStatus)
    # Ç sütunu tam gün çalışılan günleri sayar; yarım gün (YG) hemen ardındaki sütundadır.
    others = [status for status in statuses if status != AttendanceStatus.WORKED]
    headers = [
        *PERSON_HEADERS,
        *(_day_header(day) for day in grid.days),
        ATTENDANCE_CODES[AttendanceStatus.WORKED],
        SHORT_DAY_CODE,
        *(ATTENDANCE_CODES[status] for status in others),
        "Eksik gün",
        *(label for _, label in OVERTIME_HEADERS),
        "FM toplam",
        WORKED_HOURS_HEADER,
    ]
    ws.append([_title(grid)])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(headers)
    for row in grid.rows:
        person = row.employee
        totals = row.totals
        ws.append(
            [
                person.employee_no,
                person.full_name,
                person.department,
                *(_cell_code(cell, day) for cell, day in zip(row.cells, grid.days, strict=True)),
                totals.full_days,
                totals.short_days,
                *(totals.days[status] for status in others),
                totals.missing_days,
                *(totals.overtime[status] for status, _ in OVERTIME_HEADERS),
                totals.overtime_total,
                totals.hours,
            ]
        )
    _sheet(ws, grid, headers)

    overtime = workbook.create_sheet("Fazla mesai")
    overtime_headers = [*PERSON_HEADERS, *(_day_header(day) for day in grid.days), "Toplam"]
    overtime.append([f"Fazla mesai (saat) — {grid.label}"])
    overtime["A1"].font = Font(bold=True, size=12)
    overtime.append(overtime_headers)
    for row in grid.rows:
        person = row.employee
        overtime.append(
            [
                person.employee_no,
                person.full_name,
                person.department,
                *(cell.overtime_hours or None for cell in row.cells),
                row.totals.overtime_total,
            ]
        )
    _sheet(overtime, grid, overtime_headers)

    hours = workbook.create_sheet("Çalışma saatleri")
    hours_headers = [*PERSON_HEADERS, *(_day_header(day) for day in grid.days), "Toplam"]
    hours.append([f"Çalışma saatleri (saat, fazla mesai hariç) — {grid.label}"])
    hours["A1"].font = Font(bold=True, size=12)
    hours.append(hours_headers)
    for row in grid.rows:
        person = row.employee
        hours.append(
            [
                person.employee_no,
                person.full_name,
                person.department,
                *(cell.day_hours for cell in row.cells),
                row.totals.hours,
            ]
        )
    _sheet(hours, grid, hours_headers)

    legend = workbook.create_sheet("Kodlar")
    legend.append(["Kod", "Durum"])
    for status in statuses:
        legend.append([ATTENDANCE_CODES[status], status.label])
    legend.append([HALF_HOLIDAY_CODE, "Yarım gün tatilde öğleden sonra da çalıştı"])
    legend.append([SHORT_DAY_CODE, SHORT_DAY_LEGEND])
    legend.append(["Günlük çalışma saati", _daily_hours_legend(grid)])
    legend.append(["Çalışılan saat", WORKED_HOURS_LEGEND])
    legend.append([])
    legend.append(["Tarih", "Resmi tatil"])
    for cell in legend[legend.max_row]:
        cell.font = Font(bold=True)
    for day in grid.days:
        if day.holiday is not None:
            suffix = " (yarım gün)" if day.half_day else ""
            legend.append([f"{day.date:%d.%m.%Y}", f"{day.holiday_name}{suffix}"])
    legend.column_dimensions["A"].width = 22
    legend.column_dimensions["B"].width = 40
    for cell in legend[1]:
        cell.font = Font(bold=True)
    record = grid.record
    approved_on = (
        timezone.localtime(record.approved_at).date()
        if grid.approved and record is not None and record.approved_at
        else None
    )
    apply_document_control(workbook, document_control(ATTENDANCE_OUTPUT, on=approved_on))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- ön bordro (docs/DECISIONS.md "Personel bordrosu") -------------------------------------------

MONEY_FORMAT = "#,##0.00"
DRAFT_NOTE = (
    "TASLAK: bordro onaylanmadı; rakamlar puantaj, ücret, parametre ve mali müşavir rakamları "
    "değiştikçe değişebilir."
)
SUPERSEDED_NOTE = (
    "GEÇERSİZ: bu onay bordro yeniden açılınca geçersiz oldu. Ayın geçerli rakamları yeniden "
    "açılmamış (geçerli) onaydadır; ay yeniden onaylanmadıysa rakamlar taslak hesaptır."
)


def _stamp_notes(stamp: str) -> list[str]:
    if stamp == DRAFT:
        return [DRAFT_NOTE]
    return [SUPERSEDED_NOTE] if stamp == SUPERSEDED else []


def _titled(text: str, stamp: str) -> str:
    """ "Bordro — Ekim 2026 (ön bordro · TASLAK)"."""
    return f"{text} (ön bordro{f' · {stamp}' if stamp else ''})"


EMPLOYER_COST_COLUMNS = (
    "Sicil no",
    "Ad soyad",
    "Birim",
    "SGK gün",
    "Brüt toplam (TL)",
    "SGK matrahı (TL)",
    "SGK işveren (TL)",
    "Teşvik (TL)",
    "İşsizlik işveren (TL)",
    "Alt sınır farkı (TL)",
    "İşverene maliyet (TL)",
    "Not",
)


def _header(ws: Worksheet, title: str, lines: Sequence[str], columns: Sequence[str]) -> None:
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=12)
    for line in lines:
        ws.append([line])
    ws.append([])
    ws.append(list(columns))
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    # Hücre açmadan (yoksa sonraki satır bir aşağı kayar) başlığın altını dondurur.
    ws.freeze_panes = f"C{ws.max_row + 1}"


def _money_columns(ws: Worksheet, first: int, last: int, start_row: int) -> None:
    for row in ws.iter_rows(min_row=start_row, min_col=first, max_col=last):
        for cell in row:
            cell.number_format = MONEY_FORMAT


def _employer_cost_sheet(
    ws: Worksheet, month: PayrollMonth, notes: Sequence[str], *, stamp: str
) -> None:
    ws.title = "İşveren maliyeti"
    _header(
        ws,
        _titled(f"İşveren maliyeti — {month.label}", stamp),
        [*_stamp_notes(stamp), status_line(month), parameter_line(month), *notes],
        EMPLOYER_COST_COLUMNS,
    )
    first_data = ws.max_row + 1
    for row in sorted(month.rows, key=row_order):
        person = row.person
        if row.external:
            figure = row.figure
            ws.append(
                [
                    person.employee_no,
                    person.full_name,
                    person.department,
                    None,
                    figure.gross_total if figure else None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    figure.employer_cost if figure else None,
                    "Bordrosu mali müşavirde" + ("" if figure else ": rakam girilmedi"),
                ]
            )
            continue
        line = row.line
        ws.append(
            [
                person.employee_no,
                person.full_name,
                person.department,
                line.sgk_days,
                line.gross_total,
                line.sgk_base,
                line.employer_sgk_gross,
                -line.incentive,
                line.employer_unemployment,
                line.floor_gap,
                line.employer_cost,
                "",
            ]
        )
    ws.append(
        [
            "",
            "Genel toplam",
            "",
            None,
            month.gross_total,
            month.total("sgk_base"),
            month.total("employer_sgk_gross"),
            -month.total("incentive"),
            month.total("employer_unemployment"),
            month.total("floor_gap"),
            month.employer_cost,
            "",
        ]
    )
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    _money_columns(ws, 5, 11, first_data)
    for index, header in enumerate(EMPLOYER_COST_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(12, len(header) + 2)
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["L"].width = 34


def _parameters_sheet(ws: Worksheet, month: PayrollMonth, *, stamp: str) -> None:
    settings = month.settings
    params = settings.params
    record = settings.record
    rows: list[tuple[str, Any]] = [
        ("Kaynak", record.source if record and record.source else ""),
        ("Asgari ücret (aylık brüt, TL)", params.minimum_wage),
        ("SGK günlük alt sınır (TL)", params.daily_floor),
        ("SGK günlük üst sınır (TL)", params.daily_ceiling),
        ("SGK üst sınır çarpanı", params.ceiling_multiplier),
        ("SGK işçi payı (%)", params.employee_sgk_rate),
        ("İşsizlik işçi payı (%)", params.employee_unemployment_rate),
        ("SGK işveren payı (%)", params.employer_sgk_rate),
        ("SGK işveren teşviki (puan)", params.incentive_points),
        ("İşsizlik işveren payı (%)", params.employer_unemployment_rate),
        ("Etkin işveren oranı (%)", params.employer_rate),
        ("Damga vergisi (binde)", params.stamp_tax_per_mille),
        *(
            (f"Gelir vergisi {index}. dilim üst sınırı (TL)", limit)
            for index, limit in enumerate(params.tax_brackets, start=1)
        ),
        *(
            (f"Gelir vergisi {index}. dilim oranı (%)", rate)
            for index, rate in enumerate(params.tax_rates, start=1)
        ),
        ("Asgari ücret istisna matrahı (TL)", params.exemption_base),
        ("BES katkı payı (%)", params.bes_rate),
        ("Nakit yemek SGK istisnası (günlük TL)", params.meal_exemption_daily),
    ]
    ws.append(["Bordro parametreleri", month.label + (f" · {stamp}" if stamp else "")])
    ws["A1"].font = Font(bold=True, size=12)
    for label, value in rows:
        ws.append([label, value])
        if isinstance(value, Decimal):
            ws.cell(row=ws.max_row, column=2).number_format = "#,##0.00##"
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 60


WARNING_TEXTS = {
    selectors.MISSING_WAGE: "ücret eksik",
    selectors.BELOW_MINIMUM_WAGE: "asgari ücretin altında",
    selectors.EXIT_IN_MONTH: "ay içinde çıkış",
    selectors.PAY_WITHOUT_SGK_DAYS: "SGK günü yok",
    selectors.OPENING_MISSING: "devir eksik",
    selectors.CARRY_INCOMPLETE: "zincir eksik",
    selectors.NEGATIVE_PAYABLE: "ödenecek negatif",
    selectors.CEILING_WITH_BONUS: "tavanı aşan prim/ikramiye",
    selectors.EXTERNAL_MISSING: "rakam girilmedi",
}
DIFF_FILL = PatternFill("solid", fgColor="FDE2E1")
CATEGORY_LABELS = dict(PayrollItemCategory.choices)


def _category_totals(row: PayrollRow, kind: str) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for item in row.items:
        if item.kind == kind:
            totals[item.category] = totals.get(item.category, Decimal(0)) + item.amount
    return totals


def _warnings_text(row: PayrollRow) -> str:
    return ", ".join(WARNING_TEXTS.get(code, code) for code in row.warnings)


PAYROLL_LINE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("salary", "Normal ücret (TL)"),
    ("overtime_worked_pay", "Fazla mesai iş günü (TL)"),
    ("overtime_rest_pay", "Fazla mesai hafta tatili (TL)"),
    ("holiday_pay", "Resmî tatil (TL)"),
)
PAYROLL_TAX_COLUMNS: tuple[tuple[str, str], ...] = (
    ("gross_total", "Brüt toplam (TL)"),
    ("meal_exemption", "Nakit yemek SGK istisnası (TL)"),
    ("sgk_base", "SGK matrahı (TL)"),
    ("employee_sgk", "SGK işçi (TL)"),
    ("employee_unemployment", "İşsizlik işçi (TL)"),
    ("tax_base", "GV matrahı (TL)"),
    ("cumulative_tax_base_before", "Kümülatif GV matrahı önceki (TL)"),
    ("cumulative_tax_base_after", "Kümülatif GV matrahı bu ay dahil (TL)"),
    ("income_tax_computed", "Hesaplanan GV (TL)"),
    ("income_tax_exemption", "Asgari ücret GV istisnası (TL)"),
    ("income_tax", "Kesilen GV (TL)"),
    ("exemption_base_before", "Asgari ücret istisna matrahı önceki (TL)"),
    ("exemption_base_added", "Asgari ücret istisna matrahı eklenen (TL)"),
    ("stamp_tax_computed", "Hesaplanan DV (TL)"),
    ("stamp_tax_exemption", "Asgari ücret DV istisnası (TL)"),
    ("stamp_tax", "Kesilen DV (TL)"),
    ("net_pay", "Net ücret (TL)"),
    ("bes_deduction", "BES (TL)"),
)
PAYROLL_EMPLOYER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("payable", "Ödenecek (TL)"),
    ("employer_sgk_gross", "SGK işveren (TL)"),
    ("incentive", "Teşvik (TL)"),
    ("employer_unemployment", "İşsizlik işveren (TL)"),
    ("floor_gap", "Alt sınır farkı (TL)"),
    ("employer_cost", "İşverene maliyet (TL)"),
)


def payroll_columns() -> list[str]:
    """Bordro sayfasının sütunları (ek ödeme ve kesinti kategorileri ayrı sütunlarda)."""
    return [
        "Sicil no",
        "Ad soyad",
        "Birim",
        "TC kimlik no (maskeli)",
        "SGK gün",
        "Ücretli gün",
        "Fiilen çalışılan gün",
        "Aylık brüt ücret (TL)",
        *(label for _, label in PAYROLL_LINE_COLUMNS),
        *(f"{CATEGORY_LABELS[code]} (TL)" for code in EXTRA_CATEGORIES),
        *(label for _, label in PAYROLL_TAX_COLUMNS),
        *(f"{CATEGORY_LABELS[code]} (TL)" for code in DEDUCTION_CATEGORIES),
        *(label for _, label in PAYROLL_EMPLOYER_COLUMNS),
        "Devir ayı",
        "Devir GV matrahı (TL)",
        "Devir istisna ay",
        "Uyarılar",
    ]


def _payroll_values(rows: Sequence[PayrollRow], person: Any = None) -> list[Any]:
    def total(name: str) -> Decimal:
        return sum((getattr(row.line, name) for row in rows), Decimal(0))

    def categories(kind: str, codes: Sequence[str]) -> list[Decimal]:
        found: dict[str, Decimal] = {}
        for row in rows:
            for code, amount in _category_totals(row, kind).items():
                found[code] = found.get(code, Decimal(0)) + amount
        return [found.get(code, Decimal(0)) for code in codes]

    single = rows[0] if person is not None else None
    line = single.line if single else None
    opening = single.opening if single else None
    return [
        *(person or ["", "Genel toplam", "", ""]),
        sum(row.line.sgk_days for row in rows),
        line.paid_days if line else None,
        line.worked_days if line else None,
        line.monthly_wage if line else None,
        *(total(name) for name, _ in PAYROLL_LINE_COLUMNS),
        *categories(PayrollItemKind.EXTRA, EXTRA_CATEGORIES),
        *(total(name) for name, _ in PAYROLL_TAX_COLUMNS),
        *categories(PayrollItemKind.DEDUCTION, DEDUCTION_CATEGORIES),
        *(total(name) for name, _ in PAYROLL_EMPLOYER_COLUMNS),
        selectors.month_label(opening.year, opening.month) if opening else "",
        opening.tax_base if opening else None,
        opening.exemption_months if opening else None,
        _warnings_text(single) if single else "",
    ]


def _payroll_sheet(ws: Worksheet, month: PayrollMonth, notes: Sequence[str], *, stamp: str) -> None:
    ws.title = "Bordro"
    columns = payroll_columns()
    external = sum(1 for row in month.rows if row.external)
    lines = [
        *_stamp_notes(stamp),
        status_line(month),
        parameter_line(month),
        'Kümülatif GV matrahı "bu ay dahil" mali müşavir bordrolarındaki kümülatiftir; devir, '
        "kişinin zincirinin çapasıdır.",
        *(
            [
                f"Bordrosu mali müşavirde olan {external} kişi bu sayfada yok (İşveren maliyeti "
                "sayfasında)."
            ]
            if external
            else []
        ),
        *notes,
    ]
    _header(ws, _titled(f"Bordro — {month.label}", stamp), lines, columns)
    header_row = ws.max_row
    first_data = header_row + 1
    rows = sorted(month.computed, key=row_order)
    for row in rows:
        person = row.person
        ws.append(
            _payroll_values(
                [row],
                [
                    person.employee_no,
                    person.full_name,
                    person.department,
                    person.masked_national_id,
                ],
            )
        )
    if rows:
        ws.append(_payroll_values(rows))
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
    money_first = columns.index("Aylık brüt ücret (TL)") + 1
    money_last = columns.index("İşverene maliyet (TL)") + 1
    _money_columns(ws, money_first, money_last, first_data)
    _money_columns(ws, len(columns) - 2, len(columns) - 2, first_data)
    for index, header in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(10, min(len(header) + 2, 28))
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions[get_column_letter(len(columns))].width = 40
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(columns))}{ws.max_row}"


COMPARE_FIELDS: tuple[tuple[str, str], ...] = (
    ("sgk_days", "SGK gün"),
    ("gross_total", "Brüt toplam"),
    ("employee_sgk", "SGK işçi"),
    ("employee_unemployment", "İşsizlik işçi"),
    ("tax_base", "GV matrahı"),
    ("cumulative_tax_base_after", "Kümülatif GV matrahı"),
    ("income_tax", "Kesilen GV"),
    ("stamp_tax", "Kesilen DV"),
    ("net_pay", "Net ücret"),
    ("payable", "Ödenecek"),
    ("employer_cost", "İşverene maliyet"),
)


def _compare_sheet(ws: Worksheet, month: PayrollMonth, *, stamp: str) -> None:
    """Mali müşavirle kalem kalem karşılaştırma: her kalem için ERP, mali müşavir (boş; rakamlar
    yapıştırılır) ve fark (formül; 0,01'den büyük fark kırmızı)."""
    columns = ["Sicil no", "Ad soyad"]
    for _, label in COMPARE_FIELDS:
        columns += [f"{label} ERP", f"{label} mali müşavir", f"{label} fark"]
    _header(
        ws,
        f"Karşılaştırma — {month.label}{f' ({stamp})' if stamp else ''}",
        [
            'Mali müşavirin bordrosundaki rakamları "mali müşavir" sütunlarına yapıştırın; fark '
            "kendiliğinden hesaplanır.",
        ],
        columns,
    )
    first_data = ws.max_row + 1
    rows = sorted(month.computed, key=row_order)
    for offset, row in enumerate(rows):
        number = first_data + offset
        values: list[Any] = [row.person.employee_no, row.person.full_name]
        for index, (name, _) in enumerate(COMPARE_FIELDS):
            erp = get_column_letter(3 + index * 3)
            theirs = get_column_letter(4 + index * 3)
            values += [
                getattr(row.line, name),
                None,
                f'=IF({theirs}{number}="","",{theirs}{number}-{erp}{number})',
            ]
        ws.append(values)
    if not rows:
        return
    last = ws.max_row
    for index in range(len(COMPARE_FIELDS)):
        diff = get_column_letter(5 + index * 3)
        ws.conditional_formatting.add(
            f"{diff}{first_data}:{diff}{last}",
            FormulaRule(
                formula=[f"AND(ISNUMBER({diff}{first_data}),ABS({diff}{first_data})>0.01)"],
                fill=DIFF_FILL,
            ),
        )
        if index:  # SGK gün tam sayıdır
            _money_columns(ws, 3 + index * 3, 5 + index * 3, first_data)
    for index, header in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(10, min(len(header) + 2, 24))
    ws.column_dimensions["B"].width = 26


# SGK eksik gün neden kodları (e-Bildirge): rapor 01, devamsızlık 15, ücretsiz izin 21; ayda birden
# çok neden 12.
MISSING_DAY_REASONS: tuple[tuple[str, str, str], ...] = (
    (AttendanceStatus.SICK_LEAVE, "01", "İstirahat (rapor)"),
    (AttendanceStatus.UNPAID_LEAVE, "21", "Diğer ücretsiz izin"),
    (AttendanceStatus.ABSENT, "15", "Devamsızlık"),
)
MISSING_DAY_COLUMNS = (
    "Sicil no",
    "Ad soyad",
    "Birim",
    "Bordro",
    "SGK gün",
    "İşe giriş (ay içinde)",
    "Çıkış (ay içinde)",
    "Rapor (gün)",
    "Ücretsiz izin (gün)",
    "Devamsızlık (gün)",
    "Eksik gün (puantaj)",
    "Neden kodu",
    "Neden",
    "Günler",
    "Bildirgede eksik gün",
)


def _runs(days: Sequence[Any]) -> list[str]:
    """Ardışık günleri aralıklara toplar: "03–05.10, 12.10"."""
    spans: list[list[Any]] = []
    for day in sorted(days):
        if spans and (day - spans[-1][1]).days == 1:
            spans[-1][1] = day
        else:
            spans.append([day, day])
    return [selectors.day_span(first, last) for first, last in spans]


def _missing_days_sheet(ws: Worksheet, month: PayrollMonth, *, stamp: str) -> None:
    """Mali müşavire eksik gün bildirimi için: ücretsiz günü ya da ay içinde girişi/çıkışı olan
    herkes (bordrosu mali müşavirde olanlar dahil). Rapor günleri sağlık verisidir. Günler
    puantajdandır (geçersiz onayda bugünkü puantaj)."""
    lines = [
        "Eksik gün sayısı puantajdaki ücretsiz günlerdir; e-Bildirge'deki eksik gün sayısı ve "
        "kodu mali müşavirce belirlenir (ör. 31 çeken ayda 30 güne tamamlanan kişi). Kodlar: "
        "01 istirahat, 15 devamsızlık, 21 diğer ücretsiz izin, 12 birden fazla neden.",
    ]
    if stamp == SUPERSEDED:
        lines.append("Günler bugünkü puantajdandır (onaydan sonra değişmiş olabilir).")
    title = f"Eksik gün — {month.label}{f' ({stamp})' if stamp else ''}"
    _header(ws, title, lines, MISSING_DAY_COLUMNS)
    cells = {row.employee.pk: row.cells for row in month.grid.rows}
    first, last = selectors.month_bounds(month.year, month.month)
    for row in sorted(month.rows, key=row_order):
        person = row.person
        found: dict[str, list[Any]] = {status: [] for status, _, _ in MISSING_DAY_REASONS}
        for cell in cells.get(person.pk, []):
            if cell.status in found and selectors.employed_on(person, cell.date):
                found[cell.status].append(cell.date)
        hired = person.hire_date if person.hire_date and first <= person.hire_date <= last else None
        left = (
            person.termination_date
            if person.termination_date and first <= person.termination_date <= last
            else None
        )
        total = sum(len(days) for days in found.values())
        if not total and not hired and not left:
            continue
        reasons = [(code, name) for status, code, name in MISSING_DAY_REASONS if found[status]]
        if len(reasons) > 1:
            code, name = "12", "Birden fazla: " + ", ".join(name for _, name in reasons)
        elif reasons:
            code, name = reasons[0]
        else:
            code, name = "", ""
        spans = "; ".join(
            f"{name}: {', '.join(_runs(found[status]))}"
            for status, _, name in MISSING_DAY_REASONS
            if found[status]
        )
        if row.external:
            expected = "Mali müşavir belirler"
        elif hired or left:
            expected = "Ay içinde giriş/çıkış: mali müşavir belirler"
        elif row.line.sgk_days < 30:
            expected = "Evet"
        else:
            expected = "Hayır (30 güne tamamlandı)"
        ws.append(
            [
                person.employee_no,
                person.full_name,
                person.department,
                "Mali müşavirde" if row.external else "ERP",
                "—" if row.external else row.line.sgk_days,
                f"{hired:%d.%m.%Y}" if hired else "",
                f"{left:%d.%m.%Y}" if left else "",
                len(found[AttendanceStatus.SICK_LEAVE]),
                len(found[AttendanceStatus.UNPAID_LEAVE]),
                len(found[AttendanceStatus.ABSENT]),
                total,
                code,
                name,
                spans,
                expected,
            ]
        )
    for index, header in enumerate(MISSING_DAY_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(10, len(header) + 2)
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["N"].width = 50


def payroll_xlsx(month: PayrollMonth, *, stamp: str = DRAFT) -> bytes:
    """Ön bordro Excel'i. Brütten nete hesaplanan ayda "Bordro" (kişi başına bütün kalemler),
    "İşveren maliyeti", "Karşılaştırma" (mali müşavirle), "Eksik gün" ve "Parametreler"; başlangıç
    ayından önce "İşveren maliyeti", "Eksik gün" ve "Parametreler". Damga (`stamp`: onaylanmamış
    bordroda "TASLAK", yeniden açılmış onayda "GEÇERSİZ") başlıklarda ve ilk not satırında yazar
    (PDF'teki damganın karşılığı); onaylı ayda damga yoktur, onay bilgisi not satırındadır."""
    workbook = Workbook()
    ws = workbook.active
    assert ws is not None
    produced = f"Üretim zamanı: {timezone.localtime():%d.%m.%Y %H:%M}"
    notes = [PRELIMINARY_NOTE, produced]
    if month.net:
        _payroll_sheet(ws, month, notes, stamp=stamp)
        _employer_cost_sheet(workbook.create_sheet("İşveren maliyeti"), month, notes, stamp=stamp)
        _compare_sheet(workbook.create_sheet("Karşılaştırma"), month, stamp=stamp)
    else:
        _employer_cost_sheet(ws, month, notes, stamp=stamp)
    _missing_days_sheet(workbook.create_sheet("Eksik gün"), month, stamp=stamp)
    _parameters_sheet(workbook.create_sheet("Parametreler"), month, stamp=stamp)
    apply_document_control(workbook, document_control(PAYROLL_OUTPUT, on=document_date(month)))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
