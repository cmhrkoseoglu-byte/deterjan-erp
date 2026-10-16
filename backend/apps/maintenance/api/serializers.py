from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory.api.serializers import UserNameField
from apps.inventory.models import Lot
from apps.maintenance import selectors
from apps.maintenance.models import (
    ChangeoverRule,
    Downtime,
    MaintenancePlan,
    MaintenanceSettings,
    MaintenanceWorkOrder,
    WorkOrderPart,
)
from apps.maintenance.state import work_order_states
from apps.masterdata.models import Equipment, Location, Material


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, **kwargs)


class ChecklistRowSerializer(serializers.Serializer):
    item = serializers.CharField(read_only=True)
    done = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class MaintenanceSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceSettings
        fields = ["calibration_warning_days", "plan_lead_days"]


class MaintenancePlanSerializer(serializers.ModelSerializer):
    equipment = serializers.PrimaryKeyRelatedField(queryset=Equipment.objects.all())
    equipment_code = serializers.CharField(source="equipment.code", read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", read_only=True)
    equipment_type = serializers.CharField(source="equipment.equipment_type", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    responsible_role = serializers.CharField(required=False, allow_blank=True, default="")
    responsible_role_display = serializers.CharField(
        source="get_responsible_role_display", read_only=True
    )
    checklist = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False, default=list
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    runs_done = serializers.SerializerMethodField()
    is_due = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = MaintenancePlan
        fields = [
            "id",
            "equipment",
            "equipment_code",
            "equipment_name",
            "equipment_type",
            "kind",
            "kind_display",
            "title",
            "interval_days",
            "interval_runs",
            "checklist",
            "responsible_role",
            "responsible_role_display",
            "next_due_date",
            "last_done_at",
            "note",
            "is_active",
            "runs_done",
            "is_due",
            "is_overdue",
        ]
        read_only_fields = ["last_done_at", "is_active"]

    def _status(self, plan: MaintenancePlan) -> selectors.PlanStatus:
        cache: dict[int, selectors.PlanStatus] = self.context.setdefault(  # type: ignore[attr-defined]
            "_plan_status", {}
        )
        if plan.pk not in cache:
            cache[plan.pk] = selectors.plan_status(plan)
        return cache[plan.pk]

    def get_runs_done(self, plan: MaintenancePlan) -> int | None:
        return self._status(plan).runs_done

    def get_is_due(self, plan: MaintenancePlan) -> bool:
        return self._status(plan).is_due

    def get_is_overdue(self, plan: MaintenancePlan) -> bool:
        return self._status(plan).is_overdue


class WorkOrderPartSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True, default=None)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True, default=None)
    location_code = serializers.CharField(source="location.code", read_only=True, default=None)

    class Meta:
        model = WorkOrderPart
        fields = [
            "id",
            "material",
            "material_code",
            "lot",
            "lot_no",
            "location",
            "location_code",
            "description",
            "quantity",
            "unit_text",
            "movement",
        ]
        read_only_fields = fields


class PartCreateSerializer(serializers.Serializer):
    material = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.select_related("base_unit"), required=False, allow_null=True
    )
    lot = serializers.PrimaryKeyRelatedField(
        queryset=Lot.objects.all(), required=False, allow_null=True
    )
    location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")
    quantity = _quantity()
    unit_text = serializers.CharField(required=False, allow_blank=True, default="")


class WorkOrderSerializer(serializers.ModelSerializer):
    equipment = serializers.PrimaryKeyRelatedField(queryset=Equipment.objects.all())
    equipment_code = serializers.CharField(source="equipment.code", read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", read_only=True)
    status_display = serializers.SerializerMethodField()
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    responsible_role = serializers.CharField(required=False, allow_blank=True, default="")
    responsible_role_display = serializers.CharField(
        source="get_responsible_role_display", read_only=True
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")
    checklist = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False, default=list, write_only=True
    )
    checklist_rows = serializers.JSONField(source="checklist", read_only=True)
    plan_title = serializers.CharField(source="plan.title", read_only=True, default=None)
    previous_product_code = serializers.CharField(
        source="previous_product.code", read_only=True, default=None
    )
    calibration_result_display = serializers.CharField(
        source="get_calibration_result_display", read_only=True
    )
    created_by_name = UserNameField(source="created_by")
    started_by_name = UserNameField(source="started_by")
    completed_by_name = UserNameField(source="completed_by")
    parts = WorkOrderPartSerializer(many=True, read_only=True)
    downtime_minutes = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceWorkOrder
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "equipment",
            "equipment_code",
            "equipment_name",
            "plan",
            "plan_title",
            "source",
            "source_display",
            "kind",
            "kind_display",
            "title",
            "description",
            "responsible_role",
            "responsible_role_display",
            "due_date",
            "checklist",
            "checklist_rows",
            "previous_product",
            "previous_product_code",
            "started_at",
            "started_by_name",
            "completed_at",
            "completed_by_name",
            "work_done",
            "duration_minutes",
            "calibration_result",
            "calibration_result_display",
            "certificate_no",
            "cancel_reason",
            "created_at",
            "created_by_name",
            "parts",
            "downtime_minutes",
        ]
        read_only_fields = [
            "number",
            "status",
            "plan",
            "source",
            "previous_product",
            "started_at",
            "completed_at",
            "work_done",
            "duration_minutes",
            "calibration_result",
            "certificate_no",
            "cancel_reason",
            "created_at",
        ]

    def get_status_display(self, order: MaintenanceWorkOrder) -> str:
        return work_order_states.label(order.status)

    def get_downtime_minutes(self, order: MaintenanceWorkOrder) -> int | None:
        rows = [d for d in order.downtimes.all() if d.ended_at is not None]
        if not rows:
            return None
        return sum(selectors._minutes(d.started_at, d.ended_at) for d in rows if d.ended_at)


