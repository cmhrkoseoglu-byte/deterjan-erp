"""Açılış stoku şablonu: örnek satırdaki kodlar kodlama sistematiğinin varsayılan biçiminde."""

import io

import pytest
from openpyxl import load_workbook

from apps.core.coding import formats, registry, selectors
from apps.core.roles import DEPO
from apps.inventory import importers
from apps.inventory.tests.factories import storage_location
from apps.masterdata.tests.factories import MaterialFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]


def example(header):
    sheet = load_workbook(io.BytesIO(importers.build_template())).active
    headers = [cell.value for cell in sheet[1]]
    return sheet.cell(row=2, column=headers.index(header) + 1).value


@pytest.mark.parametrize(
    ("header", "key"),
    [("Malzeme kodu", "masterdata.material"), ("Lokasyon kodu", "masterdata.location")],
)
def test_opening_template_examples_follow_default_formats(header, key):
    item = registry.get_code_type(key)
    fmt = selectors.default_format(item)

    assert formats.master_number(example(header), fmt.prefix, fmt.width) is not None


def test_opening_template_passes_as_is_when_example_records_exist(make_user):
    MaterialFactory(code=example("Malzeme kodu"))
    storage_location(code=example("Lokasyon kodu"))

    report = importers.preview_opening(
        make_user(DEPO), io.BytesIO(importers.build_template()), "sablon.xlsx"
    ).as_dict()

    assert report["file_errors"] == []
    assert report["invalid"] == 0, report["rows"]
