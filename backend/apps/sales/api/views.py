from typing import Any, ClassVar

import django_filters
from django.db.models import Count, Exists, OuterRef, QuerySet
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import BusinessRuleError
from apps.core.permissions import HasRole
from apps.core.roles import DEPO, PLANLAMA, SEVKIYAT, YONETIM
from apps.inventory import selectors as inventory_selectors
from apps.inventory.api.serializers import CancelSerializer
from apps.inventory.models import Lot
from apps.masterdata.models import Location
from apps.sales import selectors, services
from apps.sales.api import serializers as s
from apps.sales.models import SalesOrder, Shipment, ShipmentPick
from apps.sales.state import shipment_states
from apps.sales.waybill import waybill_pdf

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


# --- sevkiyat (Adım 3.2) ---------------------------------------------------------------------


def resolve_lot(shipment: Shipment, data: dict[str, Any]) -> Lot:
    """Okutulan lotu bulur: lot kimliği ya da lot no / lot etiketi (`LOT:<lot_no>`). Aynı numara
    birden çok malzemede varsa sevkiyatın ürünlerindeki lot seçilir."""
    if data.get("lot"):
        lot = Lot.objects.filter(pk=data["lot"]).first()
        label = str(data["lot"])
    else:
        label = data["lot_no"].strip()
        lot_no = label.upper()
        if lot_no.startswith("LOT:"):
            lot_no = lot_no[4:]
        lots = Lot.objects.filter(lot_no=lot_no)
        products = shipment.lines.values_list("order_line__product_id", flat=True)
        lot = lots.filter(material_id__in=list(products)).first() or lots.first()
    if lot is None:
        raise BusinessRuleError("lot_not_found", f"{label} lotu bulunamadı.")
    return lot


class ShipmentFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=Shipment.Status.choices)
    customer = django_filters.NumberFilter(field_name="sales_order__customer")
    date_from = django_filters.DateFilter(field_name="planned_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="planned_date", lookup_expr="lte")

    class Meta:
        model = Shipment
        fields = ["sales_order"]


class ShipmentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Sevkiyatlar. Okuma sevkiyat, yönetim, planlama ve depoya; planlama, düzenleme, sevk onayı
    ve iptal sevkiyata; lot okutma, okutmayı geri alma ve yükleme depoya açık (admin her yere)."""

    serializer_class = s.ShipmentSerializer
    filterset_class = ShipmentFilter
    search_fields = [
        "number",
        "sales_order__number",
        "sales_order__customer__name",
        "vehicle_plate",
    ]
    ordering_fields = ["planned_date", "number", "created_at"]
    ordering = ["-planned_date", "-id"]
    action_roles: ClassVar[dict[str, tuple[str, ...]]] = {
        "pick": services.PICK_ROLES,
        "undo_pick": services.PICK_ROLES,
        "load": services.PICK_ROLES,
    }

    def get_permissions(self) -> list[BasePermission]:
        request = getattr(self, "request", None)
        if request is not None and request.method == "GET":
            return [HasRole(*READ_ROLES)()]
        return [HasRole(*self.action_roles.get(self.action, services.SHIPMENT_ROLES))()]

    def get_queryset(self) -> QuerySet[Shipment]:
        return Shipment.objects.select_related(
            "sales_order__customer",
            "loading_location",
            "loaded_by",
            "dispatched_by",
            "created_by",
        )

    def get_serializer_class(self) -> type[s.ShipmentSerializer]:
        if self.action == "list":
            return s.ShipmentSerializer
        return s.ShipmentDetailSerializer

    def _respond(self, shipment: Shipment, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=shipment.pk)
        return Response(s.ShipmentDetailSerializer(fresh).data, status=code)

    @extend_schema(request=s.ShipmentPlanSerializer, responses={201: s.ShipmentDetailSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Sevkiyat planlar; `lines` verilmezse siparişin kalan miktarları gelir."""
        body = s.ShipmentPlanSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        order = data.pop("sales_order")
        lines = data.pop("lines", None)
        if "loading_location" not in request.data:
            data.pop("loading_location", None)
        shipment = services.plan_shipment(_user(request), order, data, lines)
        return self._respond(shipment, status.HTTP_201_CREATED)

    @extend_schema(request=s.ShipmentSerializer, responses=s.ShipmentDetailSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Sevk edilmemiş sevkiyatın başlığını günceller (araç, şoför, tarih, not)."""
        kwargs.pop("partial", None)
        shipment = self.get_object()
        body = s.ShipmentSerializer(shipment, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        data = {k: v for k, v in body.validated_data.items() if k in request.data}
        if "sales_order" in data:
            raise ValidationError({"sales_order": ["Sevkiyatın siparişi değiştirilemez."]})
        return self._respond(services.update_shipment(_user(request), shipment, data))

    @extend_schema(request=s.PickSerializer, responses=s.ShipmentDetailSerializer)
    @action(detail=True, methods=["post"])
    def pick(self, request: Request, pk: str | None = None) -> Response:
        """Lot okutur (depo): lot sevk alanına taşınır."""
        shipment = self.get_object()
        body = s.PickSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        lot = resolve_lot(shipment, data)
        services.pick_lot(_user(request), shipment, lot, data["quantity"], data["reason"])
        return self._respond(shipment)

    @extend_schema(request=s.UndoPickSerializer, responses=s.ShipmentDetailSerializer)
    @action(detail=True, methods=["post"], url_path="undo-pick")
    def undo_pick(self, request: Request, pk: str | None = None) -> Response:
        """Okutmayı geri alır (depo): lot geldiği yere döner."""
        shipment = self.get_object()
        body = s.UndoPickSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        pick: ShipmentPick = body.validated_data["pick"]
        if pick.line.shipment_id != shipment.pk:
            raise ValidationError({"pick": ["Okutma bu sevkiyata ait değil."]})
        services.undo_pick(_user(request), pick, body.validated_data["note"])
        return self._respond(shipment)

    @extend_schema(request=s.SalesNoteSerializer, responses=s.ShipmentDetailSerializer)
    @action(detail=True, methods=["post"])
    def load(self, request: Request, pk: str | None = None) -> Response:
        """Yükleme tamam (depo)."""
        body = s.SalesNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        shipment = services.mark_loaded(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._respond(shipment)

    @extend_schema(request=s.SalesNoteSerializer, responses=s.ShipmentDetailSerializer)
    # `dispatch` adı View.dispatch ile çakışır; uç nokta yolu yine `dispatch/`.
    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_shipment(self, request: Request, pk: str | None = None) -> Response:
        """Sevki onaylar (sevkiyat): stoktan çıkış, sipariş durumu."""
        body = s.SalesNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        shipment = services.dispatch_shipment(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._respond(shipment)

    @extend_schema(request=CancelSerializer, responses=s.ShipmentDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Sevkiyatı iptal eder (neden zorunlu); toplanan lotlar yerine döner."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        shipment = services.cancel_shipment(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(shipment)

    @extend_schema(responses=s.PickSuggestionSerializer(many=True), filters=False)
    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
    def suggestions(self, request: Request, pk: str | None = None) -> Response:
        """Toplama önerisi: satır başına kalan miktar, rezerve lotlar ve FEFO stok."""
        rows = selectors.pick_suggestions(self.get_object())
        return Response(s.PickSuggestionSerializer(rows, many=True).data)

    def _waybill_shipment(self) -> Shipment:
        shipment = self.get_object()
        if shipment.status not in (Shipment.Status.LOADED, Shipment.Status.DISPATCHED):
            raise BusinessRuleError(
                "waybill_not_ready",
                f"{shipment.number} {shipment_states.label(shipment.status).lower()}; irsaliye "
                "yükleme tamamlanınca kesilir.",
            )
        return shipment

    @extend_schema(responses=s.WaybillSerializer, filters=False)
    @action(detail=True, methods=["get"], filter_backends=[], pagination_class=None)
    def waybill(self, request: Request, pk: str | None = None) -> Response:
        """İrsaliye verisi (dışa aktarım)."""
        data = selectors.waybill_data(self._waybill_shipment())
        return Response(s.WaybillSerializer(data).data)

    # Router dışında, urls.py'de sonda eğik çizgisiz yolla bağlanır (spesifikasyondaki yol).
    @extend_schema(responses={(200, "application/pdf"): bytes}, filters=False)
    def waybill_pdf(self, request: Request, pk: str | None = None) -> HttpResponse:
        """İrsaliye PDF'i."""
        shipment = self._waybill_shipment()
        response = HttpResponse(waybill_pdf(shipment), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="irsaliye-{shipment.number}.pdf"'
        return response


class ShippedLotViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Müşteriye sevk edilen lotlar (müşteri kartı); `customer` filtresi zorunlu."""

    serializer_class = s.ShippedLotSerializer
    filter_backends: list[Any] = []

    def get_permissions(self) -> list[BasePermission]:
        return [HasRole(SEVKIYAT, YONETIM)()]

    @extend_schema(parameters=[OpenApiParameter("customer", int, required=True)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[ShipmentPick]:
        customer = self.request.query_params.get("customer", "")
        if not customer.isdigit():
            raise ValidationError({"customer": ["Müşteri seçilmelidir."]})
        return selectors.customer_shipped_lots(int(customer))
