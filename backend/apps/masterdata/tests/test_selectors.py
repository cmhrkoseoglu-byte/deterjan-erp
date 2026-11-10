"""Ana veri seçicileri."""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.masterdata import selectors
from apps.masterdata.models import Material, MaterialUnitConversion, RetiredGtin
from apps.masterdata.tests.factories import MaterialFactory, unit

pytestmark = pytest.mark.django_db


def test_gtin_owner_matches_the_14_digit_form_of_product_and_case_gtins():
    product = MaterialFactory.create(material_type=Material.Type.FINISHED, gtin="8690000000012")
    case = MaterialUnitConversion.objects.create(
        material=product, unit=unit("KOLI"), factor_to_base=12, gtin="18690000000019"
    )
    assert selectors.gtin_owner("08690000000012") == (product, None)
    assert selectors.gtin_owner("8690000000012") == (product, None)
    assert selectors.gtin_owner("18690000000019") == (product, case)
    assert selectors.gtin_owner("8690000000029") == (None, None)
    assert selectors.gtin_owner("") == (None, None)


def test_gtin_is_unique_in_its_14_digit_form():
    MaterialFactory.create(gtin="8690000000012")
    with pytest.raises(IntegrityError), transaction.atomic():
        MaterialFactory.create(gtin="08690000000012")


def test_retired_gtin_is_found_in_its_14_digit_form():
    material = MaterialFactory.create(material_type=Material.Type.FINISHED, gtin="8690000000012")
    conversion = MaterialUnitConversion.objects.create(
        material=material, unit=unit("KOLI"), factor_to_base=Decimal("12"), gtin="28690000000016"
    )
    # Eski koli GTIN'i GTIN-13 olarak girilmişti; arşivde 14 haneli normal biçimde durur.
    retired = RetiredGtin.objects.create(
        conversion=conversion,
        gtin="08690000000029",
        factor_to_base=Decimal("6"),
        replaced_by="28690000000016",
    )
    assert selectors.retired_gtin("8690000000029") == retired
    assert selectors.retired_gtin(" 08690000000029 ") == retired
    found = selectors.retired_gtin("08690000000029")
    assert found is not None and found.conversion.material == material
    assert found.conversion.unit.code == "KOLI"
    for other in ("", "8690000000012", "28690000000016", "abc", "٨٦٩٠٠٠٠٠٠٠٠٢٩", "1" * 15):
        assert selectors.retired_gtin(other) is None
