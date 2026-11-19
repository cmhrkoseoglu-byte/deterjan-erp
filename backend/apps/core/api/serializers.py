from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core import security
from apps.core.models import AccessOverride, Attachment, AuditLog, User
from apps.core.roles import ALL_ROLES

HEALTH_STATES = ["ok", "error"]


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=HEALTH_STATES)
    db = serializers.ChoiceField(choices=HEALTH_STATES)
    redis = serializers.ChoiceField(choices=HEALTH_STATES)


class SiteInfoSerializer(serializers.Serializer):
    """Giriş öncesi de okunan ortam bilgisi."""

    training_mode = serializers.BooleanField(help_text="Eğitim ortamı (demo veri) mı?")


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

    Güvenlik alanları (Faz 5): `otp_enabled`, `password_change_required` (yöneticinin verdiği
    geçici şifreyle girdi; SPA önce şifre değiştirmeye götürür), `otp_setup_required` (rol 2FA
    istiyor, kurulmamış; SPA Güvenlik sayfasına yönlendirir), `field_device` (bu tarayıcı saha
    tableti) ve `idle_timeout_seconds` (hareketsizlik süresi).

    Yetki alanları (docs/plan/kisi-yetkileri.md §5.9): `is_admin` (admin rolü ya da süper
    kullanıcı) ve `access` (bölüm → "rvca" harfleri: r kayıtları okur, v görür, c değiştirir,
    a onaylar; yetkisi olmayan bölüm yazılmaz).

    `account_type`: `staff` (çalışan), `customer_portal` ya da `supplier_portal`; portal
    kullanıcısında `access` boştur ve SPA portal düzenini açar
    (docs/plan/musteri-siparis-takibi.md §4.2)."""

    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_admin = serializers.BooleanField(read_only=True)
    access = serializers.SerializerMethodField()
    account_type = serializers.SerializerMethodField()
    otp_enabled = serializers.SerializerMethodField()
    password_change_required = serializers.BooleanField(
        source="must_change_password", read_only=True
    )
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
            "is_admin",
            "access",
            "account_type",
            "otp_enabled",
            "password_change_required",
            "otp_setup_required",
            "field_device",
            "idle_timeout_seconds",
        ]
        read_only_fields = fields

    @extend_schema_field(
        {"type": "object", "additionalProperties": {"type": "string", "pattern": "^r?v?c?a?$"}}
    )
    @extend_schema_field(
        serializers.ChoiceField(choices=["staff", "customer_portal", "supplier_portal"])
    )
    def get_account_type(self, obj: User) -> str:
        return obj.account_type or "staff"

    def get_access(self, obj: User) -> dict[str, str]:
        if obj.is_portal:
            return {}
        return obj.access.letters()

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
            "must_change_password",
            "last_login",
            "date_joined",
            "is_locked",
            "otp_enabled",
            "personal_counts",
        ]
        read_only_fields = fields

    is_locked = serializers.SerializerMethodField()
    otp_enabled = serializers.SerializerMethodField()
    personal_counts = serializers.SerializerMethodField()

    def get_is_locked(self, obj: User) -> bool:
        return bool(getattr(obj, "is_locked_now", False))

    def get_otp_enabled(self, obj: User) -> bool:
        return bool(getattr(obj, "has_otp", False))

    def get_roles(self, obj: User) -> list[str]:
        # prefetch_related("groups") ile ek sorgu üretmez.
        return sorted(group.name for group in obj.groups.all())

    @extend_schema_field(
        {
            "type": "object",
            "properties": {"granted": {"type": "integer"}, "revoked": {"type": "integer"}},
            "required": ["granted", "revoked"],
        }
    )
    def get_personal_counts(self, obj: User) -> dict[str, int]:
        """Etkin kişiye özel ayar sayıları (etkisizler dahil; `UserViewSet.get_queryset`)."""
        return {
            "granted": int(getattr(obj, "granted_count", 0) or 0),
            "revoked": int(getattr(obj, "revoked_count", 0) or 0),
        }


class UserCreateSerializer(serializers.Serializer):
    """Yeni kullanıcı (yalnızca admin). Şifre girilmez; sistem geçici şifre üretir. Kullanıcı adı
    kuralı ve tekilliği servis katmanında denetlenir (`core.services.create_user`)."""

    username = serializers.CharField(label="Kullanıcı adı", max_length=150)
    full_name = serializers.CharField(label="Ad soyad", max_length=150)
    email = serializers.EmailField(label="E-posta", required=False, allow_blank=True, default="")
    phone = serializers.CharField(
        label="Telefon", max_length=32, required=False, allow_blank=True, default=""
    )
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ALL_ROLES), required=False, default=list
    )


class UserUpdateSerializer(serializers.Serializer):
    """Kullanıcı bilgisi güncelleme (yalnızca gönderilen alanlar değişir). Kullanıcı adı
    değiştirilemez; roller Yetkiler ekranında gerekçeyle değişir (`PUT /users/{pk}/access/`)."""

    full_name = serializers.CharField(label="Ad soyad", max_length=150, required=False)
    email = serializers.EmailField(label="E-posta", required=False, allow_blank=True)
    phone = serializers.CharField(label="Telefon", max_length=32, required=False, allow_blank=True)


class IssuedPasswordSerializer(serializers.Serializer):
    """Yeni kullanıcı ya da şifre sıfırlama yanıtı: geçici şifre yalnızca bu yanıtta görünür."""

    user = UserSerializer()
    temporary_password = serializers.CharField()


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


# --- kişiye özel yetkiler (docs/plan/kisi-yetkileri.md §5.10, §6; critic §4) --------------------

LETTERS_HELP = "Bölüm → harfler: r kayıtları okur, v görür, c değiştirir, a onaylar."
# Bir kayıtta gönderilebilecek en çok satır: her bölümün üç düzeyi ve açık kayıt satırları
# (yaklaşık 240) için pay bırakır; sınırsız liste satır kilidi altında sınırsız iş olurdu.
MAX_OVERRIDES = 400
ACCESS_WARNING_CODES = [
    "coverage_gap",
    "task_not_routed",
    "no_role_no_tasks",
    "segregation",
    "kvkk_role_removed",
    "admin_granted",
    "user_inactive",
    "sensitive_without_otp",
    "open_records_closed",
    "dependent_dropped",
    "override_ineffective",
]


def _letters_field() -> serializers.DictField:
    return serializers.DictField(child=serializers.CharField(), help_text=LETTERS_HELP)


class AccessOverrideSpecSerializer(serializers.Serializer):
    """İstenen kişiye özel ayar: bölüm, düzey, etki (`grant` eklendi, `revoke` kaldırıldı)."""

    key = serializers.CharField(label="Yetki", max_length=64)
    level = serializers.ChoiceField(label="Düzey", choices=AccessOverride.Level.choices)
    effect = serializers.ChoiceField(label="Değişiklik", choices=AccessOverride.Effect.choices)


class AccessCellSerializer(serializers.Serializer):
    key = serializers.CharField()
    level = serializers.CharField()


class UserAccessUpdateSerializer(serializers.Serializer):
    """Yetkiler kaydı: istenen etkin kişiye özel ayarların tam listesi (`overrides`), isteğe bağlı
    roller (verilmezse değişmez), gerekçe ve ekran açıldığındaki sürüm belirteci. `dry_run` hiçbir
    şey yazmadan özeti ve uyarıları döner."""

    version = serializers.CharField(label="Sürüm", max_length=64)
    dry_run = serializers.BooleanField(label="Deneme hesabı", default=False)
    note = serializers.CharField(
        label="Gerekçe", max_length=1000, required=False, allow_blank=True, default=""
    )
    roles = serializers.ListField(child=serializers.ChoiceField(choices=ALL_ROLES), required=False)
    overrides = serializers.ListField(
        child=AccessOverrideSpecSerializer(), allow_empty=True, max_length=MAX_OVERRIDES
    )


class AccessTargetSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    full_name = serializers.CharField()
    is_active = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    otp_enabled = serializers.BooleanField()


class AccessOverrideRowSerializer(serializers.Serializer):
    """Etkin kişiye özel ayar (gerekçesiyle; yalnız admin görür)."""

    id = serializers.IntegerField()
    key = serializers.CharField()
    level = serializers.CharField()
    effect = serializers.CharField()
    note = serializers.CharField()
    created_at = serializers.DateTimeField()
    created_by_name = serializers.CharField(allow_null=True)
    known = serializers.BooleanField(help_text="Bölüm ve düzey katalogda var mı?")
    ineffective = serializers.BooleanField(help_text="Ayar hiçbir şeyi değiştirmiyor mu?")


class UserAccessSerializer(serializers.Serializer):
    """Kişinin yetki matrisi (Sistem › Kullanıcılar › Yetkiler)."""

    user = AccessTargetSerializer()
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_admin = serializers.BooleanField()
    is_self = serializers.BooleanField()
    version = serializers.CharField()
    catalog_hash = serializers.CharField()
    default = _letters_field()
    effective = _letters_field()
    overrides = AccessOverrideRowSerializer(many=True)
    open_records_effects = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="Modül → açık kayıtlar kapatılınca etkilenen öteki ekranlar.",
    )


class AccessRoleChangeSerializer(serializers.Serializer):
    before = serializers.ListField(child=serializers.CharField())
    after = serializers.ListField(child=serializers.CharField())


class AccessEndedOverrideSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    key = serializers.CharField()
    level = serializers.CharField()
    effect = serializers.CharField()
    reason = serializers.CharField(help_text="Bitiş nedeni (AccessOverride.EndReason).")


class AccessOverrideChangesSerializer(serializers.Serializer):
    created = AccessOverrideSpecSerializer(many=True)
    ended = AccessEndedOverrideSerializer(many=True)


class AccessDiffSerializer(serializers.Serializer):
    before = _letters_field()
    after = _letters_field()
    granted = AccessCellSerializer(many=True)
    removed = AccessCellSerializer(many=True)


class AccessWarningSerializer(serializers.Serializer):
    code = serializers.ChoiceField(choices=ACCESS_WARNING_CODES)
    text = serializers.CharField()


class UserAccessResultSerializer(serializers.Serializer):
    """Yetkiler kaydının özeti (deneme hesabı ve kayıt aynı biçimde). `matrix` yalnız kaydedilince
    dolu: yeni sürüm belirteciyle güncel matris."""

    dry_run = serializers.BooleanField()
    changed = serializers.BooleanField()
    saved = serializers.BooleanField()
    roles = serializers.SerializerMethodField()
    overrides = AccessOverrideChangesSerializer()
    access = AccessDiffSerializer()
    warnings = AccessWarningSerializer(many=True)
    matrix = UserAccessSerializer(allow_null=True)

    @extend_schema_field(AccessRoleChangeSerializer())
    def get_roles(self, obj: dict[str, Any]) -> dict[str, list[str]]:
        """Roller önce ve sonra."""
        return dict(AccessRoleChangeSerializer(obj["roles"]).data)


class AccessHistoryLineSerializer(serializers.Serializer):
    """Geçmiş satırı: `granted` eklendi, `revoked` kaldırıldı, `ended` bitti (nedeniyle)."""

    kind = serializers.CharField()
    key = serializers.CharField()
    level = serializers.CharField()
    effect = serializers.CharField(required=False)
    reason = serializers.CharField(required=False)
    reason_label = serializers.CharField(required=False)


class AccessHistoryEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    timestamp = serializers.DateTimeField()
    actor_name = serializers.CharField(allow_null=True)
    note = serializers.CharField()
    roles = serializers.SerializerMethodField()
    lines = AccessHistoryLineSerializer(many=True)

    @extend_schema_field(AccessRoleChangeSerializer(allow_null=True))
    def get_roles(self, obj: dict[str, Any]) -> dict[str, list[str]] | None:
        """Roller önce ve sonra; bu kayıtta değişmediyse `null`."""
        value = obj["roles"]
        return None if value is None else dict(AccessRoleChangeSerializer(value).data)


class MyAccessEntrySerializer(serializers.Serializer):
    key = serializers.CharField()
    level = serializers.CharField()
    source = serializers.CharField(  # type: ignore[assignment]  # alan adı, Field.source değil
        help_text="everyone, any_role, role ya da granted"
    )
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    implied = serializers.BooleanField()


class MyRevokedSerializer(serializers.Serializer):
    key = serializers.CharField()
    level = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)


class MyAccessSerializer(serializers.Serializer):
    """Yetkilerim: yetkinin kaynağı ve kişiden kaldırılanlar (gerekçe, değiştiren ve tarih
    yoktur)."""

    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    is_admin = serializers.BooleanField()
    entries = MyAccessEntrySerializer(many=True)
    revoked = MyRevokedSerializer(many=True)


class AccessReportQuerySerializer(serializers.Serializer):
    user = serializers.IntegerField(label="Kullanıcı", min_value=1, required=False)


class AccessHoldersQuerySerializer(serializers.Serializer):
    key = serializers.CharField(label="Yetki", max_length=64)
    level = serializers.ChoiceField(label="Düzey", choices=AccessOverride.Level.choices)


class AccessPersonalSerializer(serializers.Serializer):
    key = serializers.CharField()
    level = serializers.CharField()
    effect = serializers.CharField()
    ineffective = serializers.BooleanField()


class AccessRiskyPairSerializer(serializers.Serializer):
    a = AccessCellSerializer()
    b = AccessCellSerializer()
    sources = serializers.CharField(help_text="ör. role+granted")
    text = serializers.CharField()


class AccessUserBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    full_name = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)


class AccessReportUserSerializer(AccessUserBriefSerializer):
    is_admin = serializers.BooleanField()
    access = _letters_field()
    personal = AccessPersonalSerializer(many=True)
    risky_pairs = AccessRiskyPairSerializer(many=True)


class AccessReportSerializer(serializers.Serializer):
    """Kim neyi görür: etkin kullanıcıların geçerli yetkileri."""

    catalog_hash = serializers.CharField()
    generated_at = serializers.DateTimeField()
    users = AccessReportUserSerializer(many=True)


class AccessHolderSerializer(serializers.Serializer):
    user = AccessUserBriefSerializer()
    source = serializers.CharField(  # type: ignore[assignment]  # alan adı, Field.source değil
        help_text="everyone, any_role, role, granted, implied, admin ya da revoked"
    )
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    segregation = serializers.ListField(child=serializers.CharField())


class AccessHoldersSerializer(serializers.Serializer):
    """Kimde var: hücreyi taşıyan etkin kişiler ve kaynakları."""

    key = serializers.CharField()
    level = serializers.CharField()
    holders = AccessHolderSerializer(many=True)
