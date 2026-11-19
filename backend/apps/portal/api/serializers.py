from rest_framework import serializers

from apps.masterdata.models import Customer, Supplier
from apps.portal.models import PortalAccount


class PortalAccountSerializer(serializers.ModelSerializer):
    """Portal hesabı (admin listesi): kullanıcı, bağlı firma ve giriş durumu."""

    kind = serializers.CharField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    password_change_required = serializers.BooleanField(
        source="user.must_change_password", read_only=True
    )
    firm_id = serializers.IntegerField(source="firm.pk", read_only=True)
    firm_code = serializers.CharField(source="firm.code", read_only=True)
    firm_name = serializers.CharField(source="firm.name", read_only=True)
    firm_is_active = serializers.BooleanField(source="firm.is_active", read_only=True)

    class Meta:
        model = PortalAccount
        fields = [
            "id",
            "kind",
            "username",
            "full_name",
            "email",
            "phone",
            "is_active",
            "last_login",
            "password_change_required",
            "firm_id",
            "firm_code",
            "firm_name",
            "firm_is_active",
            "created_at",
        ]
        read_only_fields = fields


class PortalAccountCreateSerializer(serializers.Serializer):
    """Yeni portal hesabı: ya müşteri ya tedarikçi. Şifre girilmez; sistem geçici şifre üretir."""

    username = serializers.CharField(label="Kullanıcı adı", max_length=150)
    full_name = serializers.CharField(label="Ad soyad", max_length=150)
    email = serializers.EmailField(label="E-posta", required=False, allow_blank=True, default="")
    phone = serializers.CharField(
        label="Telefon", max_length=32, required=False, allow_blank=True, default=""
    )
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(), required=False, allow_null=True, default=None
    )
    supplier = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.all(), required=False, allow_null=True, default=None
    )


class IssuedAccountPasswordSerializer(serializers.Serializer):
    """Yeni hesap ya da şifre sıfırlama yanıtı: geçici şifre yalnızca bu yanıtta görünür."""

    account = PortalAccountSerializer()
    temporary_password = serializers.CharField()


class PortalMeSerializer(serializers.Serializer):
    """Portal kullanıcısının hesabı: tür ve bağlı firma (yalnız kod ve ünvan)."""

    kind = serializers.CharField()
    firm_code = serializers.CharField()
    firm_name = serializers.CharField()
