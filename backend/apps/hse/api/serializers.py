from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework import serializers

from apps.core.models import Attachment
from apps.hse import selectors
from apps.hse.models import (
    HazardClass,
    HazardStatement,
    HseSettings,
    Incident,
    MaterialHazard,
    SafetyDataSheet,
    SignalWord,
    StorageLimit,
    WasteContractor,
    WasteRecord,
)
from apps.hse.state import incident_states, waste_record_states
from apps.inventory.api.serializers import UserNameField
from apps.masterdata.models import Equipment, Location, Material, Supplier


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=18, decimal_places=4, **kwargs)


def _blank(**kwargs: Any) -> serializers.CharField:
    return serializers.CharField(required=False, allow_blank=True, default="", **kwargs)


class HseSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = HseSettings
        fields = ["sds_max_age_months"]


class HazardStatementSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = HazardStatement
        fields = ["id", "code", "kind", "kind_display", "text", "is_active"]
        read_only_fields = ["is_active"]
        # Kod tekrarını servis (Türkçe mesajla) denetler.
        extra_kwargs: dict[str, Any] = {"code": {"validators": []}}


class HazardStatementUpdateSerializer(serializers.Serializer):
    text = serializers.CharField()


class StatementBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = HazardStatement
        fields = ["id", "code", "kind", "text"]


class MaterialHazardSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    is_hazardous = serializers.BooleanField(source="material.is_hazardous", read_only=True)
    pictograms = serializers.ListField(
        child=serializers.ChoiceField(choices=HazardClass.choices), required=False, default=list
    )
    pictogram_labels = serializers.SerializerMethodField()
    signal_word = serializers.ChoiceField(
        choices=SignalWord.choices, required=False, allow_blank=True, default=""
    )
    signal_word_display = serializers.CharField(source="get_signal_word_display", read_only=True)
    statements = serializers.PrimaryKeyRelatedField(
        queryset=HazardStatement.objects.all(), many=True, required=False, default=list
    )
    statement_rows = StatementBriefSerializer(source="statements", many=True, read_only=True)
    note = _blank()

    class Meta:
        model = MaterialHazard
        fields = [
            "id",
            "material",
            "material_code",
            "material_name",
            "is_hazardous",
            "pictograms",
            "pictogram_labels",
            "signal_word",
            "signal_word_display",
            "statements",
            "statement_rows",
            "note",
        ]
        read_only_fields = ["material"]

    def get_pictogram_labels(self, hazard: MaterialHazard) -> list[str]:
        return [selectors.HAZARD_LABELS.get(code, code) for code in hazard.pictograms]


