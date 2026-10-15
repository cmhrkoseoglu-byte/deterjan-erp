from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.masterdata.fields import normalize_code
from apps.masterdata.models import UnitOfMeasure
from apps.recipes.models import Recipe, RecipeLine, RecipeStep, RecipeVersion
from apps.recipes.services import can_approve


class RecipeSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    approved_version = serializers.SerializerMethodField()
    latest_version_no = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = Recipe
        fields = [
            "id",
            "code",
            "name",
            "product",
            "product_code",
            "product_name",
            "notes",
            "approved_version",
            "latest_version_no",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["is_active", "created_at", "updated_at"]
        extra_kwargs: dict[str, dict[str, Any]] = {"code": {"validators": []}}

    def get_approved_version(self, obj: Recipe) -> dict[str, int] | None:
        # get_queryset'te prefetch edilir: approved_versions (en fazla bir kayıt).
        approved = getattr(obj, "approved_versions", None)
        if approved is None:
            approved = list(obj.versions.filter(status=RecipeVersion.Status.APPROVED))
        if not approved:
            return None
        return {"id": approved[0].pk, "version_no": approved[0].version_no}


class RecipeLineSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    sequence = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    class Meta:
        model = RecipeLine
        fields = [
            "id",
            "version",
            "sequence",
            "material",
            "material_code",
            "material_name",
            "quantity",
            "unit",
            "unit_code",
            "tolerance_pct",
            "instruction",
            "is_water",
        ]
        read_only_fields = ["version"]
        validators: list = []


class RecipeStepSerializer(serializers.ModelSerializer):
    sequence = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    class Meta:
        model = RecipeStep
        fields = [
            "id",
            "version",
            "sequence",
            "description",
            "duration_min",
            "temperature_c",
            "mixer_rpm",
        ]
        read_only_fields = ["version"]
        validators: list = []


class RecipeVersionSerializer(serializers.ModelSerializer):
    recipe_code = serializers.CharField(source="recipe.code", read_only=True)
    recipe_name = serializers.CharField(source="recipe.name", read_only=True)
    product = serializers.IntegerField(source="recipe.product_id", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    batch_unit_code = serializers.CharField(source="batch_unit.code", read_only=True)
    copied_from_no = serializers.IntegerField(
        source="copied_from.version_no", read_only=True, default=None
    )
    approved_by_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RecipeVersion
        fields = [
            "id",
            "recipe",
            "recipe_code",
            "recipe_name",
            "product",
            "version_no",
            "status",
            "status_display",
            "batch_size",
            "batch_unit",
            "batch_unit_code",
            "change_note",
            "copied_from",
            "copied_from_no",
            "approved_by",
            "approved_by_name",
            "approved_at",
            "obsoleted_at",
            "created_at",
            "created_by_name",
            "updated_at",
        ]
        read_only_fields = [
            "recipe",
            "version_no",
            "status",
            "copied_from",
            "approved_by",
            "approved_at",
            "obsoleted_at",
            "created_at",
            "updated_at",
        ]

    def get_approved_by_name(self, obj: RecipeVersion) -> str | None:
        return str(obj.approved_by) if obj.approved_by else None

    def get_created_by_name(self, obj: RecipeVersion) -> str | None:
        return str(obj.created_by) if obj.created_by else None


class RecipeVersionDetailSerializer(RecipeVersionSerializer):
    lines = RecipeLineSerializer(many=True, read_only=True)
    steps = RecipeStepSerializer(many=True, read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()

    class Meta(RecipeVersionSerializer.Meta):
        fields = [*RecipeVersionSerializer.Meta.fields, "lines", "steps", "can_edit", "can_approve"]

    def get_can_edit(self, obj: RecipeVersion) -> bool:
        return obj.is_editable

    def get_can_approve(self, obj: RecipeVersion) -> bool:
        request = self.context.get("request")
        return obj.is_editable and can_approve(getattr(request, "user", None))


class RecipeVersionCreateSerializer(serializers.ModelSerializer):
    lines = RecipeLineSerializer(many=True, required=False)
    steps = RecipeStepSerializer(many=True, required=False)

    class Meta:
        model = RecipeVersion
        fields = ["batch_size", "batch_unit", "change_note", "lines", "steps"]


class VersionActionSerializer(serializers.Serializer):
    note = serializers.CharField(label="Not", required=False, allow_blank=True, default="")


class ScaleQuerySerializer(serializers.Serializer):
    qty = serializers.DecimalField(
        label="Hedef miktar", max_digits=18, decimal_places=4, min_value=Decimal("0.0001")
    )
    unit = serializers.CharField(label="Birim (kod ya da kimlik)")

    def validate_unit(self, value: str) -> UnitOfMeasure:
        lookup: dict[str, Any] = {"pk": int(value)} if value.isdigit() else {}
        if not lookup:
            lookup = {"code": normalize_code(value)}
        unit = UnitOfMeasure.objects.filter(**lookup).first()
        if unit is None:
            raise serializers.ValidationError("Birim bulunamadı.")
        return unit


class ScaledRequirementSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    line = serializers.IntegerField(source="line.pk")
    material = serializers.IntegerField(source="material.pk")
    material_code = serializers.CharField(source="material.code")
    material_name = serializers.CharField(source="material.name")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    unit = serializers.IntegerField(source="unit.pk")
    unit_code = serializers.CharField(source="unit.code")
    tolerance_pct = serializers.DecimalField(max_digits=5, decimal_places=2)
    is_water = serializers.BooleanField()
