from decimal import Decimal
from typing import Any

from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.api.serializers import AuditLogSerializer
from apps.core.models import User
from apps.personnel import payroll
from apps.personnel.models import (
    ATTENDANCE_CODES,
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeWage,
    ExternalPayrollFigure,
    PayrollItem,
    PayrollItemCategory,
    PayrollOpeningBalance,
    PayrollParameterSet,
    PublicHoliday,
)
from apps.personnel.selectors import (
    PAYROLL_START,
    AttendanceGrid,
    PayrollMonth,
    PayrollSettings,
    engine_parameters,
)
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
            "payroll_external",
            "bes_enrolled",
            "user",
            "user_info",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["termination_date", "is_active", "created_at", "updated_at"]
        extra_kwargs = {
            "payroll_external": {"required": False},
            "bes_enrolled": {"required": False},
        }
        # Sicil no, TC kimlik no ve kullanıcı benzersizliği servis katmanında (Türkçe mesaj, kod).
        validators: list = []


class TerminateSerializer(serializers.Serializer):
    termination_date = serializers.DateField(label="işten çıkış tarihi")
    note = _blank(max_length=500, label="not")
    # Çıkıştan sonra açık aylarda kayıtlı günler varsa ayrılış ancak bu onayla kaydedilir.
    remove_attendance = serializers.BooleanField(
        default=False, label="çıkıştan sonraki puantaj günlerini kaldır"
    )


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
    holiday_half_worked = serializers.BooleanField(
        help_text="yarım gün tatilde öğleden sonra da çalıştı"
    )
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
            "holiday_half_worked",
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
    holiday_half_worked = serializers.BooleanField(
        required=False, default=False, label="yarım gün tatilde çalıştı"
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


# --- ücretler ------------------------------------------------------------------------------------


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=2, **kwargs)


class WageEmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_no",
            "full_name",
            "department",
            "hire_date",
            "termination_date",
            "is_active",
        ]
        read_only_fields = fields


class EmployeeWageSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeWage
        fields = [
            "id",
            "employee",
            "employee_name",
            "gross_monthly",
            "valid_from",
            "note",
            "is_active",
            "removal_reason",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = ["is_active", "removal_reason", "created_at"]
        # Aynı kişi ve tarihte tek ücret kuralı servis katmanında (Türkçe mesaj, hata kodu).
        validators: list = []

    def get_created_by_name(self, obj: EmployeeWage) -> str | None:
        return str(obj.created_by) if obj.created_by_id else None


class WageRemoveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, label="kaldırma nedeni")


class WageSummaryQuerySerializer(serializers.Serializer):
    include_former = serializers.BooleanField(
        default=False, help_text="Ayrılan personeli de listele."
    )


class WageSummarySerializer(serializers.Serializer):
    employee = WageEmployeeSerializer()
    current_wage = _money(allow_null=True)
    current_valid_from = serializers.DateField(allow_null=True)
    history = EmployeeWageSerializer(many=True)


# --- ön bordro (docs/DECISIONS.md "Personel bordrosu") -------------------------------------------


def _rate(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=6, decimal_places=3, **kwargs)


class PayrollEmployeeSerializer(serializers.ModelSerializer):
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
            "is_active",
            "payroll_external",
            "bes_enrolled",
        ]
        read_only_fields = fields


class PayrollItemSerializer(serializers.Serializer):
    """Hesaptaki kalem (motor): `kind` kalemin kategorisidir (ör. MEAL, ADVANCE)."""

    kind = serializers.CharField()
    description = serializers.CharField(source="label")
    amount = _money()


# Brütten nete hesaba bağlı kalemler: başlangıç ayından önce (bordro mali müşavirdeyken) boş döner.
NET_LINE_FIELDS = (
    "tax_base",
    "cumulative_tax_base_before",
    "cumulative_tax_base_after",
    "income_tax_computed",
    "income_tax_exemption",
    "income_tax",
    "exemption_base_before",
    "exemption_base_added",
    "stamp_tax_computed",
    "stamp_tax_exemption",
    "stamp_tax",
    "net_pay",
    "bes_deduction",
    "deductions_total",
    "payable",
)


