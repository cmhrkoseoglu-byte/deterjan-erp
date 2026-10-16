from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.api.labels import LabelOutputSerializer, PrintRequestSerializer
from apps.core.models import User
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    Lot,
    PalletLabel,
    StockAdjustment,
    StockAdjustmentLine,
    StockBalance,
    StockMovement,
)
from apps.inventory.state import goods_receipt_states, lot_states
from apps.masterdata.models import Location, Material, Supplier, UnitOfMeasure


def user_name(user: User | None) -> str | None:
    return str(user) if user is not None else None


class UserNameField(serializers.Field):
    """Kullanıcının görünen adı (salt okunur)."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs["read_only"] = True
        super().__init__(**kwargs)

    def to_representation(self, value: User | None) -> str | None:
        return user_name(value)


extend_schema_field({"type": "string", "nullable": True})(UserNameField)


# --- lot -------------------------------------------------------------------------------------


class LotSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    material_type = serializers.CharField(source="material.material_type", read_only=True)
    material_gtin = serializers.CharField(source="material.gtin", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    released_by_name = UserNameField(source="released_by")
    total_quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, read_only=True, default=None
    )
    is_expired = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Lot
        fields = [
            "id",
            "lot_no",
            "material",
            "material_code",
            "material_name",
            "material_type",
            "material_gtin",
            "unit",
            "status",
            "status_display",
            "source",
            "source_display",
            "supplier",
            "supplier_name",
            "supplier_lot_no",
            "manufactured_at",
            "expiry_date",
            "is_expired",
            "released_by_name",
            "released_at",
            "status_note",
            "total_quantity",
            "allowed_transitions",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_expired(self, lot: Lot) -> bool:
        return lot.expiry_date is not None and lot.expiry_date < timezone.localdate()

    def get_allowed_transitions(self, lot: Lot) -> list[str]:
        return lot_states.allowed_transitions(lot.status)


class LotBalanceSerializer(serializers.ModelSerializer):
    location_code = serializers.CharField(source="location.code", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    location_type = serializers.CharField(source="location.location_type", read_only=True)

    class Meta:
        model = StockBalance
        fields = ["location", "location_code", "location_name", "location_type", "quantity"]
        read_only_fields = fields


class SourceDocumentSerializer(serializers.Serializer):
    model = serializers.CharField()
    id = serializers.IntegerField()
    number = serializers.CharField()


class LotDetailSerializer(LotSerializer):
    balances = serializers.SerializerMethodField()
    receipt = serializers.SerializerMethodField()

    class Meta(LotSerializer.Meta):
        fields = [*LotSerializer.Meta.fields, "balances", "receipt"]
        read_only_fields = fields

    @extend_schema_field(LotBalanceSerializer(many=True))
    def get_balances(self, lot: Lot) -> list[dict[str, Any]]:
        rows = (
            lot.balances.filter(quantity__gt=0)
            .select_related("location")
            .order_by("location__code")
        )
        return LotBalanceSerializer(rows, many=True).data  # type: ignore[return-value]

    @extend_schema_field(SourceDocumentSerializer(allow_null=True))
    def get_receipt(self, lot: Lot) -> dict[str, Any] | None:
        line = GoodsReceiptLine.objects.filter(created_lot=lot).select_related("receipt").first()
        if line is None:
            return None
        return {
            "model": "inventory.goodsreceipt",
            "id": line.receipt_id,
            "number": line.receipt.number,
        }


class LotDecisionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class LotReleaseSerializer(LotDecisionSerializer):
    to_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True, default=None
    )


class TraceNodeSerializer(serializers.Serializer):
    """Soy ağacı düğümü (`children` aynı yapıda, özyinelemeli)."""

    id = serializers.IntegerField()
    lot_no = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    lot_source = serializers.CharField()
    lot_source_display = serializers.CharField()
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    material_type = serializers.CharField()
    unit = serializers.CharField()
    expiry_date = serializers.DateField(allow_null=True)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    children = serializers.ListField(child=serializers.DictField())

    def to_representation(self, instance: dict[str, Any]) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["children"] = [self.to_representation(child) for child in instance["children"]]
        return data


# --- hareket ve bakiye -----------------------------------------------------------------------


class StockMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(
        source="get_movement_type_display", read_only=True
    )
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    source_model = serializers.SerializerMethodField()
    is_reversed = serializers.SerializerMethodField()
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "movement_type",
            "movement_type_display",
            "material",
            "material_code",
            "material_name",
            "lot",
            "lot_no",
            "location",
            "location_code",
            "quantity",
            "unit",
            "document_number",
            "source_model",
            "source_object_id",
            "reversal_of",
            "is_reversed",
            "transfer_group",
            "note",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = fields

    def get_source_model(self, movement: StockMovement) -> str | None:
        content_type = movement.source_content_type
        return f"{content_type.app_label}.{content_type.model}" if content_type else None

    def get_is_reversed(self, movement: StockMovement) -> bool:
        # Görünüm `has_reversal` açıklamasını ekler; yoksa ters ilişkiye bakılır.
        flag = getattr(movement, "has_reversal", None)
        return bool(flag) if flag is not None else hasattr(movement, "reversed_by")


class ReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True)


class StockBalanceSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    material_type = serializers.CharField(source="material.material_type", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    lot_status = serializers.CharField(source="lot.status", read_only=True)
    lot_status_display = serializers.CharField(source="lot.get_status_display", read_only=True)
    expiry_date = serializers.DateField(source="lot.expiry_date", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    location_type = serializers.CharField(source="location.location_type", read_only=True)
    warehouse_code = serializers.CharField(source="location.warehouse.code", read_only=True)
    # `selectors.balances()` açıklamaları (Faz 3): aktif rezervasyonlar ve kullanılabilir miktar.
    reserved_quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, read_only=True, default=None, allow_null=True
    )
    available_quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, read_only=True, default=None, allow_null=True
    )

    class Meta:
        model = StockBalance
        fields = [
            "id",
            "material",
            "material_code",
            "material_name",
            "material_type",
            "lot",
            "lot_no",
            "lot_status",
            "lot_status_display",
            "expiry_date",
            "location",
            "location_code",
            "location_name",
            "location_type",
            "warehouse_code",
            "quantity",
            "reserved_quantity",
            "available_quantity",
            "unit",
        ]
        read_only_fields = fields


class TransferSerializer(serializers.Serializer):
    lot = serializers.PrimaryKeyRelatedField(queryset=Lot.objects.select_related("material"))
    from_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    to_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    note = serializers.CharField(required=False, allow_blank=True, default="")


# --- belgeler --------------------------------------------------------------------------------

DOCUMENT_READ_FIELDS = [
    "id",
    "number",
    "status",
    "status_display",
    "cancel_reason",
    "cancelled_at",
    "posted_at",
    "posted_by_name",
    "created_at",
    "created_by_name",
]


class DocumentSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    posted_by_name = UserNameField(source="posted_by")
    created_by_name = UserNameField(source="created_by")

    def get_status_display(self, document: Any) -> str:
        return goods_receipt_states.label(document.status)


class GoodsReceiptLineSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    material = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.select_related("base_unit")
    )
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all())
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    requires_incoming_qc = serializers.BooleanField(
        source="material.requires_incoming_qc", read_only=True
    )
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    base_unit_code = serializers.CharField(source="material.base_unit.code", read_only=True)
    created_lot_no = serializers.CharField(
        source="created_lot.lot_no", read_only=True, default=None
    )
    created_lot_status = serializers.CharField(
        source="created_lot.status", read_only=True, default=None
    )

    class Meta:
        model = GoodsReceiptLine
        fields = [
            "id",
            "line_no",
            "material",
            "material_code",
            "material_name",
            "requires_incoming_qc",
            "quantity",
            "unit",
            "unit_code",
            "supplier_lot_no",
            "manufactured_at",
            "expiry_date",
            "unit_price",
            "base_quantity",
            "base_unit_code",
            "created_lot",
            "created_lot_no",
            "created_lot_status",
        ]
        read_only_fields = ["line_no", "base_quantity", "created_lot"]


class GoodsReceiptSerializer(DocumentSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    quarantine_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    storage_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    quarantine_location_code = serializers.CharField(
        source="quarantine_location.code", read_only=True, default=None
    )
    storage_location_code = serializers.CharField(
        source="storage_location.code", read_only=True, default=None
    )
    line_count = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = GoodsReceipt
        fields = [
            *DOCUMENT_READ_FIELDS,
            "supplier",
            "supplier_code",
            "supplier_name",
            "receipt_date",
            "delivery_note_no",
            "quarantine_location",
            "quarantine_location_code",
            "storage_location",
            "storage_location_code",
            "note",
            "line_count",
        ]
        read_only_fields = DOCUMENT_READ_FIELDS


class GoodsReceiptDetailSerializer(GoodsReceiptSerializer):
    """Detay ve yazma: satırlar iç içe. Yazarken `lines` verilirse satırlar onunla eşitlenir
    (`id`'li satır güncellenir, `id`'siz eklenir, listede olmayan kaldırılır)."""

    lines = GoodsReceiptLineSerializer(many=True, required=False)

    class Meta(GoodsReceiptSerializer.Meta):
        fields = [*GoodsReceiptSerializer.Meta.fields, "lines"]


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True)


class StockAdjustmentLineSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    lot = serializers.PrimaryKeyRelatedField(queryset=Lot.objects.select_related("material"))
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    material_code = serializers.CharField(source="lot.material.code", read_only=True)
    material_name = serializers.CharField(source="lot.material.name", read_only=True)
    unit = serializers.CharField(source="lot.material.base_unit.code", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)

    class Meta:
        model = StockAdjustmentLine
        fields = [
            "id",
            "line_no",
            "lot",
            "lot_no",
            "material_code",
            "material_name",
            "unit",
            "location",
            "location_code",
            "system_quantity",
            "counted_quantity",
            "difference",
            "reason",
            "movement",
        ]
        read_only_fields = ["line_no", "system_quantity", "difference", "movement"]


class StockAdjustmentSerializer(DocumentSerializer):
    line_count = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = StockAdjustment
        fields = [*DOCUMENT_READ_FIELDS, "adjustment_date", "note", "line_count"]
        read_only_fields = DOCUMENT_READ_FIELDS


class StockAdjustmentDetailSerializer(StockAdjustmentSerializer):
    lines = StockAdjustmentLineSerializer(many=True, required=False)

    class Meta(StockAdjustmentSerializer.Meta):
        fields = [*StockAdjustmentSerializer.Meta.fields, "lines"]


class OpeningUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    confirm = serializers.BooleanField(default=False)


# --- etiket ve okutma ----------------------------------------------------------------------------


class CaseLabelOutputSerializer(LabelOutputSerializer):
    units_per_case = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, label="koli içi adet"
    )


LOT_LABEL_KINDS = [("lot", "Lot etiketi"), ("case", "Koli etiketi")]


class LotPrintSerializer(PrintRequestSerializer):
    kind = serializers.ChoiceField(choices=LOT_LABEL_KINDS)
    units_per_case = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class PalletLabelSerializer(serializers.ModelSerializer):
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    material_code = serializers.CharField(source="lot.material.code", read_only=True)
    material_name = serializers.CharField(source="lot.material.name", read_only=True)
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = PalletLabel
        fields = [
            "id",
            "sscc",
            "lot",
            "lot_no",
            "material_code",
            "material_name",
            "case_count",
            "units_per_case",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "sscc", "created_at"]


class ScanLotSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    material_type = serializers.CharField(source="material.material_type", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Lot
        fields = [
            "id",
            "lot_no",
            "material",
            "material_code",
            "material_name",
            "material_type",
            "unit",
            "status",
            "status_display",
            "expiry_date",
            "is_expired",
        ]
        read_only_fields = fields

    def get_is_expired(self, lot: Lot) -> bool:
        return lot.expiry_date is not None and lot.expiry_date < timezone.localdate()


class ScanMaterialSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    material_type = serializers.CharField()


class ScanLocationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    warehouse_code = serializers.CharField(source="warehouse.code")


class ScanPalletSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sscc = serializers.CharField()
    case_count = serializers.IntegerField()


class ScanResultSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["lot", "location", "material", "pallet"])
    code = serializers.CharField()
    lots = ScanLotSerializer(many=True)
    material = ScanMaterialSerializer(allow_null=True)
    location = ScanLocationSerializer(allow_null=True)
    pallet = ScanPalletSerializer(allow_null=True)
    gs1 = serializers.DictField(child=serializers.CharField())
