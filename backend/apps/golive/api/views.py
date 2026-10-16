"""Canlıya geçiş API'si (Faz 5, Adım 5.6).

- Hazırlık listesi ve canlı başlangıç tarihi: admin, yönetim, planlama ve depo görür; tarihi
  admin ve yönetim girer.
- Stok karşılaştırması: depo ve yönetim açar; planlama da görür.
- Sorun bildirimi: herkes açar; kişi kendi bildirimlerini, admin hepsini görür.
"""

from typing import Any

from django.db.models import Case, IntegerField, Q, QuerySet, When
from django.http import FileResponse, HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole
from apps.core.roles import DEPO, PLANLAMA, YONETIM
from apps.golive import exports, selectors, services
from apps.golive.api import serializers as s
from apps.golive.models import ProblemReport, StockComparison
from apps.inventory import services as inventory
from apps.masterdata.importers import ImportHasErrors

READ_ROLES = (YONETIM, PLANLAMA, DEPO)
GO_LIVE_ROLES = (YONETIM,)
COMPARISON_WRITE_ROLES = (DEPO, YONETIM)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class ReadinessView(APIView):
    """Canlıya geçiş hazırlık kontrol listesi."""

    permission_classes = [HasRole(*READ_ROLES)]

    @extend_schema(responses=s.CheckSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.CheckSerializer(selectors.readiness(), many=True).data)


class GoLiveView(APIView):
    """Canlı başlangıç tarihi: okuma hazırlık rollerine, değiştirme yönetim ve admin'e."""

    def get_permissions(self) -> list[BasePermission]:
        roles = READ_ROLES if self.request.method == "GET" else GO_LIVE_ROLES
        return [HasRole(*roles)()]

    def _body(self) -> dict[str, Any]:
        settings = inventory.get_inventory_settings()
        return {"go_live_date": settings.go_live_date, "opening_open": inventory.opening_is_open()}

    @extend_schema(responses=s.GoLiveSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.GoLiveSerializer(self._body()).data)

    @extend_schema(request=s.GoLiveSerializer, responses=s.GoLiveSerializer)
    def put(self, request: Request) -> Response:
        body = s.GoLiveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.set_go_live_date(
            request.user,  # type: ignore[arg-type]
            body.validated_data["go_live_date"],
        )
        return Response(s.GoLiveSerializer(self._body()).data)


class StockComparisonViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Paralel çalışma stok karşılaştırmaları (`SK-`). Kayıtlar değişmez ve silinmez."""

    queryset = StockComparison.objects.select_related("created_by")
    serializer_class = s.StockComparisonSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ["level", "as_of_date"]
    ordering = ["-created_at", "-id"]

    def get_permissions(self) -> list[BasePermission]:
        if self.action == "create":
            return [HasRole(*COMPARISON_WRITE_ROLES)()]
        return [HasRole(*READ_ROLES)()]

    @extend_schema(
        request={"multipart/form-data": s.StockComparisonCreateSerializer},
        responses={
            201: s.StockComparisonSerializer,
            400: OpenApiResponse(description="import_has_errors (gövdede `report`)"),
        },
    )
    def create(self, request: Request) -> Response:
        """Excel stok listesini yükler ve karşılaştırmayı kaydeder."""
        body = s.StockComparisonCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            comparison = services.create_stock_comparison(
                request.user,  # type: ignore[arg-type]
                upload=data["file"],
                filename=data["file"].name,
                as_of_date=data.get("as_of_date"),
                only_file_materials=data["only_file_materials"],
                note=data["note"],
            )
        except ImportHasErrors as exc:
            report = {**exc.report.as_dict(), "imported": False}
            return Response(
                {"code": exc.code, "detail": exc.message, "report": report},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(comparison).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[
            OpenApiParameter("only_differences", bool, description="Yalnızca farklı satırlar")
        ],
        responses=s.StockComparisonLineSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def lines(self, request: Request, pk: str | None = None) -> Response:
        """Satırlar (sayfalı): önce farklılar, sonra malzeme koduna göre."""
        comparison = self.get_object()
        queryset = comparison.lines.select_related("material__base_unit", "location")
        if request.query_params.get("only_differences") in ("1", "true"):
            queryset = queryset.exclude(difference=0)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(material__code__icontains=search) | Q(material__name__icontains=search)
            )
        queryset = queryset.annotate(
            matched=Case(When(difference=0, then=1), default=0, output_field=IntegerField())
        ).order_by("matched", "material__code", "lot_no", "location__code")
        page = self.paginate_queryset(queryset)
        serializer = s.StockComparisonLineSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def export(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Karşılaştırma sonucu (.xlsx)."""
        comparison = self.get_object()
        return _xlsx(exports.comparison_xlsx(comparison), f"{comparison.number}.xlsx")

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    @action(detail=False, methods=["get"])
    def template(self, request: Request) -> HttpResponse:
        """Stok listesi şablonu (.xlsx)."""
        return _xlsx(exports.comparison_template(), "sablon-stok-karsilastirma.xlsx")


class ProblemReportViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """ "Sorun bildir": herkes açar; kişi kendi bildirimlerini, admin hepsini görür."""

    serializer_class = s.ProblemReportSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    ordering = ["-created_at", "-id"]

    def get_queryset(self) -> QuerySet[ProblemReport]:
        queryset = ProblemReport.objects.select_related("created_by")
        if getattr(self, "swagger_fake_view", False):  # OpenAPI şeması üretimi
            return queryset.none()
        user = self.request.user
        if not getattr(user, "is_admin", False):
            queryset = queryset.filter(created_by=user)  # type: ignore[misc]
        return queryset

    @extend_schema(
        request={"multipart/form-data": s.ProblemReportCreateSerializer},
        responses={201: s.ProblemReportSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = s.ProblemReportCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        report = services.report_problem(
            request.user,  # type: ignore[arg-type]
            **body.validated_data,
        )
        return Response(self.get_serializer(report).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def screenshot(self, request: Request, pk: str | None = None) -> FileResponse:
        """Ekran görüntüsü (yalnızca bildiren ve admin)."""
        report = self.get_object()
        if not report.screenshot:
            raise NotFound("Ekran görüntüsü yok.")
        return FileResponse(report.screenshot.open("rb"), filename=report.screenshot.name)
