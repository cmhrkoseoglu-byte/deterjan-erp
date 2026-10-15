from typing import Any, ClassVar

from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import MasterDataModel
from apps.core.permissions import HasRole
from apps.core.roles import ADMIN, PLANLAMA
from apps.masterdata import importers, services
from apps.masterdata.api import serializers as s
from apps.masterdata.models import (
    Customer,
    Equipment,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)

# Ana verileri yazabilen roller (admin her yere erişir). Okuma tüm giriş yapmış kullanıcılara açık.
MASTERDATA_WRITE_ROLES = (PLANLAMA,)
READ_ACTIONS = frozenset({"list", "retrieve", "metadata"})


class MasterDataViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Ana veri uç noktası: liste, detay, oluştur, güncelle, `activate` / `deactivate`.

    Silme yoktur (CLAUDE.md §4.6). Yazma işlemleri `masterdata.services` üzerinden yapılır.
    """

    write_roles: ClassVar[tuple[str, ...]] = MASTERDATA_WRITE_ROLES
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at", "updated_at"]

    def get_permissions(self) -> list[BasePermission]:
        if self.action in READ_ACTIONS:
            return [IsAuthenticated()]
        return [HasRole(*self.write_roles)()]

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
    write_roles = (ADMIN,)
    filterset_fields = ["is_active", "kind"]
    ordering = ["kind", "code"]


class MaterialCategoryViewSet(MasterDataViewSet):
    queryset = MaterialCategory.objects.all()
    serializer_class = s.MaterialCategorySerializer
    filterset_fields = ["is_active"]
    ordering = ["name"]


class MaterialViewSet(MasterDataViewSet):
    serializer_class = s.MaterialSerializer
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
        queryset = Material.objects.select_related("base_unit", "category")
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("conversions__unit")
        return queryset

    def get_serializer_class(self) -> type[s.MaterialSerializer]:
        if self.action == "retrieve":
            return s.MaterialDetailSerializer
        return s.MaterialSerializer


class MaterialUnitConversionViewSet(MasterDataViewSet):
    """Malzemeye özel birim dönüşümleri (`?material=<id>`)."""

    queryset = MaterialUnitConversion.objects.select_related("material__base_unit", "unit")
    serializer_class = s.MaterialUnitConversionSerializer
    filterset_fields = ["is_active", "material", "unit"]
    search_fields = ["material__code", "material__name", "unit__code"]
    ordering_fields = ["material__code", "unit__code"]
    ordering = ["material__code", "unit__code"]


class WarehouseViewSet(MasterDataViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = s.WarehouseSerializer
    filterset_fields = ["is_active"]
    ordering = ["code"]


class LocationViewSet(MasterDataViewSet):
    queryset = Location.objects.select_related("warehouse")
    serializer_class = s.LocationSerializer
    filterset_fields = {
        "is_active": ["exact"],
        "warehouse": ["exact"],
        "location_type": ["exact", "in"],
    }
    ordering = ["code"]


class EquipmentViewSet(MasterDataViewSet):
    queryset = Equipment.objects.select_related("capacity_unit", "location")
    serializer_class = s.EquipmentSerializer
    filterset_fields = {
        "is_active": ["exact"],
        "equipment_type": ["exact", "in"],
        "location": ["exact"],
    }
    ordering = ["code"]


class SupplierViewSet(MasterDataViewSet):
    queryset = Supplier.objects.all()
    serializer_class = s.SupplierSerializer
    filterset_fields = ["is_active"]
    search_fields = ["code", "name", "tax_number", "contact_person"]
    ordering = ["name"]


class CustomerViewSet(MasterDataViewSet):
    queryset = Customer.objects.all()
    serializer_class = s.CustomerSerializer
    filterset_fields = ["is_active"]
    search_fields = ["code", "name", "tax_number", "contact_person"]
    ordering = ["name"]


class ImportView(APIView):
    """Excel / CSV içe aktarma. `confirm=false` önizleme (hiçbir şey yazılmaz), `confirm=true`
    aktarır. Hatalı satır varsa hiçbir kayıt yazılmaz; 400 yanıtında `report` döner."""

    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [HasRole(*MASTERDATA_WRITE_ROLES)]

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

    permission_classes = [HasRole(*MASTERDATA_WRITE_ROLES)]

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request, kind: str) -> HttpResponse:
        spec = importers.get_spec(kind)
        response = HttpResponse(importers.build_template(kind), content_type=XLSX)
        response["Content-Disposition"] = f'attachment; filename="sablon-{spec.kind}.xlsx"'
        return response
