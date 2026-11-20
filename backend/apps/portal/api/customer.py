"""Müşteri portalı uç noktaları (`/api/v1/portal/customer/`; docs/plan/musteri-siparis-takibi.md
§4.3). Her sorgu bağlı müşteriyle başlar; başka müşterinin kaydı 404 döner. Yalnız müşteri portalı
kullanıcısı açar (çalışan ve tedarikçi hesabı 403)."""

from typing import Any

import django_filters
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.permissions import AccessPermission
from apps.ledger import exports as ledger_exports
from apps.ledger import selectors as ledger_selectors
from apps.masterdata.models import Customer, Supplier
from apps.portal import selectors, services
from apps.portal.api import customer_serializers as s
from apps.sales.models import SalesOrder, Shipment
from apps.sales.waybill import waybill_pdf

DATE_PARAMS = [OpenApiParameter("date_from", str), OpenApiParameter("date_to", str)]


class PortalCustomerOnly(AccessPermission):
    """Yalnız müşteri portalı kullanıcısı (bağlı müşterisi etkin)."""

    message = "Bu sayfa yalnız müşteri portalı hesabına açık."

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "account_type", "") == User.AccountType.CUSTOMER_PORTAL
        )


def customer_of(request: Request) -> Customer:
    account = selectors.account_of(request.user)  # type: ignore[arg-type]
    if account is None or account.customer is None:
        raise BusinessRuleError("portal_account_missing", "Portal hesabı bulunamadı.")
    return account.customer


def pdf_response(content: bytes, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["Cache-Control"] = "no-store"
    return response


class CustomerOrderFilter(django_filters.FilterSet):
    class Meta:
        model = SalesOrder
        fields = ["status"]


class CustomerOrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Siparişlerim: onaylanmış siparişler, satırlar ve tutarlar."""

    serializer_class = s.PortalCustomerOrderSerializer
    permission_classes = [PortalCustomerOnly]
    filterset_class = CustomerOrderFilter
    search_fields = ["number", "customer_po_no"]
    ordering_fields = ["order_date", "number", "due_date"]

    def get_queryset(self) -> QuerySet[SalesOrder]:
        if getattr(self, "swagger_fake_view", False):  # şema üretimi
            return SalesOrder.objects.none()
        return selectors.customer_orders(customer_of(self.request))


class CustomerShipmentFilter(django_filters.FilterSet):
    class Meta:
        model = Shipment
        fields = ["status", "sales_order"]


class CustomerShipmentViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Sevkiyatlar: planlananlar ve sevk edilenler; irsaliye (müşteri nüshası) sevkten sonra."""

    permission_classes = [PortalCustomerOnly]
    filterset_class = CustomerShipmentFilter
    search_fields = ["number", "sales_order__number", "sales_order__customer_po_no"]
    ordering_fields = ["planned_date", "number"]

    def get_queryset(self) -> QuerySet[Shipment]:
        if getattr(self, "swagger_fake_view", False):  # şema üretimi
            return Shipment.objects.none()
        return selectors.customer_shipments(customer_of(self.request))

    def get_serializer_class(self) -> Any:
        if self.action == "retrieve":
            return s.PortalCustomerShipmentDetailSerializer
        return s.PortalCustomerShipmentSerializer

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, url_path="waybill-pdf")
    def waybill_pdf(self, request: Request, pk: str | None = None) -> HttpResponse:
        """İrsaliyenin müşteri nüshası: lot ve SKT yok, şoför TC'si maskeli. Her açılış
        sevkiyatın geçmişine yazılır."""
        shipment = self.get_object()
        if shipment.status != Shipment.Status.DISPATCHED:
            raise BusinessRuleError(
                "waybill_not_ready", "İrsaliye sevkiyat yola çıktıktan sonra hazırlanır."
            )
        content = waybill_pdf(shipment, customer_copy=True)
        services.record_waybill_view(request.user, shipment)  # type: ignore[arg-type]
        return pdf_response(content, f"irsaliye-{shipment.number}.pdf")


class CustomerBalanceView(APIView):
    """Cari hesabım (müşteri; tedarikçi portalı alt sınıfla): para birimi başına bakiye, vadesi
    geçen ve yaşlandırma."""

    permission_classes = [PortalCustomerOnly]

    def firm(self, request: Request) -> Customer | Supplier:
        """Cari hesabı gösterilen firma (tedarikçi portalı bu yöntemi değiştirir)."""
        return customer_of(request)

    @extend_schema(responses=s.PortalBalanceSerializer(many=True))
    def get(self, request: Request) -> Response:
        balances = ledger_selectors.balances_of(self.firm(request))
        return Response(s.PortalBalanceSerializer(balances, many=True).data)


class CustomerStatementView(APIView):
    """Ekstre (tarih aralığı): devreden bakiye, hareketler, kapanış."""

    permission_classes = [PortalCustomerOnly]

    def firm(self, request: Request) -> Customer | Supplier:
        """Cari hesabı gösterilen firma (tedarikçi portalı bu yöntemi değiştirir)."""
        return customer_of(request)

    @extend_schema(parameters=DATE_PARAMS, responses=s.PortalStatementSerializer)
    def get(self, request: Request) -> Response:
        query = s.PortalStatementQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        dates = query.validated_data
        firm = self.firm(request)
        data = {
            **dates,
            "currencies": ledger_selectors.statement(firm, dates["date_from"], dates["date_to"]),
        }
        return Response(s.PortalStatementSerializer(data).data)


class CustomerStatementPdfView(APIView):
    """Ekstrenin PDF'i (mutabakat ekstresiyle aynı biçim)."""

    permission_classes = [PortalCustomerOnly]

    def firm(self, request: Request) -> Customer | Supplier:
        """Cari hesabı gösterilen firma (tedarikçi portalı bu yöntemi değiştirir)."""
        return customer_of(request)

    @extend_schema(parameters=DATE_PARAMS, responses={(200, "application/pdf"): bytes})
    def get(self, request: Request) -> HttpResponse:
        query = s.PortalStatementQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        dates = query.validated_data
        firm = self.firm(request)
        content = ledger_exports.statement_document(
            firm, dates["date_from"], dates["date_to"], contact=False
        )
        return pdf_response(content, f"ekstre-{timezone.localdate():%Y%m%d}.pdf")
