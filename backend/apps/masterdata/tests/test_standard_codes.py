"""Standart kod alanları (docs/plan/kodlama-sistematigi.md §6.3): birimde UN/ECE kodu ve sembol,
caride ülke kodu."""

import io

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.hse.models import HazardStatement
from apps.masterdata import importers, services
from apps.masterdata.models import Customer, Material, Supplier, UnitOfMeasure
from apps.masterdata.tests.factories import CustomerFactory, SupplierFactory

pytestmark = pytest.mark.django_db


def test_standard_units_have_unece_codes_and_symbols():
    """Göç, standart birimlere UN/ECE Rec 20 kodunu ve sembolü yazar (koli XCT, palet XPX)."""
    units = {
        code: (unece_code, symbol)
        for code, unece_code, symbol in UnitOfMeasure.objects.values_list(
            "code", "unece_code", "symbol"
        )
    }
    assert {code: units[code] for code in ("KG", "G", "LT", "ML", "ADET", "KOLI", "PALET")} == {
        "KG": ("KGM", "kg"),
        "G": ("GRM", "g"),
        "LT": ("LTR", "L"),
        "ML": ("MLT", "mL"),
        "ADET": ("C62", ""),
        "KOLI": ("XCT", ""),
        "PALET": ("XPX", ""),
    }


def test_partners_default_to_turkey():
    assert SupplierFactory.create().country_code == "TR"
    assert CustomerFactory.create().country_code == "TR"


def test_unit_unece_code_is_upper_case_and_checked(make_user):
    planner = make_user("planlama")
    unit = services.create_record(
        planner,
        UnitOfMeasure,
        {"code": "BIDON", "name": "Bidon", "kind": "COUNT", "unece_code": " xcn ", "symbol": " "},
    )
    assert (unit.unece_code, unit.symbol) == ("XCN", "")
    for wrong in ("K", "KGMX", "K-G", "ĞĞ"):
        with pytest.raises(BusinessRuleError) as exc:
            services.update_record(planner, unit, {"unece_code": wrong})
        assert exc.value.code == "invalid_unece_code"
    assert services.update_record(planner, unit, {"unece_code": ""}).unece_code == ""


@pytest.mark.parametrize("model", [Supplier, Customer])
def test_partner_country_code_is_iso_3166(model, make_user):
    planner = make_user("planlama", "satin_alma", "sevkiyat")
    partner = services.create_record(planner, model, {"code": "C1", "name": "Cari"})
    assert partner.country_code == "TR"
    assert services.update_record(planner, partner, {"country_code": " de "}).country_code == "DE"
    for wrong in ("", "XX", "UK", "TUR"):
        with pytest.raises(BusinessRuleError) as exc:
            services.update_record(planner, partner, {"country_code": wrong})
        assert exc.value.code == "invalid_country_code"
    partner.refresh_from_db()
    assert partner.country_code == "DE"


def test_standard_code_fields_in_the_api(client_for):
    admin = client_for("admin")
    units = admin.get("/api/v1/masterdata/units/", {"page_size": 100}).data["results"]
    kg = next(row for row in units if row["code"] == "KG")
    assert (kg["unece_code"], kg["symbol"]) == ("KGM", "kg")
    supplier = SupplierFactory.create()
    url = f"/api/v1/masterdata/suppliers/{supplier.pk}/"
    response = admin.patch(url, {"country_code": "iq"}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["country_code"] == "IQ"
    response = admin.patch(url, {"country_code": "XX"}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "invalid_country_code"
    customer = CustomerFactory.create()
    response = client_for("depo").patch(
        f"/api/v1/masterdata/customers/{customer.pk}/", {"country_code": "DE"}, format="json"
    )
    assert response.status_code == 403


def test_partner_import_reads_the_country_column(make_user):
    text = "Kod,Ünvan,Ülke kodu\nT1,Alman Kimya,de\nT2,Yerli Kimya,\n"
    importers.run_import(make_user("planlama"), "suppliers", io.BytesIO(text.encode()), "t.csv")
    assert dict(Supplier.objects.values_list("code", "country_code")) == {"T1": "DE", "T2": "TR"}
    report = importers.preview_import(
        "suppliers", io.BytesIO("Kod,Ünvan,Ülke kodu\nT3,Cari,XX\n".encode()), "t.csv"
    ).as_dict()
    assert report["rows"][0]["errors"][0]["column"] == "Ülke kodu"


def test_code_is_normalized_by_its_own_field():
    """Kod alanı kendi kuralıyla düzeltilir: malzeme kodu büyük harf, H/P/EUH kodu harfini korur."""
    assert services.normalized_code(Material, " mlz-1 ") == "MLZ-1"
    assert services.normalized_code(HazardStatement, " H360Fd ") == "H360Fd"
