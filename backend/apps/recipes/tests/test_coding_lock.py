"""Reçete kodu kilidi: kayıt açıldıktan sonra kodu yalnızca admin değiştirir (API)."""

import pytest

from apps.core.coding.services import CODE_LOCK_MESSAGE
from apps.core.roles import ADMIN, LABORATUVAR, PLANLAMA
from apps.recipes.tests.factories import RecipeFactory

pytestmark = pytest.mark.django_db


def test_only_admin_changes_recipe_code(client_for):
    recipe = RecipeFactory(code="REC001")
    url = f"/api/v1/recipes/recipes/{recipe.pk}/"
    for role in (PLANLAMA, LABORATUVAR):
        denied = client_for(role).patch(url, {"code": "REC-0000001"}, format="json")
        assert denied.status_code == 403
        assert denied.json() == {"code": "permission_denied", "detail": CODE_LOCK_MESSAGE}
    # Yazma rolü kodu değiştirmeden öteki alanları düzenler.
    renamed = client_for(PLANLAMA).patch(url, {"name": "Yeni ad"}, format="json")
    assert renamed.status_code == 200, renamed.json()
    assert renamed.json()["code"] == "REC001"
    allowed = client_for(ADMIN).patch(url, {"code": "REC-0000001"}, format="json")
    assert allowed.status_code == 200, allowed.json()
    assert (allowed.json()["code"], allowed.json()["former_codes"]) == ("REC-0000001", ["REC001"])
