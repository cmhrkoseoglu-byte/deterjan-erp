"""Sipariş talebi yanıtları ve istekleri (docs/plan/musteri-siparis-takibi.md §4.4)."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.masterdata.models import Material, UnitOfMeasure
from apps.portal.models import OrderRequest, OrderRequestLine
from apps.portal.state import order_request_states


class PortalRequestLineSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)

    class Meta:
        model = OrderRequestLine
        fields = [
            "line_no",
            "product",
            "product_code",
            "product_name",
            "quantity",
            "unit",
            "unit_code",
        ]
        read_only_fields = fields


class PortalRequestSerializer(serializers.ModelSerializer):
    """Müşterinin gördüğü talep: durum, ret gerekçesi ve çevrildiği sipariş (sipariş onaylanınca
    Siparişlerim'de açılır)."""

    status_display = serializers.SerializerMethodField()
    lines = PortalRequestLineSerializer(many=True, read_only=True)
    order_id = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="sales_order.number", default=None, read_only=True)

    class Meta:
        model = OrderRequest
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "requested_delivery_date",
            "customer_po_no",
            "delivery_address",
            "note",
            "lines",
            "reject_reason",
            "order_id",
            "order_number",
            "created_at",
            "decided_at",
        ]
        read_only_fields = fields

    def get_status_display(self, request: OrderRequest) -> str:
        return order_request_states.label(request.status)

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_order_id(self, request: OrderRequest) -> int | None:
        """Sipariş müşteriye onaylanınca görünür; taslakken bağlantı verilmez."""
        order = request.sales_order
        return order.pk if order is not None and order.confirmed_at is not None else None


class StaffRequestSerializer(PortalRequestSerializer):
    """İç ekrandaki talep: müşteri, gönderen ve karar veren de görünür."""

    customer = serializers.IntegerField(source="customer_id", read_only=True)
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()
    sales_order = serializers.IntegerField(source="sales_order_id", read_only=True)

    class Meta(PortalRequestSerializer.Meta):
        fields = [
            *PortalRequestSerializer.Meta.fields,
            "customer",
            "customer_code",
            "customer_name",
            "created_by_name",
            "decided_by_name",
            "sales_order",
        ]
        read_only_fields = fields

    @staticmethod
    def _name(user: Any) -> str:
        return (user.full_name or user.username) if user is not None else ""

    def get_created_by_name(self, request: OrderRequest) -> str:
        return self._name(request.created_by)

    def get_decided_by_name(self, request: OrderRequest) -> str:
        return self._name(request.decided_by)


class RequestLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    unit = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all())


class RequestInputSerializer(serializers.Serializer):
    requested_delivery_date = serializers.DateField(required=False, allow_null=True, default=None)
    customer_po_no = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    delivery_address = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    lines = RequestLineInputSerializer(many=True)


class RejectInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)


class ProductUnitSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class OrderableProductSerializer(serializers.ModelSerializer):
    """Talepte seçilebilen ürün: kod, ad ve birimler (temel birim önce). Fiyat ve stok yok."""

    units = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = ["id", "code", "name", "units"]
        read_only_fields = fields

    @extend_schema_field(ProductUnitSerializer(many=True))
    def get_units(self, product: Material) -> list[dict[str, Any]]:
        units = [product.base_unit, *(c.unit for c in product.conversions.all())]
        seen: set[int] = set()
        result = []
        for unit in units:
            if unit.pk in seen:
                continue
            seen.add(unit.pk)
            result.append({"id": unit.pk, "code": unit.code, "name": unit.name})
        return result
