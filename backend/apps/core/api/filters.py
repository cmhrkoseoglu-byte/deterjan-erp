import django_filters
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet

from apps.core.models import AuditLog, User


class UserFilter(django_filters.FilterSet):
    role = django_filters.CharFilter(field_name="groups__name", label="Rol")

    class Meta:
        model = User
        fields = ["is_active", "role"]


class AuditLogFilter(django_filters.FilterSet):
    content_type = django_filters.CharFilter(
        method="filter_content_type", label="Kayıt türü (ör. core.user)"
    )
    timestamp_after = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="gte")
    timestamp_before = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="lt")

    class Meta:
        model = AuditLog
        fields = ["content_type", "object_id", "actor", "action"]

    def filter_content_type(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        """`"app_label.model"` ya da sayısal kimlik kabul eder; bilinmeyen tür boş sonuç döner."""
        if value.isdigit():
            return queryset.filter(content_type_id=int(value))
        app_label, _, model = value.lower().partition(".")
        try:
            content_type = ContentType.objects.get_by_natural_key(app_label, model)
        except ContentType.DoesNotExist:
            return queryset.none()
        return queryset.filter(content_type=content_type)
