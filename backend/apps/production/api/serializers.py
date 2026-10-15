from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory.api.serializers import UserNameField
from apps.inventory.models import StockBalance
from apps.masterdata.models import Equipment, Location, UnitOfMeasure
from apps.production import selectors, services
from apps.production.models import (
    BatchConsumption,
    MaterialPick,
    ProductionBatch,
    ProductionOrder,
)
from apps.production.state import production_batch_states, production_order_states
from apps.recipes.models import RecipeVersion


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, **kwargs)


# --- emir --------------------------------------------------------------------------------------


class ProductionOrderSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    priority_display = serializers.CharField(source="get_priority_display", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    base_unit = serializers.CharField(source="product.base_unit.code", read_only=True)
    recipe_code = serializers.CharField(source="recipe_version.recipe.code", read_only=True)
    recipe_id = serializers.IntegerField(source="recipe_version.recipe_id", read_only=True)
    version_no = serializers.IntegerField(source="recipe_version.version_no", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    equipment_code = serializers.CharField(source="equipment.code", read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", read_only=True)
    production_location_code = serializers.CharField(
        source="production_location.code", read_only=True
    )
    recipe_version = serializers.PrimaryKeyRelatedField(
        queryset=RecipeVersion.objects.select_related("recipe__product")
    )
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all())
    equipment = serializers.PrimaryKeyRelatedField(
        queryset=Equipment.objects.select_related("location")
    )
    production_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = ProductionOrder
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "product",
            "product_code",
            "product_name",
            "base_unit",
            "recipe_version",
            "recipe_id",
            "recipe_code",
            "version_no",
            "planned_quantity",
            "unit",
            "unit_code",
            "planned_base_quantity",
            "planned_date",
            "equipment",
            "equipment_code",
            "equipment_name",
            "production_location",
            "production_location_code",
            "priority",
            "priority_display",
            "notes",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "number",
            "status",
            "product",
            "planned_base_quantity",
            "created_at",
        ]

    def get_status_display(self, order: ProductionOrder) -> str:
        return production_order_states.label(order.status)


class RequirementRowSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="requirement.id")
    sequence = serializers.IntegerField(source="requirement.sequence")
    material = serializers.IntegerField(source="requirement.material_id")
    material_code = serializers.CharField(source="requirement.material.code")
    material_name = serializers.CharField(source="requirement.material.name")
    unit = serializers.CharField(source="requirement.material.base_unit.code")
    required_quantity = _quantity(source="requirement.required_quantity")
    tolerance_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, source="requirement.tolerance_pct"
    )
    is_water = serializers.BooleanField(source="requirement.is_water")
    instruction = serializers.CharField(source="requirement.instruction")
    picked_quantity = _quantity(source="picked")
    consumed_quantity = _quantity(source="consumed")
    to_pick = _quantity()
    is_ready = serializers.BooleanField()


class MaterialPickSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="requirement.material.code", read_only=True)
    unit = serializers.CharField(source="requirement.material.base_unit.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    from_location_code = serializers.CharField(source="from_location.code", read_only=True)
    to_location_code = serializers.CharField(source="to_location.code", read_only=True)
    picked_by_name = UserNameField(source="picked_by")

    class Meta:
        model = MaterialPick
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


class ProductionBatchSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="order.number", read_only=True)
    order_status = serializers.CharField(source="order.status", read_only=True)
    product_code = serializers.CharField(source="order.product.code", read_only=True)
    product_name = serializers.CharField(source="order.product.name", read_only=True)
    unit = serializers.CharField(source="order.product.base_unit.code", read_only=True)
    equipment_code = serializers.CharField(source="equipment.code", read_only=True)
    output_lot_no = serializers.CharField(source="output_lot.lot_no", read_only=True)
    output_lot_status = serializers.CharField(source="output_lot.status", read_only=True)
    output_lot_status_display = serializers.CharField(
        source="output_lot.get_status_display", read_only=True
    )
    started_by_name = UserNameField(source="started_by")
    finished_by_name = UserNameField(source="finished_by")

    class Meta:
        model = ProductionBatch
        fields = [
            "id",
            "batch_no",
            "sequence",
            "order",
            "order_number",
            "order_status",
            "product_code",
            "product_name",
            "unit",
            "equipment",
            "equipment_code",
            "status",
            "status_display",
            "planned_quantity",
            "actual_output_quantity",
            "yield_pct",
            "output_lot",
            "output_lot_no",
            "output_lot_status",
            "output_lot_status_display",
            "started_at",
            "started_by_name",
            "finished_at",
            "finished_by_name",
            "finish_note",
            "cancel_reason",
        ]
        read_only_fields = fields

    def get_status_display(self, batch: ProductionBatch) -> str:
        return production_batch_states.label(batch.status)


