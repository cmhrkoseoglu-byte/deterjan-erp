from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.filling import selectors
from apps.filling.models import (
    FillingConsumption,
    FillingOrder,
    FillingRun,
    PackagingPick,
    PackagingSpec,
    PackagingSpecLine,
    RunLot,
    ScrapRecord,
)
from apps.filling.state import filling_order_states, filling_run_states
from apps.inventory.api.serializers import UserNameField
from apps.inventory.models import StockBalance
from apps.masterdata.models import Equipment, Location, Material, UnitOfMeasure


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, **kwargs)


def _pct(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=8, decimal_places=2, **kwargs)


# --- ambalaj reçetesi --------------------------------------------------------------------------


class PackagingSpecLineSerializer(serializers.ModelSerializer):
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    sequence = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    scrap_allowance_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True
    )

    class Meta:
        model = PackagingSpecLine
        fields = [
            "id",
            "spec",
            "sequence",
            "material",
            "material_code",
            "material_name",
            "unit",
            "quantity_per_unit",
            "scrap_allowance_pct",
        ]
        read_only_fields = ["spec"]
        validators: list = []


class PackagingSpecSerializer(serializers.ModelSerializer):
    finished_product = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    finished_product_code = serializers.CharField(source="finished_product.code", read_only=True)
    finished_product_name = serializers.CharField(source="finished_product.name", read_only=True)
    bulk_product = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    bulk_product_code = serializers.CharField(source="bulk_product.code", read_only=True)
    bulk_product_name = serializers.CharField(source="bulk_product.name", read_only=True)
    bulk_unit = serializers.CharField(source="bulk_product.base_unit.code", read_only=True)
    fill_unit = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all())
    fill_unit_code = serializers.CharField(source="fill_unit.code", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    copied_from_no = serializers.IntegerField(
        source="copied_from.version_no", read_only=True, default=None
    )
    change_note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    approved_by_name = UserNameField(source="approved_by")
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = PackagingSpec
        fields = [
            "id",
            "finished_product",
            "finished_product_code",
            "finished_product_name",
            "bulk_product",
            "bulk_product_code",
            "bulk_product_name",
            "bulk_unit",
            "version_no",
            "status",
            "status_display",
            "fill_quantity",
            "fill_unit",
            "fill_unit_code",
            "fill_tolerance_pct",
            "units_per_case",
            "cases_per_pallet",
            "change_note",
            "copied_from",
            "copied_from_no",
            "approved_by_name",
            "approved_at",
            "obsoleted_at",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = [
            "version_no",
            "status",
            "copied_from",
            "approved_at",
            "obsoleted_at",
            "created_at",
        ]


class PackagingSpecDetailSerializer(PackagingSpecSerializer):
    lines = PackagingSpecLineSerializer(many=True, read_only=True)
    is_editable = serializers.SerializerMethodField()

    class Meta(PackagingSpecSerializer.Meta):
        fields = [*PackagingSpecSerializer.Meta.fields, "lines", "is_editable"]

    def get_is_editable(self, spec: PackagingSpec) -> bool:
        return spec.status == PackagingSpec.Status.DRAFT


class PackagingSpecCreateSerializer(PackagingSpecSerializer):
    lines = PackagingSpecLineSerializer(many=True, required=False)

    class Meta(PackagingSpecSerializer.Meta):
        fields = [*PackagingSpecSerializer.Meta.fields, "lines"]


class FillingNoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


# --- dolum emri --------------------------------------------------------------------------------


class FillingOrderSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    finished_product = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    finished_product_code = serializers.CharField(source="finished_product.code", read_only=True)
    finished_product_name = serializers.CharField(source="finished_product.name", read_only=True)
    unit = serializers.CharField(source="finished_product.base_unit.code", read_only=True)
    packaging_spec_version = serializers.IntegerField(
        source="packaging_spec.version_no", read_only=True
    )
    bulk_product = serializers.IntegerField(source="packaging_spec.bulk_product_id", read_only=True)
    bulk_product_code = serializers.CharField(
        source="packaging_spec.bulk_product.code", read_only=True
    )
    fill_quantity = _quantity(source="packaging_spec.fill_quantity", read_only=True)
    fill_unit_code = serializers.CharField(source="packaging_spec.fill_unit.code", read_only=True)
    filling_line = serializers.PrimaryKeyRelatedField(
        queryset=Equipment.objects.select_related("location")
    )
    filling_line_code = serializers.CharField(source="filling_line.code", read_only=True)
    filling_line_name = serializers.CharField(source="filling_line.name", read_only=True)
    line_location_code = serializers.CharField(
        source="filling_line.location.code", read_only=True, default=None
    )
    output_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    output_location_code = serializers.CharField(source="output_location.code", read_only=True)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = FillingOrder
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "finished_product",
            "finished_product_code",
            "finished_product_name",
            "unit",
            "packaging_spec",
            "packaging_spec_version",
            "bulk_product",
            "bulk_product_code",
            "fill_quantity",
            "fill_unit_code",
            "planned_units",
            "filling_line",
            "filling_line_code",
            "filling_line_name",
            "line_location_code",
            "output_location",
            "output_location_code",
            "planned_date",
            "notes",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "number", "status", "packaging_spec", "created_at"]

    def get_status_display(self, order: FillingOrder) -> str:
        return filling_order_states.label(order.status)


class FillingRequirementRowSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="requirement.id")
    sequence = serializers.IntegerField(source="requirement.sequence")
    material = serializers.IntegerField(source="requirement.material_id")
    material_code = serializers.CharField(source="requirement.material.code")
    material_name = serializers.CharField(source="requirement.material.name")
    unit = serializers.CharField(source="requirement.material.base_unit.code")
    quantity_per_unit = serializers.DecimalField(
        max_digits=18, decimal_places=6, source="requirement.spec_line.quantity_per_unit"
    )
    scrap_allowance_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, source="requirement.spec_line.scrap_allowance_pct"
    )
    required_quantity = _quantity(source="requirement.required_quantity")
    net_quantity = _quantity()
    picked_quantity = _quantity(source="picked")
    to_pick = _quantity()
    is_ready = serializers.BooleanField()


class PackagingPickSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="requirement.material.code", read_only=True)
    unit = serializers.CharField(source="requirement.material.base_unit.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    from_location_code = serializers.CharField(source="from_location.code", read_only=True)
    to_location_code = serializers.CharField(source="to_location.code", read_only=True)
    picked_by_name = UserNameField(source="picked_by")

    class Meta:
        model = PackagingPick
        fields = [
            "id",
            "requirement",
            "material_code",
            "unit",
            "lot",
            "lot_no",
            "quantity",
            "from_location",
            "from_location_code",
            "to_location",
            "to_location_code",
            "picked_by_name",
            "picked_at",
            "returned_at",
        ]
        read_only_fields = fields


class StockRowSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    expiry_date = serializers.DateField(source="lot.expiry_date", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)

    class Meta:
        model = StockBalance
        fields = [
            "material",
            "material_code",
            "unit",
            "lot",
            "lot_no",
            "expiry_date",
            "location",
            "location_code",
            "quantity",
        ]
        read_only_fields = fields


class FillingRunSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="order.number", read_only=True)
    order_status = serializers.CharField(source="order.status", read_only=True)
    finished_product_code = serializers.CharField(
        source="order.finished_product.code", read_only=True
    )
    finished_product_name = serializers.CharField(
        source="order.finished_product.name", read_only=True
    )
    output_lot_no = serializers.CharField(source="output_lot.lot_no", read_only=True)
    output_lot_status = serializers.CharField(source="output_lot.status", read_only=True)
    output_lot_status_display = serializers.CharField(
        source="output_lot.get_status_display", read_only=True
    )
    operator_name = UserNameField(source="operator")
    finished_by_name = UserNameField(source="finished_by")

    class Meta:
        model = FillingRun
        fields = [
            "id",
            "sequence",
            "order",
            "order_number",
            "order_status",
            "finished_product_code",
            "finished_product_name",
            "status",
            "status_display",
            "output_lot",
            "output_lot_no",
            "output_lot_status",
            "output_lot_status_display",
            "operator_name",
            "started_at",
            "finished_at",
            "finished_by_name",
            "good_units",
            "theoretical_bulk",
            "actual_bulk",
            "bulk_variance_pct",
            "finish_note",
            "cancel_reason",
        ]
        read_only_fields = fields

    def get_status_display(self, run: FillingRun) -> str:
        return filling_run_states.label(run.status)


