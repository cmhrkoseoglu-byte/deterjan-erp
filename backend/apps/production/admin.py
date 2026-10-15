"""Yönetim paneli: üretim kayıtları yalnızca görüntülenir; değişiklik servislerle (API) yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.production.models import (
    BatchConsumption,
    MaterialPick,
    ProductionBatch,
    ProductionOrder,
    ProductionRequirement,
)


@admin.register(ProductionOrder)
class ProductionOrderAdmin(ReadOnlyAdmin):
    list_display = ("number", "product", "planned_quantity", "unit", "planned_date", "status")
    list_filter = ("status",)
    search_fields = ("number", "product__code", "product__name")
    list_select_related = ("product", "unit")


@admin.register(ProductionRequirement)
class ProductionRequirementAdmin(ReadOnlyAdmin):
    list_display = ("order", "sequence", "material", "required_quantity", "tolerance_pct")
    list_select_related = ("order", "material")


@admin.register(MaterialPick)
class MaterialPickAdmin(ReadOnlyAdmin):
    list_display = ("order", "requirement", "lot", "quantity", "from_location", "picked_at")
    list_select_related = ("order", "lot", "from_location")


@admin.register(ProductionBatch)
class ProductionBatchAdmin(ReadOnlyAdmin):
    list_display = ("batch_no", "order", "equipment", "status", "planned_quantity", "yield_pct")
    list_filter = ("status",)
    search_fields = ("batch_no", "order__number")
    list_select_related = ("order", "equipment")


@admin.register(BatchConsumption)
class BatchConsumptionAdmin(ReadOnlyAdmin):
    list_display = ("batch", "requirement", "lot", "actual_quantity", "deviation_pct", "weighed_at")
    list_select_related = ("batch", "lot")
