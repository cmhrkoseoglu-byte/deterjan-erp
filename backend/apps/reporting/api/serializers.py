from typing import Any

from rest_framework import serializers

from apps.core.models import User
from apps.reporting import services
from apps.reporting.models import ReportJob


class ExportRequestSerializer(serializers.Serializer):
    file_format = serializers.ChoiceField(choices=ReportJob.Format.choices, label="biçim")


class ReportJobSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    file_format_display = serializers.CharField(source="get_file_format_display", read_only=True)
    can_download = serializers.SerializerMethodField()
    download_required = serializers.SerializerMethodField()

    class Meta:
        model = ReportJob
        fields = [
            "id",
            "report_code",
            "title",
            "file_format",
            "file_format_display",
            "params",
            "status",
            "status_display",
            "file_name",
            "row_count",
            "error",
            "created_at",
            "started_at",
            "finished_at",
            "expires_at",
            "can_download",
            "download_required",
        ]
        read_only_fields = fields

    def get_can_download(self, job: ReportJob) -> bool:
        return job.status == ReportJob.Status.DONE and bool(job.file)

    def get_download_required(self, job: ReportJob) -> list[dict[str, Any]]:
        """Dosyayı indirmek için isteyende artık eksik olan yetkiler (plan §8 madde 12): boşsa
        indirebilir. Ön yüz indirme bağlantısını yalnız boşken gösterir."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not isinstance(user, User):
            return []
        return [
            {"key": key, "level": level}
            for key, level in services.missing_download_access(user, job)
        ]


class ColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    kind = serializers.CharField()


class SummaryItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    kind = serializers.CharField()
    value = serializers.JSONField(allow_null=True)


class ReportInfoSerializer(serializers.Serializer):
    code = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    filters = serializers.ListField(child=serializers.CharField())
    default_days = serializers.IntegerField(allow_null=True)
    columns = ColumnSerializer(many=True)


class ReportPageSerializer(serializers.Serializer):
    code = serializers.CharField()
    title = serializers.CharField()
    columns = ColumnSerializer(many=True)
    summary = SummaryItemSerializer(many=True)
    filters = serializers.DictField()
    count = serializers.IntegerField()
    sync_limit = serializers.IntegerField()
    results = serializers.ListField(child=serializers.DictField())


class DashboardInfoSerializer(serializers.Serializer):
    code = serializers.CharField()
    title = serializers.CharField()
