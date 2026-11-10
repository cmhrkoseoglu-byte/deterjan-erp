"""Test tanımı kodu kilidi (serbest kod): kayıt açıldıktan sonra kodu yalnızca admin değiştirir."""

import pytest

from apps.core.coding.services import CODE_LOCK_MESSAGE
from apps.core.roles import ADMIN, LABORATUVAR
from apps.quality.tests.factories import tdef

pytestmark = pytest.mark.django_db


def test_only_admin_changes_test_definition_code(client_for):
    url = f"/api/v1/quality/tests/{tdef('PH').pk}/"
    denied = client_for(LABORATUVAR).patch(url, {"code": "PH_DEGERI"}, format="json")
    assert denied.status_code == 403
    assert denied.json() == {"code": "permission_denied", "detail": CODE_LOCK_MESSAGE}
    # Laboratuvar kodu değiştirmeden öteki alanları düzenler.
    renamed = client_for(LABORATUVAR).patch(url, {"name": "pH değeri"}, format="json")
    assert renamed.status_code == 200, renamed.json()
    assert renamed.json()["code"] == "PH"
    allowed = client_for(ADMIN).patch(url, {"code": "PH_DEGERI"}, format="json")
    assert allowed.status_code == 200, allowed.json()
    assert (allowed.json()["code"], allowed.json()["former_codes"]) == ("PH_DEGERI", ["PH"])
