"""Barkod okutma eski kodları da tanır (yenilenmemiş raf ve malzeme etiketleri; core.coding)."""

import pytest

from apps.inventory import selectors
from apps.inventory.tests.factories import storage_location
from apps.masterdata import services as masterdata
from apps.masterdata.tests.factories import MaterialFactory

pytestmark = pytest.mark.usefixtures("invariants")


@pytest.fixture
def admin(make_user):
    return make_user("admin")


def test_scan_resolves_former_location_code(admin):
    location = storage_location(code="DENEME-1")
    masterdata.update_record(admin, location, {"code": "LOKASYON-0001"})

    for raw in ("LOC:DENEME-1", "loc:deneme-1", "DENEME-1"):
        result = selectors.decode_scan(raw)
        assert (result.kind, result.location, result.former_code) == (
            "location",
            location,
            "DENEME-1",
        ), raw
        assert result.code == raw
    current = selectors.decode_scan("LOC:LOKASYON-0001")
    assert (current.location, current.former_code) == (location, "")


def test_scan_resolves_former_material_code(admin):
    material = MaterialFactory(code="ESKI-M")
    masterdata.update_record(admin, material, {"code": "MLZ-0000001"})
    result = selectors.decode_scan("MAT:ESKI-M")
    assert (result.kind, result.material, result.former_code) == ("material", material, "ESKI-M")
    assert selectors.decode_scan("ESKI-M").former_code == "ESKI-M"


def test_scan_api_returns_former_code(admin, client_for):
    location = storage_location(code="DENEME-2")
    masterdata.update_record(admin, location, {"code": "LOKASYON-0002"})
    body = client_for("depo").get("/api/v1/inventory/scan/", {"code": "LOC:DENEME-2"}).json()
    assert body["kind"] == "location" and body["former_code"] == "DENEME-2"
    assert body["location"]["code"] == "LOKASYON-0002"
