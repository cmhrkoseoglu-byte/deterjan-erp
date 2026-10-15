from typing import Any

from django.contrib.contenttypes.models import ContentType
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import AuditLog, User

HEALTH_STATES = ["ok", "error"]


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=HEALTH_STATES)
    db = serializers.ChoiceField(choices=HEALTH_STATES)
    redis = serializers.ChoiceField(choices=HEALTH_STATES)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(label="Kullanıcı adı", max_length=150)
    password = serializers.CharField(
        label="Şifre", max_length=128, trim_whitespace=False, style={"input_type": "password"}
    )


class MeSerializer(serializers.ModelSerializer):
    """Giriş yapmış kullanıcı. Biçim docs/DECISIONS.md'deki auth sözleşmesindedir."""

    roles = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "email", "roles", "is_superuser"]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "email",
            "phone",
            "roles",
            "is_active",
            "is_superuser",
            "last_login",
            "date_joined",
        ]
        read_only_fields = fields

    def get_roles(self, obj: User) -> list[str]:
        # prefetch_related("groups") ile ek sorgu üretmez.
        return sorted(group.name for group in obj.groups.all())


@extend_schema_field(OpenApiTypes.STR)
class ContentTypeField(serializers.RelatedField):
    """İçerik türünü `"app_label.model"` biçiminde gösterir (ör. `"core.user"`)."""

    def to_representation(self, value: Any) -> str:
        content_type: ContentType = value
        return f"{content_type.app_label}.{content_type.model}"


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    content_type = ContentTypeField(read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "timestamp",
            "actor",
            "actor_name",
            "action",
            "content_type",
            "object_id",
            "object_repr",
            "changes",
            "ip_address",
            "note",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj: AuditLog) -> str | None:
        return str(obj.actor) if obj.actor else None
