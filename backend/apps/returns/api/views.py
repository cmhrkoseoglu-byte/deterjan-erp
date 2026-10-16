from typing import Any

import django_filters
from django.db.models import Count, Prefetch, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.roles import DEPO, SEVKIYAT
from apps.inventory.api.serializers import CancelSerializer
from apps.inventory.api.views import DocumentViewSet
from apps.returns import services
from apps.returns.api import serializers as s
from apps.returns.models import CustomerReturn, CustomerReturnLine


def _user(request: Request) -> Any:
    return request.user


class CustomerReturnFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=CustomerReturn.Status.choices)
    date_from = django_filters.DateFilter(field_name="return_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="return_date", lookup_expr="lte")
    lot = django_filters.NumberFilter(field_name="lines__lot", distinct=True)

    class Meta:
        model = CustomerReturn
        fields = ["customer"]


class CustomerReturnViewSet(DocumentViewSet):
    """Müşteri iadeleri (sevkiyat yazar). Satırlar iç içe yazılır; `receive` iadeyi karantinaya
    alır ve laboratuvara numune açar; `scrap` imha kararı verilen satırı stoktan düşer."""

    serializer_class = s.CustomerReturnSerializer
    detail_serializer = s.CustomerReturnDetailSerializer  # type: ignore[assignment]
    write_roles = (SEVKIYAT,)
    action_roles = {"receive": (SEVKIYAT, DEPO), "scrap": (DEPO, SEVKIYAT)}
    filterset_class = CustomerReturnFilter
    search_fields = ["number", "customer__name", "customer__code", "lines__lot__lot_no"]
    ordering_fields = ["return_date", "number", "created_at"]
    ordering = ["-return_date", "-id"]

    def get_queryset(self) -> QuerySet[CustomerReturn]:
        queryset = CustomerReturn.objects.select_related(
            "customer", "quarantine_location", "received_by", "created_by"
        ).annotate(line_count=Count("lines", distinct=True))
        if self.action != "list":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "lines",
                    queryset=CustomerReturnLine.objects.select_related(
                        "product__base_unit", "lot", "unit", "sample"
                    ).order_by("line_no"),
                )
            )
        return queryset

    def create_document(self, data: dict[str, Any], lines: list[dict[str, Any]]) -> Any:
        return services.create_return(_user(self.request), data, lines)

    def update_document(
        self, instance: Any, data: dict[str, Any], lines: list[dict[str, Any]] | None
    ) -> Any:
        return services.update_return(_user(self.request), instance, data, lines)

    @extend_schema(request=None, responses=s.CustomerReturnDetailSerializer)
    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str | None = None) -> Response:
        """İadeyi teslim alır: ürün karantinaya girer, lot bekletilir, numune açılır."""
        return self._respond(services.receive_return(_user(request), self.get_object()))

    @extend_schema(request=CancelSerializer, responses=s.CustomerReturnDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Taslak iadeyi iptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        document = services.cancel_return(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(document)

    @extend_schema(request=s.ScrapSerializer, responses=s.CustomerReturnDetailSerializer)
    @action(detail=True, methods=["post"], url_path=r"lines/(?P<line_id>\d+)/scrap")
    def scrap(self, request: Request, pk: str | None = None, line_id: str = "") -> Response:
        """İmha kararı verilen satırın iade miktarını karantinadan `SCRAP` hareketiyle düşer."""
        document = self.get_object()
        line = document.lines.filter(pk=line_id).first()
        if line is None:
            raise NotFound("Satır bulunamadı.")
        body = s.ScrapSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.scrap_line(_user(request), line, body.validated_data["note"])
        return self._respond(document)
