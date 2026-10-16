from rest_framework import serializers

from apps.ops.models import BackupRun


class BackupRunSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    offsite_display = serializers.CharField(source="get_offsite_display", read_only=True)

    class Meta:
        model = BackupRun
        fields = [
            "id",
            "kind",
            "kind_display",
            "run_id",
            "source_run_id",
            "started_at",
            "finished_at",
            "status",
            "status_display",
            "message",
            "database_bytes",
            "media_bytes",
            "media_files",
            "tables",
            "rows",
            "offsite",
            "offsite_display",
            "offsite_message",
            "mismatches",
        ]
        read_only_fields = fields


class CheckSerializer(serializers.Serializer):
    check = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    status = serializers.CharField(help_text="ok, error ya da unknown")
    title = serializers.CharField()
    detail = serializers.CharField()
    since = serializers.DateTimeField(allow_null=True)


class DiskSerializer(serializers.Serializer):
    path = serializers.CharField()
    total_bytes = serializers.IntegerField()
    free_bytes = serializers.IntegerField()
    used_pct = serializers.FloatField()


class SystemStatusSerializer(serializers.Serializer):
    checks = CheckSerializer(many=True)
    disks = DiskSerializer(many=True)
    load_15 = serializers.FloatField(allow_null=True)
    cpu_count = serializers.IntegerField(allow_null=True)
    queue_length = serializers.IntegerField(allow_null=True)
    runs = BackupRunSerializer(many=True)


class OpsHealthSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="ok, error ya da unknown")
    db = serializers.CharField(help_text="ok, error ya da unknown")
    redis = serializers.CharField(help_text="ok, error ya da unknown")
    backup = serializers.CharField(help_text="ok, error ya da unknown")
    restore_test = serializers.CharField(help_text="ok, error ya da unknown")
    celery = serializers.CharField(help_text="ok, error ya da unknown")


class ClientErrorSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=1000)
    stack = serializers.CharField(max_length=8000, required=False, allow_blank=True)
    url = serializers.CharField(max_length=500, required=False, allow_blank=True)
