"""Rapor filtreleri: ekran sorgusu ve arka plan işi aynı doğrulamayı kullanır.

Arka plan işi filtreleri JSON olarak saklar (`ReportJob.params`, kimlikler ve ISO tarihler) ve
çalışırken bu serializer ile yeniden çözer.
"""

from datetime import timedelta
from typing import Any

from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework import serializers

from apps.core.roles import ROLE_LABELS
from apps.inventory.models import Lot, StockMovement
from apps.masterdata.models import Customer, Equipment, Location, Material, Warehouse
from apps.quality.models import QualityDecision, SampleStage
from apps.reporting.reports import ReportDefinition

MAX_RANGE_DAYS = 366


class ReportFilterSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False, label="başlangıç tarihi")
    date_to = serializers.DateField(required=False, label="bitiş tarihi")
    material = serializers.PrimaryKeyRelatedField(
        queryset=Material.objects.all(), required=False, label="malzeme"
    )
    material_type = serializers.ChoiceField(
        choices=Material.Type.choices, required=False, label="malzeme türü"
    )
    warehouse = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.objects.all(), required=False, label="depo"
    )
    location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, label="lokasyon"
    )
    equipment = serializers.PrimaryKeyRelatedField(
        queryset=Equipment.objects.all(), required=False, label="ekipman"
    )
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(), required=False, label="müşteri"
    )
    lot_status = serializers.ChoiceField(
        choices=Lot.Status.choices, required=False, label="lot durumu"
    )
    movement_type = serializers.ChoiceField(
        choices=StockMovement.Type.choices, required=False, label="hareket türü"
    )
    stage = serializers.ChoiceField(choices=SampleStage.choices, required=False, label="aşama")
    decision = serializers.ChoiceField(
        choices=QualityDecision.Decision.choices, required=False, label="karar"
    )
    role = serializers.SlugRelatedField(
        slug_field="name", queryset=Group.objects.all(), required=False, label="birim"
    )
    lot_no = serializers.CharField(required=False, max_length=64, label="lot no")
    expiring_days = serializers.IntegerField(
        required=False, min_value=0, max_value=3650, label="SKT'ye kalan gün"
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start, end = attrs.get("date_from"), attrs.get("date_to")
        if start and end:
            if start > end:
                raise serializers.ValidationError(
                    {"date_to": "Bitiş tarihi başlangıçtan önce olamaz."}
                )
            if (end - start).days > MAX_RANGE_DAYS:
                raise serializers.ValidationError(
                    {"date_from": f"Tarih aralığı en fazla {MAX_RANGE_DAYS} gün olabilir."}
                )
        return attrs


def parse_filters(definition: ReportDefinition, data: Any) -> dict[str, Any]:
    """Raporun kabul ettiği filtreleri doğrular; tarih filtresi boşsa varsayılan aralık (son
    `default_days` gün) uygulanır. Geçersiz değer `ValidationError` (400) verir."""
    allowed = set(definition.filters)
    raw = {key: data[key] for key in allowed if key in data and data[key] not in ("", None)}
    serializer = ReportFilterSerializer(data=raw)
    serializer.is_valid(raise_exception=True)
    values = {k: v for k, v in serializer.validated_data.items() if k in allowed}
    if definition.default_days and "date_from" in allowed and not values.get("date_from"):
        end = values.get("date_to") or timezone.localdate()
        values["date_from"] = end - timedelta(days=definition.default_days - 1)
    return values


def to_params(values: dict[str, Any]) -> dict[str, Any]:
    """Çözülmüş filtreleri JSON'a yazılabilir hale getirir (kimlik, ISO tarih, kod)."""
    params: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, Group):
            params[key] = value.name
        elif hasattr(value, "pk"):
            params[key] = value.pk
        elif hasattr(value, "isoformat"):
            params[key] = value.isoformat()
        else:
            params[key] = value
    return params


def describe(values: dict[str, Any]) -> list[tuple[str, str]]:
    """Dosya başlığında gösterilen filtreler (Türkçe etiket, değer)."""
    fields = ReportFilterSerializer().fields
    out = []
    for key, value in values.items():
        field = fields[key]
        if isinstance(value, Group):
            text = ROLE_LABELS.get(value.name, value.name)
        elif hasattr(value, "strftime"):
            text = value.strftime("%d.%m.%Y")
        elif isinstance(field, serializers.ChoiceField):
            text = str(field.choices.get(value, value))
        else:
            text = str(value)
        out.append((str(field.label).capitalize(), text))
    return out
