"""Yönetim paneli: İSG kayıtları yalnızca görüntülenir; değişiklik servislerle yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.hse.models import (
    HazardStatement,
    Incident,
    MaterialHazard,
    SafetyDataSheet,
    StorageLimit,
    WasteContractor,
    WasteRecord,
)


@admin.register(HazardStatement)
class HazardStatementAdmin(ReadOnlyAdmin):
    list_display = ("code", "kind", "text", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("code", "text")


@admin.register(MaterialHazard)
class MaterialHazardAdmin(ReadOnlyAdmin):
    list_display = ("material", "pictograms", "signal_word")
    search_fields = ("material__code", "material__name")
    list_select_related = ("material",)


@admin.register(SafetyDataSheet)
class SafetyDataSheetAdmin(ReadOnlyAdmin):
    list_display = ("material", "revision_no", "revision_date", "valid_until", "superseded_at")
    search_fields = ("material__code", "material__name", "revision_no")
    list_select_related = ("material",)


@admin.register(StorageLimit)
class StorageLimitAdmin(ReadOnlyAdmin):
    list_display = ("location", "hazard_class", "max_kg", "is_active")
    list_filter = ("hazard_class", "is_active")
    list_select_related = ("location",)


@admin.register(WasteContractor)
class WasteContractorAdmin(ReadOnlyAdmin):
    list_display = ("name", "license_no", "license_valid_until", "is_active")
    search_fields = ("name", "license_no")


@admin.register(WasteRecord)
class WasteRecordAdmin(ReadOnlyAdmin):
    list_display = ("number", "waste_code", "quantity_kg", "contractor", "delivered_on", "status")
    list_filter = ("status", "is_hazardous")
    search_fields = ("number", "waste_code", "description", "document_no")
    list_select_related = ("contractor",)


@admin.register(Incident)
class IncidentAdmin(ReadOnlyAdmin):
    list_display = ("number", "incident_type", "occurred_at", "place", "severity", "status")
    list_filter = ("status", "incident_type", "severity", "injury")
    search_fields = ("number", "place", "description")
