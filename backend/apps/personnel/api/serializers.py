from typing import Any

from django.urls import reverse
from rest_framework import serializers

from apps.core.api.serializers import AuditLogSerializer
from apps.core.models import User
from apps.personnel.models import Employee, EmployeeDocument


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
    # Boşluklu yazım ("123 456 789 01") kabul edilir; servis boşlukları atıp 11 haneyi denetler.
    national_id = _blank(max_length=20)
    birth_place = _blank(max_length=100)
    education_level = serializers.ChoiceField(
        choices=Employee.EducationLevel.choices, required=False, allow_blank=True, default=""
    )
    education_level_display = serializers.CharField(
        source="get_education_level_display", read_only=True
    )
    school = _blank(max_length=200)
    field_of_study = _blank(max_length=200)
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
            "national_id",
            "birth_date",
            "birth_place",
            "education_level",
            "education_level_display",
            "school",
            "field_of_study",
            "graduation_year",
            "user",
            "user_info",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["termination_date", "is_active", "created_at", "updated_at"]
        # Sicil no, TC kimlik no ve kullanıcı benzersizliği servis katmanında (Türkçe mesaj, kod).
        validators: list = []


class TerminateSerializer(serializers.Serializer):
    termination_date = serializers.DateField(label="işten çıkış tarihi")
    note = _blank(max_length=500, label="not")


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    """Özlük belgesi. Dosya açık yoldan değil `download_url` ucundan verilir."""

    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeDocument
        fields = [
            "id",
            "employee",
            "kind",
            "kind_display",
            "original_name",
            "size",
            "mime_type",
            "period",
            "valid_from",
            "valid_until",
            "note",
            "uploaded_by_name",
            "created_at",
            "download_url",
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj: EmployeeDocument) -> str | None:
        return str(obj.created_by) if obj.created_by_id else None

    def get_download_url(self, obj: EmployeeDocument) -> str:
        return reverse("personnel:document-download", args=[obj.pk])


class DocumentQuerySerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), label="personel")


class DocumentUploadSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), label="personel")
    kind = serializers.ChoiceField(choices=EmployeeDocument.Kind.choices, label="tür")
    file = serializers.FileField(label="dosya")
    # Bordro dönemi "2026-09" (ay) ya da tam tarih olarak gelebilir.
    period = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        input_formats=["%Y-%m", "iso-8601"],
        label="dönem",
    )
    valid_from = serializers.DateField(
        required=False, allow_null=True, default=None, label="başlangıç tarihi"
    )
    valid_until = serializers.DateField(
        required=False, allow_null=True, default=None, label="bitiş tarihi"
    )
    note = _blank(max_length=500, label="not")


class DocumentRemoveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, label="kaldırma nedeni")


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
