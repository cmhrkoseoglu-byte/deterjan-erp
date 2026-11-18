"""`core.xlsx.sheet_text`: kullanıcının yazdığı metin Excel'de formül olmaz."""

import io
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook

from apps.core.xlsx import sheet_text


def _round_trip(value: Any) -> Any:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append([sheet_text(sheet, value)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    loaded = load_workbook(io.BytesIO(buffer.getvalue())).active
    assert loaded is not None
    return loaded.cell(row=1, column=1)


@pytest.mark.parametrize("text", ["=1+1", "+90 555", "-5", "@x", "\tsekme"])
def test_formula_like_text_is_a_text_cell(text: str) -> None:
    cell = _round_trip(text)

    assert (cell.value, cell.data_type, cell.quotePrefix) == (text, "s", True)


def test_text_starting_with_carriage_return_is_a_text_cell() -> None:
    # Dosyada satır başı XML gereği "\n" olarak okunur; hücre yine metindir.
    cell = _round_trip("\rsatır")

    assert (cell.value, cell.data_type, cell.quotePrefix) == ("\nsatır", "s", True)


@pytest.mark.parametrize("value", ["Ali Yılmaz", "", None, 5, Decimal("1.5")])
def test_other_values_are_unchanged(value: Any) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None

    assert sheet_text(sheet, value) is value