class PayrollLineSerializer(serializers.Serializer):
    """Bordro satırının kalemleri (hesap motoru, `personnel.payroll.Result`)."""

    employed_days = serializers.IntegerField()
    worked_days = serializers.IntegerField(
        help_text="fiilen çalışılan gün (Ç, fazla mesaili hafta tatili ve resmî tatil)"
    )
    paid_days = serializers.IntegerField(help_text="30 gün usulü ücretli gün")
    unpaid_days = serializers.IntegerField(help_text="ücretsiz izin + rapor + devamsız")
    sick_days = serializers.IntegerField()
    unpaid_leave_days = serializers.IntegerField()
    absent_days = serializers.IntegerField()
    sgk_days = serializers.IntegerField()
    monthly_wage = _money(allow_null=True, help_text="ayın son işte olunan günündeki brüt ücret")
    missing_wage = serializers.BooleanField()
    salary = _money()
    overtime_worked_hours = _hours()
    overtime_worked_pay = _money()
    overtime_rest_hours = _hours()
    overtime_rest_pay = _money()
    holiday_days = serializers.IntegerField(help_text="çalışılan tam gün resmi tatil")
    holiday_half_days = serializers.IntegerField(help_text="öğleden sonra çalışılan yarım gün")
    holiday_hours = _hours()
    holiday_extra_hours = _hours(help_text="tatilde 7,5 saati aşan saatler")
    holiday_pay = _money()
    extras = PayrollItemSerializer(many=True)
    extras_total = _money()
    gross_total = _money()
    meal_exemption = _money(help_text="nakit yemeğin SGK matrahına girmeyen kısmı")
    sgk_gross = _money(help_text="SGK'ya tabi brüt (brüt − yemek istisnası)")
    sgk_base = _money()
    floor_applied = serializers.BooleanField()
    ceiling_applied = serializers.BooleanField()
    employee_sgk = _money()
    employee_unemployment = _money()
    tax_base = _money(allow_null=True)
    cumulative_tax_base_before = _money(allow_null=True)
    cumulative_tax_base_after = _money(allow_null=True)
    income_tax_computed = _money(allow_null=True)
    income_tax_exemption = _money(allow_null=True)
    income_tax = _money(allow_null=True)
    exemption_base_before = _money(allow_null=True)
    exemption_base_added = _money(allow_null=True)
    stamp_tax_computed = _money(allow_null=True)
    stamp_tax_exemption = _money(allow_null=True)
    stamp_tax = _money(allow_null=True)
    net_pay = _money(allow_null=True)
    bes_deduction = _money(allow_null=True)
    deductions = PayrollItemSerializer(many=True)
    deductions_total = _money(allow_null=True)
    payable = _money(allow_null=True)
    employer_sgk_gross = _money()
    incentive = _money()
    employer_sgk = _money()
    employer_unemployment = _money()
    floor_gap = _money()
    employer_cost = _money()

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)
        if not self.context.get("net", True):
            for name in NET_LINE_FIELDS:
                data[name] = None
        return data


class ExternalFigureSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ExternalPayrollFigure
        fields = [
            "id",
            "employee",
            "year",
            "month",
            "gross_total",
            "employer_cost",
            "note",
            "updated_at",
            "updated_by_name",
        ]
        read_only_fields = fields

    def get_updated_by_name(self, obj: ExternalPayrollFigure) -> str | None:
        return str(obj.updated_by) if obj.updated_by_id else None


class ExternalFigureInputSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), label="personel")
    gross_total = _money(min_value=Decimal(0), label="brüt toplam (TL)")
    employer_cost = _money(min_value=Decimal(0), label="işverene maliyet (TL)")
    note = _blank(max_length=200, label="not")


MAX_BATCH_ROWS = 1000


def _name(user: User | None) -> str | None:
    return str(user) if user else None


