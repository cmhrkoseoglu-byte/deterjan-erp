from decimal import Decimal
from typing import Any

from django.urls import reverse
from rest_framework import serializers

from apps.core.api.serializers import AuditLogSerializer
from apps.core.models import User
from apps.personnel.models import (
    ATTENDANCE_CODES,
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    PublicHoliday,
)
from apps.personnel.selectors import AttendanceGrid
from apps.personnel.state import attendance_month_states


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


# --- puantaj ------------------------------------------------------------------------------------


def _hours(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=7, decimal_places=2, **kwargs)


class AttendanceColumnSerializer(serializers.Serializer):
    """Tablonun bir günü: hafta tatili mi, resmi tatil mi."""

    date = serializers.DateField()
    weekday = serializers.IntegerField(help_text="pazartesi 0 … pazar 6")
    rest = serializers.BooleanField(help_text="varsayılan hafta tatili günü")
    holiday_name = serializers.CharField()
    half_day = serializers.BooleanField()


class AttendanceCellSerializer(serializers.Serializer):
    date = serializers.DateField()
    status = serializers.CharField(help_text="boşsa kişi o gün işte değil")
    code = serializers.CharField()
    overtime_hours = _hours()
    note = serializers.CharField()
    explicit = serializers.BooleanField(help_text="kayıtlı gün; değilse takvimden varsayılan")
    editable = serializers.BooleanField()


class AttendanceTotalsSerializer(serializers.Serializer):
    days = serializers.DictField(child=serializers.IntegerField(), help_text="durum → gün")
    missing_days = serializers.IntegerField(help_text="ücretsiz izin + rapor + devamsız")
    overtime = serializers.DictField(child=_hours(), help_text="günün durumu → saat")
    overtime_total = _hours()


class AttendanceEmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "employee_no", "full_name", "department", "is_active"]
        read_only_fields = fields


class AttendanceRowSerializer(serializers.Serializer):
    employee = AttendanceEmployeeSerializer()
    cells = AttendanceCellSerializer(many=True)
    totals = AttendanceTotalsSerializer()


class AttendanceMonthSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceMonth
        fields = [
            "id",
            "number",
            "year",
            "month",
            "status",
            "status_display",
            "approved_at",
            "approved_by_name",
        ]
        read_only_fields = fields

    def get_status_display(self, obj: AttendanceMonth) -> str:
        return attendance_month_states.label(obj.status)

    def get_approved_by_name(self, obj: AttendanceMonth) -> str | None:
        return str(obj.approved_by) if obj.approved_by_id else None


class AttendanceGridSerializer(serializers.Serializer):
    """Aylık puantaj tablosu. `month_record` ay hiç yazılmadıysa boştur (durum: açık)."""

    year = serializers.IntegerField()
    month = serializers.IntegerField()
    period_label = serializers.CharField(source="label")
    status = serializers.CharField()
    finished = serializers.BooleanField(help_text="ay bitti (onay ancak ay bitince)")
    month_record = serializers.SerializerMethodField()
    days = AttendanceColumnSerializer(many=True)
    rows = AttendanceRowSerializer(many=True)

    def get_month_record(self, obj: AttendanceGrid) -> dict[str, Any] | None:
        return AttendanceMonthSerializer(obj.record).data if obj.record else None


class AttendanceEntrySerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    code = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceEntry
        fields = [
            "id",
            "employee",
            "date",
            "status",
            "status_display",
            "code",
            "overtime_hours",
            "note",
        ]
        read_only_fields = fields

    def get_code(self, obj: AttendanceEntry) -> str:
        return ATTENDANCE_CODES.get(obj.status, "")


class AttendanceDayInputSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), label="personel")
    date = serializers.DateField(label="tarih")
    status = serializers.ChoiceField(choices=AttendanceStatus.choices, label="durum")
    overtime_hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal(0),
        required=False,
        default=Decimal(0),
        label="fazla mesai (saat)",
    )
    note = _blank(max_length=200, label="not")


class AttendanceRangeSerializer(serializers.Serializer):
    """Aralık girişi: tek kişi (`employee`), birim (`department`) ya da ikisi de boşsa herkes."""

    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        allow_null=True,
        required=False,
        default=None,
        label="personel",
    )
    department = _blank(max_length=64, label="birim")
    start = serializers.DateField(label="başlangıç")
    end = serializers.DateField(label="bitiş")
    status = serializers.ChoiceField(choices=AttendanceStatus.choices, label="durum")
    note = _blank(max_length=200, label="not")


class AttendanceRangeResultSerializer(serializers.Serializer):
    updated = serializers.IntegerField(help_text="değişen gün sayısı")


class AttendanceReopenSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, label="gerekçe")


class PublicHolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = PublicHoliday
        fields = ["id", "date", "name", "half_day"]
        # Aynı tarihte tek tatil kuralı servis katmanında (Türkçe mesaj, hata kodu).
        validators: list = []


class FixedHolidaysSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100, label="yıl")


class AttendanceSettingsSerializer(serializers.ModelSerializer):
    rest_weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        allow_empty=True,
        help_text="hafta tatili günleri: pazartesi 0 … pazar 6",
    )

    class Meta:
        model = AttendanceSettings
        fields = ["rest_weekdays", "updated_at"]
        read_only_fields = ["updated_at"]
