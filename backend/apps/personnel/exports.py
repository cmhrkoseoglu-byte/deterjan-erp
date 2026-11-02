"""Personel Excel çıktıları (openpyxl): puantaj (aylık tablo ve toplamlar, günlük fazla mesai,
kodlar) ve ön bordro (işveren maliyeti, parametreler)."""

import io
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from apps.personnel.models import ATTENDANCE_CODES, AttendanceStatus
from apps.personnel.pdf import PRELIMINARY_NOTE, parameter_line, status_line
from apps.personnel.selectors import AttendanceCell, AttendanceDay, AttendanceGrid, PayrollMonth

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


def _cell_code(cell: AttendanceCell, day: AttendanceDay) -> str:
    """Günün kodu; yarım gün tatilde öğleden sonra da çalışılan gün "Ç½"."""
    if cell.holiday_half_worked and day.half_day:
        return HALF_HOLIDAY_CODE
    return cell.code


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
    """Aylık puantaj: "Puantaj" (günlük kodlar ve toplamlar), "Fazla mesai" (günlük saat) ve
    "Kodlar" (kod açıklamaları ve ayın tatilleri)."""
    workbook = Workbook()
    ws = workbook.active
    assert ws is not None
    ws.title = "Puantaj"
    statuses = list(AttendanceStatus)
    headers = [
        *PERSON_HEADERS,
        *(_day_header(day) for day in grid.days),
        *(ATTENDANCE_CODES[status] for status in statuses),
        "Eksik gün",
        *(label for _, label in OVERTIME_HEADERS),
        "FM toplam",
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
                *(totals.days[status] for status in statuses),
                totals.missing_days,
                *(totals.overtime[status] for status, _ in OVERTIME_HEADERS),
                totals.overtime_total,
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

    legend = workbook.create_sheet("Kodlar")
    legend.append(["Kod", "Durum"])
    for status in statuses:
        legend.append([ATTENDANCE_CODES[status], status.label])
    legend.append([HALF_HOLIDAY_CODE, "Yarım gün tatilde öğleden sonra da çalıştı"])
    legend.append([])
    legend.append(["Tarih", "Resmi tatil"])
    for cell in legend[legend.max_row]:
        cell.font = Font(bold=True)
    for day in grid.days:
        if day.holiday is not None:
            suffix = " (yarım gün)" if day.half_day else ""
            legend.append([f"{day.date:%d.%m.%Y}", f"{day.holiday_name}{suffix}"])
    legend.column_dimensions["A"].width = 12
    legend.column_dimensions["B"].width = 40
    for cell in legend[1]:
        cell.font = Font(bold=True)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- ön bordro (docs/DECISIONS.md "Personel bordrosu") -------------------------------------------

MONEY_FORMAT = "#,##0.00"
DRAFT_NOTE = (
    "TASLAK: bordro onaylanmadı; rakamlar puantaj, ücret, parametre ve mali müşavir rakamları "
    "değiştikçe değişebilir."
)
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
    ws: Worksheet, month: PayrollMonth, notes: Sequence[str], *, draft: bool
) -> None:
    ws.title = "İşveren maliyeti"
    _header(
        ws,
        f"İşveren maliyeti — {month.label} (ön bordro{' · TASLAK' if draft else ''})",
        [*([DRAFT_NOTE] if draft else []), status_line(month), parameter_line(month), *notes],
        EMPLOYER_COST_COLUMNS,
    )
    first_data = ws.max_row + 1
    for row in sorted(month.rows, key=lambda item: (item.employee.department, item.employee.pk)):
        person = row.employee
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


def _parameters_sheet(ws: Worksheet, month: PayrollMonth, *, draft: bool) -> None:
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
    ]
    ws.append(["Bordro parametreleri", month.label + (" · TASLAK" if draft else "")])
    ws["A1"].font = Font(bold=True, size=12)
    for label, value in rows:
        ws.append([label, value])
        if isinstance(value, Decimal):
            ws.cell(row=ws.max_row, column=2).number_format = "#,##0.00##"
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 60


def payroll_xlsx(month: PayrollMonth, *, draft: bool = True) -> bytes:
    """Ön bordro Excel'i: "İşveren maliyeti" (kişi satırları ve genel toplam) ve "Parametreler".
    Onaylanmamış bordroda (`draft`) başlıklarda ve ilk not satırında "TASLAK" yazar (PDF'teki
    damganın karşılığı)."""
    workbook = Workbook()
    ws = workbook.active
    assert ws is not None
    produced = f"Üretim zamanı: {timezone.localtime():%d.%m.%Y %H:%M}"
    _employer_cost_sheet(ws, month, [PRELIMINARY_NOTE, produced], draft=draft)
    _parameters_sheet(workbook.create_sheet("Parametreler"), month, draft=draft)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