class PayrollItemRecordSerializer(serializers.ModelSerializer):
    """Ek ödeme ya da kesinti kaydı. Açıklama kişisel veri olabilir (icra dosyası); yalnızca
    yönetim ve admin görür."""

    category_label = serializers.CharField(source="get_category_display", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    removed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollItem
        fields = [
            "id",
            "employee",
            "employee_name",
            "year",
            "month",
            "kind",
            "category",
            "category_label",
            "description",
            "amount",
            "is_active",
            "created_at",
            "created_by_name",
            "updated_at",
            "updated_by_name",
            "removed_at",
            "removed_by_name",
            "removal_reason",
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj: PayrollItem) -> str | None:
        return _name(obj.created_by)

    def get_updated_by_name(self, obj: PayrollItem) -> str | None:
        return _name(obj.updated_by)

    def get_removed_by_name(self, obj: PayrollItem) -> str | None:
        return _name(obj.removed_by)


class PayrollItemInputSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), label="personel")
    year = serializers.IntegerField(label="yıl")
    month = serializers.IntegerField(label="ay")
    category = serializers.ChoiceField(choices=PayrollItemCategory.choices, label="kategori")
    description = _blank(max_length=100, label="açıklama")
    amount = _money(label="tutar (TL)")


class PayrollItemUpdateSerializer(serializers.Serializer):
    """Kalemin düzeltilebilen alanları (kişi, ay ve tür değişmez)."""

    category = serializers.ChoiceField(
        choices=PayrollItemCategory.choices, label="kategori", required=False
    )
    description = serializers.CharField(
        max_length=100, allow_blank=True, required=False, label="açıklama"
    )
    amount = _money(label="tutar (TL)", required=False)


class PayrollItemRowSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), label="personel")
    category = serializers.ChoiceField(choices=PayrollItemCategory.choices, label="kategori")
    description = _blank(max_length=100, label="açıklama")
    amount = _money(label="tutar (TL)")


class PayrollItemBatchSerializer(serializers.Serializer):
    """Toplu ekleme ("Toplu ekle", "Geçen aydan kopyala"): hepsi kaydedilir ya da hiçbiri."""

    year = serializers.IntegerField(label="yıl")
    month = serializers.IntegerField(label="ay")
    items = PayrollItemRowSerializer(many=True, allow_empty=False)

    def validate_items(self, value: list[Any]) -> list[Any]:
        if len(value) > MAX_BATCH_ROWS:
            raise serializers.ValidationError(f"En çok {MAX_BATCH_ROWS} satır gönderilebilir.")
        return value


class PayrollOpeningSerializer(serializers.ModelSerializer):
    """Devir: `month` ayından önceki kümülatif GV matrahı ve asgari ücret istisna matrahı."""

    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    removed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollOpeningBalance
        fields = [
            "id",
            "employee",
            "employee_name",
            "year",
            "month",
            "tax_base",
            "exemption_months",
            "exemption_base",
            "note",
            "is_active",
            "created_at",
            "created_by_name",
            "updated_at",
            "updated_by_name",
            "removed_at",
            "removed_by_name",
            "removal_reason",
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj: PayrollOpeningBalance) -> str | None:
        return _name(obj.created_by)

    def get_updated_by_name(self, obj: PayrollOpeningBalance) -> str | None:
        return _name(obj.updated_by)

    def get_removed_by_name(self, obj: PayrollOpeningBalance) -> str | None:
        return _name(obj.removed_by)


class PayrollOpeningRowSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), label="personel")
    tax_base = _money(label="kümülatif gelir vergisi matrahı (TL)")
    exemption_months = serializers.IntegerField(
        min_value=0, max_value=11, label="asgari ücret istisnası uygulanan ay"
    )
    note = _blank(max_length=200, label="not")
    confirm_override = serializers.BooleanField(
        default=False,
        help_text="kişi önceki ay ERP'de hesaplandıysa devrin o ayların yerine geçtiği onayı",
    )


class PayrollOpeningInputSerializer(PayrollOpeningRowSerializer):
    year = serializers.IntegerField(label="yıl")
    month = serializers.IntegerField(label="ay")


class PayrollOpeningBatchSerializer(serializers.Serializer):
    """Ayın devirleri (devir penceresinin tek "Kaydet"i): hepsi kaydedilir ya da hiçbiri."""

    year = serializers.IntegerField(label="yıl")
    month = serializers.IntegerField(label="ay")
    rows = PayrollOpeningRowSerializer(many=True, allow_empty=False)

    def validate_rows(self, value: list[Any]) -> list[Any]:
        if len(value) > MAX_BATCH_ROWS:
            raise serializers.ValidationError(f"En çok {MAX_BATCH_ROWS} satır gönderilebilir.")
        return value


class BatchErrorRowSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    employee = serializers.IntegerField(allow_null=True)
    code = serializers.CharField()
    detail = serializers.CharField()


class BatchErrorSerializer(serializers.Serializer):
    """Toplu kaydın reddi (400): satır hataları; hiçbir satır kaydedilmedi."""

    code = serializers.CharField()
    detail = serializers.CharField()
    rows = BatchErrorRowSerializer(many=True)


class CarryMonthSerializer(serializers.Serializer):
    """Ay başı kümülatifin halkası (`kind`): "opening" (devir; tutarlar `month` ayından önceki
    kümülatif),
    "erp" (o ayın eklenen GV matrahı ve istisna matrahı) ya da "external" (bordro mali müşavirdeydi;
    zincir kopar)."""

    month = serializers.IntegerField()
    kind = serializers.CharField(source="source", help_text="opening, erp ya da external")
    tax_base = _money()
    exemption_base = _money()
    flags = serializers.ListField(child=serializers.CharField())


class PayrollRowSerializer(serializers.Serializer):
    employee = PayrollEmployeeSerializer()
    external = serializers.BooleanField(help_text="bordrosu mali müşavirde (rakamlar `figure`)")
    figure = ExternalFigureSerializer(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField())
    line = PayrollLineSerializer()
    gross_total = _money()
    employer_cost = _money()
    items = PayrollItemRecordSerializer(many=True, help_text="ayın ek ödeme ve kesintileri")
    opening = PayrollOpeningSerializer(
        allow_null=True, help_text="zincirin çapası olan devir (bu ay ya da önceki bir ay)"
    )
    openings = PayrollOpeningSerializer(
        many=True, help_text="kişinin bu yıl bu aya kadarki etkin devirleri (ay sırasıyla)"
    )
    entry_month = serializers.IntegerField(
        allow_null=True, help_text="devrin beklendiği giriş ayı (zincir buradan başlar)"
    )
    opening_needed = serializers.BooleanField(help_text="giriş ayının devri girilmedi")
    suggestion_months = serializers.IntegerField(
        help_text="giriş ayı devri için asgari ücret istisnası ay önerisi (işe girişten)"
    )
    suggestion_base = _money(help_text="önerilen ayların asgari ücret istisna matrahı toplamı")
    carry_months = CarryMonthSerializer(many=True, help_text="ay başı kümülatifin kuruluşu")


class PayrollValuesSerializer(serializers.Serializer):
    """Hesapta kullanılan değerler (kayıtlı set ya da yasal değerler)."""

    minimum_wage = _money()
    daily_floor = _money()
    daily_ceiling = _money()
    ceiling_multiplier = _money()
    employee_sgk_rate = _money()
    employee_unemployment_rate = _money()
    employer_sgk_rate = _money()
    employer_unemployment_rate = _money()
    incentive_points = _money()
    employer_rate = _money(help_text="SGK işveren − teşvik + işsizlik işveren")
    stamp_tax_per_mille = _rate()
    tax_brackets = serializers.ListField(child=_money())
    tax_rates = serializers.ListField(child=_money())
    exemption_base = _money(help_text="asgari ücretin gelir vergisi matrahı")
    bes_rate = _money()
    meal_exemption_daily = _money(help_text="nakit yemek SGK istisnası (günlük TL)")


def values_data(params: payroll.Parameters) -> dict[str, Any]:
    return {
        "minimum_wage": params.minimum_wage,
        "daily_floor": params.daily_floor,
        "daily_ceiling": params.daily_ceiling,
        "ceiling_multiplier": params.ceiling_multiplier,
        "employee_sgk_rate": params.employee_sgk_rate,
        "employee_unemployment_rate": params.employee_unemployment_rate,
        "employer_sgk_rate": params.employer_sgk_rate,
        "employer_unemployment_rate": params.employer_unemployment_rate,
        "incentive_points": params.incentive_points,
        "employer_rate": params.employer_rate,
        "stamp_tax_per_mille": params.stamp_tax_per_mille,
        "tax_brackets": list(params.tax_brackets),
        "tax_rates": list(params.tax_rates),
        "exemption_base": params.exemption_base,
        "bes_rate": params.bes_rate,
        "meal_exemption_daily": params.meal_exemption_daily,
    }


