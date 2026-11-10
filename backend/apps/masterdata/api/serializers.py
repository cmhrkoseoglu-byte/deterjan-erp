from typing import Any

from django.db.models.manager import BaseManager
from rest_framework import serializers

from apps.core.api.coding import FormerCodesListSerializer, FormerCodesMixin
from apps.masterdata import services
from apps.masterdata.models import (
    CompanyProfile,
    Customer,
    Equipment,
    LabelSettings,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    Printer,
    RetiredGtin,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)

AUDIT_FIELDS = ["is_active", "created_at", "updated_at"]
# Benzersizlik servis katmanında (kod büyük harfe çevrildikten sonra) denetlenir.
NO_UNIQUE_VALIDATOR: dict[str, dict[str, Any]] = {"code": {"validators": []}}


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = UnitOfMeasure
        fields = [
            "id",
            "code",
            "name",
            "kind",
            "kind_display",
            "factor_to_kind_base",
            "unece_code",
            "symbol",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class MaterialCategorySerializer(FormerCodesMixin, serializers.ModelSerializer):
    class Meta:
        model = MaterialCategory
        list_serializer_class = FormerCodesListSerializer
        fields = ["id", "code", "former_codes", "name", *AUDIT_FIELDS]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


# GTIN biçimi, tekilliği ve kilidi serviste denetlenir (Türkçe mesaj, hata kodu): uzun değer de
# `invalid_gtin` alsın diye alan uzunluğu burada sınırlanmaz.
GTIN_INPUT: dict[str, Any] = {"max_length": 32}


class RetiredGtinListSerializer(serializers.ListSerializer):
    """Eski koli GTIN'leri en yeniden eskiye. Liste ve detay sorgusu satırları önceden getirir
    (`prefetch_related`); sıralama burada yapılır, satır başına sorgu olmaz."""

    def to_representation(self, data: Any) -> list[Any]:
        rows = data.all() if isinstance(data, BaseManager) else data
        newest_first = sorted(rows, key=lambda row: (row.created_at, row.pk), reverse=True)
        return super().to_representation(newest_first)


class RetiredGtinSerializer(serializers.ModelSerializer):
    """Eski koli GTIN'i (salt okunur): koli içi miktar değişince eski miktarıyla arşivlenir; bir
    daha verilmez, okutulunca eski koli düzeniyle çözülür."""

    retired_at = serializers.DateTimeField(
        source="created_at", read_only=True, help_text="GTIN'in değiştiği an"
    )
    retired_by_name = serializers.SerializerMethodField(help_text="Değiştiren kullanıcı")

    class Meta:
        model = RetiredGtin
        list_serializer_class = RetiredGtinListSerializer
        fields = ["gtin", "factor_to_base", "replaced_by", "retired_at", "retired_by_name"]
        read_only_fields = fields

    def get_retired_by_name(self, instance: RetiredGtin) -> str:
        user = instance.created_by
        return (user.full_name or user.username) if user is not None else ""


class MaterialUnitConversionSerializer(serializers.ModelSerializer):
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    material_code = serializers.CharField(source="material.code", read_only=True)
    material_type = serializers.CharField(
        source="material.material_type",
        read_only=True,
        help_text="Malzemenin türü; koli GTIN'i önerisi yalnız mamulde (FINISHED).",
    )
    base_unit_code = serializers.CharField(source="material.base_unit.code", read_only=True)
    gtin_locked = serializers.SerializerMethodField(
        help_text="Lotu olan mamulde koli GTIN'i dolu: değiştirilemez; koli içi miktar yalnız "
        "yeni koli GTIN'iyle değişir (eski GTIN arşivlenir)."
    )
    retired_gtins = RetiredGtinSerializer(
        many=True,
        read_only=True,
        help_text="Eski koli GTIN'leri (koli içi miktar değişince arşivlenir), en yeniden eskiye",
    )

    class Meta:
        model = MaterialUnitConversion
        fields = [
            "id",
            "material",
            "material_code",
            "material_type",
            "unit",
            "unit_code",
            "factor_to_base",
            "base_unit_code",
            "gtin",
            "gtin_locked",
            "retired_gtins",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        validators: list = []
        extra_kwargs = {"gtin": GTIN_INPUT}

    def get_gtin_locked(self, instance: MaterialUnitConversion) -> bool:
        return services.case_gtin_locked(instance)


class MaterialSerializer(FormerCodesMixin, serializers.ModelSerializer):
    material_type_display = serializers.CharField(
        source="get_material_type_display", read_only=True
    )
    base_unit_code = serializers.CharField(source="base_unit.code", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    gtin_locked = serializers.SerializerMethodField(
        help_text="Mamul, GTIN dolu ve lotu var: değiştirilemez (kilit yalnız mamulde)."
    )

    class Meta:
        model = Material
        list_serializer_class = FormerCodesListSerializer
        fields = [
            "id",
            "code",
            "former_codes",
            "name",
            "material_type",
            "material_type_display",
            "category",
            "category_name",
            "base_unit",
            "base_unit_code",
            "density",
            "shelf_life_days",
            "min_stock",
            "gtin",
            "gtin_locked",
            "requires_incoming_qc",
            "is_hazardous",
            "storage_notes",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = {**NO_UNIQUE_VALIDATOR, "gtin": GTIN_INPUT}

    def get_gtin_locked(self, instance: Material) -> bool:
        return services.gtin_locked(instance)


class MaterialDetailSerializer(MaterialSerializer):
    conversions = MaterialUnitConversionSerializer(many=True, read_only=True)

    class Meta(MaterialSerializer.Meta):
        fields = [*MaterialSerializer.Meta.fields, "conversions"]


class WarehouseSerializer(FormerCodesMixin, serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        list_serializer_class = FormerCodesListSerializer
        fields = ["id", "code", "former_codes", "name", *AUDIT_FIELDS]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class LocationSerializer(FormerCodesMixin, serializers.ModelSerializer):
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    location_type_display = serializers.CharField(
        source="get_location_type_display", read_only=True
    )

    class Meta:
        model = Location
        list_serializer_class = FormerCodesListSerializer
        fields = [
            "id",
            "warehouse",
            "warehouse_code",
            "code",
            "former_codes",
            "name",
            "location_type",
            "location_type_display",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class EquipmentSerializer(FormerCodesMixin, serializers.ModelSerializer):
    equipment_type_display = serializers.CharField(
        source="get_equipment_type_display", read_only=True
    )
    capacity_unit_code = serializers.CharField(
        source="capacity_unit.code", read_only=True, default=None
    )
    location_code = serializers.CharField(source="location.code", read_only=True, default=None)

    class Meta:
        model = Equipment
        list_serializer_class = FormerCodesListSerializer
        fields = [
            "id",
            "code",
            "former_codes",
            "name",
            "equipment_type",
            "equipment_type_display",
            "capacity",
            "capacity_unit",
            "capacity_unit_code",
            "location",
            "location_code",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


PARTNER_FIELDS = [
    "id",
    "code",
    "former_codes",
    "name",
    "tax_office",
    "tax_number",
    "address",
    "phone",
    "email",
    "contact_person",
    "country_code",
    *AUDIT_FIELDS,
]


class SupplierSerializer(FormerCodesMixin, serializers.ModelSerializer):
    class Meta:
        model = Supplier
        list_serializer_class = FormerCodesListSerializer
        fields = PARTNER_FIELDS
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class CustomerSerializer(FormerCodesMixin, serializers.ModelSerializer):
    class Meta:
        model = Customer
        list_serializer_class = FormerCodesListSerializer
        fields = [*PARTNER_FIELDS, "min_remaining_shelf_life_days"]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class ImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField(label="Dosya (.xlsx / .csv)")
    confirm = serializers.BooleanField(
        label="Onayla", default=False, help_text="false: yalnızca önizleme, true: aktar"
    )


class ImportRowErrorSerializer(serializers.Serializer):
    column = serializers.CharField()
    message = serializers.CharField()


IMPORT_ROW_ACTIONS = ["create", "update"]


class ImportRowSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    code = serializers.CharField()
    action = serializers.ChoiceField(choices=IMPORT_ROW_ACTIONS)
    errors = ImportRowErrorSerializer(many=True)  # type: ignore[assignment]


class ImportReportSerializer(serializers.Serializer):
    kind = serializers.CharField()
    total = serializers.IntegerField()
    valid = serializers.IntegerField()
    invalid = serializers.IntegerField()
    to_create = serializers.IntegerField()
    to_update = serializers.IntegerField()
    file_errors = serializers.ListField(child=serializers.CharField())
    rows = ImportRowSerializer(many=True)
    imported = serializers.BooleanField()


class PrinterSerializer(FormerCodesMixin, serializers.ModelSerializer):
    printer_type_display = serializers.CharField(source="get_printer_type_display", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True, default=None)

    class Meta:
        model = Printer
        list_serializer_class = FormerCodesListSerializer
        fields = [
            "id",
            "code",
            "former_codes",
            "name",
            "printer_type",
            "printer_type_display",
            "host",
            "port",
            "dpi",
            "location",
            "location_code",
            "note",
            *AUDIT_FIELDS,
        ]
        read_only_fields = AUDIT_FIELDS
        extra_kwargs = NO_UNIQUE_VALIDATOR


class LabelSettingsSerializer(serializers.ModelSerializer):
    """Etiket ayarları. GS1 alanları burada salt okunurdur (gönderilirse yok sayılır); Sistem >
    Kodlama sistematiği > GS1'de değiştirilir (`Gs1SettingsSerializer`)."""

    sscc_enabled = serializers.SerializerMethodField()
    default_printer_code = serializers.CharField(
        source="default_printer.code", read_only=True, default=None
    )

    class Meta:
        model = LabelSettings
        fields = [
            "company_name",
            "gs1_company_prefix",
            "sscc_extension_digit",
            "next_sscc_serial",
            "default_printer",
            "default_printer_code",
            "sscc_enabled",
            "updated_at",
        ]
        read_only_fields = [
            "gs1_company_prefix",
            "sscc_extension_digit",
            "next_sscc_serial",
            "updated_at",
        ]

    def get_sscc_enabled(self, instance: LabelSettings) -> bool:
        return bool(instance.gs1_company_prefix)


class Gs1SettingsSerializer(serializers.Serializer):
    """GS1 ayarları (Sistem > Kodlama sistematiği > GS1; `services.Gs1Settings`)."""

    company_prefix = serializers.CharField(help_text="GS1 firma öneki (6-12 rakam); boşsa kapalı")
    extension_digit = serializers.IntegerField(help_text="SSCC uzantı hanesi (0-9)")
    next_sscc_serial = serializers.IntegerField(
        help_text="Sıradaki SSCC seri no (salt okunur; önek ya da uzantı değişince o önekle "
        "basılmış en büyük seri no + 1)"
    )
    next_item_reference = serializers.IntegerField(
        allow_null=True, help_text="GTIN önerisinde sıradaki ürün referansı; boşsa öneri kapalı"
    )
    sscc_enabled = serializers.BooleanField()
    gtin_suggestion_enabled = serializers.BooleanField()
    item_reference_digits = serializers.IntegerField(
        allow_null=True, help_text="Ürün referansının hane sayısı: 12 - önek uzunluğu"
    )
    updated_at = serializers.DateTimeField(
        allow_null=True, help_text="Son GS1 değişikliği (denetim günlüğünden)"
    )
    updated_by_name = serializers.CharField(allow_blank=True)


class Gs1SettingsUpdateSerializer(serializers.Serializer):
    """GS1 ayarı değişikliği: verilmeyen alan değişmez. Doğrulama serviste yapılır (hata kodları
    `note_required`, `invalid_gs1_prefix`, `invalid_extension_digit`, `invalid_item_reference`)."""

    company_prefix = serializers.CharField(required=False, allow_blank=True, max_length=32)
    extension_digit = serializers.IntegerField(required=False)
    next_item_reference = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class GtinSuggestionSerializer(serializers.Serializer):
    active = serializers.BooleanField(
        help_text="GS1 firma öneki ve sıradaki ürün referansı girildiyse açık (yalnızca mamul)"
    )
    gtin = serializers.CharField(allow_null=True, help_text="Sıradaki boş GTIN-13")
    reason = serializers.CharField()


class CaseGtinSuggestionSerializer(serializers.Serializer):
    gtin = serializers.CharField(
        allow_null=True,
        help_text=(
            "Ürün GTIN'inden gösterge hanesi 1-8 ile türetilen boş GTIN-14; mamul değilse ya da "
            "türetilemezse boş (nedeni reason'da)"
        ),
    )
    reason = serializers.CharField()


class CompanyProfileSerializer(serializers.ModelSerializer):
    """Firma bilgileri (tek kayıt). Doğrulama servis katmanında (Türkçe mesaj, hata kodu)."""

    class Meta:
        model = CompanyProfile
        fields = [
            "legal_name",
            "address",
            "tax_office",
            "tax_number",
            "trade_registry_no",
            "mersis_no",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]
        # "123 456 7890" gibi boşluklu yazım kabul edilir: boşluklar serviste atılır, uzunluk ve
        # kontrol hanesi orada denetlenir.
        extra_kwargs: dict[str, dict[str, Any]] = {
            "tax_number": {"max_length": 20},
            "mersis_no": {"max_length": 24},
        }
