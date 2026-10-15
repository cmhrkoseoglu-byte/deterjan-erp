from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.quality.models import (
    QualityDecision,
    Sample,
    Specification,
    SpecificationLine,
    TestDefinition,
    TestResult,
)


class SpecificationLineInline(admin.TabularInline):
    model = SpecificationLine
    extra = 0
    fields = (
        "sequence",
        "test",
        "min_value",
        "max_value",
        "target_value",
        "text_expected",
        "is_mandatory",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


class TestResultInline(admin.TabularInline):
    model = TestResult
    extra = 0
    fields = (
        "spec_line",
        "numeric_value",
        "text_value",
        "passed",
        "is_within_spec",
        "measured_by",
        "measured_at",
        "superseded_by",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


class QualityDecisionInline(admin.TabularInline):
    model = QualityDecision
    extra = 0
    fields = ("decision", "reason", "decided_by", "decided_at", "approval_status", "approved_by")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(TestDefinition)
class TestDefinitionAdmin(ReadOnlyAdmin):
    """Test tanımları uygulamadan yönetilir; panelde yalnızca görüntülenir."""

    list_display = ("code", "name", "result_type", "unit", "is_active")
    search_fields = ("code", "name")
    list_filter = ("result_type", "is_active")


@admin.register(Specification)
class SpecificationAdmin(ReadOnlyAdmin):
    list_display = ("material", "sample_stage", "version_no", "status", "approved_at")
    list_filter = ("status", "sample_stage")
    search_fields = ("material__code", "material__name")
    inlines = [SpecificationLineInline]


@admin.register(Sample)
class SampleAdmin(ReadOnlyAdmin):
    list_display = ("number", "lot", "stage", "status", "created_at")
    list_filter = ("status", "stage", "origin")
    search_fields = ("number", "lot__lot_no")
    inlines = [TestResultInline, QualityDecisionInline]