class PayrollParametersInfoSerializer(serializers.Serializer):
    origin = serializers.CharField(
        help_text="saved: kayıtlı set; legal_default: yasal değerler (set kaydedilmedi); "
        "fallback: başka yılın değerleriyle tahmin"
    )
    year = serializers.IntegerField(help_text="değerlerin ait olduğu yıl")
    record = serializers.IntegerField(allow_null=True)
    valid_from = serializers.DateField(allow_null=True)
    values = PayrollValuesSerializer()


def parameters_info(settings: PayrollSettings) -> dict[str, Any]:
    record = settings.record
    return {
        "origin": settings.source,
        "year": settings.year,
        "record": record.pk if record else None,
        "valid_from": record.valid_from if record else None,
        "values": values_data(settings.params),
    }


TOTAL_FIELDS = (
    "salary",
    "overtime_worked_pay",
    "overtime_rest_pay",
    "holiday_pay",
    "extras_total",
    "sgk_base",
    "employee_sgk",
    "employee_unemployment",
    "income_tax",
    "stamp_tax",
    "net_pay",
    "bes_deduction",
    "deductions_total",
    "payable",
    "employer_sgk_gross",
    "incentive",
    "employer_sgk",
    "employer_unemployment",
    "floor_gap",
)


NET_TOTAL_FIELDS = (
    "income_tax",
    "stamp_tax",
    "net_pay",
    "bes_deduction",
    "deductions_total",
    "payable",
)


class PayrollTotalsSerializer(serializers.Serializer):
    """Toplamlar. `gross_total` ve `employer_cost` mali müşavirde hesaplananların girilmiş
    rakamlarını da içerir; `computed_*` ve diğerleri yalnızca ERP'de hesaplanan satırların
    toplamıdır. Net toplamlar başlangıç ayından önce boştur."""

    employee_count = serializers.IntegerField()
    external_count = serializers.IntegerField()
    gross_total = _money()
    employer_cost = _money()
    computed_gross_total = _money(help_text="ERP'de hesaplanan satırların brüt toplamı")
    computed_employer_cost = _money(help_text="ERP'de hesaplanan satırların işverene maliyeti")
    salary = _money()
    overtime_worked_pay = _money()
    overtime_rest_pay = _money()
    holiday_pay = _money()
    extras_total = _money()
    sgk_base = _money()
    employee_sgk = _money()
    employee_unemployment = _money()
    income_tax = _money(allow_null=True)
    stamp_tax = _money(allow_null=True)
    net_pay = _money(allow_null=True)
    bes_deduction = _money(allow_null=True)
    deductions_total = _money(allow_null=True)
    payable = _money(allow_null=True)
    employer_sgk_gross = _money()
    incentive = _money()
    employer_sgk = _money()
    employer_unemployment = _money()
    floor_gap = _money()


def totals_data(month: PayrollMonth) -> dict[str, Any]:
    data = {
        "employee_count": len(month.rows),
        "external_count": sum(1 for row in month.rows if row.external),
        "gross_total": month.gross_total,
        "employer_cost": month.employer_cost,
        "computed_gross_total": month.total("gross_total"),
        "computed_employer_cost": month.total("employer_cost"),
        **{name: month.total(name) for name in TOTAL_FIELDS},
    }
    if not month.net:
        data.update(dict.fromkeys(NET_TOTAL_FIELDS))
    return data


