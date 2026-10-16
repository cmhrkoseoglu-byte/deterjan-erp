from typing import Any

from rest_framework import serializers

from apps.inventory.api.serializers import TraceNodeSerializer
from apps.inventory.models import Lot


def _qty() -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4)


class ShipmentRowSerializer(serializers.Serializer):
    """Sevkiyat satırı: lot + sevkiyat belgesi (müşteri, Adım 3.2 bağlayana kadar boş)."""

    lot_id = serializers.IntegerField()
    document_number = serializers.CharField()
    source_model = serializers.CharField(allow_null=True)
    source_id = serializers.IntegerField(allow_null=True)
    shipped_at = serializers.DateTimeField()
    quantity = _qty()
    customer_id = serializers.IntegerField(allow_null=True)
    customer_code = serializers.CharField(allow_null=True)
    customer_name = serializers.CharField(allow_null=True)
    order_number = serializers.CharField(allow_null=True)


class BackwardNodeSerializer(TraceNodeSerializer):
    """Geri izleme düğümü; satın alma lotunda tedarikçi ve mal kabul."""

    manufactured_at = serializers.DateField(allow_null=True)
    supplier_id = serializers.IntegerField(allow_null=True)
    supplier_code = serializers.CharField(allow_null=True)
    supplier_name = serializers.CharField(allow_null=True)
    supplier_lot_no = serializers.CharField(allow_blank=True)
    receipt_id = serializers.IntegerField(allow_null=True)
    receipt_number = serializers.CharField(allow_null=True)
    receipt_date = serializers.DateField(allow_null=True)


class ForwardNodeSerializer(TraceNodeSerializer):
    """İleri izleme düğümü; stokta, sevk edilen ve iade gelen miktar, sevkiyat satırları."""

    on_hand = _qty()
    shipped = _qty()
    returned = _qty()
    shipments = ShipmentRowSerializer(many=True)

    def to_representation(self, instance: dict[str, Any]) -> dict[str, Any]:
        data = super().to_representation(instance)
        data["shipments"] = ShipmentRowSerializer(instance["shipments"], many=True).data
        return data


class LotRefSerializer(serializers.Serializer):
    lot_id = serializers.IntegerField()
    lot_no = serializers.CharField()
    lot_status = serializers.CharField()
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    material_type = serializers.CharField()
    unit = serializers.CharField()


class RecallLotSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    lot_no = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    material_type = serializers.CharField()
    unit = serializers.CharField()
    expiry_date = serializers.DateField(allow_null=True)
    is_selected = serializers.BooleanField()
    on_hand = _qty()
    shipped = _qty()
    returned = _qty()


class RecallStockSerializer(LotRefSerializer):
    location_id = serializers.IntegerField()
    location_code = serializers.CharField()
    location_name = serializers.CharField()
    location_type = serializers.CharField()
    warehouse_code = serializers.CharField()
    quantity = _qty()


class RecallShipmentSerializer(LotRefSerializer, ShipmentRowSerializer):
    pass


class RecallCustomerSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(allow_null=True)
    customer_code = serializers.CharField(allow_null=True)
    customer_name = serializers.CharField(allow_null=True)
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    unit = serializers.CharField()
    quantity = _qty()
    lots = serializers.ListField(child=serializers.CharField())
    documents = serializers.ListField(child=serializers.CharField())


class RecallSummarySerializer(serializers.Serializer):
    lot_count = serializers.IntegerField()
    finished_lot_count = serializers.IntegerField()
    lots_in_stock = serializers.IntegerField()
    shipped_lot_count = serializers.IntegerField()
    shipment_count = serializers.IntegerField()
    customer_count = serializers.IntegerField()


class RecallSerializer(serializers.Serializer):
    selected = serializers.ListField(child=serializers.IntegerField())
    lots = RecallLotSerializer(many=True)
    stock = RecallStockSerializer(many=True)
    shipments = RecallShipmentSerializer(many=True)
    customers = RecallCustomerSerializer(many=True)
    summary = RecallSummarySerializer()


class RecallQuerySerializer(serializers.Serializer):
    lot = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Lot.objects.all()),
        min_length=1,
        max_length=50,
        error_messages={"min_length": "En az bir lot seçilmelidir."},
    )
