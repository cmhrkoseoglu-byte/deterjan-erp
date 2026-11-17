from datetime import date, timedelta
from typing import Any

import django_filters
from django.db.models import Min, QuerySet
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import APPROVE, CHANGE, PRICES, VIEW
from apps.core.permissions import AccessMixin, HasAccess, ReadRule
from apps.inventory.api.serializers import CancelSerializer
from apps.masterdata.models import Material, Supplier
from apps.purchasing import selectors, services
from apps.purchasing.access import (
    DELIVERIES,
    ORDERS,
    OVER_LIMIT,
    PERFORMANCE,
    REQUESTS,
    SETTINGS,
    SUGGESTIONS,
)
from apps.purchasing.api import serializers as s
from apps.purchasing.models import PurchaseOrder, PurchaseRequest, ReceiptLineLink
from apps.purchasing.pdf import purchase_order_pdf

ORDER_CHANGE = HasAccess(ORDERS, CHANGE)
# Onay ve taslağa geri gönderme uç noktası: siparişi onaylayan ya da limit üstü onaylayan; limit
# kararını (D-13) ve taslağa geri göndermeyi servis verir (plan §5.4).
ORDER_APPROVE = HasAccess(ORDERS, APPROVE) | HasAccess(OVER_LIMIT, APPROVE)


def _user(request: Request) -> Any:
    return request.user


# --- talep -----------------------------------------------------------------------------------


class PurchaseRequestFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=PurchaseRequest.Status.choices)
    source = django_filters.ChoiceFilter(choices=PurchaseRequest.Source.choices)
    need_from = django_filters.DateFilter(field_name="need_date", lookup_expr="gte")
    need_to = django_filters.DateFilter(field_name="need_date", lookup_expr="lte")

    class Meta:
        model = PurchaseRequest
        fields = ["material"]


