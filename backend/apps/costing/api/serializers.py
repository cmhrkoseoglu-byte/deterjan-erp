from typing import Any

from rest_framework import serializers

from apps.costing.models import (
    CostRate,
    CostStage,
    EmployeeWage,
    LotCost,
    LotCostLine,
    PersonnelCostSettings,
    StandardCost,
)
from apps.inventory.api.serializers import UserNameField
from apps.masterdata.models import Material
from apps.personnel.models import Employee

MATERIAL_TYPES = Material.Type.choices


class LotCostLineSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True, default=None)
    source_lot_no = serializers.CharField(source="source_lot.lot_no", read_only=True, default=None)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True, default=None)

    class Meta:
        model = LotCostLine
        fields = [
            "line_no",
            "category",
            "description",
            "material",
            "material_code",
            "source_lot",
            "source_lot_no",
            "quantity",
            "unit",
            "unit_cost",
            "amount",
            "is_estimated",
            "is_missing",
        ]


class LotCostSerializer(serializers.ModelSerializer):
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    lot_source = serializers.CharField(source="lot.source", read_only=True)
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    material_type = serializers.CharField(source="material.material_type", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    calculated_by_name = UserNameField(source="calculated_by")

    class Meta:
        model = LotCost
        fields = [
            "id",
            "lot",
            "lot_no",
            "lot_source",
            "material",
            "material_code",
            "material_name",
            "material_type",
            "unit",
            "version",
            "is_current",
            "method",
            "quantity",
            "total_cost",
            "unit_cost",
            "finished_scrap_cost",
            "is_estimated",
            "has_missing",
            "cost_date",
            "calculated_at",
            "calculated_by_name",
            "note",
        ]


class LotCostDetailSerializer(LotCostSerializer):
    lines = LotCostLineSerializer(many=True, read_only=True)

    class Meta(LotCostSerializer.Meta):
        fields = [*LotCostSerializer.Meta.fields, "lines"]


class LotCostHistorySerializer(serializers.Serializer):
    lot = serializers.IntegerField()
    lot_no = serializers.CharField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    is_costable = serializers.BooleanField()
    versions = LotCostDetailSerializer(many=True)


class RecalculateSerializer(serializers.Serializer):
    note = serializers.CharField()
    cascade = serializers.BooleanField(default=False)


class CostRateSerializer(serializers.ModelSerializer):
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = CostRate
        fields = [
            "id",
            "stage",
            "kind",
            "rate_per_kg",
            "valid_from",
            "note",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = ["created_at"]
        # Benzersizlik servis katmanında Türkçe mesajla denetlenir.
        validators: list = []


class StandardCostSerializer(serializers.ModelSerializer):
    material = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.select_related("base_unit")
    )
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    material_type = serializers.CharField(source="material.material_type", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)

    class Meta:
        model = StandardCost
        fields = [
            "id",
            "material",
            "material_code",
            "material_name",
            "material_type",
            "unit",
            "unit_cost",
            "note",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]
        validators: list = []


# --- raporlar --------------------------------------------------------------------------------


class ReportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all(), required=False)


class TopMaterialsQuerySerializer(ReportQuerySerializer):
    material_type = serializers.ChoiceField(
        choices=[Material.Type.RAW, Material.Type.PACKAGING], required=False
    )
    limit = serializers.IntegerField(min_value=1, max_value=200, default=20)


class StockValueQuerySerializer(serializers.Serializer):
    material_type = serializers.ChoiceField(choices=MATERIAL_TYPES, required=False)
    warehouse = serializers.IntegerField(required=False)
    location = serializers.IntegerField(required=False)
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all(), required=False)


class CostTrendRowSerializer(serializers.Serializer):
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    unit = serializers.CharField()
    month = serializers.DateField()
    lot_count = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    total_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    unit_cost = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    has_estimated = serializers.BooleanField()


class BatchVarianceRowSerializer(serializers.Serializer):
    lot_cost_id = serializers.IntegerField()
    lot_id = serializers.IntegerField()
    lot_no = serializers.CharField()
    order_number = serializers.CharField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    unit = serializers.CharField()
    cost_date = serializers.DateField()
    planned_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    actual_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    theoretical_material_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    actual_material_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    overhead_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    theoretical_unit_cost = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True
    )
    actual_material_unit_cost = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True
    )
    unit_cost = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    variance_pct = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    is_estimated = serializers.BooleanField()


