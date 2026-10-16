from django.contrib import admin

from apps.ops.models import BackupRun, CheckState


@admin.register(BackupRun)
class BackupRunAdmin(admin.ModelAdmin):
    list_display = ["kind", "run_id", "status", "offsite", "finished_at", "rows"]
    list_filter = ["kind", "status", "offsite"]
    readonly_fields = [f.name for f in BackupRun._meta.fields]

    def has_add_permission(self, request):  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(CheckState)
class CheckStateAdmin(admin.ModelAdmin):
    list_display = ["code", "failing", "since", "last_alert_at", "detail"]
    readonly_fields = ["code", "failing", "since", "last_alert_at", "detail"]
