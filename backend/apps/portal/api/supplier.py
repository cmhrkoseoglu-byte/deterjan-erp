"""Tedarikçi portalı uç noktaları (`/api/v1/portal/supplier/`; docs/plan/musteri-siparis-takibi.md
§4.3a). Her sorgu bağlı tedarikçiyle başlar; başka tedarikçinin kaydı 404 döner. Yalnız tedarikçi
portalı kullanıcısı açar (çalışan ve müşteri hesabı 403). Tedarikçi yalnız görür."""

from typing import Any

import django_filters
from django.db.models import QuerySet
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.permissions import AccessPermission
from apps.inventory.models import GoodsReceipt
from apps.masterdata.models import Customer, Supplier
from apps.portal import selectors
from apps.portal.api import customer
from apps.portal.api import supplier_serializers as s
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.pdf import purchase_order_pdf


class PortalSupplierOnly(AccessPermission):
    """Yalnız tedarikçi portalı kullanıcısı."""

    message = "Bu sayfa yalnız tedarikçi portalı hesabına açık."

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "account_type", "") == User.AccountType.SUPPLIER_PORTAL
        )


def _supplier(request: Request) -> Supplier:
    account = selectors.account_of(request.user)  # type: ignore[arg-type]
    if account is None or account.supplier is None:
        raise BusinessRuleError("portal_account_missing", "Portal hesabı bulunamadı.")
    return account.supplier


class SupplierOrderFilter(django_filters.FilterSet):
    class Meta:
        model = PurchaseOrder
        fields = ["status"]


class SupplierOrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Siparişlerim: tedarikçiye gönderilmiş satın alma siparişleri ve PDF'leri."""

    serializer_class = s.PortalSupplierOrderSerializer
    permission_classes = [PortalSupplierOnly]
    filterset_class = SupplierOrderFilter
    search_fields = ["number"]
    ordering_fields = ["order_date", "number"]

    def get_queryset(self) -> QuerySet[PurchaseOrder]:
        if getattr(self, "swagger_fake_view", False):  # şema üretimi
            return PurchaseOrder.objects.none()
        return selectors.supplier_orders(_supplier(self.request))

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True)
    def pdf(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Siparişin tedarikçiye giden PDF'i (aynı belge)."""
        order = self.get_object()
        return customer.pdf_response(purchase_order_pdf(order), f"{order.number}.pdf")


class SupplierReceiptViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Teslimatlarım: bu tedarikçiden kaydedilmiş mal kabuller."""

    serializer_class = s.PortalReceiptSerializer
    permission_classes = [PortalSupplierOnly]
    search_fields = ["number", "delivery_note_no"]
    ordering_fields = ["receipt_date", "number"]

    def get_queryset(self) -> QuerySet[GoodsReceipt]:
        if getattr(self, "swagger_fake_view", False):  # şema üretimi
            return GoodsReceipt.objects.none()
        return selectors.supplier_receipts(_supplier(self.request))


class SupplierBalanceView(customer.CustomerBalanceView):
    """Cari hesabım (tedarikçi): para birimi başına bakiye, vadesi geçen ve yaşlandırma."""

    permission_classes = [PortalSupplierOnly]

    def firm(self, request: Request) -> Customer | Supplier:
        return _supplier(request)


class SupplierStatementView(customer.CustomerStatementView):
    """Ekstre (tarih aralığı)."""

    permission_classes = [PortalSupplierOnly]

    def firm(self, request: Request) -> Customer | Supplier:
        return _supplier(request)


class SupplierStatementPdfView(customer.CustomerStatementPdfView):
    """Ekstrenin PDF'i (mutabakat ekstresiyle aynı biçim)."""

    permission_classes = [PortalSupplierOnly]

    def firm(self, request: Request) -> Customer | Supplier:
        return _supplier(request)
