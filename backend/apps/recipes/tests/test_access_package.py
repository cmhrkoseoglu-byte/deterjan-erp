"""Reçeteler: paket denkliği (docs/plan/kisi-yetkileri.md §3.2 ve §5.5, 3. parça).

Reçeteyi ve sürümlerini bugün planlama ve laboratuvar yazar ve onaylar; plan ikisini ayırır
(Değiştirir ve Onaylar) ama paketi bugünkü gibi ikisini de verir. Okuma giriş yapan herkese açıktır
(açık okuma; üretim emri formunun reçete seçimi dahil, §5.3).

2. adımda modül bölüm denetimine geçti: backend satırlarının `live` bağlantısı kaldırıldı (sabitler
yok); satırlar bugünkü rollerin kataloğa denkliğini kayıt olarak tutar. Ön yüz sabitlerine bağlantı
8. adıma kadar kalır.
"""

from apps.core.access import APPROVE, CHANGE
from apps.core.coding.registry import code_type
from apps.core.tests.access_helpers import SIGNED_IN, Row, assert_rows, level, read
from apps.recipes.access import RECIPES

APPROVER_ROLES = "apps.recipes.services:APPROVER_ROLES"
FRONTEND_WRITE_ROLES = "frontend:src/modules/recipes/config.ts:RECIPE_WRITE_ROLES"
RECIPE_ROLES = ("planlama", "laboratuvar")

ROWS: list[Row] = [
    # --- API okumaları (bugün IsAuthenticated) ---
    Row(
        "api.views.RecipeViewSet okuma (list, retrieve, metadata) ve versions GET",
        SIGNED_IN,
        read(RECIPES),
    ),
    Row(
        "api.views.RECIPE_READ_ACTIONS (RecipeVersionViewSet list, retrieve, metadata, scale)",
        SIGNED_IN,
        read(RECIPES),
    ),
    Row(
        "api.views.RECIPE_READ_ACTIONS (RecipeLineViewSet ve RecipeStepViewSet retrieve)",
        SIGNED_IN,
        read(RECIPES),
    ),
    # --- API ve servis yazmaları ---
    Row(
        "api.views.RECIPE_WRITE_ROLES (RecipeViewSet.write_roles: create, update, "
        "partial_update, activate, deactivate, versions POST)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
    ),
    Row(
        "api.views.RECIPE_WRITE_ROLES (RecipeVersionViewSet update, partial_update, copy, "
        "lines, steps)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
    ),
    Row(
        "api.views.RECIPE_WRITE_ROLES (RecipeVersionViewSet.approve)",
        RECIPE_ROLES,
        level(RECIPES, APPROVE),
    ),
    Row(
        "api.views.RECIPE_WRITE_ROLES (RecipeLineViewSet ve RecipeStepViewSet update, "
        "partial_update, destroy)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
    ),
    Row(
        "api.views.RECIPE_WRITE_ROLES (RecipeImportView: Excel'den taslak)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
    ),
    Row(
        "api.views.RECIPE_WRITE_ROLES (RecipeImportTemplateView: içe aktarma şablonu)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
    ),
    Row(
        "api.views.RECIPE_WRITE_ROLES (apps.py recipes.recipe write_roles: kod önerisi)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
    ),
    Row(
        "services.APPROVER_ROLES (can_approve, approve_version)",
        RECIPE_ROLES,
        level(RECIPES, APPROVE),
    ),
    Row(
        "services.APPROVER_ROLES (api.serializers.RecipeVersionDetailSerializer.can_approve: "
        "Onayla düğmesi)",
        RECIPE_ROLES,
        level(RECIPES, APPROVE),
    ),
    # --- ön yüz ---
    Row(
        "frontend config.ts RECIPE_WRITE_ROLES (RecipeListPage canWrite: yeni reçete, içe aktarma)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
        live=FRONTEND_WRITE_ROLES,
    ),
    Row(
        "frontend config.ts RECIPE_WRITE_ROLES (RecipePage canWrite: düzenle, pasife al, yeni "
        "sürüm)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
        live=FRONTEND_WRITE_ROLES,
    ),
    Row(
        "frontend config.ts RECIPE_WRITE_ROLES (VersionPage canWrite: satır ve adım düzenleme, "
        "kopyala)",
        RECIPE_ROLES,
        level(RECIPES, CHANGE),
        live=FRONTEND_WRITE_ROLES,
    ),
    # Menü ve sayfa korumaları (menuRoles('recipes')) test_access_package_shell.py'dedir.
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_code_type_write_roles_match_today() -> None:
    """Kod önerisinin rolleri kod türü kaydından gelir (live= okuyamaz)."""
    item = code_type("recipes.recipe")
    assert item is not None
    assert item.write_access == (RECIPES.key, CHANGE)
