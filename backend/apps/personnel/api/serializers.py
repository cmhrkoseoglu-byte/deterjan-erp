from typing import Any

from rest_framework import serializers

from apps.core.api.serializers import AuditLogSerializer
from apps.core.models import User
from apps.personnel.models import Employee


def _blank(**kwargs: Any) -> serializers.CharField:
    return serializers.CharField(required=False, allow_blank=True, default="", **kwargs)


class LinkedUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "full_name", "is_active"]
        read_only_fields = fields


class EmployeeSerializer(serializers.ModelSerializer):
    employee_no = _blank(max_length=32)
    title = _blank(max_length=100)
    phone = _blank(max_length=32)
    emergency_contact_name = _blank(max_length=150)
    emergency_contact_phone = _blank(max_length=32)
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), allow_null=True, required=False, default=None
    )
    user_info = LinkedUserSerializer(source="user", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_no",
            "full_name",
            "department",
            "title",
            "hire_date",
            "termination_date",
            "phone",
            "emergency_contact_name",
            "emergency_contact_phone",
            "user",
            "user_info",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["termination_date", "is_active", "created_at", "updated_at"]
        # Sicil no ve kullanıcı benzersizliği servis katmanında (Türkçe mesaj, hata kodu).
        validators: list = []


class TerminateSerializer(serializers.Serializer):
    termination_date = serializers.DateField(label="işten çıkış tarihi")
    note = _blank(max_length=500, label="not")


class EmployeeHistorySerializer(AuditLogSerializer):
    """Kartın değişiklik geçmişi (yalnızca admin ve yönetim; IP adresi gösterilmez)."""

    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta(AuditLogSerializer.Meta):
        fields = [
            "id",
            "timestamp",
            "actor",
            "actor_name",
            "action",
            "action_label",
            "changes",
            "note",
        ]
        read_only_fields = fields