class PurchaseRequestViewSet(
    AccessMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Satın alma talepleri: Görür okur, Değiştirir açar. Değiştirme ve iptal talebi açana ya da
    "Satın alma siparişleri: Değiştirir"e açıktır (satır kuralı serviste, plan §4)."""

    serializer_class = s.PurchaseRequestSerializer
    filterset_class = PurchaseRequestFilter
    search_fields = ["number", "material__code", "material__name", "reason"]
    ordering_fields = ["need_date", "number", "created_at"]
    ordering = ["need_date", "-id"]
    read_access = HasAccess(REQUESTS, VIEW)
    unhandled_access = HasAccess(REQUESTS, CHANGE)
    action_access = {
        "create": HasAccess(REQUESTS, CHANGE),
        "update": HasAccess(REQUESTS, CHANGE),
        "partial_update": HasAccess(REQUESTS, CHANGE),
        "cancel": HasAccess(REQUESTS, CHANGE),
    }

    def get_queryset(self) -> QuerySet[PurchaseRequest]:
        return PurchaseRequest.objects.select_related(
            "material__base_unit", "order_line__order", "created_by"
        )

    def _respond(self, request_obj: PurchaseRequest, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=request_obj.pk)
        return Response(s.PurchaseRequestSerializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Manuel satın alma talebi."""
        body = s.PurchaseRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        created = services.create_request(_user(request), body.validated_data)
        return self._respond(created, status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Açık talebi günceller."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        body = s.PurchaseRequestSerializer(instance, data=request.data, partial=partial)
        body.is_valid(raise_exception=True)
        return self._respond(services.update_request(_user(request), instance, body.validated_data))

    @extend_schema(request=CancelSerializer, responses=s.PurchaseRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Açık talebi iptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        cancelled = services.cancel_request(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(cancelled)


# --- sipariş ---------------------------------------------------------------------------------


class PurchaseOrderFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=PurchaseOrder.Status.choices)
    date_from = django_filters.DateFilter(field_name="order_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="order_date", lookup_expr="lte")
    material = django_filters.NumberFilter(field_name="lines__material", distinct=True)

    class Meta:
        model = PurchaseOrder
        fields = ["supplier"]


class PurchaseOrderViewSet(
    AccessMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Satın alma siparişleri. Okuma "Satın alma siparişleri: Görür" (tutarlar yalnız Fiyatları
    görür ile); yazma Değiştirir. Siparişten mal kabul "Beklenen teslimatlar ve siparişten mal
    kabul: Değiştirir" ister. Durum eylem uç noktalarıyla değişir.

    Bugünkü gibi yalnız GET okumadır: HEAD ve OPTIONS (PDF dahil her yolda) ile karşılanmayan
    metotlar sipariş yazma yetkisini ister; karşılanmayan yoldaki GET okuma kuralıyla denetlenir,
    sonra 405 döner. Sipariş PDF'i tutarlı belgedir: Görür ve Fiyatları görür (plan §5.6)."""

    serializer_class = s.PurchaseOrderSerializer
    filterset_class = PurchaseOrderFilter
    search_fields = ["number", "supplier__name", "supplier__code", "notes"]
    ordering_fields = ["order_date", "number", "created_at"]
    ordering = ["-order_date", "-id"]
    read_access = ReadRule(ORDERS)
    read_methods = frozenset({"GET"})
    other_safe_access = ORDER_CHANGE
    unhandled_access = ORDER_CHANGE
    unhandled_read_methods = frozenset({"GET"})
    action_access = {
        "create": ORDER_CHANGE,
        "update": ORDER_CHANGE,
        "partial_update": ORDER_CHANGE,
        "submit": ORDER_CHANGE,
        "approve": ORDER_APPROVE,
        "return_to_draft": ORDER_APPROVE,
        "send": ORDER_CHANGE,
        # Durumu bilmeden: taslak ya da onay bekleyen Değiştirir, onaylı ya da gönderilmiş
        # Onaylar ister; servis duruma göre denetler.
        "cancel": ORDER_CHANGE | HasAccess(ORDERS, APPROVE),
        "close": ORDER_CHANGE,
        "receive": HasAccess(DELIVERIES, CHANGE),
        "pdf": HasAccess(ORDERS, VIEW) & HasAccess(PRICES, VIEW),
    }

    def get_queryset(self) -> QuerySet[PurchaseOrder]:
        return (
            PurchaseOrder.objects.select_related("supplier", "approved_by", "sent_by", "created_by")
            .prefetch_related("lines")
            .annotate(expected_date=Min("lines__expected_date"))
        )

    def get_serializer_class(self) -> type[s.PurchaseOrderSerializer]:
        if self.action == "list":
            return s.PurchaseOrderSerializer
        return s.PurchaseOrderDetailSerializer

    def _respond(self, order: PurchaseOrder, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=order.pk)
        data = s.PurchaseOrderDetailSerializer(fresh, context=self.get_serializer_context()).data
        return Response(data, status=code)

    @staticmethod
    def _split(serializer: Any) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
        data = dict(serializer.validated_data)
        return data, data.pop("lines", None)

    @extend_schema(
        request=s.PurchaseOrderDetailSerializer, responses={201: s.PurchaseOrderDetailSerializer}
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Taslak sipariş (satırlarıyla; satır talep bağlayabilir)."""
        body = s.PurchaseOrderDetailSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        body.is_valid(raise_exception=True)
        data, lines = self._split(body)
        order = services.create_order(_user(request), data, lines or [])
        return self._respond(order, status.HTTP_201_CREATED)

    @extend_schema(
        request=s.PurchaseOrderDetailSerializer, responses=s.PurchaseOrderDetailSerializer
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Taslak siparişi günceller; `lines` verilirse satırlar eşitlenir."""
        partial = kwargs.pop("partial", False)
        order = self.get_object()
        body = s.PurchaseOrderDetailSerializer(
            order, data=request.data, partial=partial, context=self.get_serializer_context()
        )
        body.is_valid(raise_exception=True)
        data, lines = self._split(body)
        return self._respond(services.update_order(_user(request), order, data, lines))

    @extend_schema(request=None, responses=s.PurchaseOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: str | None = None) -> Response:
        """Yönetim onayına gönderir."""
        return self._respond(services.submit_for_approval(_user(request), self.get_object()))

    @extend_schema(request=None, responses=s.PurchaseOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Siparişi onaylar (Karar D-13 limit kuralıyla)."""
        return self._respond(services.approve_order(_user(request), self.get_object()))

    @extend_schema(request=s.PurchaseNoteSerializer, responses=s.PurchaseOrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="return-to-draft")
    def return_to_draft(self, request: Request, pk: str | None = None) -> Response:
        """Yönetim onayındaki siparişi gerekçeyle taslağa geri gönderir (servis Limit üstü
        sipariş onayı: Onaylar ister)."""
        body = s.PurchaseNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.return_to_draft(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._respond(order)

    @extend_schema(request=s.SendSerializer, responses=s.PurchaseOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def send(self, request: Request, pk: str | None = None) -> Response:
        """Gönderildi yapar; `email` verilirse sipariş PDF'i o adrese e-postayla gider."""
        body = s.SendSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.mark_sent(
            _user(request), self.get_object(), email=body.validated_data["email"]
        )
        return self._respond(order)

    @extend_schema(request=CancelSerializer, responses=s.PurchaseOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Mal kabul gelmemiş siparişi iptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.cancel_order(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(order)

    @extend_schema(request=s.PurchaseNoteSerializer, responses=s.PurchaseOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str | None = None) -> Response:
        """Kısmen teslim alınmış siparişin kalanını kapatır (gerekçe zorunlu)."""
        body = s.PurchaseNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.close_order(_user(request), self.get_object(), body.validated_data["note"])
        return self._respond(order)

    @extend_schema(request=s.ReceiveSerializer, responses={201: s.ReceiveResultSerializer})
    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str | None = None) -> Response:
        """Siparişten taslak mal kabul açar (birim ve fiyat siparişten). Mal kabul, depo
        ekranında kontrol edilip kaydedilir."""
        body = s.ReceiveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        lines = data.pop("lines")
        receipt = services.create_receipt_from_order(_user(request), self.get_object(), data, lines)
        return Response({"id": receipt.pk, "number": receipt.number}, status.HTTP_201_CREATED)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def pdf(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Sipariş PDF'i (tutarlı belge; sipariş Görür ve Fiyatları görür)."""
        order = self.get_object()
        response = HttpResponse(purchase_order_pdf(order), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{order.number}.pdf"'
        return response


# --- okuma uç noktaları ----------------------------------------------------------------------


class ExpectedDeliveriesView(AccessMixin, APIView):
    """Teslimat bekleyen sipariş satırları (Beklenen teslimatlar: Görür; tutarsız)."""

    read_access = HasAccess(DELIVERIES, VIEW)
    unhandled_access = HasAccess(DELIVERIES, VIEW)

    @extend_schema(
        parameters=[
            OpenApiParameter("supplier", int),
            OpenApiParameter("material", int),
        ],
        responses=s.ExpectedDeliverySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        supplier = _object_param(request, "supplier", Supplier)
        material = _object_param(request, "material", Material)
        today = timezone.localdate()
        rows = selectors.open_order_lines(supplier=supplier, material=material)
        for row in rows:
            row.is_late = row.expected_date < today  # type: ignore[attr-defined]
        return Response(s.ExpectedDeliverySerializer(rows, many=True).data)


class SuggestionsView(AccessMixin, APIView):
    """Talep önerisi (basit MRP), anlık hesap."""

    read_access = HasAccess(SUGGESTIONS, VIEW)
    unhandled_access = HasAccess(SUGGESTIONS, VIEW)

    @extend_schema(responses=s.SuggestionSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.SuggestionSerializer(selectors.purchase_suggestions(), many=True).data)


class SupplierPerformanceView(AccessMixin, APIView):
    """Tedarikçi performansı: zamanında teslim ve QC red oranı (varsayılan: son 90 gün)."""

    read_access = HasAccess(PERFORMANCE, VIEW)
    unhandled_access = HasAccess(PERFORMANCE, VIEW)

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", date),
            OpenApiParameter("date_to", date),
            OpenApiParameter("supplier", int),
        ],
        responses=s.SupplierPerformanceSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        today = timezone.localdate()
        date_to = _date_param(request, "date_to") or today
        date_from = _date_param(request, "date_from") or date_to - timedelta(days=90)
        if date_from > date_to:
            raise ValidationError({"date_from": ["Başlangıç bitişten sonra olamaz."]})
        supplier = _object_param(request, "supplier", Supplier)
        rows = selectors.supplier_performance(date_from, date_to, supplier=supplier)
        return Response(s.SupplierPerformanceSerializer(rows, many=True).data)


class ReceiptLinksView(AccessMixin, APIView):
    """Mal kabulün siparişe bağlı satırları (`?receipt=<id>`; Beklenen teslimatlar: Görür)."""

    read_access = HasAccess(DELIVERIES, VIEW)
    unhandled_access = HasAccess(DELIVERIES, VIEW)

    @extend_schema(
        parameters=[OpenApiParameter("receipt", int, required=True)],
        responses=s.ReceiptLinkSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        receipt_id = request.query_params.get("receipt", "")
        if not receipt_id.isdigit():
            raise ValidationError({"receipt": ["Mal kabul seçilmelidir."]})
        links = ReceiptLineLink.objects.filter(
            receipt_line__receipt_id=int(receipt_id)
        ).select_related("order_line__order")
        return Response(s.ReceiptLinkSerializer(links, many=True).data)


class PurchasingSettingsView(AccessMixin, APIView):
    """Onay limiti ve fazla teslim toleransı. Değerleri Satın alma ayarları: Görür ve sipariş
    yazan (Satın alma siparişleri: Değiştirir) okur (plan §3.10); değiştirme Satın alma ayarları:
    Değiştirir. HEAD, OPTIONS ve karşılanmayan metotlar bugünkü gibi değiştirme yetkisini ister."""

    read_access = HasAccess(SETTINGS, VIEW) | ORDER_CHANGE
    read_methods = frozenset({"GET"})
    other_safe_access = HasAccess(SETTINGS, CHANGE)
    unhandled_access = HasAccess(SETTINGS, CHANGE)
    action_access = {"patch": HasAccess(SETTINGS, CHANGE)}

    @extend_schema(responses=s.PurchasingSettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.PurchasingSettingsSerializer(services.get_settings()).data)

    @extend_schema(request=s.PurchasingSettingsSerializer, responses=s.PurchasingSettingsSerializer)
    def patch(self, request: Request) -> Response:
        body = s.PurchasingSettingsSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        instance = services.update_settings(_user(request), body.validated_data)
        return Response(s.PurchasingSettingsSerializer(instance).data)


def _date_param(request: Request, name: str) -> date | None:
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: ["Geçerli bir tarih girin (YYYY-AA-GG)."]}) from exc


def _object_param(request: Request, name: str, model: Any) -> Any:
    value = request.query_params.get(name)
    if not value:
        return None
    if not value.isdigit():
        raise ValidationError({name: ["Geçerli bir kimlik girin."]})
    obj = model.objects.filter(pk=value).first()
    if obj is None:
        raise ValidationError({name: ["Kayıt bulunamadı."]})
    return obj
