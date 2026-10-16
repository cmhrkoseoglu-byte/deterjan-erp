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
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole
from apps.core.roles import DEPO, PLANLAMA, SATIN_ALMA, YONETIM
from apps.inventory.api.serializers import CancelSerializer
from apps.masterdata.models import Material, Supplier
from apps.purchasing import selectors, services
from apps.purchasing.api import serializers as s
from apps.purchasing.models import PurchaseOrder, PurchaseRequest, ReceiptLineLink
from apps.purchasing.pdf import purchase_order_pdf

ORDER_READ_ROLES = (SATIN_ALMA, YONETIM, DEPO)
SUGGESTION_ROLES = (SATIN_ALMA, YONETIM, PLANLAMA)
PERFORMANCE_ROLES = (SATIN_ALMA, YONETIM)


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
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Satın alma talepleri. Talep açan roller (planlama, depo, üretim, satın alma, yönetim)
    görür ve açar; değiştirme ve iptal talebi açana ya da satın almaya açıktır."""

    serializer_class = s.PurchaseRequestSerializer
    filterset_class = PurchaseRequestFilter
    search_fields = ["number", "material__code", "material__name", "reason"]
    ordering_fields = ["need_date", "number", "created_at"]
    ordering = ["need_date", "-id"]
    permission_classes = [HasRole(*services.REQUEST_ROLES)]

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
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Satın alma siparişleri. Okuma satın alma, yönetim ve depoya (depo tutarları görmez);
    yazma satın alma ve yönetime. Siparişten mal kabulü depo da açar. Durum eylem uç
    noktalarıyla değişir."""

    serializer_class = s.PurchaseOrderSerializer
    filterset_class = PurchaseOrderFilter
    search_fields = ["number", "supplier__name", "supplier__code", "notes"]
    ordering_fields = ["order_date", "number", "created_at"]
    ordering = ["-order_date", "-id"]

    def get_permissions(self) -> list[BasePermission]:
        if self.action == "pdf":
            return [HasRole(*services.ORDER_ROLES)()]
        if self.request.method == "GET":
            return [HasRole(*ORDER_READ_ROLES)()]
        if self.action == "receive":
            return [HasRole(*services.RECEIPT_ROLES)()]
        return [HasRole(*services.ORDER_ROLES)()]

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
        """Yönetim onayındaki siparişi gerekçeyle taslağa geri gönderir (yönetim)."""
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
        """Sipariş PDF'i (tutarlı belge; yalnızca satın alma ve yönetim)."""
        order = self.get_object()
        response = HttpResponse(purchase_order_pdf(order), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{order.number}.pdf"'
        return response


# --- okuma uç noktaları ----------------------------------------------------------------------


class ExpectedDeliveriesView(APIView):
    """Teslimat bekleyen sipariş satırları (depo, satın alma, yönetim; tutarsız)."""

    permission_classes = [HasRole(*ORDER_READ_ROLES)]

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


class SuggestionsView(APIView):
    """Talep önerisi (basit MRP), anlık hesap."""

    permission_classes = [HasRole(*SUGGESTION_ROLES)]

    @extend_schema(responses=s.SuggestionSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.SuggestionSerializer(selectors.purchase_suggestions(), many=True).data)


class SupplierPerformanceView(APIView):
    """Tedarikçi performansı: zamanında teslim ve QC red oranı (varsayılan: son 90 gün)."""

    permission_classes = [HasRole(*PERFORMANCE_ROLES)]

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


class ReceiptLinksView(APIView):
    """Mal kabulün siparişe bağlı satırları (`?receipt=<id>`); mal kabul ekranı kullanır."""

    permission_classes = [HasRole(*ORDER_READ_ROLES)]

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


class PurchasingSettingsView(APIView):
    """Onay limiti ve fazla teslim toleransı. Okuma satın alma ve yönetime, değiştirme yönetime."""

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [HasRole(SATIN_ALMA, YONETIM)()]
        return [HasRole(*services.APPROVER_ROLES)()]

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
