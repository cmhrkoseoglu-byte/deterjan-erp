"""Maliyet API'si (Karar D-15): bölümler Lot maliyetleri ve maliyet raporları, Gider oranları ve
standart maliyetler, Personel maliyeti (docs/plan/kisi-yetkileri.md §3.11). Her bölüm Maliyetleri
görür'ü ister. Bugünkü gibi her metot (HEAD, OPTIONS ve karşılanmayan metotlar dahil) bölümün
yetkisiyle denetlenir."""

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
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from apps.core.access import CHANGE, VIEW
from apps.core.permissions import AccessMixin, HasAccess
from apps.costing import exports, selectors, services
from apps.costing.access import LOT_COSTS, PERSONNEL_COST, RATES
from apps.costing.api import serializers as s
from apps.costing.models import CostRate, LotCost, StandardCost
from apps.inventory.models import Lot
from apps.personnel import services as personnel_services

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(request: Request) -> Any:
    return request.user


class LotCostFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="cost_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="cost_date", lookup_expr="lte")
    material_type = django_filters.CharFilter(field_name="material__material_type")
    lot_no = django_filters.CharFilter(field_name="lot__lot_no", lookup_expr="icontains")

    class Meta:
        model = LotCost
        fields = ["material", "method", "is_estimated", "has_missing", "lot"]


class LotCostViewSet(AccessMixin, viewsets.ReadOnlyModelViewSet):
    """Lotların güncel maliyetleri; detayda kalem kalem döküm. `lots/{lot_id}/` tüm sürümleri
    verir, `lots/{lot_id}/recalculate/` yeniden hesaplar."""

    read_access = HasAccess(LOT_COSTS, VIEW)
    unhandled_access = HasAccess(LOT_COSTS, VIEW)

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


class LotCostHistoryView(AccessMixin, APIView):
    read_access = HasAccess(LOT_COSTS, VIEW)
    unhandled_access = HasAccess(LOT_COSTS, VIEW)

    def _lot(self, pk: int) -> Lot:
        return get_object_or_404(Lot.objects.select_related("material"), pk=pk)

    @extend_schema(responses=s.LotCostHistorySerializer)
    def get(self, request: Request, pk: int) -> Response:
        """Lotun tüm maliyet sürümleri (en yenisi başta), kalemleriyle."""
        return Response(s.LotCostHistorySerializer(_history(self._lot(pk))).data)


class LotRecalculateView(LotCostHistoryView):
    # GET (geçmiş) okumadır; yeniden hesap Değiştirir ister. Servisin kendi denetimi yoktur.
    unhandled_access = HasAccess(LOT_COSTS, CHANGE)
    action_access = {"post": HasAccess(LOT_COSTS, CHANGE)}

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
    AccessMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Silme yok (CLAUDE.md §4.6); yazma servis üzerinden. Gider oranları ve standart maliyetler:
    okuma Görür, yazma Değiştirir (servislerin kendi denetimi yoktur)."""

    read_access = HasAccess(RATES, VIEW)
    unhandled_access = HasAccess(RATES, CHANGE)
    action_access = {
        "create": HasAccess(RATES, CHANGE),
        "update": HasAccess(RATES, CHANGE),
        "partial_update": HasAccess(RATES, CHANGE),
    }

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


class ReportView(AccessMixin, APIView):
    """Maliyet raporları ve Excel'leri: Lot maliyetleri ve maliyet raporları: Görür."""

    read_access = HasAccess(LOT_COSTS, VIEW)
    unhandled_access = HasAccess(LOT_COSTS, VIEW)
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
            exports.to_xlsx(
                [("Maliyet trendi", exports.COST_TREND, rows)], output="costing.cost-trend"
            ),
            "maliyet-trendi",
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
            exports.to_xlsx(
                [("Teorik ve fiili", exports.BATCH_VARIANCE, rows)],
                output="costing.batch-variance",
            ),
            "sarj-maliyeti",
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
            exports.to_xlsx(
                [("Fire maliyeti", exports.SCRAP_COST, rows)], output="costing.scrap-cost"
            ),
            "fire-maliyeti",
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
            exports.to_xlsx(
                [("En pahalı kalemler", exports.TOP_MATERIALS, rows)],
                output="costing.top-materials",
            ),
            "en-pahali",
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
            ],
            output="costing.stock-value",
        )
        return _xlsx(content, "stok-degeri")