class ScrapCostRowSerializer(serializers.Serializer):
    lot_cost_id = serializers.IntegerField()
    lot_id = serializers.IntegerField()
    lot_no = serializers.CharField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    cost_date = serializers.DateField()
    good_units = serializers.DecimalField(max_digits=18, decimal_places=4)
    material_scrap_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    finished_scrap_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_scrap_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=18, decimal_places=2)
    scrap_pct = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)


class TopMaterialRowSerializer(serializers.Serializer):
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    material_type = serializers.CharField()
    unit = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    average_unit_cost = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    share_pct = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    has_missing = serializers.BooleanField()


class StockValueRowSerializer(serializers.Serializer):
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    material_type = serializers.CharField()
    unit = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    value = serializers.DecimalField(max_digits=18, decimal_places=2)
    average_unit_cost = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    uncosted_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    estimated_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)


class StockValueTypeSerializer(serializers.Serializer):
    material_type = serializers.CharField()
    value = serializers.DecimalField(max_digits=18, decimal_places=2)


class StockValueSerializer(serializers.Serializer):
    total_value = serializers.DecimalField(max_digits=18, decimal_places=2)
    by_type = StockValueTypeSerializer(many=True)
    rows = StockValueRowSerializer(many=True)


# --- personel maliyeti -----------------------------------------------------------------------


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=2, **kwargs)


def _unit(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, **kwargs)


class CostEmployeeSerializer(serializers.ModelSerializer):
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


class PersonnelCostRowSerializer(serializers.Serializer):
    employee = CostEmployeeSerializer()
    stage = serializers.CharField(help_text="PRODUCTION, FILLING ya da boş (genel gider)")
    gross_monthly = _money(allow_null=True)
    employed_days = serializers.IntegerField()
    unpaid_days = serializers.IntegerField()
    paid_days = serializers.IntegerField()
    overtime_hours = serializers.DecimalField(max_digits=9, decimal_places=2)
    gross_salary = _money()
    overtime_pay = _money()
    gross_total = _money()
    employer_share = _money()
    total_cost = _money()
    missing_wage = serializers.BooleanField()


class StageCostSerializer(serializers.Serializer):
    stage = serializers.CharField()
    cost = _money()
    employee_count = serializers.IntegerField()
    kg = _unit(allow_null=True)
    unconverted = serializers.IntegerField()
    current_rate = _unit(allow_null=True)
    suggested_rate = _unit(allow_null=True)
    missing_wage_count = serializers.IntegerField()


class PersonnelCostReportSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    period_label = serializers.CharField(source="label")
    attendance_status = serializers.CharField()
    attendance_number = serializers.CharField()
    attendance_approved = serializers.BooleanField()
    employer_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    missing_wage_count = serializers.IntegerField()
    gross_salary = _money()
    overtime_pay = _money()
    employer_share = _money()
    total_cost = _money()
    stages = StageCostSerializer(many=True)
    rows = PersonnelCostRowSerializer(many=True)


class LaborRateFromPersonnelSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=CostStage.choices, label="aşama")
    valid_from = serializers.DateField(label="geçerlilik başlangıcı")


class EmployeeWageSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    created_by_name = UserNameField(source="created_by")

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


class WageRemoveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, label="kaldırma nedeni")


class WageSummaryQuerySerializer(serializers.Serializer):
    include_former = serializers.BooleanField(
        default=False, help_text="Ayrılan personeli de listele."
    )


class WageSummarySerializer(serializers.Serializer):
    employee = CostEmployeeSerializer()
    stage = serializers.CharField()
    current_wage = _money(allow_null=True)
    current_valid_from = serializers.DateField(allow_null=True)
    history = EmployeeWageSerializer(many=True)


# Birim → maliyet aşaması; boş = genel gider.
COST_CENTER_STAGES = [("", "Genel gider"), *CostStage.choices]


class CostCenterSerializer(serializers.Serializer):
    department = serializers.CharField(max_length=64, label="birim")
    stage = serializers.ChoiceField(choices=COST_CENTER_STAGES, allow_blank=True, label="aşama")


class PersonnelCostSettingsSerializer(serializers.ModelSerializer):
    # Ayar hiç kaydedilmediyse varsayılan döner ve tarihi boştur.
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = PersonnelCostSettings
        fields = ["employer_rate", "updated_at"]
        read_only_fields = ["updated_at"]
        extra_kwargs = {"employer_rate": {"required": True}}