class FillingOrderDetailSerializer(FillingOrderSerializer):
    requirements = serializers.SerializerMethodField()
    picks = serializers.SerializerMethodField()
    runs = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    approved_by_name = UserNameField(source="approved_by")
    units_per_case = serializers.IntegerField(
        source="packaging_spec.units_per_case", read_only=True
    )

    class Meta(FillingOrderSerializer.Meta):
        fields = [
            *FillingOrderSerializer.Meta.fields,
            "units_per_case",
            "requirements",
            "picks",
            "runs",
            "allowed_transitions",
            "approved_by_name",
            "approved_at",
            "completed_at",
            "cancel_reason",
        ]
        read_only_fields = [*FillingOrderSerializer.Meta.read_only_fields, "cancel_reason"]

    @extend_schema_field(FillingRequirementRowSerializer(many=True))
    def get_requirements(self, order: FillingOrder) -> Any:
        return FillingRequirementRowSerializer(selectors.requirement_rows(order), many=True).data

    @extend_schema_field(PackagingPickSerializer(many=True))
    def get_picks(self, order: FillingOrder) -> Any:
        picks = order.picks.select_related(
            "requirement__material__base_unit", "lot", "from_location", "to_location", "picked_by"
        ).order_by("picked_at", "id")
        return PackagingPickSerializer(picks, many=True).data

    @extend_schema_field(FillingRunSerializer(many=True))
    def get_runs(self, order: FillingOrder) -> Any:
        runs = order.runs.select_related(
            "order__finished_product", "output_lot", "operator", "finished_by"
        ).order_by("sequence")
        return FillingRunSerializer(runs, many=True).data

    def get_allowed_transitions(self, order: FillingOrder) -> list[str]:
        return filling_order_states.allowed_transitions(order.status)


# --- dolum partisi -----------------------------------------------------------------------------


class FillingConsumptionSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    material_code = serializers.CharField(source="material.code", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    consumed_by_name = UserNameField(source="consumed_by")

    class Meta:
        model = FillingConsumption
        fields = [
            "id",
            "kind",
            "kind_display",
            "material",
            "material_code",
            "unit",
            "lot",
            "lot_no",
            "location",
            "location_code",
            "quantity",
            "consumed_by_name",
            "consumed_at",
        ]
        read_only_fields = fields


class ScrapRecordSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    reason_display = serializers.CharField(source="get_reason_code_display", read_only=True)
    material_code = serializers.CharField(source="material.code", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    recorded_by_name = UserNameField(source="recorded_by")

    class Meta:
        model = ScrapRecord
        fields = [
            "id",
            "kind",
            "kind_display",
            "material",
            "material_code",
            "unit",
            "lot",
            "lot_no",
            "quantity",
            "reason_code",
            "reason_display",
            "note",
            "recorded_by_name",
            "recorded_at",
        ]
        read_only_fields = fields


class RunLotSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    scanned_by_name = UserNameField(source="scanned_by")

    class Meta:
        model = RunLot
        fields = [
            "id",
            "material",
            "material_code",
            "material_name",
            "lot",
            "lot_no",
            "scanned_by_name",
            "scanned_at",
        ]
        read_only_fields = fields


class PackagingRowSerializer(serializers.Serializer):
    material = serializers.IntegerField(source="line.material_id")
    material_code = serializers.CharField(source="line.material.code")
    material_name = serializers.CharField(source="line.material.name")
    unit = serializers.CharField(source="line.material.base_unit.code")
    quantity_per_unit = serializers.DecimalField(
        max_digits=18, decimal_places=6, source="line.quantity_per_unit"
    )
    scrap_allowance_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, source="line.scrap_allowance_pct"
    )
    theoretical = _quantity()
    consumed = _quantity()
    scrap = _quantity()
    actual = _quantity()
    variance = _quantity()
    variance_pct = _pct()
    over_allowance = serializers.BooleanField()


class BulkRowSerializer(serializers.Serializer):
    theoretical = _quantity()
    consumed = _quantity()
    scrap = _quantity()
    actual = _quantity()
    variance = _quantity()
    variance_pct = _pct()


class ConsumptionReportSerializer(serializers.Serializer):
    """Teorik / gerçek tüketim raporu."""

    good_units = serializers.IntegerField()
    scrapped_units = serializers.IntegerField()
    bulk_product_code = serializers.SerializerMethodField()
    bulk_unit = serializers.SerializerMethodField()
    threshold_pct = _pct()
    bulk_over_threshold = serializers.BooleanField()
    bulk = BulkRowSerializer()
    packaging = PackagingRowSerializer(many=True)
    runs = FillingRunSerializer(many=True)

    def get_bulk_product_code(self, report: selectors.ConsumptionReport) -> str:
        return str(self.context["order"].packaging_spec.bulk_product.code)

    def get_bulk_unit(self, report: selectors.ConsumptionReport) -> str:
        return str(self.context["order"].packaging_spec.bulk_product.base_unit.code)


class FillingRunDetailSerializer(FillingRunSerializer):
    bulk_product = serializers.IntegerField(
        source="order.packaging_spec.bulk_product_id", read_only=True
    )
    bulk_product_code = serializers.CharField(
        source="order.packaging_spec.bulk_product.code", read_only=True
    )
    bulk_unit = serializers.CharField(
        source="order.packaging_spec.bulk_product.base_unit.code", read_only=True
    )
    fill_quantity = _quantity(source="order.packaging_spec.fill_quantity", read_only=True)
    fill_unit_code = serializers.CharField(
        source="order.packaging_spec.fill_unit.code", read_only=True
    )
    planned_units = serializers.IntegerField(source="order.planned_units", read_only=True)
    line_location_code = serializers.CharField(
        source="order.filling_line.location.code", read_only=True, default=None
    )
    consumptions = serializers.SerializerMethodField()
    scraps = serializers.SerializerMethodField()
    scanned_lots = serializers.SerializerMethodField()
    packaging = serializers.SerializerMethodField()
    bulk_lots = serializers.SerializerMethodField()
    line_stock = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta(FillingRunSerializer.Meta):
        fields = [
            *FillingRunSerializer.Meta.fields,
            "bulk_product",
            "bulk_product_code",
            "bulk_unit",
            "fill_quantity",
            "fill_unit_code",
            "planned_units",
            "line_location_code",
            "consumptions",
            "scraps",
            "scanned_lots",
            "packaging",
            "bulk_lots",
            "line_stock",
            "allowed_transitions",
        ]
        read_only_fields = fields

    @extend_schema_field(FillingConsumptionSerializer(many=True))
    def get_consumptions(self, run: FillingRun) -> Any:
        rows = run.consumptions.select_related(
            "material__base_unit", "lot", "location", "consumed_by"
        ).order_by("consumed_at", "id")
        return FillingConsumptionSerializer(rows, many=True).data

    @extend_schema_field(ScrapRecordSerializer(many=True))
    def get_scraps(self, run: FillingRun) -> Any:
        rows = run.scraps.select_related("material__base_unit", "lot", "recorded_by").order_by(
            "recorded_at", "id"
        )
        return ScrapRecordSerializer(rows, many=True).data

    @extend_schema_field(RunLotSerializer(many=True))
    def get_scanned_lots(self, run: FillingRun) -> Any:
        rows = run.run_lots.select_related("material", "lot", "scanned_by")
        return RunLotSerializer(rows, many=True).data

    @extend_schema_field(PackagingSpecLineSerializer(many=True))
    def get_packaging(self, run: FillingRun) -> Any:
        lines = run.order.packaging_spec.lines.select_related("material__base_unit")
        return PackagingSpecLineSerializer(lines.order_by("sequence"), many=True).data

    @extend_schema_field(StockRowSerializer(many=True))
    def get_bulk_lots(self, run: FillingRun) -> Any:
        if run.status != FillingRun.Status.IN_PROGRESS:
            return []
        return StockRowSerializer(selectors.bulk_lots(run.order)[:20], many=True).data

    @extend_schema_field(StockRowSerializer(many=True))
    def get_line_stock(self, run: FillingRun) -> Any:
        if run.status != FillingRun.Status.IN_PROGRESS:
            return []
        return StockRowSerializer(selectors.line_stock(run.order), many=True).data

    def get_allowed_transitions(self, run: FillingRun) -> list[str]:
        return filling_run_states.allowed_transitions(run.status)


# --- eylem gövdeleri ---------------------------------------------------------------------------


class LotRefSerializer(serializers.Serializer):
    """Lot kimlikle ya da okutulan lot numarasıyla verilir."""

    lot = serializers.IntegerField(required=False, allow_null=True)
    lot_no = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("lot") and not attrs.get("lot_no", "").strip():
            raise serializers.ValidationError({"lot_no": ["Lot okutulmalı ya da seçilmelidir."]})
        return attrs


class PackagingPickCreateSerializer(LotRefSerializer):
    requirement = serializers.IntegerField()
    quantity = _quantity()
    from_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class RunStartSerializer(serializers.Serializer):
    order = serializers.PrimaryKeyRelatedField(queryset=FillingOrder.objects.all())


class BulkConsumeSerializer(LotRefSerializer):
    quantity = _quantity()


class ScrapCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ScrapRecord.Kind.choices)
    reason_code = serializers.ChoiceField(choices=ScrapRecord.Reason.choices)
    quantity = _quantity()
    lot = serializers.IntegerField(required=False, allow_null=True)
    lot_no = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        has_lot = attrs.get("lot") or attrs.get("lot_no", "").strip()
        if attrs["kind"] != ScrapRecord.Kind.FINISHED and not has_lot:
            raise serializers.ValidationError({"lot_no": ["Fire için lot okutulmalıdır."]})
        return attrs


class RunFinishSerializer(serializers.Serializer):
    good_units = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, default="")
