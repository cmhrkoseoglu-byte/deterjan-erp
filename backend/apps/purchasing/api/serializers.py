from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.core.models import Currency
from apps.core.permissions import user_has_role
from apps.inventory.api.serializers import UserNameField
from apps.masterdata.models import Location, Material, Supplier, UnitOfMeasure
from apps.purchasing import selectors, services
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchasingSettings,
)
from apps.purchasing.state import purchase_order_states, purchase_request_states

# Depo siparişi ve beklenen teslimatları görür, tutarları görmez.
PRICE_FIELDS = frozenset(
    {
        "unit_price",
        "line_total",
        "total",
        "total_try",
        "exchange_rate",
        "approval_total_try",
        "approval_limit_try",
    }
)


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, **kwargs)


def can_see_prices(context: dict[str, Any]) -> bool:
    request = context.get("request")
    return request is not None and user_has_role(request.user, services.ORDER_ROLES)


class PriceHidingMixin:
    """Fiyat yetkisi olmayan kullanıcıda fiyat alanlarını yanıttan çıkarır."""

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)  # type: ignore[misc]
        if not can_see_prices(self.context):  # type: ignore[attr-defined]
            for name in PRICE_FIELDS:
                data.pop(name, None)
        return data


class PurchaseNoteSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=True, required=False, default="")


class SendSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True, default="")


# --- talep -----------------------------------------------------------------------------------


class PurchaseRequestSerializer(serializers.ModelSerializer):
    material = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.select_related("base_unit")
    )
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    unit_code = serializers.CharField(source="material.base_unit.code", read_only=True)
    status_display = serializers.SerializerMethodField()
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    order_id = serializers.IntegerField(source="order_line.order_id", read_only=True, default=None)
    order_number = serializers.CharField(
        source="order_line.order.number", read_only=True, default=None
    )
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = PurchaseRequest
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "source",
            "source_display",
            "material",
            "material_code",
            "material_name",
            "unit_code",
            "quantity",
            "need_date",
            "reason",
            "order_id",
            "order_number",
            "cancel_reason",
            "cancelled_at",
            "created_at",
            "created_by",
            "created_by_name",
        ]
        read_only_fields = [
            "number",
            "status",
            "source",
            "cancel_reason",
            "cancelled_at",
            "created_by",
        ]

    def get_status_display(self, request: PurchaseRequest) -> str:
        return purchase_request_states.label(request.status)


# --- sipariş ---------------------------------------------------------------------------------


class PurchaseOrderLineSerializer(PriceHidingMixin, serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    material = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.select_related("base_unit")
    )
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all())
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    base_unit_code = serializers.CharField(source="material.base_unit.code", read_only=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    requests = serializers.PrimaryKeyRelatedField(
        queryset=PurchaseRequest.objects.all(), many=True, required=False
    )
    request_numbers = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()
    received_quantity = _quantity(read_only=True, default=None, allow_null=True)
    pending_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id",
            "line_no",
            "material",
            "material_code",
            "material_name",
            "quantity",
            "unit",
            "unit_code",
            "base_quantity",
            "base_unit_code",
            "unit_price",
            "line_total",
            "expected_date",
            "note",
            "requests",
            "request_numbers",
            "received_quantity",
            "pending_quantity",
        ]
        read_only_fields = ["line_no", "base_quantity"]

    def get_request_numbers(self, line: PurchaseOrderLine) -> list[str]:
        if not line.pk:
            return []
        return [r.number for r in line.requests.all()]

    def get_line_total(self, line: PurchaseOrderLine) -> str | None:
        if line.quantity is None or line.unit_price is None:
            return None
        return str((line.quantity * line.unit_price).quantize(Decimal("0.01")))

    def get_pending_quantity(self, line: PurchaseOrderLine) -> str | None:
        if not hasattr(line, "received_quantity"):
            return None
        return str(selectors.pending_quantity(line))

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)
        data["requests"] = [r.pk for r in instance.requests.all()] if instance.pk else []
        return data


