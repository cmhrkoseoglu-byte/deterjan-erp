import django_filters
from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef, QuerySet

from apps.core.effective_access import active_overrides
from apps.core.models import AuditLog, User


class UserFilter(django_filters.FilterSet):
    role = django_filters.CharFilter(field_name="groups__name", label="Rol")
    has_personal = django_filters.BooleanFilter(
        method="filter_has_personal", label="Kişiye özel yetkisi var"
    )

    class Meta:
        model = User
        fields = ["is_active", "role", "has_personal"]

    def filter_has_personal(self, queryset: QuerySet, name: str, value: bool | None) -> QuerySet:
        """Etkin kişiye özel ayarı (etkisizler dahil) olan ya da olmayan kullanıcılar."""
        if value is None:
            return queryset
        personal = Exists(active_overrides().filter(user=OuterRef("pk")))
        return queryset.filter(personal) if value else queryset.exclude(personal)


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
