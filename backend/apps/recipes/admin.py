from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.recipes.models import Recipe, RecipeLine, RecipeStep, RecipeVersion


class RecipeLineInline(admin.TabularInline):
    model = RecipeLine
    extra = 0
    fields = (
        "sequence",
        "material",
        "quantity",
        "unit",
        "tolerance_pct",
        "is_water",
        "instruction",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


class RecipeStepInline(admin.TabularInline):
    model = RecipeStep
    extra = 0
    fields = ("sequence", "description", "duration_min", "temperature_c", "mixer_rpm")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(Recipe)
class RecipeAdmin(ReadOnlyAdmin):
    """Reçeteler sürüm kurallarıyla uygulamadan yönetilir; panelde yalnızca görüntülenir."""

    list_display = ("code", "name", "product", "is_active")
    search_fields = ("code", "name")


@admin.register(RecipeVersion)
class RecipeVersionAdmin(ReadOnlyAdmin):
    list_display = ("recipe", "version_no", "status", "batch_size", "batch_unit", "approved_at")
    list_filter = ("status",)
    inlines = [RecipeLineInline, RecipeStepInline]
