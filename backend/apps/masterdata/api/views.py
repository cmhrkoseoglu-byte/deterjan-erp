from collections.abc import Mapping
from typing import Any, ClassVar

from django.db.models import Prefetch, QuerySet
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import CHANGE
from apps.core.api.coding import FormerCodeSearchFilter
from apps.core.api.labels import (
    LABEL_PARAMETERS,
    PDF,
    LabelOutputSerializer,
    PrintRequestSerializer,
    PrintResultSerializer,
    label_response,
)
from apps.core.exceptions import BusinessRuleError
from apps.core.labels import render_zpl
from apps.core.models import MasterDataModel
from apps.core.permissions import (
    AccessMixin,
    AdminOnly,
    HasAccess,
    PermissionClass,
    ReadRule,
    sees_fields,
)
from apps.masterdata import importers, labels, services
from apps.masterdata.access import CARDS, COMPANY, REFERENCE
from apps.masterdata.api import serializers as s
from apps.masterdata.models import (
    Customer,
    Equipment,
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

# Bölüm denetimi (docs/plan/kisi-yetkileri.md §3.1). Kartlar, birimler ve yazıcılar seçimler ve
# etiket basımı için herkese açık okunur; lokasyon etiketi ve yazıcı deneme baskısı herkese açıktır.
CARD_CHANGE = HasAccess(CARDS, CHANGE)
REFERENCE_CHANGE = HasAccess(REFERENCE, CHANGE)


def writes(rule: PermissionClass) -> dict[str, PermissionClass]:
    """Ana veri uç noktasının yazma eylemleri (oluştur, güncelle, aktif yap, pasife al)."""
    return {name: rule for name in ("create", "update", "partial_update", "activate", "deactivate")}


class MasterDataViewSet(
    AccessMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Ana veri uç noktası: liste, detay, oluştur, güncelle, `activate` / `deactivate`.

    Silme yoktur (CLAUDE.md §4.6). Yazma işlemleri `masterdata.services` üzerinden yapılır.
    """

    read_access = ReadRule(CARDS)
    action_access: ClassVar[Mapping[str, PermissionClass]] = writes(CARD_CHANGE)
    unhandled_access: ClassVar[PermissionClass | None] = CARD_CHANGE
    # Arama eski kodlarda da yapılır (kodu değişmiş kayıt eski koduyla bulunur).
    filter_backends = [DjangoFilterBackend, FormerCodeSearchFilter, OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at", "updated_at"]

    @property
    def model(self) -> type[MasterDataModel]:
        return self.get_serializer_class().Meta.model  # type: ignore[attr-defined,no-any-return]

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.create_record(
            self.request.user,  # type: ignore[arg-type]
            self.model,
            serializer.validated_data,
        )

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_record(
            self.request.user,  # type: ignore[arg-type]
            serializer.instance,
            serializer.validated_data,
        )

    def _set_active(self, active: bool) -> Response:
        instance = services.set_active(
            self.request.user,  # type: ignore[arg-type]
            self.get_object(),
            active,
        )
        return Response(self.get_serializer(instance).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """Kaydı aktif yapar."""
        return self._set_active(True)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """Kaydı pasife alır (ana veriler silinmez)."""
        return self._set_active(False)


class UnitOfMeasureViewSet(MasterDataViewSet):
    """Birimler. Birim tanımı fabrika genelini etkilediğinden yalnızca admin yazar."""

    queryset = UnitOfMeasure.objects.all()
    serializer_class = s.UnitOfMeasureSerializer
    read_access = ReadRule(REFERENCE)
    action_access = writes(REFERENCE_CHANGE)
    unhandled_access = REFERENCE_CHANGE
    filterset_fields = ["is_active", "kind"]
    ordering = ["kind", "code"]


class MaterialCategoryViewSet(MasterDataViewSet):
    queryset = MaterialCategory.objects.all()
    serializer_class = s.MaterialCategorySerializer
    filterset_fields = ["is_active"]
    ordering = ["name"]


def retired_gtins(prefix: str = "") -> Prefetch:
    """Dönüşümlerin eski koli GTIN'leri ve değiştiren kullanıcıları tek sorguda (`retired_gtins`
    alanı satır başına sorgu yapmaz)."""
    return Prefetch(
        f"{prefix}retired_gtins", queryset=RetiredGtin.objects.select_related("created_by")
    )


class MaterialViewSet(MasterDataViewSet):
    serializer_class = s.MaterialSerializer
    action_access = {**writes(CARD_CHANGE), "case_gtin_suggestion": CARD_CHANGE}
    filterset_fields = {
        "is_active": ["exact"],
        "material_type": ["exact", "in"],
        "category": ["exact"],
        "base_unit": ["exact"],
        "is_hazardous": ["exact"],
        "requires_incoming_qc": ["exact"],
    }
    ordering = ["code"]

    def get_queryset(self) -> QuerySet[Material]:
        # GTIN kilidi (`gtin_locked`) için lot var mı bilgisi tek sorguda.
        queryset = Material.objects.select_related("base_unit", "category").annotate(
            has_lots=services.lot_exists("pk")
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                "conversions__unit", retired_gtins("conversions__")
            )
        return queryset

    def get_serializer_class(self) -> type[s.MaterialSerializer]:
        if self.action == "retrieve":
            return s.MaterialDetailSerializer
        return s.MaterialSerializer

    @extend_schema(request=None, responses=s.CaseGtinSuggestionSerializer)
    @action(detail=True, methods=["get"], url_path="case-gtin-suggestion")
    def case_gtin_suggestion(self, request: Request, pk: str | None = None) -> Response:
        """Koli GTIN'i önerisi (yalnız mamulde): ürün GTIN'inden gösterge hanesi 1-8 ile türetilen
        ilk boş GTIN-14. Öteki türlerde ve türetilemezse `gtin` boştur, `reason` nedenini yazar
        (malzeme yazma rolleri)."""
        suggestion = services.case_gtin_suggestion(self.get_object())
        return Response(s.CaseGtinSuggestionSerializer(suggestion).data)


class MaterialUnitConversionViewSet(MasterDataViewSet):
    """Malzemeye özel birim dönüşümleri (`?material=<id>`). Koli (KOLI) dönüşümünde koli GTIN'i
    ve eski koli GTIN'leri (`retired_gtins`) tutulur. Lotu olan mamulün kilitli koli GTIN'inde
    koli içi miktar yalnız yeni koli GTIN'iyle değişir (`case_gtin_required`)."""

    queryset = MaterialUnitConversion.objects.select_related("material__base_unit", "unit")
    serializer_class = s.MaterialUnitConversionSerializer
    filterset_fields = ["is_active", "material", "unit"]
    search_fields = ["material__code", "material__name", "unit__code"]
    ordering_fields = ["material__code", "unit__code"]
    ordering = ["material__code", "unit__code"]

    def get_queryset(self) -> QuerySet[MaterialUnitConversion]:
        # Koli GTIN'i kilidi (`gtin_locked`) için malzemenin lotu var mı bilgisi ve eski koli
        # GTIN'leri tek sorguda.
        return (
            super()
            .get_queryset()
            .annotate(material_has_lots=services.lot_exists("material"))
            .prefetch_related(retired_gtins())
        )


class WarehouseViewSet(MasterDataViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = s.WarehouseSerializer
    filterset_fields = ["is_active"]
    ordering = ["code"]


class LocationViewSet(MasterDataViewSet):
    queryset = Location.objects.select_related("warehouse")
    serializer_class = s.LocationSerializer
    action_access = {**writes(CARD_CHANGE), "print_label": ReadRule(CARDS)}
    filterset_fields = {
        "is_active": ["exact"],
        "warehouse": ["exact"],
        "location_type": ["exact", "in"],
    }
    ordering = ["code"]

    def _labels(self, copies: int) -> list[labels.Label]:
        company = services.get_label_settings().company_name
        return [labels.location_label(self.get_object(), company)] * copies

    @extend_schema(parameters=LABEL_PARAMETERS, responses={(200, PDF): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def label(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Lokasyon etiketi (Code128 + QR, içerik `LOC:<kod>`): PDF, A4 PDF ya da ZPL."""
        params = LabelOutputSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        location = self.get_object()
        return label_response(
            self._labels(params.validated_data["copies"]),
            params.validated_data["output"],
            f"lokasyon-{location.code}",
        )

    @extend_schema(request=PrintRequestSerializer, responses=PrintResultSerializer)
    @action(detail=True, methods=["post"], url_path="print-label")
    def print_label(self, request: Request, pk: str | None = None) -> Response:
        """Lokasyon etiketini ağ yazıcısına gönderir."""
        body = PrintRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        printer = get_printer(body.validated_data["printer"])
        copies = body.validated_data["copies"]
        location = self.get_object()
        services.send_to_printer(
            request.user,  # type: ignore[arg-type]
            printer,
            render_zpl(self._labels(copies), dpi=printer.dpi),
            target=location,
            description=f"lokasyon etiketi × {copies}",
        )
        return Response({"printed": copies, "printer": printer.code})


class EquipmentViewSet(MasterDataViewSet):
    queryset = Equipment.objects.select_related("capacity_unit", "location")
    serializer_class = s.EquipmentSerializer
    filterset_fields = {
        "is_active": ["exact"],
        "equipment_type": ["exact", "in"],
        "location": ["exact"],
    }
    ordering = ["code"]


def get_printer(printer_id: int) -> Printer:
    """Yazdırma isteğindeki yazıcıyı bulur (aktif olmalı)."""
    printer = Printer.objects.filter(pk=printer_id).first()
    if printer is None:
        raise BusinessRuleError("printer_not_found", "Yazıcı bulunamadı.")
    if not printer.is_active:
        raise BusinessRuleError("inactive", f"{printer.code} yazıcısı pasif.")
    return printer


class PrinterViewSet(MasterDataViewSet):
    """Etiket yazıcıları. Tanımı admin yazar; deneme etiketi herkes basabilir."""

    queryset = Printer.objects.select_related("location")
    serializer_class = s.PrinterSerializer
    read_access = ReadRule(REFERENCE)
    action_access = {**writes(REFERENCE_CHANGE), "test": ReadRule(REFERENCE)}
    unhandled_access = REFERENCE_CHANGE
    filterset_fields = ["is_active", "printer_type", "location"]
    search_fields = ["code", "name", "host"]
    ordering = ["code"]

    @extend_schema(request=None, responses=PrintResultSerializer)
    @action(detail=True, methods=["post"])
    def test(self, request: Request, pk: str | None = None) -> Response:
        """Yazıcıya deneme etiketi gönderir."""
        printer = self.get_object()
        services.send_to_printer(
            request.user,  # type: ignore[arg-type]
            printer,
            render_zpl([labels.printer_test_label(printer)], dpi=printer.dpi),
            description="deneme etiketi",
        )
        return Response({"printed": 1, "printer": printer.code})


class LabelSettingsView(AccessMixin, APIView):
    """Etiket ayarları (tek kayıt): okuma herkese, değiştirme yalnız admin. HEAD ve OPTIONS bugünkü
    gibi değiştirme yetkisiyle denetlenir."""

    read_access = ReadRule(REFERENCE)
    read_methods = frozenset({"GET"})
    other_safe_access = REFERENCE_CHANGE
    unhandled_access = REFERENCE_CHANGE
    action_access = {"put": REFERENCE_CHANGE}

    @extend_schema(responses=s.LabelSettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.LabelSettingsSerializer(services.get_label_settings()).data)

    @extend_schema(request=s.LabelSettingsSerializer, responses=s.LabelSettingsSerializer)
    def put(self, request: Request) -> Response:
        current = services.get_label_settings()
        body = s.LabelSettingsSerializer(current, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        instance = services.update_label_settings(
            request.user,  # type: ignore[arg-type]
            body.validated_data,
        )
        return Response(s.LabelSettingsSerializer(instance).data)


class Gs1SettingsView(APIView):
    """GS1 ayarları (Sistem > Kodlama sistematiği > GS1): firma öneki, SSCC uzantı hanesi,
    sıradaki ürün referansı. Okuma ve değiştirme yalnızca admin; değişiklik notu zorunlu."""

    permission_classes = [AdminOnly]

    @extend_schema(responses=s.Gs1SettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.Gs1SettingsSerializer(services.get_gs1_settings()).data)

    @extend_schema(request=s.Gs1SettingsUpdateSerializer, responses=s.Gs1SettingsSerializer)
    def patch(self, request: Request) -> Response:
        body = s.Gs1SettingsUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data: dict[str, Any] = dict(body.validated_data)
        services.update_gs1_settings(
            request.user,  # type: ignore[arg-type]
            **data,
        )
        return Response(s.Gs1SettingsSerializer(services.get_gs1_settings()).data)


class GtinSuggestionView(APIView):
    """Mamul için sıradaki boş GTIN-13 önerisi (Ana veri kartları: Değiştirir). Firma öneki ve
    sıradaki ürün referansı girilmemişse `active=false`; `?material_type=` verilir ve mamul değilse
    de kapalıdır."""

    permission_classes = [CARD_CHANGE]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "material_type",
                str,
                required=False,
                description="Malzeme türü; FINISHED (mamul) dışında öneri kapalı",
            )
        ],
        responses=s.GtinSuggestionSerializer,
    )
    def get(self, request: Request) -> Response:
        material_type = request.query_params.get("material_type") or None
        suggestion = services.gtin_suggestion(material_type)
        return Response(s.GtinSuggestionSerializer(suggestion).data)


class CompanyProfileView(AccessMixin, APIView):
    """Firma ticari bilgileri (tek kayıt): okuma giriş yapmış herkese (bilgiler belgelerde zaten
    görünür), değiştirme Firma bilgileri: Değiştirir. HEAD ve OPTIONS bugünkü gibi değiştirme
    yetkisiyle denetlenir."""

    read_access = ReadRule(COMPANY)
    read_methods = frozenset({"GET"})
    other_safe_access = HasAccess(COMPANY, CHANGE)
    unhandled_access = HasAccess(COMPANY, CHANGE)
    action_access = {"put": HasAccess(COMPANY, CHANGE)}

    @extend_schema(responses=s.CompanyProfileSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.CompanyProfileSerializer(services.get_company_profile()).data)

    @extend_schema(request=s.CompanyProfileSerializer, responses=s.CompanyProfileSerializer)
    def put(self, request: Request) -> Response:
        body = s.CompanyProfileSerializer(
            services.get_company_profile(), data=request.data, partial=True
        )
        body.is_valid(raise_exception=True)
        instance = services.update_company_profile(
            request.user,  # type: ignore[arg-type]
            body.validated_data,
        )
        return Response(s.CompanyProfileSerializer(instance).data)


class PartnerSearchFilter(FormerCodeSearchFilter):
    """Tedarikçi ve müşteri araması: iletişim alanlarını tam göremeyen kişi yalnız kodda, eski
    kodda ve adda arar; vergi numarasında ve yetkili kişide aramaz (sade kart, plan §5.6)."""

    def get_search_fields(self, view: Any, request: Request) -> Any:
        fields = super().get_search_fields(view, request)
        if sees_fields(request.user, view.contact_group):
            return fields
        return [name for name in fields or () if name in ("code", "name")]


class SupplierViewSet(MasterDataViewSet):
    queryset = Supplier.objects.all()
    serializer_class = s.SupplierSerializer
    contact_group = s.SUPPLIER_CONTACT
    filter_backends = [DjangoFilterBackend, PartnerSearchFilter, OrderingFilter]
    filterset_fields = ["is_active"]
    search_fields = ["code", "name", "tax_number", "contact_person"]
    ordering = ["name"]


class CustomerViewSet(MasterDataViewSet):
    queryset = Customer.objects.all()
    serializer_class = s.CustomerSerializer
    contact_group = s.CUSTOMER_CONTACT
    filter_backends = [DjangoFilterBackend, PartnerSearchFilter, OrderingFilter]
    filterset_fields = ["is_active"]
    search_fields = ["code", "name", "tax_number", "contact_person"]
    ordering = ["name"]


class ImportView(APIView):
    """Excel / CSV içe aktarma. `confirm=false` önizleme (hiçbir şey yazılmaz), `confirm=true`
    aktarır. Hatalı satır varsa hiçbir kayıt yazılmaz; 400 yanıtında `report` döner."""

    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [CARD_CHANGE]

    @extend_schema(
        request={"multipart/form-data": s.ImportUploadSerializer},
        responses={
            200: s.ImportReportSerializer,
            400: OpenApiResponse(description="import_has_errors (gövdede `report`)"),
        },
    )
    def post(self, request: Request, kind: str) -> Response:
        importers.get_spec(kind)
        upload = s.ImportUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        file = upload.validated_data["file"]
        if upload.validated_data["confirm"]:
            try:
                report = importers.run_import(
                    request.user,  # type: ignore[arg-type]
                    kind,
                    file,
                    file.name,
                )
            except importers.ImportHasErrors as exc:
                report_body = {**exc.report.as_dict(), "imported": False}
                body = {"code": exc.code, "detail": exc.message, "report": report_body}
                return Response(body, status=status.HTTP_400_BAD_REQUEST)
            return Response({**report.as_dict(), "imported": True})
        report = importers.preview_import(kind, file, file.name)
        return Response({**report.as_dict(), "imported": False})


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ImportTemplateView(APIView):
    """İçe aktarma şablonu (.xlsx)."""

    permission_classes = [CARD_CHANGE]

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request, kind: str) -> HttpResponse:
        spec = importers.get_spec(kind)
        response = HttpResponse(importers.build_template(kind), content_type=XLSX)
        response["Content-Disposition"] = f'attachment; filename="sablon-{spec.kind}.xlsx"'
        return response
