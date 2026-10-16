from rest_framework import serializers

from apps.inventory.api.serializers import UserNameField
from apps.inventory.models import Lot
from apps.masterdata.models import Customer, Location, Material, UnitOfMeasure
from apps.returns.models import CustomerReturn, CustomerReturnLine
from apps.returns.state import customer_return_states
from apps.sales.models import Shipment


class CustomerReturnLineSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    product = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.select_related("base_unit")
    )
    lot = serializers.PrimaryKeyRelatedField(queryset=Lot.objects.select_related("material"))
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all())
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    lot_status = serializers.CharField(source="lot.status", read_only=True)
    lot_status_display = serializers.CharField(source="lot.get_status_display", read_only=True)
    expiry_date = serializers.DateField(source="lot.expiry_date", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    base_unit_code = serializers.CharField(source="product.base_unit.code", read_only=True)
    sample_number = serializers.CharField(source="sample.number", read_only=True, default=None)
    sample_status = serializers.CharField(source="sample.status", read_only=True, default=None)
    disposition_display = serializers.CharField(source="get_disposition_display", read_only=True)
    is_scrapped = serializers.SerializerMethodField()
    is_settled = serializers.BooleanField(read_only=True)

    class Meta:
        model = CustomerReturnLine
        fields = [
            "id",
            "line_no",
            "product",
            "product_code",
            "product_name",
            "lot",
            "lot_no",
            "lot_status",
            "lot_status_display",
            "expiry_date",
            "quantity",
            "unit",
            "unit_code",
            "base_quantity",
            "base_unit_code",
            "sample",
            "sample_number",
            "sample_status",
            "disposition",
            "disposition_display",
            "decided_at",
            "is_scrapped",
            "is_settled",
        ]
        read_only_fields = ["line_no", "base_quantity", "sample", "disposition", "decided_at"]

    def get_is_scrapped(self, line: CustomerReturnLine) -> bool:
        return line.scrap_movement_id is not None


RETURN_READ_FIELDS = [
    "id",
    "number",
    "status",
    "status_display",
    "cancel_reason",
    "cancelled_at",
    "received_at",
    "received_by_name",
    "closed_at",
    "created_at",
    "created_by_name",
]


class CustomerReturnSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    received_by_name = UserNameField(source="received_by")
    created_by_name = UserNameField(source="created_by")
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    quarantine_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    quarantine_location_code = serializers.CharField(
        source="quarantine_location.code", read_only=True
    )
    shipment = serializers.PrimaryKeyRelatedField(
        queryset=Shipment.objects.select_related("sales_order"),
        required=False,
        allow_null=True,
        default=None,
    )
    shipment_number = serializers.CharField(
        source="shipment.number", read_only=True, default=None, allow_null=True
    )
    line_count = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = CustomerReturn
        fields = [
            *RETURN_READ_FIELDS,
            "customer",
            "customer_code",
            "customer_name",
            "shipment",
            "shipment_number",
            "return_date",
            "reason",
            "quarantine_location",
            "quarantine_location_code",
            "note",
            "line_count",
        ]
        read_only_fields = RETURN_READ_FIELDS

    def get_status_display(self, document: CustomerReturn) -> str:
        return customer_return_states.label(document.status)


class CustomerReturnDetailSerializer(CustomerReturnSerializer):
    """Detay ve yazma: satırlar iç içe. Yazarken `lines` verilirse satırlar onunla eşitlenir
    (`id`'li satır güncellenir, `id`'siz eklenir, listede olmayan kaldırılır)."""

    lines = CustomerReturnLineSerializer(many=True, required=False)

    class Meta(CustomerReturnSerializer.Meta):
        fields = [*CustomerReturnSerializer.Meta.fields, "lines"]


class ScrapSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")