class CompleteSerializer(serializers.Serializer):
    work_done = serializers.CharField(allow_blank=True)
    duration_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    checklist = ChecklistRowSerializer(many=True, required=False)
    calibration_result = serializers.ChoiceField(
        choices=MaintenanceWorkOrder.CalibrationResult.choices, required=False, allow_blank=True
    )
    certificate_no = serializers.CharField(required=False, allow_blank=True, default="")


class BreakdownSerializer(serializers.Serializer):
    equipment = serializers.PrimaryKeyRelatedField(queryset=Equipment.objects.all())
    description = serializers.CharField(allow_blank=True)
    stop_equipment = serializers.BooleanField(required=False, default=True)


class CleaningSerializer(serializers.Serializer):
    equipment = serializers.PrimaryKeyRelatedField(queryset=Equipment.objects.all())
    work_done = serializers.CharField(allow_blank=True)
    checklist = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False, default=list
    )
    duration_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class DowntimeSerializer(serializers.ModelSerializer):
    equipment = serializers.PrimaryKeyRelatedField(queryset=Equipment.objects.all())
    equipment_code = serializers.CharField(source="equipment.code", read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", read_only=True)
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    started_at = serializers.DateTimeField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    work_order_number = serializers.CharField(
        source="work_order.number", read_only=True, default=None
    )
    created_by_name = UserNameField(source="created_by")
    ended_by_name = UserNameField(source="ended_by")
    minutes = serializers.SerializerMethodField()

    class Meta:
        model = Downtime
        fields = [
            "id",
            "equipment",
            "equipment_code",
            "equipment_name",
            "reason",
            "reason_display",
            "started_at",
            "ended_at",
            "note",
            "end_note",
            "work_order",
            "work_order_number",
            "created_by_name",
            "ended_by_name",
            "minutes",
        ]
        read_only_fields = ["ended_at", "end_note", "work_order"]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_minutes(self, downtime: Downtime) -> int | None:
        if downtime.ended_at is None:
            return None
        return selectors._minutes(downtime.started_at, downtime.ended_at)


class EndDowntimeSerializer(serializers.Serializer):
    ended_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class ChangeoverRuleSerializer(serializers.ModelSerializer):
    from_product = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    to_product = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    from_product_code = serializers.CharField(source="from_product.code", read_only=True)
    from_product_name = serializers.CharField(source="from_product.name", read_only=True)
    to_product_code = serializers.CharField(source="to_product.code", read_only=True)
    to_product_name = serializers.CharField(source="to_product.name", read_only=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = ChangeoverRule
        fields = [
            "id",
            "from_product",
            "from_product_code",
            "from_product_name",
            "to_product",
            "to_product_code",
            "to_product_name",
            "note",
            "is_active",
        ]
        read_only_fields = ["is_active"]


class CalibrationStatusSerializer(serializers.Serializer):
    equipment = serializers.IntegerField(source="equipment.pk")
    equipment_code = serializers.CharField(source="equipment.code")
    equipment_name = serializers.CharField(source="equipment.name")
    status = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    next_due_date = serializers.DateField(allow_null=True)
    days_left = serializers.IntegerField(allow_null=True)
    is_down = serializers.BooleanField()


class CleaningCheckSerializer(serializers.Serializer):
    required = serializers.BooleanField()  # type: ignore[assignment]
    previous_product_code = serializers.CharField(allow_null=True)
    previous_product_name = serializers.CharField(allow_null=True)
    is_down = serializers.BooleanField()
    downtime_reason = serializers.CharField(allow_null=True)


class DowntimeSummarySerializer(serializers.Serializer):
    equipment_id = serializers.IntegerField()
    equipment_code = serializers.CharField()
    equipment_name = serializers.CharField()
    reason = serializers.CharField()
    reason_display = serializers.CharField()
    count = serializers.IntegerField()
    minutes = serializers.IntegerField()
