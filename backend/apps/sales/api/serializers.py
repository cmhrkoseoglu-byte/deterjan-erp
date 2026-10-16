from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.audit import mask_identifier
from apps.inventory.api.serializers import UserNameField
from apps.inventory.models import Lot, StockReservation
from apps.masterdata.models import Customer, Location, Material, UnitOfMeasure
from apps.sales import selectors
from apps.sales.models import (
    Currency,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentLine,
    ShipmentPick,
)
from apps.sales.state import sales_order_states, shipment_states


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
    planned_quantity = _quantity(read_only=True, default=None, allow_null=True)
    plannable_quantity = _quantity(read_only=True, default=None, allow_null=True)
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
            "planned_quantity",
            "plannable_quantity",
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


class ShipmentSerializer(serializers.ModelSerializer):
    """Sevkiyat başlığı. Şoför TC kimlik no yalnızca yazılır; okumada maskeli
    (`driver_id_no_masked`, KVKK)."""

    sales_order = serializers.PrimaryKeyRelatedField(
        queryset=SalesOrder.objects.select_related("customer")
    )
    order_number = serializers.CharField(source="sales_order.number", read_only=True)
    customer = serializers.IntegerField(source="sales_order.customer_id", read_only=True)
    customer_code = serializers.CharField(source="sales_order.customer.code", read_only=True)
    customer_name = serializers.CharField(source="sales_order.customer.name", read_only=True)
    status_display = serializers.SerializerMethodField()
    loading_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False
    )
    loading_location_code = serializers.CharField(source="loading_location.code", read_only=True)
    vehicle_plate = serializers.CharField(required=False, allow_blank=True, default="")
    driver_name = serializers.CharField(required=False, allow_blank=True, default="")
    driver_id_no = serializers.CharField(
        required=False, allow_blank=True, default="", write_only=True
    )
    driver_id_no_masked = serializers.SerializerMethodField()
    carrier = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    loaded_by_name = UserNameField(source="loaded_by")
    dispatched_by_name = UserNameField(source="dispatched_by")
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = Shipment
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "sales_order",
            "order_number",
            "customer",
            "customer_code",
            "customer_name",
            "planned_date",
            "loading_location",
            "loading_location_code",
            "vehicle_plate",
            "driver_name",
            "driver_id_no",
            "driver_id_no_masked",
            "carrier",
            "notes",
            "loaded_at",
            "loaded_by_name",
            "dispatched_at",
            "dispatched_by_name",
            "cancel_reason",
            "cancelled_at",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = [
            "number",
            "status",
            "loaded_at",
            "dispatched_at",
            "cancel_reason",
            "cancelled_at",
            "created_at",
        ]

    def get_status_display(self, shipment: Shipment) -> str:
        return shipment_states.label(shipment.status)

    def get_driver_id_no_masked(self, shipment: Shipment) -> str:
        return selectors.masked_driver_id(shipment)


class SalesOrderDetailSerializer(SalesOrderSerializer):
    """Detay ve yazma: satırlar iç içe. Yazarken `lines` verilirse satırlar onunla eşitlenir
    (`id`'li satır güncellenir, `id`'siz eklenir, listede olmayan kaldırılır)."""

    lines = SalesOrderLineSerializer(many=True, required=False)
    totals = serializers.SerializerMethodField()
    reservations = serializers.SerializerMethodField()
    shipments = serializers.SerializerMethodField()
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
            "shipments",
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

    @extend_schema_field(ShipmentSerializer(many=True))
    def get_shipments(self, order: SalesOrder) -> list[dict[str, Any]]:
        rows = order.shipments.select_related("sales_order__customer", "loading_location")
        return ShipmentSerializer(rows.order_by("id"), many=True).data  # type: ignore[return-value]


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


# --- sevkiyat (Adım 3.2) ---------------------------------------------------------------------


