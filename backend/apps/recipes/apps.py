from django.apps import AppConfig


class RecipesConfig(AppConfig):
    name = "apps.recipes"
    label = "recipes"
    verbose_name = "Reçeteler"

    def ready(self) -> None:
        # Reçete kodu: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_master_code
        from apps.recipes.api.views import RECIPE_WRITE_ROLES

        register_master_code(
            "recipes.recipe",
            label="Reçete",
            model="recipes.recipe",
            default_prefix="REC",
            default_width=7,
            write_roles=RECIPE_WRITE_ROLES,
        )
