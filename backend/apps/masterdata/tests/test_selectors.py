"""Ana veri seçicileri."""

import pytest
from django.db import IntegrityError, transaction

from apps.masterdata import selectors
from apps.masterdata.models import Material, MaterialUnitConversion
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