class PayrollMonthSerializer(serializers.Serializer):
    """Ayın ön bordrosu (canlı hesap). Puantaj açıkken girilmemiş günler takvimden sayılır."""

    year = serializers.IntegerField()
    month = serializers.IntegerField()
    period_label = serializers.CharField(source="label")
    attendance_status = serializers.CharField(source="grid.status")
    attendance_number = serializers.CharField()
    attendance_approved = serializers.BooleanField()
    attendance_finished = serializers.BooleanField(source="grid.finished")
    net = serializers.BooleanField(
        help_text="brütten nete hesaplandı (başlangıç ayından önce hayır; net alanları boş)"
    )
    net_available = serializers.BooleanField()
    start = serializers.SerializerMethodField(help_text="brütten nete bordronun ilk ayı (YYYY-AA)")
    parameters = serializers.SerializerMethodField()
    rows = PayrollRowSerializer(many=True)
    orphan_items = PayrollItemRecordSerializer(
        many=True, help_text="bu ay işte olmayan kişilere girilmiş kalemler"
    )
    totals = serializers.SerializerMethodField()

    def to_representation(self, instance: PayrollMonth) -> Any:
        # İç içe satır serileştiricileri net alanlarını bu bilgiyle boşaltır.
        self._context = {**getattr(self, "_context", {}), "net": instance.net}
        return super().to_representation(instance)

    def get_start(self, obj: PayrollMonth) -> str:
        year, month = PAYROLL_START
        return f"{year}-{month:02d}"

    @extend_schema_field(PayrollParametersInfoSerializer)
    def get_parameters(self, obj: PayrollMonth) -> dict[str, Any]:
        return dict(PayrollParametersInfoSerializer(parameters_info(obj.settings)).data)

    @extend_schema_field(PayrollTotalsSerializer)
    def get_totals(self, obj: PayrollMonth) -> dict[str, Any]:
        return dict(PayrollTotalsSerializer(totals_data(obj)).data)


PARAMETER_VALUE_FIELDS = (
    "minimum_wage",
    "ceiling_multiplier",
    "employee_sgk_rate",
    "employee_unemployment_rate",
    "employer_sgk_rate",
    "employer_unemployment_rate",
    "incentive_points",
    "stamp_tax_per_mille",
    "tax_bracket_1",
    "tax_bracket_2",
    "tax_bracket_3",
    "tax_bracket_4",
    "tax_rate_1",
    "tax_rate_2",
    "tax_rate_3",
    "tax_rate_4",
    "tax_rate_5",
    "bes_rate",
    "meal_exemption_daily",
)


class PayrollParameterSetSerializer(serializers.ModelSerializer):
    """Bordro parametre seti. Geçerlilik "2026-01" (ay) ya da tarih olarak gelir; ayın ilk gününe
    çekilir. Kurallar servis katmanında (Türkçe mesaj, hata kodu)."""

    valid_from = serializers.DateField(input_formats=["%Y-%m", "iso-8601"], label="geçerlilik")
    year = serializers.SerializerMethodField()
    derived = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollParameterSet
        fields = [
            "id",
            "valid_from",
            *PARAMETER_VALUE_FIELDS,
            "source",
            "note",
            "year",
            "derived",
            "is_active",
            "created_at",
            "updated_at",
            "updated_by_name",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]
        validators: list = []

    def get_year(self, obj: PayrollParameterSet) -> int:
        return obj.valid_from.year

    @extend_schema_field(PayrollValuesSerializer)
    def get_derived(self, obj: PayrollParameterSet) -> dict[str, Any]:
        """Setten hesaplanan değerler (günlük alt ve üst sınır, etkin işveren oranı, istisna
        matrahı) ekranda kontrol içindir."""
        return dict(PayrollValuesSerializer(values_data(engine_parameters(obj))).data)

    def get_updated_by_name(self, obj: PayrollParameterSet) -> str | None:
        return str(obj.updated_by) if obj.updated_by_id else None


class ParameterDefaultsQuerySerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100, label="yıl")


class ParameterDefaultsSerializer(serializers.Serializer):
    """Yılın yasal değerleri (parametre formunu doldurmak için). `known` yanlışsa en yakın
    yılın değerleri döner ve kaynak boştur: yeni yılın değerleri mali müşavirden teyit edilerek
    girilir."""

    year = serializers.IntegerField()
    known = serializers.BooleanField()
    values_year = serializers.IntegerField()
    legal_source = serializers.CharField()
    values = PayrollValuesSerializer()


def defaults_data(year: int) -> dict[str, Any]:
    known = payroll.legal_parameters(year) is not None
    values_year = year if known else payroll.nearest_legal_year(year)
    return {
        "year": year,
        "known": known,
        "values_year": values_year,
        "legal_source": payroll.LEGAL_SOURCES.get(year, "") if known else "",
        "values": values_data(payroll.LEGAL_DEFAULTS[values_year]),
    }


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, label="neden")
