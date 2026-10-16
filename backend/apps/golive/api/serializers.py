from rest_framework import serializers

from apps.golive.models import ProblemReport, StockComparison, StockComparisonLine


class CheckSerializer(serializers.Serializer):
    code = serializers.CharField()
    group = serializers.CharField()
    title = serializers.CharField()
    status = serializers.ChoiceField(choices=["OK", "WARNING", "MISSING"])
    detail = serializers.CharField()
    count = serializers.IntegerField(allow_null=True)
    link = serializers.CharField()
    items = serializers.ListField(child=serializers.CharField())
    more = serializers.IntegerField()


class GoLiveSerializer(serializers.Serializer):
    go_live_date = serializers.DateField(allow_null=True)
    opening_open = serializers.BooleanField(read_only=True)


class StockComparisonSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source="get_level_display", read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockComparison
        fields = [
            "id",
            "number",
            "as_of_date",
            "level",
            "level_display",
            "only_file_materials",
            "file_name",
            "note",
            "line_count",
            "difference_count",
            "created_at",
            "created_by_name",
        ]

    def get_created_by_name(self, obj: StockComparison) -> str:
        user = obj.created_by
        return (user.get_full_name() or user.username) if user else ""


class StockComparisonCreateSerializer(serializers.Serializer):
    file = serializers.FileField(label="Stok listesi (.xlsx / .csv)")
    as_of_date = serializers.DateField(required=False, allow_null=True)
    only_file_materials = serializers.BooleanField(default=False)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class StockComparisonLineSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.code")
    material_name = serializers.CharField(source="material.name")
    unit = serializers.CharField(source="material.base_unit.code")
    location_code = serializers.CharField(source="location.code", default="")

    class Meta:
        model = StockComparisonLine
        fields = [
            "id",
            "material",
            "material_code",
            "material_name",
            "lot_no",
            "location",
            "location_code",
            "file_quantity",
            "system_quantity",
            "difference",
            "unit",
            "in_file",
        ]


class ProblemReportSerializer(serializers.ModelSerializer):
    reporter = serializers.SerializerMethodField()
    has_screenshot = serializers.SerializerMethodField()

    class Meta:
        model = ProblemReport
        fields = [
            "id",
            "number",
            "description",
            "page_url",
            "page_title",
            "user_agent",
            "screen",
            "has_screenshot",
            "reporter",
            "created_at",
        ]

    def get_reporter(self, obj: ProblemReport) -> str:
        user = obj.created_by
        return (user.get_full_name() or user.username) if user else ""

    def get_has_screenshot(self, obj: ProblemReport) -> bool:
        return bool(obj.screenshot)


class ProblemReportCreateSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=5000)
    page_url = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    page_title = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    user_agent = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    screen = serializers.CharField(required=False, allow_blank=True, default="", max_length=32)
    screenshot = serializers.FileField(required=False, allow_null=True)
