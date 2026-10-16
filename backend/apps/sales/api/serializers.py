from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory.api.serializers import UserNameField
from apps.inventory.models import Lot, StockReservation
from apps.masterdata.models import Customer, Location, Material, UnitOfMeasure
from apps.sales import selectors
from apps.sales.models import Currency, SalesOrder, SalesOrderLine
from apps.sales.state import sales_order_states


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, **kwargs)


class SalesOrderLineSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    product = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.select_related("base_unit")
    )
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all())
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    base_unit_code = serializers.CharField(source="product.base_unit.code", read_only=True)
    unit_price = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, allow_null=True
    )
    currency = serializers.ChoiceField(
        choices=Currency.choices, required=False, allow_blank=True, default=""
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    reserved_quantity = _quantity(read_only=True, default=None, allow_null=True)
    shipped_quantity = _quantity(read_only=True, default=None, allow_null=True)
    shortage_quantity = _quantity(read_only=True, default=None, allow_null=True)
    line_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True, default=None, allow_null=True
    )

    class Meta:
        model = SalesOrderLine
        fields = [
            "id",
            "line_no",
            "product",
            "product_code",
            "product_name",
            "quantity",
            "unit",
            "unit_code",
            "base_quantity",
            "base_unit_code",
            "unit_price",
            "currency",
            "line_total",
            "note",
            "reserved_quantity",
            "shipped_quantity",
            "shortage_quantity",
        ]
        read_only_fields = ["line_no", "base_quantity"]


class SalesOrderSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    status_display = serializers.SerializerMethodField()
    delivery_address = serializers.CharField(required=False, allow_blank=True, default="")
    customer_po_no = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    line_count = serializers.IntegerField(read_only=True, default=None)
    has_shortage = serializers.BooleanField(read_only=True, default=None)
    confirmed_by_name = UserNameField(source="confirmed_by")
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "customer",
            "customer_code",
            "customer_name",
            "order_date",
            "requested_delivery_date",
            "delivery_address",
            "customer_po_no",
            "notes",
            "line_count",
            "has_shortage",
            "confirmed_at",
            "confirmed_by_name",
            "closed_at",
            "cancel_reason",
            "cancelled_at",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = [
            "number",
            "status",
            "confirmed_at",
            "closed_at",
            "cancel_reason",
            "cancelled_at",
            "created_at",
        ]

    def get_status_display(self, order: SalesOrder) -> str:
        return sales_order_states.label(order.status)


class OrderTotalSerializer(serializers.Serializer):
    currency = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class ReservationSerializer(serializers.ModelSerializer):
    line = serializers.IntegerField(source="line_id", read_only=True, default=None)
    line_no = serializers.IntegerField(read_only=True, default=None)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    expiry_date = serializers.DateField(source="lot.expiry_date", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    unit = serializers.CharField(source="material.base_unit.code", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = StockReservation
        fields = [
            "id",
            "line",
            "line_no",
            "lot",
            "lot_no",
            "expiry_date",
            "location",
            "location_code",
            "quantity",
            "unit",
            "status",
            "status_display",
            "note",
            "created_at",
            "created_by_name",
            "closed_at",
        ]
        read_only_fields = fields


class SalesOrderDetailSerializer(SalesOrderSerializer):
    """Detay ve yazma: satırlar iç içe. Yazarken `lines` verilirse satırlar onunla eşitlenir
    (`id`'li satır güncellenir, `id`'siz eklenir, listede olmayan kaldırılır)."""

    lines = SalesOrderLineSerializer(many=True, required=False)
    totals = serializers.SerializerMethodField()
    reservations = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()
    min_remaining_shelf_life_days = serializers.IntegerField(
        source="customer.min_remaining_shelf_life_days", read_only=True, default=None
    )

    class Meta(SalesOrderSerializer.Meta):
        fields = [
            *SalesOrderSerializer.Meta.fields,
            "min_remaining_shelf_life_days",
            "is_editable",
            "lines",
            "totals",
            "reservations",
        ]

    def to_representation(self, order: SalesOrder) -> dict[str, Any]:
        data = super().to_representation(order)
        data["lines"] = SalesOrderLineSerializer(selectors.order_lines(order), many=True).data
        return data

    def get_is_editable(self, order: SalesOrder) -> bool:
        return order.status == SalesOrder.Status.DRAFT

    @extend_schema_field(OrderTotalSerializer(many=True))
    def get_totals(self, order: SalesOrder) -> list[dict[str, Any]]:
        return selectors.order_totals(order)  # type: ignore[return-value]

    @extend_schema_field(ReservationSerializer(many=True))
    def get_reservations(self, order: SalesOrder) -> list[dict[str, Any]]:
        rows = selectors.order_reservations(order)
        return ReservationSerializer(rows, many=True).data  # type: ignore[return-value]


class SalesNoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class ReserveSerializer(serializers.Serializer):
    line = serializers.PrimaryKeyRelatedField(queryset=SalesOrderLine.objects.all())
    lot = serializers.PrimaryKeyRelatedField(queryset=Lot.objects.select_related("material"))
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    quantity = _quantity()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class ReleaseSerializer(serializers.Serializer):
    reservation = serializers.PrimaryKeyRelatedField(queryset=StockReservation.objects.all())
    note = serializers.CharField(required=False, allow_blank=True, default="")


class CandidateSerializer(serializers.Serializer):
    """Satıra rezerve edilebilecek stok (FEFO sırasıyla)."""

    lot = serializers.IntegerField(source="lot_id")
    lot_no = serializers.CharField(source="lot.lot_no")
    expiry_date = serializers.DateField(source="lot.expiry_date", allow_null=True)
    location = serializers.IntegerField(source="location_id")
    location_code = serializers.CharField(source="location.code")
    quantity = _quantity()
    reserved_quantity = _quantity()
    available_quantity = _quantity()
    unit = serializers.CharField(source="material.base_unit.code")
    meets_shelf_life = serializers.BooleanField()
