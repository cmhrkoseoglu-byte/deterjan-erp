from typing import Any, ClassVar

from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from apps.core.admin import AuditedAdminMixin, ReadOnlyAdmin
from apps.masterdata import services
from apps.masterdata.models import (
    Customer,
    Equipment,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    RetiredGtin,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)


class MasterDataAdmin(AuditedAdminMixin, admin.ModelAdmin):
    """Yönetim paneli: kayıtlar denetim günlüğüne yazılır, silinemez (pasife alınır)."""

    search_fields = ("code", "name")
    readonly_fields: ClassVar[tuple[str, ...]] = (
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    )


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
    fields = ("unit", "factor_to_base", "gtin", "is_active")
    # Koli GTIN'i yalnızca uygulamadan girilir (biçim, tekillik ve kilit kuralları serviste).
    readonly_fields = ("gtin",)
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
    # GTIN yalnızca uygulamadan girilir: panel kaydı servis kurallarını (kontrol hanesi, ürün ve
    # koli GTIN'lerinde tekillik, lotu olan malzemede kilit) atlar.
    readonly_fields = (*MasterDataAdmin.readonly_fields, "gtin")
    inlines = [MaterialUnitConversionInline]

    def get_readonly_fields(self, request: HttpRequest, obj: Model | None = None) -> Any:
        # Lotu olan malzemenin türü panelden de değişmez (servis kuralı `material_type_locked`;
        # panel kaydı servisleri atlar).
        fields = super().get_readonly_fields(request, obj)
        if isinstance(obj, Material) and services.material_has_lots(obj):
            return (*fields, "material_type")
        return fields


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


@admin.register(RetiredGtin)
class RetiredGtinAdmin(ReadOnlyAdmin):
    """Eski koli GTIN'leri salt okunur: değiştirilmez, silinmez."""

    list_display = ("gtin", "conversion", "factor_to_base", "replaced_by", "created_at")
    search_fields = ("gtin", "replaced_by", "conversion__material__code")
