from django.apps import AppConfig


class RecipesConfig(AppConfig):
    name = "apps.recipes"
    label = "recipes"
    verbose_name = "Reçeteler"

    def ready(self) -> None:
        # Reçete kodu: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.access import CHANGE
        from apps.core.coding.registry import register_master_code
        from apps.masterdata.services import recode_record
        from apps.recipes.access import RECIPES

        register_master_code(
            "recipes.recipe",
            label="Reçete",
            model="recipes.recipe",
            default_prefix="REC",
            default_width=7,
            write_access=(RECIPES.key, CHANGE),
            recode=recode_record,
        )

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        register_output(
            "recipes.template",
            label="Reçeteler",
            group="İçe aktarma şablonları",
            formats=("Excel",),
            suggested_code="FR-SIS-008",
        )
