from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import User
from apps.inventory.api.serializers import UserNameField
from apps.inventory.models import Lot
from apps.masterdata.models import Location, Material
from apps.quality import coa, services
from apps.quality.models import (
    QualityDecision,
    Sample,
    SampleStage,
    Specification,
    SpecificationLine,
    TestDefinition,
    TestResult,
)
from apps.quality.state import sample_states

# --- test tanımı -----------------------------------------------------------------------------


class TestDefinitionSerializer(serializers.ModelSerializer):
    result_type_display = serializers.CharField(source="get_result_type_display", read_only=True)

    class Meta:
        model = TestDefinition
        fields = [
            "id",
            "code",
            "name",
            "result_type",
            "result_type_display",
            "unit",
            "method",
            "decimal_places",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["is_active", "created_at", "updated_at"]
        extra_kwargs: dict[str, dict[str, Any]] = {"code": {"validators": []}}


# --- spesifikasyon ---------------------------------------------------------------------------


class SpecificationLineSerializer(serializers.ModelSerializer):
    test = serializers.PrimaryKeyRelatedField(queryset=TestDefinition.objects.all())
    test_code = serializers.CharField(source="test.code", read_only=True)
    test_name = serializers.CharField(source="test.name", read_only=True)
    result_type = serializers.CharField(source="test.result_type", read_only=True)
    unit = serializers.CharField(source="test.unit", read_only=True)
    decimal_places = serializers.IntegerField(source="test.decimal_places", read_only=True)
    sequence = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    text_expected = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )

    class Meta:
        model = SpecificationLine
        fields = [
            "id",
            "specification",
            "sequence",
            "test",
            "test_code",
            "test_name",
            "result_type",
            "unit",
            "decimal_places",
            "min_value",
            "max_value",
            "target_value",
            "text_expected",
            "is_mandatory",
        ]
        read_only_fields = ["specification"]
        validators: list = []


class SpecificationSerializer(serializers.ModelSerializer):
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    material_type = serializers.CharField(source="material.material_type", read_only=True)
    sample_stage_display = serializers.CharField(source="get_sample_stage_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    copied_from_no = serializers.IntegerField(
        source="copied_from.version_no", read_only=True, default=None
    )
    approved_by_name = UserNameField(source="approved_by")
    created_by_name = UserNameField(source="created_by")
    line_count = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = Specification
        fields = [
            "id",
            "material",
            "material_code",
            "material_name",
            "material_type",
            "sample_stage",
            "sample_stage_display",
            "version_no",
            "status",
            "status_display",
            "change_note",
            "copied_from",
            "copied_from_no",
            "approved_by_name",
            "approved_at",
            "obsoleted_at",
            "created_by_name",
            "created_at",
            "line_count",
        ]
        read_only_fields = [
            "version_no",
            "status",
            "copied_from",
            "approved_at",
            "obsoleted_at",
            "created_at",
        ]


class SpecificationDetailSerializer(SpecificationSerializer):
    lines = SpecificationLineSerializer(many=True, read_only=True)
    is_editable = serializers.SerializerMethodField()

    class Meta(SpecificationSerializer.Meta):
        fields = [*SpecificationSerializer.Meta.fields, "lines", "is_editable"]

    def get_is_editable(self, spec: Specification) -> bool:
        return spec.status == Specification.Status.DRAFT


class SpecificationCreateSerializer(serializers.Serializer):
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    sample_stage = serializers.ChoiceField(choices=SampleStage.choices)
    change_note = serializers.CharField(required=False, allow_blank=True, default="")
    lines = SpecificationLineSerializer(many=True, required=False)


class QualityNoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


# --- numune ----------------------------------------------------------------------------------


class SampleSerializer(serializers.ModelSerializer):
    lot = serializers.PrimaryKeyRelatedField(queryset=Lot.objects.select_related("material"))
    lot_no = serializers.CharField(source="lot.lot_no", read_only=True)
    lot_status = serializers.CharField(source="lot.status", read_only=True)
    material = serializers.IntegerField(source="lot.material_id", read_only=True)
    material_code = serializers.CharField(source="lot.material.code", read_only=True)
    material_name = serializers.CharField(source="lot.material.name", read_only=True)
    material_type = serializers.CharField(source="lot.material.material_type", read_only=True)
    stage_display = serializers.CharField(source="get_stage_display", read_only=True)
    origin_display = serializers.CharField(source="get_origin_display", read_only=True)
    status_display = serializers.SerializerMethodField()
    specification_label = serializers.SerializerMethodField()
    taken_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    taken_by_name = UserNameField(source="taken_by")
    retain_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    retain_location_code = serializers.CharField(
        source="retain_location.code", read_only=True, default=None
    )
    created_by_name = UserNameField(source="created_by")
    waiting_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Sample
        fields = [
            "id",
            "number",
            "status",
            "status_display",
            "lot",
            "lot_no",
            "lot_status",
            "material",
            "material_code",
            "material_name",
            "material_type",
            "stage",
            "stage_display",
            "origin",
            "origin_display",
            "specification",
            "specification_label",
            "taken_by",
            "taken_by_name",
            "taken_at",
            "retain_location",
            "retain_location_code",
            "note",
            "decided_at",
            "created_by_name",
            "created_at",
            "waiting_minutes",
        ]
        read_only_fields = ["number", "status", "origin", "specification", "decided_at"]

    def get_status_display(self, sample: Sample) -> str:
        return sample_states.label(sample.status)

    def get_specification_label(self, sample: Sample) -> str | None:
        spec = sample.specification
        return f"v{spec.version_no}" if spec is not None else None

    def get_waiting_minutes(self, sample: Sample) -> int | None:
        """Karar bekleyen numunenin açılıştan beri geçen süresi (dakika)."""
        if sample.status in (Sample.Status.DECIDED, Sample.Status.CANCELLED):
            return None
        return int((timezone.now() - sample.created_at).total_seconds() // 60)


class SampleCreateSerializer(serializers.Serializer):
    lot = serializers.PrimaryKeyRelatedField(queryset=Lot.objects.all())
    stage = serializers.ChoiceField(choices=SampleStage.choices)
    taken_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    retain_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True, default=None
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class TestResultSerializer(serializers.ModelSerializer):
    test_code = serializers.CharField(source="spec_line.test.code", read_only=True)
    measured_by_name = UserNameField(source="measured_by")

    class Meta:
        model = TestResult
        fields = [
            "id",
            "spec_line",
            "test_code",
            "numeric_value",
            "text_value",
            "passed",
            "is_within_spec",
            "measured_by_name",
            "measured_at",
            "instrument",
            "note",
            "superseded_by",
            "created_at",
        ]
        read_only_fields = fields


class ResultInputSerializer(serializers.Serializer):
    spec_line = serializers.PrimaryKeyRelatedField(
        queryset=SpecificationLine.objects.select_related("test")
    )
    numeric_value = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, allow_null=True, default=None
    )
    text_value = serializers.CharField(required=False, allow_blank=True, default="")
    passed = serializers.BooleanField(required=False, allow_null=True, default=None)
    instrument = serializers.CharField(required=False, allow_blank=True, default="")
    measured_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class AssignSpecificationSerializer(serializers.Serializer):
    specification = serializers.PrimaryKeyRelatedField(queryset=Specification.objects.all())


class DecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=QualityDecision.Decision.choices)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    release_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True, default=None
    )


class SampleCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True)


class ReviewSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class QualityDecisionSerializer(serializers.ModelSerializer):
    decision_display = serializers.CharField(source="get_decision_display", read_only=True)
    approval_status_display = serializers.CharField(
        source="get_approval_status_display", read_only=True
    )
    decided_by_name = UserNameField(source="decided_by")
    approved_by_name = UserNameField(source="approved_by")
    release_location_code = serializers.CharField(
        source="release_location.code", read_only=True, default=None
    )
    sample_number = serializers.CharField(source="sample.number", read_only=True)
    lot_no = serializers.CharField(source="sample.lot.lot_no", read_only=True)
    material_code = serializers.CharField(source="sample.lot.material.code", read_only=True)
    material_name = serializers.CharField(source="sample.lot.material.name", read_only=True)

    class Meta:
        model = QualityDecision
        fields = [
            "id",
            "sample",
            "sample_number",
            "lot_no",
            "material_code",
            "material_name",
            "decision",
            "decision_display",
            "reason",
            "decided_by_name",
            "decided_at",
            "release_location",
            "release_location_code",
            "approval_status",
            "approval_status_display",
            "approved_by_name",
            "approved_at",
            "approval_note",
        ]
        read_only_fields = fields


class SampleLineSerializer(serializers.Serializer):
    """Numune detayında bir spesifikasyon satırı: sınırlar, geçerli sonuç ve düzeltme geçmişi."""

    line = SpecificationLineSerializer()
    current = TestResultSerializer(allow_null=True)
    history = TestResultSerializer(many=True)


class SampleDetailSerializer(SampleSerializer):
    lines = serializers.SerializerMethodField()
    decisions = QualityDecisionSerializer(many=True, read_only=True)
    missing_tests = serializers.SerializerMethodField()
    out_of_spec_tests = serializers.SerializerMethodField()
    default_release_location = serializers.SerializerMethodField()
    allowed_transitions = serializers.SerializerMethodField()
    cancel_reason = serializers.CharField(read_only=True)
    coa_available = serializers.SerializerMethodField()

    class Meta(SampleSerializer.Meta):
        fields = [
            *SampleSerializer.Meta.fields,
            "lines",
            "decisions",
            "missing_tests",
            "out_of_spec_tests",
            "default_release_location",
            "allowed_transitions",
            "cancel_reason",
            "coa_available",
        ]

    @extend_schema_field(SampleLineSerializer(many=True))
    def get_lines(self, sample: Sample) -> Any:
        if sample.specification_id is None:
            return []
        results = list(
            sample.results.select_related("spec_line__test", "measured_by").order_by("id")
        )
        rows = []
        for line in sample.specification.lines.select_related("test").order_by("sequence"):  # type: ignore[union-attr]
            own = [r for r in results if r.spec_line_id == line.pk]
            current = next((r for r in own if r.superseded_by_id is None), None)
            rows.append(
                {"line": line, "current": current, "history": [r for r in own if r is not current]}
            )
        return SampleLineSerializer(rows, many=True).data

    def get_missing_tests(self, sample: Sample) -> list[str]:
        return [line.test.code for line in services.missing_mandatory_tests(sample)]

    def get_out_of_spec_tests(self, sample: Sample) -> list[str]:
        return [r.spec_line.test.code for r in services.out_of_spec_results(sample)]

    def get_default_release_location(self, sample: Sample) -> int | None:
        location = services.default_release_location(sample.lot)
        return location.pk if location is not None else None

    def get_allowed_transitions(self, sample: Sample) -> list[str]:
        return sample_states.allowed_transitions(sample.status)

    def get_coa_available(self, sample: Sample) -> bool:
        return coa.coa_available(sample)
