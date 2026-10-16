from typing import Any

import django_filters
from django.db.models import Count, Exists, OuterRef, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import HasRole
from apps.core.roles import DEPO, PLANLAMA, SEVKIYAT, YONETIM
from apps.inventory import selectors as inventory_selectors
from apps.inventory.api.serializers import CancelSerializer
from apps.masterdata.models import Location
from apps.sales import selectors, services
from apps.sales.api import serializers as s
from apps.sales.models import SalesOrder

READ_ROLES = (SEVKIYAT, YONETIM, PLANLAMA, DEPO)
WRITE_ROLES = services.ORDER_ROLES
READ_ACTIONS = frozenset({"list", "retrieve", "metadata", "candidates"})


def _user(request: Request) -> Any:
    return request.user


class SalesOrderFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=SalesOrder.Status.choices)
    date_from = django_filters.DateFilter(field_name="order_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="order_date", lookup_expr="lte")
    has_shortage = django_filters.BooleanFilter(field_name="has_shortage")

    class Meta:
        model = SalesOrder
        fields = ["customer"]


class SalesOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Satış siparişleri. Okuma sevkiyat, yönetim, planlama ve depoya; yazma sevkiyat ve
    yönetime açık (admin her yere). Durum PATCH ile değişmez; eylem uç noktaları kullanılır."""

    serializer_class = s.SalesOrderSerializer
    filterset_class = SalesOrderFilter
    search_fields = ["number", "customer__name", "customer__code", "customer_po_no"]
    ordering_fields = ["order_date", "requested_delivery_date", "number", "created_at"]
    ordering = ["-order_date", "-id"]

    def get_permissions(self) -> list[BasePermission]:
        if self.action in READ_ACTIONS or self.request.method == "GET":
            return [HasRole(*READ_ROLES)()]
        return [HasRole(*WRITE_ROLES)()]

    def get_queryset(self) -> QuerySet[SalesOrder]:
        shortage = selectors.lines_with_quantities().filter(
            order=OuterRef("pk"),
            shortage_quantity__gt=0,  # type: ignore[misc]
        )
        return (
            SalesOrder.objects.select_related("customer", "confirmed_by", "created_by")
            .annotate(line_count=Count("lines", distinct=True))
            .annotate(
                has_shortage=Exists(shortage)
                & Exists(
                    SalesOrder.objects.filter(
                        pk=OuterRef("pk"),
                        status__in=(
                            SalesOrder.Status.CONFIRMED,
                            SalesOrder.Status.PARTIALLY_SHIPPED,
                        ),
                    )
                )
            )
        )

    def get_serializer_class(self) -> type[s.SalesOrderSerializer]:
        if self.action == "list":
            return s.SalesOrderSerializer
        return s.SalesOrderDetailSerializer

    def _respond(self, order: SalesOrder, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=order.pk)
        return Response(s.SalesOrderDetailSerializer(fresh).data, status=code)

    @staticmethod
    def _split(serializer: Any) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
        data = dict(serializer.validated_data)
        return data, data.pop("lines", None)

    @extend_schema(
        request=s.SalesOrderDetailSerializer, responses={201: s.SalesOrderDetailSerializer}
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Taslak sipariş (satırlarıyla)."""
        body = s.SalesOrderDetailSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data, lines = self._split(body)
        order = services.create_order(_user(request), data, lines or [])
        return self._respond(order, status.HTTP_201_CREATED)

    @extend_schema(request=s.SalesOrderDetailSerializer, responses=s.SalesOrderDetailSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Taslak siparişi günceller; `lines` verilirse satırlar eşitlenir."""
        partial = kwargs.pop("partial", False)
        order = self.get_object()
        body = s.SalesOrderDetailSerializer(order, data=request.data, partial=partial)
        body.is_valid(raise_exception=True)
        data, lines = self._split(body)
        return self._respond(services.update_order(_user(request), order, data, lines))

    @extend_schema(request=s.SalesNoteSerializer, responses=s.SalesOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: str | None = None) -> Response:
        """Siparişi onaylar ve FEFO ile rezervasyon yapar."""
        body = s.SalesNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.confirm_order(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._respond(order)

    @extend_schema(request=CancelSerializer, responses=s.SalesOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Siparişi iptal eder (neden zorunlu); rezervasyonlar bırakılır."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.cancel_order(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(order)

    @extend_schema(request=s.SalesNoteSerializer, responses=s.SalesOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str | None = None) -> Response:
        """Sevk edilmiş siparişi kapatır; kalan rezervasyonlar bırakılır."""
        body = s.SalesNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.close_order(_user(request), self.get_object(), body.validated_data["note"])
        return self._respond(order)

    @extend_schema(request=None, responses=s.SalesOrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="reserve-shortages")
    def reserve_shortages(self, request: Request, pk: str | None = None) -> Response:
        """Eksik miktarları yeni serbest stoktan FEFO ile rezerve eder."""
        order = self.get_object()
        services.reserve_shortages(_user(request), order)
        return self._respond(order)

    @extend_schema(request=s.ReserveSerializer, responses=s.SalesOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def reserve(self, request: Request, pk: str | None = None) -> Response:
        """Satıra elle lot rezerve eder."""
        order = self.get_object()
        body = s.ReserveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        if data["line"].order_id != order.pk:
            raise ValidationError({"line": ["Satır bu siparişe ait değil."]})
        services.reserve_lot(
            _user(request),
            data["line"],
            lot=data["lot"],
            location=data["location"],
            quantity=data["quantity"],
            note=data["note"],
        )
        return self._respond(order)

    @extend_schema(request=s.ReleaseSerializer, responses=s.SalesOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def release(self, request: Request, pk: str | None = None) -> Response:
        """Satırdaki bir rezervasyonu bırakır."""
        order = self.get_object()
        body = s.ReleaseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        reservation = body.validated_data["reservation"]
        line = services.order_line_of(reservation)
        if line is None or line.order_id != order.pk:
            raise ValidationError({"reservation": ["Rezervasyon bu siparişe ait değil."]})
        services.release_line_reservation(_user(request), reservation, body.validated_data["note"])
        return self._respond(order)

    @extend_schema(
        parameters=[OpenApiParameter("line", int, required=True)],
        responses=s.CandidateSerializer(many=True),
        filters=False,
    )
    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
    def candidates(self, request: Request, pk: str | None = None) -> Response:
        """Satıra rezerve edilebilecek stok (serbest, SKT'si geçmemiş, karantina dışı), FEFO
        sırasıyla; müşterinin raf ömrü şartını karşılamayanlar `meets_shelf_life=false`."""
        order = self.get_object()
        line_id = request.query_params.get("line", "")
        line = order.lines.filter(pk=line_id).first() if line_id.isdigit() else None
        if line is None:
            raise ValidationError({"line": ["Geçerli bir sipariş satırı seçilmelidir."]})
        limit = services.min_expiry_date(order.customer, services.shelf_life_reference_date(order))
        rows = list(
            inventory_selectors.available_lots(line.product).exclude(
                location__location_type=Location.Type.QUARANTINE
            )
        )
        for row in rows:
            expiry = row.lot.expiry_date
            row.meets_shelf_life = limit is None or expiry is None or expiry >= limit  # type: ignore[attr-defined]
        return Response(s.CandidateSerializer(rows, many=True).data)
