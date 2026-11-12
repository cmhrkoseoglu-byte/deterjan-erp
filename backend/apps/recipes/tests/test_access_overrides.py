"""Kişiye özel ayarla reçeteler (docs/plan/kisi-yetkileri.md §10, 2. adım): Açık kayıtlar
kapatılınca üretim emri formunun reçete seçimi sade listeyle açık kalır; sürüm onayı kendi
düzeyine bağlıdır."""

from collections.abc import Callable
from typing import cast

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, READ
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.recipes import services
from apps.recipes.models import Recipe, RecipeLine, RecipeVersion
from apps.recipes.tests.factories import RecipeFactory, RecipeLineFactory, RecipeVersionFactory

pytestmark = pytest.mark.django_db
RECIPES = reverse("recipes:recipe-list")
CHOICE_FIELDS = {
    "id",
    "code",
    "former_codes",
    "name",
    "product",
    "product_code",
    "product_name",
    "approved_version",
}


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_closed_recipes_still_offer_a_plain_choice_list(make_user: Callable[..., User]) -> None:
    recipe = cast(Recipe, RecipeFactory())
    closed = api(override(make_user("uretim"), "recipes.open_records", READ))

    listing = closed.get(RECIPES)
    assert listing.status_code == 200, listing.json()
    [row] = listing.json()["results"]
    assert set(row) == CHOICE_FIELDS
    assert row["id"] == recipe.pk
    assert closed.get(reverse("recipes:recipe-detail", args=[recipe.pk])).status_code == 403

    [full] = api(make_user("uretim")).get(RECIPES).json()["results"]
    assert "notes" in full and "latest_version_no" in full


def test_version_approval_follows_its_level(make_user: Callable[..., User]) -> None:
    version = cast(RecipeVersion, RecipeVersionFactory())
    RecipeLineFactory(version=version)
    planner = override(make_user("planlama"), "recipes.recipes", APPROVE)
    detail = reverse("recipes:version-detail", args=[version.pk])

    assert api(planner).get(detail).json()["can_approve"] is False
    approve = api(planner).post(reverse("recipes:version-approve", args=[version.pk]))
    assert approve.status_code == 403
    assert approve.json()["required"] == [{"key": "recipes.recipes", "level": "approve"}]
    with pytest.raises(MissingAccess):
        services.approve_version(planner, version)

    lab = make_user("laboratuvar")
    assert api(lab).post(reverse("recipes:version-approve", args=[version.pk])).status_code == 200


def test_editing_needs_change_while_approval_stays_with_approve(
    make_user: Callable[..., User],
) -> None:
    version = cast(RecipeVersion, RecipeVersionFactory())
    line = cast(RecipeLine, RecipeLineFactory(version=version))
    planner = api(override(make_user("planlama"), "recipes.recipes", CHANGE))

    edit_line = planner.patch(
        reverse("recipes:line-detail", args=[line.pk]), {"quantity": "5"}, format="json"
    )
    assert edit_line.status_code == 403
    copy = planner.post(reverse("recipes:version-copy", args=[version.pk]), {"note": "x"})
    assert copy.status_code == 403
    approve = planner.post(reverse("recipes:version-approve", args=[version.pk]))
    assert approve.status_code == 200, approve.json()
