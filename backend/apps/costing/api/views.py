"""Maliyet API'si: yalnızca yonetim ve admin (Karar D-15: tutarları diğer roller görmez)."""

from collections.abc import Callable
from typing import Any

import django_filters
from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from apps.core.permissions import HasRole
from apps.core.roles import YONETIM
from apps.costing import exports, selectors, services
from apps.costing.api import serializers as s
from apps.costing.models import CostRate, LotCost, StandardCost
from apps.inventory.models import Lot

COST_ROLES = (YONETIM,)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(request: Request) -> Any:
    return request.user


class CostPermissionMixin:
    def get_permissions(self) -> list[BasePermission]:
        return [HasRole(*COST_ROLES)()]


class LotCostFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="cost_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="cost_date", lookup_expr="lte")
    material_type = django_filters.CharFilter(field_name="material__material_type")
    lot_no = django_filters.CharFilter(field_name="lot__lot_no", lookup_expr="icontains")

    class Meta:
        model = LotCost
        fields = ["material", "method", "is_estimated", "has_missing", "lot"]


class LotCostViewSet(CostPermissionMixin, viewsets.ReadOnlyModelViewSet):
    """Lotların güncel maliyetleri; detayda kalem kalem döküm. `lots/{lot_id}/` tüm sürümleri
    verir, `lots/{lot_id}/recalculate/` yeniden hesaplar."""

    filterset_class = LotCostFilter
    search_fields = ["lot__lot_no", "material__code", "material__name"]
    ordering_fields = ["cost_date", "unit_cost", "total_cost", "id"]
    ordering = ["-cost_date", "-id"]

    def get_queryset(self) -> QuerySet[LotCost]:
        queryset = LotCost.objects.filter(is_current=True).select_related(
            "lot", "material__base_unit", "calculated_by"
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("lines__material__base_unit", "lines__source_lot")
        return queryset

    def get_serializer_class(self) -> type[Serializer]:
        if self.action == "retrieve":
            return s.LotCostDetailSerializer
        return s.LotCostSerializer


def _history(lot: Lot) -> dict[str, Any]:
    versions = (
        LotCost.objects.filter(lot=lot)
        .select_related("lot", "material__base_unit", "calculated_by")
        .prefetch_related("lines__material__base_unit", "lines__source_lot")
        .order_by("-version")
    )
    return {
        "lot": lot.pk,
        "lot_no": lot.lot_no,
        "material_code": lot.material.code,
        "material_name": lot.material.name,
        "is_costable": services.is_costable(lot),
        "versions": versions,
    }


class LotCostHistoryView(CostPermissionMixin, APIView):
    def _lot(self, pk: int) -> Lot:
        return get_object_or_404(Lot.objects.select_related("material"), pk=pk)

    @extend_schema(responses=s.LotCostHistorySerializer)
    def get(self, request: Request, pk: int) -> Response:
        """Lotun tüm maliyet sürümleri (en yenisi başta), kalemleriyle."""
        return Response(s.LotCostHistorySerializer(_history(self._lot(pk))).data)


class LotRecalculateView(LotCostHistoryView):
    @extend_schema(request=s.RecalculateSerializer, responses=s.LotCostHistorySerializer)
    def post(self, request: Request, pk: int) -> Response:
        """Lotun maliyetini yeniden hesaplar (yeni sürüm, not zorunlu). `cascade`: soy ağacında
        ileri giden lotlar da yeniden hesaplanır."""
        lot = self._lot(pk)
        body = s.RecalculateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.recalculate_lot_cost(
            _user(request),
            lot,
            body.validated_data["note"],
            cascade=body.validated_data["cascade"],
        )
        return Response(s.LotCostHistorySerializer(_history(lot)).data)


class _MasterViewSet(
    CostPermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Silme yok (CLAUDE.md §4.6); yazma servis üzerinden."""

    create_service: Callable[..., Any]
    update_service: Callable[..., Any]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = type(self).create_service(_user(request), serializer.validated_data)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        instance = type(self).update_service(_user(request), instance, serializer.validated_data)
        return Response(self.get_serializer(instance).data)


class CostRateViewSet(_MasterViewSet):
    """Genel gider oranları (Karar D-15): aşama × tür için TL/kg, geçerlilik tarihiyle."""

    serializer_class = s.CostRateSerializer
    queryset = CostRate.objects.select_related("created_by")
    filterset_fields = ["stage", "kind"]
    ordering = ["stage", "kind", "-valid_from"]
    create_service = staticmethod(services.create_rate)
    update_service = staticmethod(services.update_rate)


class StandardCostViewSet(_MasterViewSet):
    """Malzemelerin standart birim maliyetleri (fiyatsız lot için tahmin kaynağı)."""

    serializer_class = s.StandardCostSerializer
    queryset = StandardCost.objects.select_related("material__base_unit")
    filterset_fields = ["is_active", "material", "material__material_type"]
    search_fields = ["material__code", "material__name"]
    ordering = ["material__code"]
    create_service = staticmethod(services.create_standard_cost)
    update_service = staticmethod(services.update_standard_cost)


# --- raporlar --------------------------------------------------------------------------------


def _xlsx(content: bytes, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type=XLSX)
    filename = f"{name}-{timezone.localtime():%Y%m%d-%H%M}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class ReportView(CostPermissionMixin, APIView):
    query_serializer: type[Serializer] = s.ReportQuerySerializer

    def query(self, request: Request) -> dict[str, Any]:
        params = self.query_serializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        return dict(params.validated_data)


def _dated(query: dict[str, Any], key: str = "material") -> dict[str, Any]:
    return {
        key: query.get("material"),
        "date_from": query.get("date_from"),
        "date_to": query.get("date_to"),
    }


class CostTrendView(ReportView):
    @extend_schema(
        parameters=[s.ReportQuerySerializer], responses=s.CostTrendRowSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Ürün bazında aylık birim maliyet trendi (bulk ve mamul)."""
        rows = selectors.cost_trend(**_dated(self.query(request)))
        return Response(s.CostTrendRowSerializer(rows, many=True).data)


class CostTrendExcelView(ReportView):
    @extend_schema(
        parameters=[s.ReportQuerySerializer], responses={(200, XLSX): OpenApiTypes.BINARY}
    )
    def get(self, request: Request) -> HttpResponse:
        rows = selectors.cost_trend(**_dated(self.query(request)))
        return _xlsx(
            exports.to_xlsx([("Maliyet trendi", exports.COST_TREND, rows)]), "maliyet-trendi"
        )


class BatchVarianceView(ReportView):
    @extend_schema(
        parameters=[s.ReportQuerySerializer], responses=s.BatchVarianceRowSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Şarj bazında reçete (teorik) ve fiili maliyet."""
        rows = selectors.batch_variance(**_dated(self.query(request), "product"))
        return Response(s.BatchVarianceRowSerializer(rows, many=True).data)


class BatchVarianceExcelView(ReportView):
    @extend_schema(
        parameters=[s.ReportQuerySerializer], responses={(200, XLSX): OpenApiTypes.BINARY}
    )
    def get(self, request: Request) -> HttpResponse:
        rows = selectors.batch_variance(**_dated(self.query(request), "product"))
        return _xlsx(
            exports.to_xlsx([("Teorik ve fiili", exports.BATCH_VARIANCE, rows)]), "sarj-maliyeti"
        )


class ScrapCostView(ReportView):
    @extend_schema(
        parameters=[s.ReportQuerySerializer], responses=s.ScrapCostRowSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Dolum lotu bazında fire maliyeti."""
        rows = selectors.scrap_cost(**_dated(self.query(request), "product"))
        return Response(s.ScrapCostRowSerializer(rows, many=True).data)


class ScrapCostExcelView(ReportView):
    @extend_schema(
        parameters=[s.ReportQuerySerializer], responses={(200, XLSX): OpenApiTypes.BINARY}
    )
    def get(self, request: Request) -> HttpResponse:
        rows = selectors.scrap_cost(**_dated(self.query(request), "product"))
        return _xlsx(
            exports.to_xlsx([("Fire maliyeti", exports.SCRAP_COST, rows)]), "fire-maliyeti"
        )


def _top(query: dict[str, Any]) -> list[dict[str, Any]]:
    return selectors.top_materials(
        date_from=query.get("date_from"),
        date_to=query.get("date_to"),
        material_type=query.get("material_type"),
        limit=query["limit"],
    )


class TopMaterialsView(ReportView):
    query_serializer = s.TopMaterialsQuerySerializer

    @extend_schema(
        parameters=[s.TopMaterialsQuerySerializer], responses=s.TopMaterialRowSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Üretim ve dolumda en çok maliyet getiren hammadde ve ambalaj kalemleri."""
        return Response(s.TopMaterialRowSerializer(_top(self.query(request)), many=True).data)


class TopMaterialsExcelView(TopMaterialsView):
    @extend_schema(
        parameters=[s.TopMaterialsQuerySerializer], responses={(200, XLSX): OpenApiTypes.BINARY}
    )
    def get(self, request: Request) -> HttpResponse:  # type: ignore[override]
        rows = _top(self.query(request))
        return _xlsx(
            exports.to_xlsx([("En pahalı kalemler", exports.TOP_MATERIALS, rows)]), "en-pahali"
        )


def _stock_filters(query: dict[str, Any]) -> dict[str, Any]:
    return {
        "material_type": query.get("material_type"),
        "warehouse_id": query.get("warehouse"),
        "location_id": query.get("location"),
        "material": query.get("material"),
    }


class StockValueView(ReportView):
    query_serializer = s.StockValueQuerySerializer

    @extend_schema(parameters=[s.StockValueQuerySerializer], responses=s.StockValueSerializer)
    def get(self, request: Request) -> Response:
        """Stok değeri (bakiye × lot birim maliyeti), malzeme bazında."""
        result = selectors.stock_value(**_stock_filters(self.query(request)))
        return Response(s.StockValueSerializer(result).data)


class StockValueExcelView(StockValueView):
    @extend_schema(
        parameters=[s.StockValueQuerySerializer], responses={(200, XLSX): OpenApiTypes.BINARY}
    )
    def get(self, request: Request) -> HttpResponse:  # type: ignore[override]
        filters = _stock_filters(self.query(request))
        summary = selectors.stock_value(**filters)
        lots = selectors.stock_value_lots(**filters)
        content = exports.to_xlsx(
            [
                ("Malzeme bazında", exports.STOCK_VALUE, summary["rows"]),
                ("Lot bazında", exports.STOCK_VALUE_LOTS, lots),
            ]
        )
        return _xlsx(content, "stok-degeri")
