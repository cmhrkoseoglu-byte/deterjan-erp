"""Müşteri portalının yanıtları (docs/plan/musteri-siparis-takibi.md §4.3). Yalnız burada adı geçen
alanlar müşteriye gider: iç notlar, rezervasyon, lot, SKT, eksik bilgisi ve kişi adları yoktur."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.portal import selectors
from apps.sales import selectors as sales_selectors
from apps.sales.models import SalesOrder, SalesOrderLine, Shipment
from apps.sales.state import sales_order_states, shipment_states

CENT = Decimal("0.01")


def _quantity() -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)


def _money() -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)


class PortalCustomerOrderLineSerializer(serializers.ModelSerializer):
    """Sipariş satırı: miktarlar sipariş birimiyle (`*_in_unit`) ve temel birimde."""

    product_code = serializers.CharField(source="product.code", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    base_unit_code = serializers.CharField(source="product.base_unit.code", read_only=True)
    shipped_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()
    shipped_in_unit = serializers.SerializerMethodField()
    remaining_in_unit = serializers.SerializerMethodField()
    line_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True, allow_null=True
    )

    class Meta:
        model = SalesOrderLine
        fields = [
            "line_no",
            "product_code",
            "product_name",
            "quantity",
            "unit_code",
            "base_quantity",
            "base_unit_code",
            "shipped_quantity",
            "remaining_quantity",
            "shipped_in_unit",
            "remaining_in_unit",
            "unit_price",
            "currency",
            "line_total",
        ]
        read_only_fields = fields

    @staticmethod
    def _shipped(line: SalesOrderLine) -> Decimal:
        return getattr(line, "shipped_quantity", None) or Decimal(0)

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_shipped_quantity(self, line: SalesOrderLine) -> str:
        return f"{self._shipped(line):.4f}"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_remaining_quantity(self, line: SalesOrderLine) -> str:
        return f"{sales_selectors.line_remaining(line):.4f}"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_shipped_in_unit(self, line: SalesOrderLine) -> str:
        return f"{sales_selectors.in_order_unit(line, self._shipped(line)):.4f}"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_remaining_in_unit(self, line: SalesOrderLine) -> str:
        remaining = sales_selectors.line_remaining(line)
        return f"{sales_selectors.in_order_unit(line, remaining):.4f}"


class PortalOrderTotalSerializer(serializers.Serializer):
    currency = serializers.CharField()
    amount = _money()


class PortalCustomerOrderSerializer(serializers.ModelSerializer):
    """Müşterinin siparişi: vade (termin, yoksa istenen teslim), durum, satırlar, tutar."""

    status_display = serializers.SerializerMethodField()
    due_date = serializers.DateField(read_only=True, allow_null=True)
    lines = PortalCustomerOrderLineSerializer(many=True, read_only=True)
    totals = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "number",
            "customer_po_no",
            "order_date",
            "requested_delivery_date",
            "promised_date",
            "due_date",
            "status",
            "status_display",
            "delivery_address",
            "lines",
            "totals",
        ]
        read_only_fields = fields

    def get_status_display(self, order: SalesOrder) -> str:
        return sales_order_states.label(order.status)

    @extend_schema_field(PortalOrderTotalSerializer(many=True))
    def get_totals(self, order: SalesOrder) -> list[dict[str, str]]:
        totals: dict[str, Decimal] = {}
        for line in order.lines.all():
            if line.unit_price is not None:
                amount = line.quantity * line.unit_price
                totals[line.currency] = totals.get(line.currency, Decimal(0)) + amount
        return [
            {"currency": currency, "amount": f"{amount.quantize(CENT, ROUND_HALF_UP):.2f}"}
            for currency, amount in sorted(totals.items())
        ]


class PortalCustomerShipmentLineSerializer(serializers.Serializer):
    line_no = serializers.IntegerField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    quantity = _quantity()
    base_unit_code = serializers.CharField()
    quantity_in_unit = _quantity()
    unit_code = serializers.CharField()


class PortalCustomerShipmentSerializer(serializers.ModelSerializer):
    """Sevkiyat: planlanan tarih ve durum; araç ve taşıyıcı yalnız sevk edildikten sonra
    görünür. Şoför bilgisi yalnız irsaliyededir (TC maskeli)."""

    status_display = serializers.SerializerMethodField()
    order_id = serializers.IntegerField(source="sales_order_id", read_only=True)
    order_number = serializers.CharField(source="sales_order.number", read_only=True)
    customer_po_no = serializers.CharField(source="sales_order.customer_po_no", read_only=True)
    vehicle_plate = serializers.SerializerMethodField()
    carrier = serializers.SerializerMethodField()
    has_waybill = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "order_id",
            "order_number",
            "customer_po_no",
            "planned_date",
            "dispatched_at",
            "vehicle_plate",
            "carrier",
            "has_waybill",
        ]
        read_only_fields = fields

    @staticmethod
    def _dispatched(shipment: Shipment) -> bool:
        return shipment.status == Shipment.Status.DISPATCHED

    def get_status_display(self, shipment: Shipment) -> str:
        return shipment_states.label(shipment.status)

    def get_vehicle_plate(self, shipment: Shipment) -> str:
        return shipment.vehicle_plate if self._dispatched(shipment) else ""

    def get_carrier(self, shipment: Shipment) -> str:
        return shipment.carrier if self._dispatched(shipment) else ""

    def get_has_waybill(self, shipment: Shipment) -> bool:
        return self._dispatched(shipment)


class PortalCustomerShipmentDetailSerializer(PortalCustomerShipmentSerializer):
    lines = serializers.SerializerMethodField()

    class Meta(PortalCustomerShipmentSerializer.Meta):
        fields = [*PortalCustomerShipmentSerializer.Meta.fields, "lines"]
        read_only_fields = fields

    @extend_schema_field(PortalCustomerShipmentLineSerializer(many=True))
    def get_lines(self, shipment: Shipment) -> Any:
        return PortalCustomerShipmentLineSerializer(
            selectors.shipment_lines(shipment), many=True
        ).data


# --- cari hesabım ---------------------------------------------------------------------------


class PortalAgingSerializer(serializers.Serializer):
    not_due = _money()
    d1_30 = _money()
    d31_60 = _money()
    d61_90 = _money()
    d90_plus = _money()


class PortalBalanceSerializer(serializers.Serializer):
    """Para birimi başına bakiye: artı ise firma borçlu (B), eksi ise alacaklı (A)."""

    currency = serializers.CharField()
    debit = _money()
    credit = _money()
    balance = _money()
    overdue = _money()
    last_date = serializers.DateField(allow_null=True)
    aging = PortalAgingSerializer()


class PortalStatementEntrySerializer(serializers.Serializer):
    number = serializers.CharField(source="entry.number")
    entry_date = serializers.DateField(source="entry.entry_date")
    kind_display = serializers.CharField(source="entry.get_kind_display")
    document = serializers.SerializerMethodField()
    description = serializers.CharField(source="entry.description")
    debit = serializers.DecimalField(
        source="entry.debit", max_digits=18, decimal_places=2, read_only=True
    )
    credit = serializers.DecimalField(
        source="entry.credit", max_digits=18, decimal_places=2, read_only=True
    )
    balance = _money()
    due_date = serializers.DateField(allow_null=True)
    is_reversed = serializers.BooleanField()

    def get_document(self, row: dict[str, Any]) -> str:
        entry = row["entry"]
        for attr in ("shipment", "customer_return", "goods_receipt", "reversal_of"):
            target = getattr(entry, attr, None)
            if target is not None:
                return str(target.number)
        return str(entry.reference or "")


class PortalStatementCurrencySerializer(serializers.Serializer):
    currency = serializers.CharField()
    opening = _money()
    rows = PortalStatementEntrySerializer(many=True)
    total_debit = _money()
    total_credit = _money()
    closing = _money()


class PortalStatementSerializer(serializers.Serializer):
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)
    currencies = PortalStatementCurrencySerializer(many=True)


class PortalStatementQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False, allow_null=True, default=None)
    date_to = serializers.DateField(required=False, allow_null=True, default=None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start, end = attrs.get("date_from"), attrs.get("date_to")
        if start and end and start > end:
            raise serializers.ValidationError({"date_to": "Bitiş tarihi başlangıçtan önce olamaz."})
        return attrs
