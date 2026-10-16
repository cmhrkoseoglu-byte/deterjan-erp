"""Yönetim paneli: bakım kayıtları yalnızca görüntülenir; değişiklik servislerle yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.maintenance.models import (
    ChangeoverRule,
    Downtime,
    MaintenancePlan,
    MaintenanceWorkOrder,
    WorkOrderPart,
)


@admin.register(MaintenancePlan)
class MaintenancePlanAdmin(ReadOnlyAdmin):
    list_display = ("equipment", "kind", "title", "interval_days", "interval_runs", "next_due_date")
    list_filter = ("kind", "is_active")
    search_fields = ("title", "equipment__code")
    list_select_related = ("equipment",)


@admin.register(MaintenanceWorkOrder)
class MaintenanceWorkOrderAdmin(ReadOnlyAdmin):
    list_display = ("number", "equipment", "kind", "source", "status", "due_date")
    list_filter = ("status", "kind", "source")
    search_fields = ("number", "title", "equipment__code")
    list_select_related = ("equipment",)


@admin.register(WorkOrderPart)
class WorkOrderPartAdmin(ReadOnlyAdmin):
    list_display = ("work_order", "material", "lot", "description", "quantity")
    list_select_related = ("work_order", "material", "lot")


@admin.register(Downtime)
class DowntimeAdmin(ReadOnlyAdmin):
    list_display = ("equipment", "reason", "started_at", "ended_at", "work_order")
    list_filter = ("reason",)
    list_select_related = ("equipment", "work_order")


@admin.register(ChangeoverRule)
class ChangeoverRuleAdmin(ReadOnlyAdmin):
    list_display = ("from_product", "to_product", "is_active")
    list_select_related = ("from_product", "to_product")
