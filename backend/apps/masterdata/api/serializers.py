from typing import Any

from rest_framework import serializers

from apps.masterdata.models import (
    Customer,
    Equipment,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)

AUDIT_FIELDS = ["is_active", "created_at", "updated_at"]
# Benzersizlik servis katmanında (kod büyük harfe çevrildikten sonra) denetlenir.
NO_UNIQUE_VALIDATOR: dict[str, dict[str, Any]] = {"code": {"validators": []}}


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = UnitOfMeasure
        fields = [
            "id",
            "code",
            "name",
            "kind",
            "kind_display",
            "factor_to_kind_base",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class MaterialCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterialCategory
        fields = ["id", "code", "name", *AUDIT_FIELDS]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class MaterialUnitConversionSerializer(serializers.ModelSerializer):
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    material_code = serializers.CharField(source="material.code", read_only=True)
    base_unit_code = serializers.CharField(source="material.base_unit.code", read_only=True)

    class Meta:
        model = MaterialUnitConversion
        fields = [
            "id",
            "material",
            "material_code",
            "unit",
            "unit_code",
            "factor_to_base",
            "base_unit_code",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        validators: list = []


class MaterialSerializer(serializers.ModelSerializer):
    material_type_display = serializers.CharField(
        source="get_material_type_display", read_only=True
    )
    base_unit_code = serializers.CharField(source="base_unit.code", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)

    class Meta:
        model = Material
        fields = [
            "id",
            "code",
            "name",
            "material_type",
            "material_type_display",
            "category",
            "category_name",
            "base_unit",
            "base_unit_code",
            "density",
            "shelf_life_days",
            "min_stock",
            "requires_incoming_qc",
            "is_hazardous",
            "storage_notes",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class MaterialDetailSerializer(MaterialSerializer):
    conversions = MaterialUnitConversionSerializer(many=True, read_only=True)

    class Meta(MaterialSerializer.Meta):
        fields = [*MaterialSerializer.Meta.fields, "conversions"]


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "code", "name", *AUDIT_FIELDS]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class LocationSerializer(serializers.ModelSerializer):
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    location_type_display = serializers.CharField(
        source="get_location_type_display", read_only=True
    )

    class Meta:
        model = Location
        fields = [
            "id",
            "warehouse",
            "warehouse_code",
            "code",
            "name",
            "location_type",
            "location_type_display",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class EquipmentSerializer(serializers.ModelSerializer):
    equipment_type_display = serializers.CharField(
        source="get_equipment_type_display", read_only=True
    )
    capacity_unit_code = serializers.CharField(
        source="capacity_unit.code", read_only=True, default=None
    )
    location_code = serializers.CharField(source="location.code", read_only=True, default=None)

    class Meta:
        model = Equipment
        fields = [
            "id",
            "code",
            "name",
            "equipment_type",
            "equipment_type_display",
            "capacity",
            "capacity_unit",
            "capacity_unit_code",
            "location",
            "location_code",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


PARTNER_FIELDS = [
    "id",
    "code",
    "name",
    "tax_office",
    "tax_number",
    "address",
    "phone",
    "email",
    "contact_person",
    *AUDIT_FIELDS,
]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = PARTNER_FIELDS
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [*PARTNER_FIELDS, "min_remaining_shelf_life_days"]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class ImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField(label="Dosya (.xlsx / .csv)")
    confirm = serializers.BooleanField(
        label="Onayla", default=False, help_text="false: yalnızca önizleme, true: aktar"
    )


class ImportRowErrorSerializer(serializers.Serializer):
    column = serializers.CharField()
    message = serializers.CharField()


IMPORT_ROW_ACTIONS = ["create", "update"]


class ImportRowSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    code = serializers.CharField()
    action = serializers.ChoiceField(choices=IMPORT_ROW_ACTIONS)
    errors = ImportRowErrorSerializer(many=True)  # type: ignore[assignment]


class ImportReportSerializer(serializers.Serializer):
    kind = serializers.CharField()
    total = serializers.IntegerField()
    valid = serializers.IntegerField()
    invalid = serializers.IntegerField()
    to_create = serializers.IntegerField()
    to_update = serializers.IntegerField()
    file_errors = serializers.ListField(child=serializers.CharField())
    rows = ImportRowSerializer(many=True)
    imported = serializers.BooleanField()
