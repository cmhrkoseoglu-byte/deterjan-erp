"""Tedarikçi portalının yanıtları (docs/plan/musteri-siparis-takibi.md §4.3a). Onay tutarı ve
limiti, TL kuru, onaylayan ve gönderen kişi, satın alma talepleri, kapanış notu, satır notu; mal
kabulde bizim lot numaramız, depo, kalite durumu, birim maliyet ve ek masraflar yoktur."""

from decimal import ROUND_HALF_UP, Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory.models import GoodsReceipt, GoodsReceiptLine
from apps.purchasing import selectors as purchasing_selectors
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.state import purchase_order_states

CENT = Decimal("0.01")


class PortalSupplierOrderLineSerializer(serializers.ModelSerializer):
    """Sipariş satırı; teslim alınan ve kalan temel birimde ve sipariş birimiyle."""

    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    base_unit_code = serializers.CharField(source="material.base_unit.code", read_only=True)
    line_total = serializers.SerializerMethodField()
    received_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    received_in_unit = serializers.SerializerMethodField()
    remaining_in_unit = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "line_no",
            "material_code",
            "material_name",
            "quantity",
            "unit_code",
            "base_quantity",
            "base_unit_code",
            "unit_price",
            "line_total",
            "expected_date",
            "received_quantity",
            "remaining_quantity",
            "received_in_unit",
            "remaining_in_unit",
        ]
        read_only_fields = fields

    @staticmethod
    def _received(line: PurchaseOrderLine) -> Decimal:
        return getattr(line, "received_quantity", None) or Decimal(0)

    @staticmethod
    def _remaining(line: PurchaseOrderLine) -> Decimal:
        return purchasing_selectors.pending_quantity(line)

    @staticmethod
    def _in_unit(line: PurchaseOrderLine, base: Decimal) -> str:
        if not line.base_quantity:
            return "0.0000"
        return f"{(base * line.quantity / line.base_quantity).quantize(Decimal('0.0001')):.4f}"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=2))
    def get_line_total(self, line: PurchaseOrderLine) -> str:
        total = (line.quantity * line.unit_price).quantize(CENT, ROUND_HALF_UP)
        return f"{total:.2f}"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_received_quantity(self, line: PurchaseOrderLine) -> str:
        return f"{self._received(line):.4f}"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_remaining_quantity(self, line: PurchaseOrderLine) -> str:
        return f"{self._remaining(line):.4f}"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_received_in_unit(self, line: PurchaseOrderLine) -> str:
        return self._in_unit(line, self._received(line))

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_remaining_in_unit(self, line: PurchaseOrderLine) -> str:
        return self._in_unit(line, self._remaining(line))


class PortalSupplierOrderSerializer(serializers.ModelSerializer):
    """Gönderilmiş satın alma siparişi: tarih, para birimi, durum, notlar (siparişin PDF'iyle
    aynı), satırlar ve sipariş tutarı."""

    status_display = serializers.SerializerMethodField()
    lines = PortalSupplierOrderLineSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "number",
            "order_date",
            "sent_at",
            "currency",
            "status",
            "status_display",
            "notes",
            "lines",
            "total",
        ]
        read_only_fields = fields

    def get_status_display(self, order: PurchaseOrder) -> str:
        return purchase_order_states.label(order.status)

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=2))
    def get_total(self, order: PurchaseOrder) -> str:
        return f"{purchasing_selectors.order_totals(order).total:.2f}"


class PortalReceiptLineSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    order_number = serializers.SerializerMethodField()

    class Meta:
        model = GoodsReceiptLine
        fields = [
            "line_no",
            "material_code",
            "material_name",
            "quantity",
            "unit_code",
            "supplier_lot_no",
            "order_number",
        ]
        read_only_fields = fields

    def get_order_number(self, line: GoodsReceiptLine) -> str | None:
        link = getattr(line, "purchase_link", None)
        return link.order_line.order.number if link is not None else None


class PortalReceiptSerializer(serializers.ModelSerializer):
    """Teslim aldığımız mal: mal kabul no, tarih, tedarikçinin irsaliye no'su, satırlar."""

    lines = PortalReceiptLineSerializer(many=True, read_only=True)

    class Meta:
        model = GoodsReceipt
        fields = ["id", "number", "receipt_date", "delivery_note_no", "lines"]
        read_only_fields = fields
