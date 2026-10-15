from django.contrib import admin

from apps.core.admin import AuditedAdminMixin
from apps.masterdata.models import (
    Customer,
    Equipment,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)


class MasterDataAdmin(AuditedAdminMixin, admin.ModelAdmin):
    """Yönetim paneli: kayıtlar denetim günlüğüne yazılır, silinemez (pasife alınır)."""

    search_fields = ("code", "name")
    readonly_fields = ("created_at", "created_by", "updated_at", "updated_by")


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(MasterDataAdmin):
    list_display = ("code", "name", "kind", "factor_to_kind_base", "is_active")
    list_filter = ("kind", "is_active")


@admin.register(MaterialCategory)
class MaterialCategoryAdmin(MasterDataAdmin):
    list_filter = ("is_active",)
    list_display = ("code", "name", "is_active")


class MaterialUnitConversionInline(admin.TabularInline):
    model = MaterialUnitConversion
    fk_name = "material"
    extra = 0
    fields = ("unit", "factor_to_base", "is_active")
    can_delete = False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(Material)
class MaterialAdmin(MasterDataAdmin):
    list_display = ("code", "name", "material_type", "base_unit", "category", "is_active")
    list_filter = ("material_type", "category", "is_hazardous", "is_active")
    list_select_related = ("base_unit", "category")
    inlines = [MaterialUnitConversionInline]


@admin.register(Warehouse)
class WarehouseAdmin(MasterDataAdmin):
    list_filter = ("is_active",)
    list_display = ("code", "name", "is_active")


@admin.register(Location)
class LocationAdmin(MasterDataAdmin):
    list_display = ("code", "name", "warehouse", "location_type", "is_active")
    list_filter = ("location_type", "warehouse", "is_active")


@admin.register(Equipment)
class EquipmentAdmin(MasterDataAdmin):
    list_display = ("code", "name", "equipment_type", "capacity", "capacity_unit", "location")
    list_filter = ("equipment_type", "is_active")


@admin.register(Supplier)
class SupplierAdmin(MasterDataAdmin):
    list_filter = ("is_active",)
    list_display = ("code", "name", "tax_number", "phone", "is_active")


@admin.register(Customer)
class CustomerAdmin(MasterDataAdmin):
    list_filter = ("is_active",)
    list_display = ("code", "name", "tax_number", "phone", "is_active")
