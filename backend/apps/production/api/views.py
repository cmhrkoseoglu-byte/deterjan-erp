from typing import Any

import django_filters
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.access import APPROVE, CHANGE
from apps.core.exceptions import BusinessRuleError
from apps.core.permissions import AccessMixin, HasAccess, ReadRule
from apps.inventory import selectors as inventory_selectors
from apps.inventory.api.serializers import CancelSerializer, StockBalanceSerializer
from apps.inventory.models import Lot
from apps.production import selectors, services
from apps.production.access import BATCHES, ORDERS, PREP
from apps.production.api import serializers as s
from apps.production.models import ProductionBatch, ProductionOrder, ProductionRequirement

# Emir ve şarj okuması: üç bölümden birinde okuma yeter (plan §5.1).
RECORD_READ = ReadRule(ORDERS, PREP, BATCHES)
ORDER_CHANGE = HasAccess(ORDERS, CHANGE)
ORDER_APPROVE = HasAccess(ORDERS, APPROVE)
PREP_CHANGE = HasAccess(PREP, CHANGE)
BATCH_CHANGE = HasAccess(BATCHES, CHANGE)


def _user(request: Request) -> Any:
    return request.user


def resolve_lot(requirement: ProductionRequirement, data: dict[str, Any]) -> Lot:
    """Okutulan lotu (lot kimliği, lot no, lot etiketi ya da GS1 barkodu; ortak çözüm
    `inventory.selectors.resolve_lot`) yalnızca ihtiyacın malzemesindeki lotlarda arar."""
    if data.get("lot"):
        lot = Lot.objects.filter(material_id=requirement.material_id, pk=data["lot"]).first()
    else:
        lot = inventory_selectors.resolve_lot(data["lot_no"], materials=[requirement.material_id])
    if lot is None:
        label = data.get("lot") or inventory_selectors.scan_label(data["lot_no"])
        raise BusinessRuleError(
            "lot_not_found",
            f"{requirement.material.code} malzemesinde {label} lotu bulunamadı.",
        )
    return lot


def _requirement(order_id: int, requirement_id: int) -> ProductionRequirement:
    requirement = (
        ProductionRequirement.objects.select_related("material")
        .filter(order_id=order_id, pk=requirement_id)
        .first()
    )
    if requirement is None:
        raise ValidationError({"requirement": ["İhtiyaç satırı bu emre ait değil."]})
    return requirement


class ProductionAccessMixin(AccessMixin):
    """Emir ve şarj okuması, her yazma eylemi kendi bölümüyle (plan §3.4). Her GET okumadır,
    karşılanmayan yolda da; karşılanmayan diğer metotlar bugünkü yedek kural gibi emir yazma
    yetkisi ister (sonra DRF 405 döner). Listede olmayan yazma eylemi reddedilir (plan §5.4)."""

    read_access = RECORD_READ
    unhandled_access = ORDER_CHANGE
    unhandled_read_methods = frozenset({"GET"})


class ProductionOrderFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=ProductionOrder.Status.choices)
    date_from = django_filters.DateFilter(field_name="planned_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="planned_date", lookup_expr="lte")

    class Meta:
        model = ProductionOrder
        fields = ["product", "equipment", "priority"]


class ProductionOrderViewSet(
    ProductionAccessMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Üretim emirleri. Durum yalnızca eylem uç noktalarıyla değişir (PATCH ile değişmez)."""

    filterset_class = ProductionOrderFilter
    search_fields = ["number", "product__code", "product__name", "notes"]
    ordering_fields = ["planned_date", "number", "priority", "created_at"]
    ordering = ["-planned_date", "-id"]
    action_access = {
        "create": ORDER_CHANGE,
        "update": ORDER_CHANGE,
        "partial_update": ORDER_CHANGE,
        "complete": ORDER_CHANGE,
        "approve": ORDER_APPROVE,
        # Uç nokta emrin durumunu bilmeden denetler; servis taslakta Değiştirir, onaylı ya da
        # hazırlıktaki emirde Onaylar ister.
        "cancel": ORDER_CHANGE | ORDER_APPROVE,
        "start_prep": PREP_CHANGE,
        "mark_ready": PREP_CHANGE,
        # GET hazırlanan lotları okur, POST okutur; HEAD bugünkü gibi okutma yetkisiyle.
        "picks:get": RECORD_READ,
        "picks": PREP_CHANGE,
    }

    def get_queryset(self) -> QuerySet[ProductionOrder]:
        return ProductionOrder.objects.select_related(
            "product__base_unit",
            "recipe_version__recipe",
            "unit",
            "equipment",
            "production_location",
            "created_by",
            "approved_by",
            "rework_lot",
        ).prefetch_related("rework_additions__material", "rework_additions__unit")

    def get_serializer_class(self) -> type[s.ProductionOrderSerializer]:
        if self.action == "list":
            return s.ProductionOrderSerializer
        return s.ProductionOrderDetailSerializer

    def _respond(self, order: ProductionOrder, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=order.pk)
        return Response(s.ProductionOrderDetailSerializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = s.ProductionOrderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.create_order(_user(request), body.validated_data)
        return self._respond(order, status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        order = self.get_object()
        body = s.ProductionOrderSerializer(order, data=request.data, partial=partial)
        body.is_valid(raise_exception=True)
        return self._respond(services.update_order(_user(request), order, body.validated_data))

    @extend_schema(request=s.NoteSerializer, responses=s.ProductionOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Emri onaylar; reçete ölçeklenir, ihtiyaç listesi oluşur (Üretim emirleri: Onaylar)."""
        body = s.NoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.approve_order(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._respond(order)

    @extend_schema(request=None, responses=s.ProductionOrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="start-prep")
    def start_prep(self, request: Request, pk: str | None = None) -> Response:
        """Malzeme hazırlığını başlatır (Malzeme hazırlama: Değiştirir)."""
        return self._respond(services.start_material_prep(_user(request), self.get_object()))

    @extend_schema(request=None, responses=s.ProductionOrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="mark-ready")
    def mark_ready(self, request: Request, pk: str | None = None) -> Response:
        """Malzeme hazır (Malzeme hazırlama: Değiştirir); her ihtiyaç toleransın alt sınırına
        kadar hazırlanmış olmalı."""
        return self._respond(services.mark_material_ready(_user(request), self.get_object()))

    @extend_schema(request=CancelSerializer, responses=s.ProductionOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Emri iptal eder (taslak: Değiştirir, onaylı ya da hazırlıktaki emir: Onaylar);
        hazırlanan malzeme geri transfer edilir."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.cancel_order(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(order)

    @extend_schema(request=None, responses=s.ProductionOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        """Emri elle tamamlar (Üretim emirleri: Değiştirir). Son çıktı lotu serbest bırakılınca
        kendiliğinden olur."""
        return self._respond(services.complete_order(_user(request), self.get_object()))

    @extend_schema(methods=["GET"], request=None, responses=s.MaterialPickSerializer(many=True))
    @extend_schema(
        methods=["POST"], request=s.PickCreateSerializer, responses=s.MaterialPickSerializer
    )
    @action(detail=True, methods=["get", "post"], pagination_class=None, filter_backends=[])
    def picks(self, request: Request, pk: str | None = None) -> Response:
        """Hazırlanan lotlar (GET) / lot okutarak hazırla (POST, Malzeme hazırlama: Değiştirir)."""
        order = self.get_object()
        if request.method == "GET":
            rows = order.picks.select_related(
                "requirement__material__base_unit", "lot", "from_location", "to_location"
            ).order_by("picked_at", "id")
            return Response(s.MaterialPickSerializer(rows, many=True).data)
        body = s.PickCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        requirement = _requirement(order.pk, data["requirement"])
        pick = services.pick_material(
            _user(request),
            order,
            requirement,
            resolve_lot(requirement, data),
            data["quantity"],
            from_location=data.get("from_location"),
            note=data["note"],
        )
        return Response(s.MaterialPickSerializer(pick).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("requirement", int, required=True)],
        responses=StockBalanceSerializer(many=True),
        filters=False,
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="pick-suggestions",
        pagination_class=None,
        filter_backends=[],
    )
    def pick_suggestions(self, request: Request, pk: str | None = None) -> Response:
        """Hazırlama önerisi: serbest, SKT'si geçmemiş lotlar FEFO sırasıyla."""
        order = self.get_object()
        value = request.query_params.get("requirement", "")
        if not value.isdigit():
            raise ValidationError({"requirement": ["İhtiyaç satırı seçilmelidir."]})
        requirement = _requirement(order.pk, int(value))
        rows = selectors.pick_suggestions(order, requirement)[:20]
        return Response(StockBalanceSerializer(rows, many=True).data)


class ProductionBatchFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=ProductionBatch.Status.choices)

    class Meta:
        model = ProductionBatch
        fields = ["order", "equipment"]


class ProductionBatchViewSet(
    ProductionAccessMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Şarjlar. Oluşturma şarjı başlatır; tartım `consume`, bitiş `finish` (Şarj ve tartım).
    Karşılanmayan metot, bugünkü gibi bütün üretim görünümlerinde emir yazma yetkisi ister."""

    filterset_class = ProductionBatchFilter
    search_fields = ["batch_no", "order__number", "order__product__code"]
    ordering_fields = ["started_at", "batch_no"]
    ordering = ["-started_at", "-id"]
    action_access = {name: BATCH_CHANGE for name in ("create", "consume", "finish", "cancel")}

    def get_queryset(self) -> QuerySet[ProductionBatch]:
        return ProductionBatch.objects.select_related(
            "order__product__base_unit",
            "order__production_location",
            "equipment",
            "output_lot",
            "started_by",
            "finished_by",
        )

    def get_serializer_class(self) -> type[s.ProductionBatchSerializer]:
        if self.action == "list":
            return s.ProductionBatchSerializer
        return s.ProductionBatchDetailSerializer

    def _respond(self, batch: ProductionBatch, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=batch.pk)
        return Response(s.ProductionBatchDetailSerializer(fresh).data, status=code)

    @extend_schema(request=s.BatchStartSerializer, responses=s.ProductionBatchDetailSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Şarjı başlatır; çıktı lotu karantinada açılır."""
        body = s.BatchStartSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        batch = services.start_batch(
            _user(request),
            data["order"],
            data.get("equipment"),
            data.get("planned_quantity"),
        )
        return self._respond(batch, status.HTTP_201_CREATED)

    @extend_schema(request=s.ConsumeSerializer, responses=s.ProductionBatchDetailSerializer)
    @action(detail=True, methods=["post"])
    def consume(self, request: Request, pk: str | None = None) -> Response:
        """Tartım kaydı: lot okut, gerçek miktar (tolerans dışıysa not zorunlu)."""
        batch = self.get_object()
        body = s.ConsumeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        requirement = _requirement(batch.order_id, data["requirement"])
        services.record_consumption(
            _user(request),
            batch,
            requirement,
            resolve_lot(requirement, data),
            data["quantity"],
            data["note"],
            scale=data.get("scale"),
        )
        return self._respond(batch)

    @extend_schema(request=s.BatchFinishSerializer, responses=s.ProductionBatchDetailSerializer)
    @action(detail=True, methods=["post"])
    def finish(self, request: Request, pk: str | None = None) -> Response:
        """Şarjı bitirir: çıktı miktarı tank lokasyonuna girer, lot analiz bekler."""
        body = s.BatchFinishSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        batch = services.finish_batch(
            _user(request),
            self.get_object(),
            body.validated_data["output_quantity"],
            body.validated_data["note"],
        )
        return self._respond(batch)

    @extend_schema(request=CancelSerializer, responses=s.ProductionBatchDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Tartım yapılmamış şarjı iptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        batch = services.cancel_batch(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(batch)
