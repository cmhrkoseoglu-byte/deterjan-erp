from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core import security
from apps.core.models import Attachment, AuditLog, User

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
    otp_code = serializers.CharField(
        label="Doğrulama kodu", max_length=16, required=False, allow_blank=True, default=""
    )


class MeSerializer(serializers.ModelSerializer):
    """Giriş yapmış kullanıcı. Biçim docs/DECISIONS.md'deki auth sözleşmesindedir.

    Güvenlik alanları (Faz 5): `otp_enabled`, `otp_setup_required` (rol 2FA istiyor, kurulmamış;
    SPA Güvenlik sayfasına yönlendirir), `field_device` (bu tarayıcı saha tableti) ve
    `idle_timeout_seconds` (hareketsizlik süresi)."""

    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    otp_enabled = serializers.SerializerMethodField()
    otp_setup_required = serializers.SerializerMethodField()
    field_device = serializers.SerializerMethodField()
    idle_timeout_seconds = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "email",
            "roles",
            "is_superuser",
            "otp_enabled",
            "otp_setup_required",
            "field_device",
            "idle_timeout_seconds",
        ]
        read_only_fields = fields

    def _request(self) -> Any:
        request = self.context.get("request")
        return getattr(request, "_request", request)

    def get_otp_enabled(self, obj: User) -> bool:
        return security.otp_enabled(obj)

    def get_otp_setup_required(self, obj: User) -> bool:
        return security.otp_setup_required(obj)

    def get_field_device(self, obj: User) -> bool:
        request = self._request()
        return request is not None and security.is_field_device(request)

    def get_idle_timeout_seconds(self, obj: User) -> int:
        request = self._request()
        if request is None:
            return int(settings.SESSION_IDLE_TIMEOUT_MINUTES) * 60
        return security.idle_timeout_seconds(request)


class SecurityStatusSerializer(serializers.Serializer):
    otp_enabled = serializers.BooleanField()
    otp_required = serializers.BooleanField()
    recovery_codes_remaining = serializers.IntegerField()
    field_device = serializers.BooleanField()
    idle_timeout_seconds = serializers.IntegerField()
    password_help = serializers.ListField(child=serializers.CharField())


class OtpSetupSerializer(serializers.Serializer):
    secret = serializers.CharField()
    uri = serializers.CharField()
    qr_svg = serializers.CharField()


class OtpCodeSerializer(serializers.Serializer):
    code = serializers.CharField(label="Doğrulama kodu", max_length=16)


class RecoveryCodesSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(child=serializers.CharField())


class PasswordConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(label="Şifre", max_length=128, trim_whitespace=False)


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        label="Mevcut şifre", max_length=128, trim_whitespace=False
    )
    new_password = serializers.CharField(label="Yeni şifre", max_length=128, trim_whitespace=False)


class FieldDeviceSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(label="Saha tableti")


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
            "is_locked",
            "otp_enabled",
        ]
        read_only_fields = fields

    is_locked = serializers.SerializerMethodField()
    otp_enabled = serializers.SerializerMethodField()

    def get_is_locked(self, obj: User) -> bool:
        return bool(getattr(obj, "is_locked_now", False))

    def get_otp_enabled(self, obj: User) -> bool:
        return bool(getattr(obj, "has_otp", False))

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


class AttachmentSerializer(serializers.ModelSerializer):
    content_type = ContentTypeField(read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    removed_by_name = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    can_remove = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id",
            "content_type",
            "object_id",
            "kind",
            "kind_display",
            "original_name",
            "size",
            "mime_type",
            "note",
            "is_active",
            "uploaded_by_name",
            "created_at",
            "removed_at",
            "removed_by_name",
            "removal_reason",
            "download_url",
            "can_remove",
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj: Attachment) -> str | None:
        return str(obj.created_by) if obj.created_by_id else None

    def get_removed_by_name(self, obj: Attachment) -> str | None:
        return str(obj.removed_by) if obj.removed_by_id else None

    def get_download_url(self, obj: Attachment) -> str:
        return reverse("core:attachment-download", args=[obj.pk])

    def get_can_remove(self, obj: Attachment) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not obj.is_active or not isinstance(user, User):
            return False
        return user.is_admin or obj.created_by_id == user.pk


class AttachmentUploadSerializer(serializers.Serializer):
    content_type = serializers.CharField(label="Kayıt türü (ör. inventory.lot)", max_length=100)
    object_id = serializers.IntegerField(label="Kayıt no", min_value=1)
    file = serializers.FileField(label="Dosya")
    kind = serializers.ChoiceField(
        choices=Attachment.Kind.choices, default=Attachment.Kind.OTHER, label="Tür"
    )
    note = serializers.CharField(label="Not", max_length=500, required=False, allow_blank=True)


class AttachmentQuerySerializer(serializers.Serializer):
    content_type = serializers.CharField(label="Kayıt türü (ör. inventory.lot)")
    object_id = serializers.IntegerField(label="Kayıt no", min_value=1)
    include_removed = serializers.BooleanField(default=False, required=False)


class AttachmentRemoveSerializer(serializers.Serializer):
    reason = serializers.CharField(label="Neden", max_length=500, required=False, allow_blank=True)
