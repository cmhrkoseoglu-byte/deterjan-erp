"""Yönetim paneli: dolum kayıtları yalnızca görüntülenir; değişiklik servislerle (API) yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.filling.models import (
    FillingConsumption,
    FillingOrder,
    FillingRun,
    PackagingPick,
    PackagingSpec,
    ScrapRecord,
)


@admin.register(PackagingSpec)
class PackagingSpecAdmin(ReadOnlyAdmin):
    list_display = ("finished_product", "version_no", "bulk_product", "fill_quantity", "status")
    list_filter = ("status",)
    search_fields = ("finished_product__code", "finished_product__name")
    list_select_related = ("finished_product", "bulk_product")


@admin.register(FillingOrder)
class FillingOrderAdmin(ReadOnlyAdmin):
    list_display = ("number", "finished_product", "planned_units", "planned_date", "status")
    list_filter = ("status",)
    search_fields = ("number", "finished_product__code", "finished_product__name")
    list_select_related = ("finished_product",)


@admin.register(PackagingPick)
class PackagingPickAdmin(ReadOnlyAdmin):
    list_display = ("order", "requirement", "lot", "quantity", "from_location", "picked_at")
    list_select_related = ("order", "lot", "from_location")


@admin.register(FillingRun)
class FillingRunAdmin(ReadOnlyAdmin):
    list_display = ("output_lot", "order", "status", "good_units", "bulk_variance_pct")
    list_filter = ("status",)
    search_fields = ("output_lot__lot_no", "order__number")
    list_select_related = ("order", "output_lot")


@admin.register(FillingConsumption)
class FillingConsumptionAdmin(ReadOnlyAdmin):
    list_display = ("run", "kind", "material", "lot", "quantity", "consumed_at")
    list_filter = ("kind",)
    list_select_related = ("run__output_lot", "material", "lot")


@admin.register(ScrapRecord)
class ScrapRecordAdmin(ReadOnlyAdmin):
    list_display = ("run", "kind", "material", "lot", "quantity", "reason_code", "recorded_at")
    list_filter = ("kind", "reason_code")
    list_select_related = ("run__output_lot", "material", "lot")