class ShipmentLineSerializer(serializers.ModelSerializer):
    line_no = serializers.IntegerField(source="order_line.line_no", read_only=True)
    product = serializers.IntegerField(source="order_line.product_id", read_only=True)
    product_code = serializers.CharField(source="order_line.product.code", read_only=True)
    product_name = serializers.CharField(source="order_line.product.name", read_only=True)
    unit = serializers.CharField(source="order_line.product.base_unit.code", read_only=True)
    picked_quantity = _quantity(read_only=True, default=None, allow_null=True)

    class Meta:
        model = ShipmentLine
        fields = [
            "id",
            "order_line",
            "line_no",
            "product",
            "product_code",
            "product_name",
            "quantity",
            "unit",
            "picked_quantity",
        ]
        read_only_fields = fields


class ShipmentPickSerializer(serializers.ModelSerializer):
    line_no = serializers.IntegerField(source="line.order_line.line_no", read_only=True)
    product_code = serializers.CharField(source="line.order_line.product.code", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    expiry_date = serializers.DateField(source="lot.expiry_date", read_only=True)
    from_location_code = serializers.CharField(source="from_location.code", read_only=True)
    to_location_code = serializers.CharField(source="to_location.code", read_only=True)
    picked_by_name = UserNameField(source="picked_by")
    is_shipped = serializers.SerializerMethodField()

    class Meta:
        model = ShipmentPick
        fields = [
            "id",
            "line",
            "line_no",
            "product_code",
            "lot",
            "lot_no",
            "expiry_date",
            "quantity",
            "from_location_code",
            "to_location_code",
            "picked_by_name",
            "picked_at",
            "deviation_reason",
            "returned_at",
            "is_shipped",
        ]
        read_only_fields = fields

    def get_is_shipped(self, pick: ShipmentPick) -> bool:
        return pick.movement_id is not None


class ShipmentDetailSerializer(ShipmentSerializer):
    """Detay: satırlar (toplanan miktarla) ve toplama kayıtları."""

    lines = serializers.SerializerMethodField()
    picks = serializers.SerializerMethodField()
    delivery_address = serializers.CharField(source="sales_order.delivery_address", read_only=True)
    min_remaining_shelf_life_days = serializers.IntegerField(
        source="sales_order.customer.min_remaining_shelf_life_days", read_only=True, default=None
    )

    class Meta(ShipmentSerializer.Meta):
        fields = [
            *ShipmentSerializer.Meta.fields,
            "delivery_address",
            "min_remaining_shelf_life_days",
            "lines",
            "picks",
        ]

    @extend_schema_field(ShipmentLineSerializer(many=True))
    def get_lines(self, shipment: Shipment) -> list[dict[str, Any]]:
        rows = selectors.shipment_lines(shipment)
        return ShipmentLineSerializer(rows, many=True).data  # type: ignore[return-value]

    @extend_schema_field(ShipmentPickSerializer(many=True))
    def get_picks(self, shipment: Shipment) -> list[dict[str, Any]]:
        rows = selectors.shipment_picks(shipment)
        return ShipmentPickSerializer(rows, many=True).data  # type: ignore[return-value]


class ShipmentPlanLineSerializer(serializers.Serializer):
    order_line = serializers.PrimaryKeyRelatedField(queryset=SalesOrderLine.objects.all())
    quantity = _quantity()


class ShipmentPlanSerializer(ShipmentSerializer):
    """Sevkiyat planlama: `lines` verilmezse sipariş satırlarının kalan miktarı gelir."""

    lines = ShipmentPlanLineSerializer(many=True, required=False)

    class Meta(ShipmentSerializer.Meta):
        fields = [*ShipmentSerializer.Meta.fields, "lines"]


class PickSerializer(serializers.Serializer):
    """Lot okutma: lot kimliği ya da okutulan metin (lot no veya `LOT:<lot_no>` etiketi)."""

    lot = serializers.IntegerField(required=False)
    lot_no = serializers.CharField(required=False, allow_blank=True, default="")
    quantity = _quantity(required=False, allow_null=True, default=None)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("lot") and not attrs.get("lot_no", "").strip():
            raise serializers.ValidationError({"lot_no": ["Lot okutun ya da seçin."]})
        return attrs


class UndoPickSerializer(serializers.Serializer):
    pick = serializers.PrimaryKeyRelatedField(
        queryset=ShipmentPick.objects.select_related("line__shipment")
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class PickSuggestionRowSerializer(serializers.Serializer):
    lot = serializers.IntegerField()
    lot_no = serializers.CharField()
    expiry_date = serializers.DateField(allow_null=True)
    location = serializers.IntegerField()
    location_code = serializers.CharField()
    quantity = _quantity()
    reserved = serializers.BooleanField()
    meets_shelf_life = serializers.BooleanField()


class PickSuggestionSerializer(serializers.Serializer):
    """Toplama tableti: satır, kalan miktar ve öneriler (rezerve lotlar önce, sonra FEFO)."""

    line = serializers.IntegerField()
    line_no = serializers.IntegerField()
    product = serializers.IntegerField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    unit = serializers.CharField()
    quantity = _quantity()
    picked_quantity = _quantity()
    remaining_quantity = _quantity()
    suggestions = PickSuggestionRowSerializer(many=True)


class WaybillLineSerializer(serializers.Serializer):
    line_no = serializers.IntegerField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    gtin = serializers.CharField()
    lot_no = serializers.CharField()
    expiry_date = serializers.DateField(allow_null=True)
    quantity = _quantity()
    unit = serializers.CharField()
    cases = serializers.IntegerField(allow_null=True)
    loose_units = _quantity()


class WaybillPartySerializer(serializers.Serializer):
    name = serializers.CharField()
    address = serializers.CharField()
    tax_office = serializers.CharField()
    tax_no = serializers.CharField()


class WaybillCustomerSerializer(WaybillPartySerializer):
    code = serializers.CharField()


class WaybillSerializer(serializers.Serializer):
    """İrsaliye verisi (dışa aktarım; e-İrsaliye Faz 5). Şoför TC kimlik no maskeli."""

    number = serializers.CharField()
    status = serializers.CharField()
    date = serializers.DateField()
    dispatched_at = serializers.DateTimeField(allow_null=True)
    company = WaybillPartySerializer()
    customer = WaybillCustomerSerializer()
    delivery_address = serializers.CharField()
    order_number = serializers.CharField()
    customer_po_no = serializers.CharField()
    vehicle_plate = serializers.CharField()
    driver_name = serializers.CharField()
    driver_id_no = serializers.SerializerMethodField()
    carrier = serializers.CharField()
    lines = WaybillLineSerializer(many=True)
    total_quantity = _quantity()
    total_cases = serializers.IntegerField()

    def get_driver_id_no(self, data: dict[str, Any]) -> str:
        return mask_identifier(data["driver_id_no"])


class ShippedLotSerializer(serializers.ModelSerializer):
    """Müşteriye sevk edilen lot (müşteri kartı)."""

    shipment = serializers.IntegerField(source="line.shipment_id", read_only=True)
    shipment_number = serializers.CharField(source="line.shipment.number", read_only=True)
    order_number = serializers.CharField(source="line.order_line.order.number", read_only=True)
    dispatched_at = serializers.DateTimeField(source="line.shipment.dispatched_at", read_only=True)
    product_code = serializers.CharField(source="line.order_line.product.code", read_only=True)
    product_name = serializers.CharField(source="line.order_line.product.name", read_only=True)
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    expiry_date = serializers.DateField(source="lot.expiry_date", read_only=True)

    class Meta:
        model = ShipmentPick
        fields = [
            "id",
            "shipment",
            "shipment_number",
            "order_number",
            "dispatched_at",
            "product_code",
            "product_name",
            "lot",
            "lot_no",
            "expiry_date",
            "quantity",
        ]
        read_only_fields = fields
