from django.contrib import admin

from apps.reporting.models import ReportJob


@admin.register(ReportJob)
class ReportJobAdmin(admin.ModelAdmin):
    list_display = ("title", "file_format", "status", "row_count", "created_by", "created_at")
    list_filter = ("status", "file_format", "report_code")
    readonly_fields = [f.name for f in ReportJob._meta.fields]

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