class SafetyDataSheetSerializer(serializers.ModelSerializer):
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    supplier = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.all(), required=False, allow_null=True
    )
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    language = serializers.CharField(required=False, default="tr")
    note = _blank()
    is_current = serializers.BooleanField(read_only=True)
    file_count = serializers.SerializerMethodField()
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = SafetyDataSheet
        fields = [
            "id",
            "material",
            "material_code",
            "material_name",
            "supplier",
            "supplier_name",
            "revision_no",
            "revision_date",
            "valid_until",
            "language",
            "note",
            "superseded_at",
            "is_current",
            "file_count",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = ["superseded_at", "created_at"]

    def get_file_count(self, sheet: SafetyDataSheet) -> int:
        content_type = ContentType.objects.get_for_model(SafetyDataSheet)
        return Attachment.objects.filter(
            content_type=content_type, object_id=sheet.pk, is_active=True
        ).count()


class SafetyDataSheetUpdateSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = SafetyDataSheet
        fields = ["supplier", "revision_no", "revision_date", "valid_until", "language", "note"]


class SdsStatusSerializer(serializers.Serializer):
    material_id = serializers.IntegerField()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    material_type = serializers.CharField()
    material_type_display = serializers.CharField()
    is_hazardous = serializers.BooleanField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    sds_id = serializers.IntegerField(allow_null=True)
    revision_no = serializers.CharField()
    revision_date = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    has_file = serializers.BooleanField()


class StorageLimitSerializer(serializers.ModelSerializer):
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
    location_code = serializers.CharField(source="location.code", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    hazard_class_display = serializers.CharField(source="get_hazard_class_display", read_only=True)
    max_kg = _quantity()
    note = _blank()

    class Meta:
        model = StorageLimit
        fields = [
            "id",
            "location",
            "location_code",
            "location_name",
            "hazard_class",
            "hazard_class_display",
            "max_kg",
            "note",
            "is_active",
        ]
        read_only_fields = ["is_active"]
        validators: list[Any] = []  # tekrar denetimi servis / model doğrulamasında


class StorageUtilisationSerializer(serializers.Serializer):
    limit_id = serializers.IntegerField()
    location_id = serializers.IntegerField()
    location_code = serializers.CharField()
    location_name = serializers.CharField()
    hazard_class = serializers.CharField()
    hazard_class_display = serializers.CharField()
    limit_kg = _quantity()
    quantity_kg = _quantity()
    pct = serializers.DecimalField(max_digits=18, decimal_places=2)
    exceeded = serializers.BooleanField()


class WasteContractorSerializer(serializers.ModelSerializer):
    phone = _blank()
    note = _blank()
    license_expired = serializers.SerializerMethodField()

    class Meta:
        model = WasteContractor
        fields = [
            "id",
            "name",
            "license_no",
            "license_valid_until",
            "license_expired",
            "phone",
            "note",
            "is_active",
        ]
        read_only_fields = ["is_active"]

    def get_license_expired(self, contractor: WasteContractor) -> bool:
        return contractor.license_valid_until < timezone.localdate()


class WasteRecordSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    contractor = serializers.PrimaryKeyRelatedField(queryset=WasteContractor.objects.all())
    contractor_name = serializers.CharField(source="contractor.name", read_only=True)
    contractor_license_no = serializers.CharField(source="contractor.license_no", read_only=True)
    waste_code = serializers.CharField(max_length=16)
    is_hazardous = serializers.BooleanField(required=False, default=False)
    quantity_kg = _quantity()
    document_no = _blank()
    note = _blank()
    created_by_name = UserNameField(source="created_by")

    class Meta:
        model = WasteRecord
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "waste_code",
            "description",
            "is_hazardous",
            "quantity_kg",
            "contractor",
            "contractor_name",
            "contractor_license_no",
            "delivered_on",
            "document_no",
            "note",
            "cancel_reason",
            "created_at",
            "created_by_name",
        ]
        read_only_fields = ["number", "status", "cancel_reason", "created_at"]

    def get_status_display(self, record: WasteRecord) -> str:
        return waste_record_states.label(record.status)


class WasteSummarySerializer(serializers.Serializer):
    waste_code = serializers.CharField()
    description = serializers.CharField()
    is_hazardous = serializers.BooleanField()
    count = serializers.IntegerField()
    quantity_kg = _quantity()


class IncidentSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    incident_type_display = serializers.CharField(
        source="get_incident_type_display", read_only=True
    )
    severity = serializers.ChoiceField(
        choices=Incident.Severity.choices, required=False, default=Incident.Severity.LOW
    )
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    place = _blank()
    location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    location_code = serializers.CharField(source="location.code", read_only=True, default=None)
    equipment = serializers.PrimaryKeyRelatedField(
        queryset=Equipment.objects.all(), required=False, allow_null=True
    )
    equipment_code = serializers.CharField(source="equipment.code", read_only=True, default=None)
    description = serializers.CharField(allow_blank=True)
    injury = serializers.BooleanField(required=False, default=False)
    injured_person = _blank()
    created_by_name = UserNameField(source="created_by")
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Incident
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "incident_type",
            "incident_type_display",
            "occurred_at",
            "place",
            "location",
            "location_code",
            "equipment",
            "equipment_code",
            "description",
            "injury",
            "injured_person",
            "severity",
            "severity_display",
            "root_cause",
            "corrective_action",
            "action_owner",
            "action_due",
            "closed_note",
            "cancel_reason",
            "created_at",
            "created_by_name",
            "allowed_transitions",
        ]
        read_only_fields = [
            "number",
            "status",
            "root_cause",
            "corrective_action",
            "action_owner",
            "action_due",
            "closed_note",
            "cancel_reason",
            "created_at",
        ]

    def get_status_display(self, incident: Incident) -> str:
        return incident_states.label(incident.status)

    def get_allowed_transitions(self, incident: Incident) -> list[str]:
        return incident_states.allowed_transitions(incident.status)


class InvestigationSerializer(serializers.Serializer):
    severity = serializers.ChoiceField(choices=Incident.Severity.choices, required=False)
    root_cause = serializers.CharField(required=False, allow_blank=True)
    corrective_action = serializers.CharField(required=False, allow_blank=True)
    action_owner = serializers.CharField(required=False, allow_blank=True, max_length=200)
    action_due = serializers.DateField(required=False, allow_null=True)


class CloseIncidentSerializer(InvestigationSerializer):
    closed_note = serializers.CharField(required=False, allow_blank=True)


class CountRowSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    count = serializers.IntegerField()


class IncidentSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    injury_count = serializers.IntegerField()
    open_count = serializers.IntegerField()
    by_type = CountRowSerializer(many=True)
    by_severity = CountRowSerializer(many=True)


class HseSummarySerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    incidents = IncidentSummarySerializer()
    waste = WasteSummarySerializer(many=True)