class ProductionOrderDetailSerializer(ProductionOrderSerializer):
    requirements = serializers.SerializerMethodField()
    picks = serializers.SerializerMethodField()
    batches = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    suggested_batch_quantity = serializers.SerializerMethodField()
    approved_by_name = UserNameField(source="approved_by")

    class Meta(ProductionOrderSerializer.Meta):
        fields = [
            *ProductionOrderSerializer.Meta.fields,
            "requirements",
            "picks",
            "batches",
            "allowed_transitions",
            "remaining_quantity",
            "suggested_batch_quantity",
            "approved_by_name",
            "approved_at",
            "completed_at",
            "cancel_reason",
        ]
        read_only_fields = [*ProductionOrderSerializer.Meta.read_only_fields, "cancel_reason"]

    @extend_schema_field(RequirementRowSerializer(many=True))
    def get_requirements(self, order: ProductionOrder) -> Any:
        return RequirementRowSerializer(selectors.requirement_rows(order), many=True).data

    @extend_schema_field(MaterialPickSerializer(many=True))
    def get_picks(self, order: ProductionOrder) -> Any:
        picks = order.picks.select_related(
            "requirement__material__base_unit",
            "lot",
            "from_location",
            "to_location",
            "picked_by",
        ).order_by("picked_at", "id")
        return MaterialPickSerializer(picks, many=True).data

    @extend_schema_field(ProductionBatchSerializer(many=True))
    def get_batches(self, order: ProductionOrder) -> Any:
        batches = order.batches.select_related(
            "order__product__base_unit", "equipment", "output_lot", "started_by", "finished_by"
        ).order_by("sequence")
        return ProductionBatchSerializer(batches, many=True).data

    def get_allowed_transitions(self, order: ProductionOrder) -> list[str]:
        return production_order_states.allowed_transitions(order.status)

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_remaining_quantity(self, order: ProductionOrder) -> Decimal:
        return services.remaining_quantity(order)

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_suggested_batch_quantity(self, order: ProductionOrder) -> Decimal:
        return services.suggested_batch_quantity(order)


# --- şarj ---------------------------------------------------------------------------------------


class BatchConsumptionSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="requirement.material.code", read_only=True)
    unit = serializers.CharField(source="requirement.material.base_unit.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    weighed_by_name = UserNameField(source="weighed_by")

    class Meta:
        model = BatchConsumption
        fields = [
            "id",
            "requirement",
            "material_code",
            "unit",
            "lot",
            "lot_no",
            "location",
            "location_code",
            "planned_quantity",
            "actual_quantity",
            "deviation_pct",
            "deviation_note",
            "weighed_by_name",
            "weighed_at",
        ]
        read_only_fields = fields


class ConsumableLotSerializer(serializers.ModelSerializer):
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    expiry_date = serializers.DateField(source="lot.expiry_date", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)

    class Meta:
        model = StockBalance
        fields = ["lot", "lot_no", "expiry_date", "location", "location_code", "quantity"]
        read_only_fields = fields


class BatchLineSerializer(serializers.Serializer):
    requirement = serializers.IntegerField(source="requirement.id")
    sequence = serializers.IntegerField(source="requirement.sequence")
    material = serializers.IntegerField(source="requirement.material_id")
    material_code = serializers.CharField(source="requirement.material.code")
    material_name = serializers.CharField(source="requirement.material.name")
    unit = serializers.CharField(source="requirement.material.base_unit.code")
    tolerance_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, source="requirement.tolerance_pct"
    )
    is_water = serializers.BooleanField(source="requirement.is_water")
    instruction = serializers.CharField(source="requirement.instruction")
    planned_quantity = _quantity(source="planned")
    consumed_quantity = _quantity(source="consumed")
    deviation_pct = serializers.DecimalField(max_digits=8, decimal_places=2)
    state = serializers.ChoiceField(choices=["pending", "under", "ok", "over"])
    available = serializers.SerializerMethodField()

    @extend_schema_field(ConsumableLotSerializer(many=True))
    def get_available(self, line: selectors.BatchLine) -> Any:
        batch: ProductionBatch | None = self.context.get("batch")
        if batch is None or batch.status != ProductionBatch.Status.IN_PROGRESS:
            return []
        rows = selectors.consumable_balances(batch.order, line.requirement)[:10]
        return ConsumableLotSerializer(rows, many=True).data


class ProductionBatchDetailSerializer(ProductionBatchSerializer):
    lines = serializers.SerializerMethodField()
    consumptions = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta(ProductionBatchSerializer.Meta):
        fields = [
            *ProductionBatchSerializer.Meta.fields,
            "lines",
            "consumptions",
            "allowed_transitions",
        ]
        read_only_fields = fields

    @extend_schema_field(BatchLineSerializer(many=True))
    def get_lines(self, batch: ProductionBatch) -> Any:
        return BatchLineSerializer(
            selectors.batch_lines(batch), many=True, context={"batch": batch}
        ).data

    @extend_schema_field(BatchConsumptionSerializer(many=True))
    def get_consumptions(self, batch: ProductionBatch) -> Any:
        rows = batch.consumptions.select_related(
            "requirement__material__base_unit", "lot", "location", "weighed_by"
        ).order_by("weighed_at", "id")
        return BatchConsumptionSerializer(rows, many=True).data

    def get_allowed_transitions(self, batch: ProductionBatch) -> list[str]:
        return production_batch_states.allowed_transitions(batch.status)


# --- eylem gövdeleri ------------------------------------------------------------------------------


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class LotInputSerializer(serializers.Serializer):
    """Lot kimlikle ya da okutulan lot numarasıyla verilir."""

    requirement = serializers.IntegerField()
    lot = serializers.IntegerField(required=False, allow_null=True)
    lot_no = serializers.CharField(required=False, allow_blank=True, default="")
    quantity = _quantity()
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("lot") and not attrs.get("lot_no", "").strip():
            raise serializers.ValidationError({"lot_no": ["Lot okutulmalı ya da seçilmelidir."]})
        return attrs


class PickCreateSerializer(LotInputSerializer):
    from_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )


class BatchStartSerializer(serializers.Serializer):
    order = serializers.PrimaryKeyRelatedField(queryset=ProductionOrder.objects.all())
    equipment = serializers.PrimaryKeyRelatedField(
        queryset=Equipment.objects.all(), required=False, allow_null=True
    )
    planned_quantity = _quantity(required=False, allow_null=True)


class BatchFinishSerializer(serializers.Serializer):
    output_quantity = _quantity()
    note = serializers.CharField(required=False, allow_blank=True, default="")
