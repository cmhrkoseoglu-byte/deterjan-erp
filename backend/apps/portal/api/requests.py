"""Sipariş talebi uç noktaları (docs/plan/musteri-siparis-takibi.md §4.4).

- `/api/v1/portal/customer/requests/`, `/customer/products/`: müşteri portalı kullanıcısı (kendi
  firmasının talepleri; açar, geri çeker).
- `/api/v1/portal/requests/`: iç ekran (Sevkiyat > Portal talepleri). Satış siparişleri: Görür ile
  okunur; siparişe çevirme ve reddetme Değiştirir ister. Portal kullanıcısı bu uçları açamaz.
"""

from typing import Any

import django_filters
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.access import CHANGE, VIEW
from apps.core.models import User
from apps.core.permissions import AccessMixin, HasAccess, ReadRule
from apps.masterdata.models import Material
from apps.portal import selectors, services
from apps.portal.api import request_serializers as s
from apps.portal.api.customer import PortalCustomerOnly, customer_of
from apps.portal.models import OrderRequest
from apps.sales.access import ORDERS


def _actor(request: Request) -> User:
    return request.user  # type: ignore[return-value]


class RequestFilter(django_filters.FilterSet):
    class Meta:
        model = OrderRequest
        fields = ["status", "customer"]


class CustomerRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Taleplerim (müşteri): liste, yeni talep, geri çekme."""

    serializer_class = s.PortalRequestSerializer
    permission_classes = [PortalCustomerOnly]
    filterset_class = RequestFilter
    search_fields = ["number", "customer_po_no"]
    ordering_fields = ["created_at", "number"]

    def get_queryset(self) -> QuerySet[OrderRequest]:
        if getattr(self, "swagger_fake_view", False):  # şema üretimi
            return OrderRequest.objects.none()
        return selectors.customer_requests(customer_of(self.request))

    @extend_schema(request=s.RequestInputSerializer, responses={201: s.PortalRequestSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = s.RequestInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        lines = data.pop("lines")
        created = services.submit_request(_actor(request), data, lines)
        fresh = self.get_queryset().get(pk=created.pk)
        return Response(s.PortalRequestSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.PortalRequestSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request: Request, pk: str | None = None) -> Response:
        withdrawn = services.withdraw_request(_actor(request), self.get_object())
        fresh = self.get_queryset().get(pk=withdrawn.pk)
        return Response(s.PortalRequestSerializer(fresh).data)


class OrderableProductViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Talepte seçilebilen ürünler (aktif mamuller ve birimleri; fiyat ve stok yok)."""

    serializer_class = s.OrderableProductSerializer
    permission_classes = [PortalCustomerOnly]
    search_fields = ["code", "name"]

    def get_queryset(self) -> QuerySet[Material]:
        return selectors.orderable_products()


class StaffRequestViewSet(
    AccessMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Portal talepleri (iç ekran): liste ve ayrıntı (Satış siparişleri: Görür), siparişe çevirme
    ve reddetme (Değiştirir)."""

    serializer_class = s.StaffRequestSerializer
    filterset_class = RequestFilter
    search_fields = ["number", "customer__code", "customer__name", "customer_po_no"]
    ordering_fields = ["created_at", "number"]
    read_access = ReadRule(ORDERS)
    unhandled_access = HasAccess(ORDERS, VIEW)
    action_access = {"convert": HasAccess(ORDERS, CHANGE), "reject": HasAccess(ORDERS, CHANGE)}

    def get_queryset(self) -> QuerySet[OrderRequest]:
        return selectors.order_requests()

    def _fresh(self, pk: Any) -> Any:
        return s.StaffRequestSerializer(self.get_queryset().get(pk=pk)).data

    @extend_schema(request=None, responses=s.StaffRequestSerializer)
    @action(detail=True, methods=["post"])
    def convert(self, request: Request, pk: str | None = None) -> Response:
        """Talepten taslak satış siparişi açar; yanıtta `sales_order` (siparişin kimliği)."""
        services.convert_request(_actor(request), self.get_object())
        return Response(self._fresh(pk))

    @extend_schema(request=s.RejectInputSerializer, responses=s.StaffRequestSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        body = s.RejectInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.reject_request(_actor(request), self.get_object(), body.validated_data["reason"])
        return Response(self._fresh(pk))