# --- personel maliyeti ---------------------------------------------------------------------


def _check_month(year: int, month: int) -> None:
    if not (1 <= month <= 12 and 2000 <= year <= 2100):
        raise NotFound("Geçersiz ay.")


class PersonnelCostView(AccessMixin, APIView):
    """Ayın personel maliyeti: kişiler, aşama toplamları ve işçilik oranı önerisi."""

    read_access = HasAccess(PERSONNEL_COST, VIEW)
    unhandled_access = HasAccess(PERSONNEL_COST, VIEW)

    @extend_schema(responses=s.PersonnelCostReportSerializer)
    def get(self, request: Request, year: int, month: int) -> Response:
        _check_month(year, month)
        report = selectors.personnel_cost_report(year, month)
        return Response(s.PersonnelCostReportSerializer(report).data)


class PersonnelCostExcelView(AccessMixin, APIView):
    """Personel maliyeti Excel'i. Kişi başına ön bordro rakamları taşıdığı için bordro çıktıları
    gibi tarayıcı önbelleğine alınmaz ve açılışı denetim günlüğüne yazılır (docs/KVKK.md).
    Maliyet kendi bölümüyle (Personel maliyeti: Görür) denetler (plan §5.4)."""

    read_access = HasAccess(PERSONNEL_COST, VIEW)
    unhandled_access = HasAccess(PERSONNEL_COST, VIEW)

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request, year: int, month: int) -> HttpResponse:
        _check_month(year, month)
        report = selectors.personnel_cost_report(year, month)
        content = exports.personnel_cost_xlsx(report)
        personnel_services.log_payroll_access(
            _user(request), year, month, "Personel maliyeti (Excel)"
        )
        response = _xlsx(content, f"personel-maliyeti-{year}-{month:02d}")
        response["Cache-Control"] = "no-store"
        return response


class PersonnelLaborRateView(AccessMixin, APIView):
    """Onaylı ayın gerçekleşen işçiliğinden yeni işçilik oranı açar (Personel maliyeti:
    Değiştirir ve Gider oranları: Değiştirir). OPTIONS bugünkü gibi bölümü görene açıktır."""

    read_access = HasAccess(PERSONNEL_COST, VIEW)
    unhandled_access = HasAccess(PERSONNEL_COST, CHANGE)
    action_access = {"post": HasAccess(PERSONNEL_COST, CHANGE) & HasAccess(RATES, CHANGE)}

    @extend_schema(
        request=s.LaborRateFromPersonnelSerializer, responses={201: s.CostRateSerializer}
    )
    def post(self, request: Request, year: int, month: int) -> Response:
        _check_month(year, month)
        body = s.LaborRateFromPersonnelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        rate = services.add_labor_rate_from_personnel_cost(
            _user(request),
            year,
            month,
            body.validated_data["stage"],
            body.validated_data["valid_from"],
        )
        data = s.CostRateSerializer(rate, context={"request": request}).data
        return Response(data, status=status.HTTP_201_CREATED)


class CostCenterView(AccessMixin, APIView):
    """Personel birimlerinin maliyet aşaması (eşleştirilmemiş birim genel giderdir)."""

    read_access = HasAccess(PERSONNEL_COST, VIEW)
    unhandled_access = HasAccess(PERSONNEL_COST, CHANGE)
    action_access = {"put": HasAccess(PERSONNEL_COST, CHANGE)}

    @extend_schema(responses=s.CostCenterSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.CostCenterSerializer(selectors.cost_centers(), many=True).data)

    @extend_schema(request=s.CostCenterSerializer, responses=s.CostCenterSerializer)
    def put(self, request: Request) -> Response:
        body = s.CostCenterSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        center = services.set_department_cost_center(
            _user(request), body.validated_data["department"], body.validated_data["stage"]
        )
        return Response(s.CostCenterSerializer(center).data)