class PurchaseOrderSerializer(PriceHidingMixin, serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    supplier_email = serializers.CharField(source="supplier.email", read_only=True)
    status_display = serializers.SerializerMethodField()
    currency = serializers.ChoiceField(choices=Currency.choices, required=False, default="TRY")
    exchange_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, required=False, default=Decimal(1)
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    total = serializers.SerializerMethodField()
    total_try = serializers.SerializerMethodField()
    expected_date = serializers.DateField(read_only=True, default=None)
    approved_by_name = UserNameField(source="approved_by")
    sent_by_name = UserNameField(source="sent_by")
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "supplier",
            "supplier_code",
            "supplier_name",
            "supplier_email",
            "order_date",
            "currency",
            "exchange_rate",
            "notes",
            "total",
            "total_try",
            "expected_date",
            "approval_total_try",
            "approval_limit_try",
            "approved_at",
            "approved_by_name",
            "sent_at",
            "sent_by_name",
            "sent_to",
            "closed_note",
            "cancel_reason",
            "cancelled_at",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = [
            "number",
            "status",
            "approval_total_try",
            "approval_limit_try",
            "approved_at",
            "sent_at",
            "sent_to",
            "closed_note",
            "cancel_reason",
            "cancelled_at",
            "created_at",
        ]

    def get_status_display(self, order: PurchaseOrder) -> str:
        return purchase_order_states.label(order.status)

    def get_total(self, order: PurchaseOrder) -> str:
        return str(selectors.order_totals(order).total)

    def get_total_try(self, order: PurchaseOrder) -> str:
        return str(selectors.order_totals(order).total_try)


class OrderReceiptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    status = serializers.CharField()
    receipt_date = serializers.DateField()


class PurchaseOrderDetailSerializer(PurchaseOrderSerializer):
    lines = PurchaseOrderLineSerializer(many=True, required=False)
    can_approve = serializers.SerializerMethodField()
    receipts = serializers.SerializerMethodField()

    class Meta(PurchaseOrderSerializer.Meta):
        fields = [*PurchaseOrderSerializer.Meta.fields, "lines", "can_approve", "receipts"]

    def get_can_approve(self, order: PurchaseOrder) -> bool:
        request = self.context.get("request")
        if request is None or order.status not in (
            PurchaseOrder.Status.DRAFT,
            PurchaseOrder.Status.PENDING_APPROVAL,
        ):
            return False
        return services.can_approve(request.user, order)

    def get_receipts(self, order: PurchaseOrder) -> list[dict[str, Any]]:
        from apps.inventory.models import GoodsReceipt

        receipts = (
            GoodsReceipt.objects.filter(lines__purchase_link__order_line__order=order)
            .distinct()
            .order_by("receipt_date", "id")
        )
        return [
            {"id": r.pk, "number": r.number, "status": r.status, "receipt_date": r.receipt_date}
            for r in receipts
        ]

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)
        if instance.pk:
            lines = selectors.order_lines().filter(order=instance).order_by("line_no")
            data["lines"] = PurchaseOrderLineSerializer(lines, many=True, context=self.context).data
        return data


# --- siparişten mal kabul --------------------------------------------------------------------


class ReceiveLineSerializer(serializers.Serializer):
    order_line = serializers.IntegerField()
    quantity = _quantity()
    supplier_lot_no = serializers.CharField(required=False, allow_blank=True, default="")
    manufactured_at = serializers.DateField(required=False, allow_null=True, default=None)
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)


class ReceiveSerializer(serializers.Serializer):
    receipt_date = serializers.DateField()
    delivery_note_no = serializers.CharField(required=False, allow_blank=True, default="")
    quarantine_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True, default=None
    )
    storage_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True, default=None
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    lines = ReceiveLineSerializer(many=True)


class ReceiveResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()


class ReceiptLinkSerializer(serializers.Serializer):
    receipt_line = serializers.IntegerField(source="receipt_line_id")
    order_line = serializers.IntegerField(source="order_line_id")
    order_id = serializers.IntegerField(source="order_line.order_id")
    order_number = serializers.CharField(source="order_line.order.number")


# --- beklenen teslimat, öneri, performans, ayarlar -------------------------------------------


class ExpectedDeliverySerializer(serializers.Serializer):
    order_line = serializers.IntegerField(source="pk")
    order_id = serializers.IntegerField(source="order.pk")
    order_number = serializers.CharField(source="order.number")
    order_status = serializers.CharField(source="order.status")
    supplier_id = serializers.IntegerField(source="order.supplier_id")
    supplier_name = serializers.CharField(source="order.supplier.name")
    material = serializers.IntegerField(source="material_id")
    material_code = serializers.CharField(source="material.code")
    material_name = serializers.CharField(source="material.name")
    quantity = _quantity()
    unit_code = serializers.CharField(source="unit.code")
    base_unit_code = serializers.CharField(source="material.base_unit.code")
    base_quantity = _quantity()
    received_quantity = _quantity()
    pending_quantity = _quantity()
    expected_date = serializers.DateField()
    is_late = serializers.BooleanField()


class SuggestionSourceSerializer(serializers.Serializer):
    order_number = serializers.CharField()
    planned_date = serializers.DateField()
    quantity = _quantity()


class SuggestionSerializer(serializers.Serializer):
    material = serializers.IntegerField(source="material.pk")
    material_code = serializers.CharField(source="material.code")
    material_name = serializers.CharField(source="material.name")
    unit_code = serializers.CharField(source="material.base_unit.code")
    demand = _quantity()
    min_stock = _quantity()
    free_stock = _quantity()
    open_orders = _quantity()
    open_requests = _quantity()
    suggested = _quantity()
    need_date = serializers.DateField()
    sources = SuggestionSourceSerializer(many=True)


class SupplierPerformanceSerializer(serializers.Serializer):
    supplier = serializers.IntegerField(source="supplier.pk")
    supplier_code = serializers.CharField(source="supplier.code")
    supplier_name = serializers.CharField(source="supplier.name")
    due_lines = serializers.IntegerField()
    on_time_lines = serializers.IntegerField()
    on_time_rate = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)
    received_lots = serializers.IntegerField()
    rejected_lots = serializers.IntegerField()
    reject_rate = serializers.DecimalField(max_digits=5, decimal_places=1, allow_null=True)


class PurchasingSettingsSerializer(serializers.ModelSerializer):
    approval_limit_try = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True, required=False, min_value=0
    )
    over_receipt_tolerance_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, min_value=0
    )
    updated_by_name = UserNameField(source="updated_by")

    class Meta:
        model = PurchasingSettings
        fields = [
            "approval_limit_try",
            "over_receipt_tolerance_pct",
            "updated_at",
            "updated_by_name",
        ]
        read_only_fields = ["updated_at"]
