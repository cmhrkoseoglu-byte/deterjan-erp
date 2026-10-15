from collections.abc import Iterable
from typing import Any, ClassVar

import django_filters
from django.db.models import Prefetch, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.exceptions import BusinessRuleError
from apps.core.permissions import HasRole
from apps.core.roles import DEPO, DOLUM, PLANLAMA
from apps.filling import selectors, services
from apps.filling.api import serializers as s
from apps.filling.models import (
    FillingOrder,
    FillingRequirement,
    FillingRun,
    PackagingSpec,
    PackagingSpecLine,
    ScrapRecord,
)
from apps.inventory.api.serializers import CancelSerializer, StockBalanceSerializer
from apps.inventory.models import Lot

READ_ACTIONS = frozenset({"list", "retrieve", "metadata", "pick_suggestions", "report"})


def _user(request: Request) -> Any:
    return request.user


def resolve_lot(material_ids: Iterable[int], data: dict[str, Any], what: str) -> Lot:
    """Okutulan lot numarasını (ya da lot kimliğini) verilen malzemelerdeki lota çevirir. Lot
    başka bir malzemedense servis "yanlış malzeme" hatası versin diye o lot döner."""
    if data.get("lot"):
        lot = Lot.objects.select_related("material").filter(pk=data["lot"]).first()
    else:
        lot_no = data["lot_no"].strip().upper()
        if lot_no.startswith("LOT:"):  # lot etiketi içeriği (Adım 2.3)
            lot_no = lot_no[4:]
        lots = Lot.objects.select_related("material").filter(lot_no=lot_no)
        lot = lots.filter(material_id__in=list(material_ids)).first() or lots.first()
    if lot is None:
        label = data.get("lot_no") or data.get("lot")
        raise BusinessRuleError("lot_not_found", f"{what} için {label} lotu bulunamadı.")
    return lot


class RolePermissionMixin:
    """Okuma giriş yapmış herkese; her yazma eylemi kendi rolüne açık (admin her yere)."""

    action_roles: ClassVar[dict[str, tuple[str, ...]]] = {}
    default_roles: ClassVar[tuple[str, ...]] = (PLANLAMA,)

    def get_permissions(self) -> list[BasePermission]:
        name = getattr(self, "action", None) or ""
        request = getattr(self, "request", None)
        if name in READ_ACTIONS or (request is not None and request.method == "GET"):
            return [IsAuthenticated()]
        return [HasRole(*self.action_roles.get(name, self.default_roles))()]


# --- ambalaj reçetesi ------------------------------------------------------------------------


def _spec_queryset() -> QuerySet[PackagingSpec]:
    return PackagingSpec.objects.select_related(
        "finished_product",
        "bulk_product__base_unit",
        "fill_unit",
        "copied_from",
        "approved_by",
        "created_by",
    ).prefetch_related(
        Prefetch("lines", queryset=PackagingSpecLine.objects.select_related("material__base_unit"))
    )


class PackagingSpecFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=PackagingSpec.Status.choices)

    class Meta:
        model = PackagingSpec
        fields = ["finished_product", "bulk_product"]


class PackagingSpecViewSet(
    RolePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Sürümlü ambalaj reçeteleri (planlama yazar). Durum yalnızca `approve` ile değişir; taslak
    dışındaki sürüm değiştirilmez (`copy` ile yeni taslak açılır)."""

    filterset_class = PackagingSpecFilter
    search_fields = ["finished_product__code", "finished_product__name", "change_note"]
    ordering_fields = ["version_no", "created_at", "approved_at"]
    ordering = ["finished_product__code", "-version_no"]

    def get_queryset(self) -> QuerySet[PackagingSpec]:
        return _spec_queryset()

    def get_serializer_class(self) -> type[s.PackagingSpecSerializer]:
        if self.action == "list":
            return s.PackagingSpecSerializer
        return s.PackagingSpecDetailSerializer

    def _detail(self, spec: PackagingSpec, code: int = status.HTTP_200_OK) -> Response:
        fresh = _spec_queryset().get(pk=spec.pk)
        return Response(s.PackagingSpecDetailSerializer(fresh).data, status=code)

    @extend_schema(
        request=s.PackagingSpecCreateSerializer, responses={201: s.PackagingSpecDetailSerializer}
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Mamul için yeni taslak sürüm (satırlarıyla)."""
        body = s.PackagingSpecCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        spec = services.create_spec(_user(request), dict(body.validated_data))
        return self._detail(spec, status.HTTP_201_CREATED)

    @extend_schema(request=s.PackagingSpecSerializer, responses=s.PackagingSpecDetailSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Taslak sürümü günceller."""
        partial = kwargs.pop("partial", False)
        spec = self.get_object()
        body = s.PackagingSpecSerializer(spec, data=request.data, partial=partial)
        body.is_valid(raise_exception=True)
        return self._detail(services.update_spec(_user(request), spec, body.validated_data))

    @extend_schema(
        request=s.FillingNoteSerializer, responses={201: s.PackagingSpecDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def copy(self, request: Request, pk: str | None = None) -> Response:
        """Sürümü yeni taslak sürüme kopyalar (gövde: `note` = değişiklik notu)."""
        body = s.FillingNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        spec = services.copy_spec(_user(request), self.get_object(), body.validated_data["note"])
        return self._detail(spec, status.HTTP_201_CREATED)

    @extend_schema(request=s.FillingNoteSerializer, responses=s.PackagingSpecDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sürümü onaylar; mamulün önceki onaylı sürümü eski sürüm olur."""
        body = s.FillingNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        spec = services.approve_spec(_user(request), self.get_object(), body.validated_data["note"])
        return self._detail(spec)

    @extend_schema(
        request=s.PackagingSpecLineSerializer, responses={201: s.PackagingSpecLineSerializer}
    )
    @action(detail=True, methods=["post"])
    def lines(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sürüme ambalaj satırı ekler."""
        body = s.PackagingSpecLineSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        line = services.add_spec_line(_user(request), self.get_object(), body.validated_data)
        return Response(s.PackagingSpecLineSerializer(line).data, status=status.HTTP_201_CREATED)


class PackagingSpecLineViewSet(
    RolePermissionMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Taslak sürüm satırı: güncelle ve kaldır (onaylı sürümde 400 `packaging_spec_locked`)."""

    queryset = PackagingSpecLine.objects.select_related("material__base_unit", "spec")
    serializer_class = s.PackagingSpecLineSerializer

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_spec_line(
            self.request.user,  # type: ignore[arg-type]
            serializer.instance,
            serializer.validated_data,
        )

    def perform_destroy(self, instance: PackagingSpecLine) -> None:
        services.remove_spec_line(self.request.user, instance)  # type: ignore[arg-type]


# --- dolum emri ------------------------------------------------------------------------------


def _requirement(order_id: int, requirement_id: int) -> FillingRequirement:
    requirement = (
        FillingRequirement.objects.select_related("material", "spec_line", "order")
        .filter(order_id=order_id, pk=requirement_id)
        .first()
    )
    if requirement is None:
        raise ValidationError({"requirement": ["İhtiyaç satırı bu emre ait değil."]})
    return requirement


class FillingOrderFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=FillingOrder.Status.choices)
    date_from = django_filters.DateFilter(field_name="planned_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="planned_date", lookup_expr="lte")

    class Meta:
        model = FillingOrder
        fields = ["finished_product", "filling_line"]


class FillingOrderViewSet(
    RolePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Dolum emirleri. Durum yalnızca eylem uç noktalarıyla değişir (PATCH ile değişmez)."""

    filterset_class = FillingOrderFilter
    search_fields = ["number", "finished_product__code", "finished_product__name", "notes"]
    ordering_fields = ["planned_date", "number", "created_at"]
    ordering = ["-planned_date", "-id"]
    action_roles = {
        "create": (PLANLAMA,),
        "update": (PLANLAMA,),
        "partial_update": (PLANLAMA,),
        "approve": (PLANLAMA,),
        "cancel": (PLANLAMA,),
        "start_prep": (DEPO,),
        "mark_ready": (DEPO,),
        "picks": (DEPO,),
        "finish": (DOLUM,),
    }

    def get_queryset(self) -> QuerySet[FillingOrder]:
        return FillingOrder.objects.select_related(
            "finished_product__base_unit",
            "packaging_spec__bulk_product__base_unit",
            "packaging_spec__fill_unit",
            "filling_line__location",
            "output_location",
            "created_by",
            "approved_by",
        )

    def get_serializer_class(self) -> type[s.FillingOrderSerializer]:
        if self.action == "list":
            return s.FillingOrderSerializer
        return s.FillingOrderDetailSerializer

    def _respond(self, order: FillingOrder, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=order.pk)
        return Response(s.FillingOrderDetailSerializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = s.FillingOrderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.create_order(_user(request), body.validated_data)
        return self._respond(order, status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        order = self.get_object()
        body = s.FillingOrderSerializer(order, data=request.data, partial=partial)
        body.is_valid(raise_exception=True)
        return self._respond(services.update_order(_user(request), order, body.validated_data))

    @extend_schema(request=s.FillingNoteSerializer, responses=s.FillingOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Emri onaylar; ambalaj ihtiyacı hesaplanır (planlama)."""
        body = s.FillingNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.approve_order(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._respond(order)

    @extend_schema(request=None, responses=s.FillingOrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="start-prep")
    def start_prep(self, request: Request, pk: str | None = None) -> Response:
        """Ambalaj hazırlığını başlatır (depo)."""
        return self._respond(services.start_material_prep(_user(request), self.get_object()))

    @extend_schema(request=None, responses=s.FillingOrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="mark-ready")
    def mark_ready(self, request: Request, pk: str | None = None) -> Response:
        """Ambalaj hazır (depo); her satır fire payı hariç ihtiyaç kadar hazırlanmış olmalı."""
        return self._respond(services.mark_material_ready(_user(request), self.get_object()))

    @extend_schema(request=CancelSerializer, responses=s.FillingOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Emri iptal eder (planlama); hazırlanan ambalaj geri transfer edilir."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.cancel_order(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(order)

    @extend_schema(request=s.FillingNoteSerializer, responses=s.FillingOrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def finish(self, request: Request, pk: str | None = None) -> Response:
        """Dolumu bitirir (dolum): emir analiz bekler; lotlar serbest kalınca tamamlanır."""
        body = s.FillingNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        order = services.finish_filling(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._respond(order)

    @extend_schema(methods=["GET"], request=None, responses=s.PackagingPickSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=s.PackagingPickCreateSerializer,
        responses=s.PackagingPickSerializer,
    )
    @action(detail=True, methods=["get", "post"], pagination_class=None, filter_backends=[])
    def picks(self, request: Request, pk: str | None = None) -> Response:
        """Hazırlanan ambalaj lotları (GET) / lot okutarak hazırla (POST, depo)."""
        order = self.get_object()
        if request.method == "GET":
            rows = order.picks.select_related(
                "requirement__material__base_unit", "lot", "from_location", "to_location"
            ).order_by("picked_at", "id")
            return Response(s.PackagingPickSerializer(rows, many=True).data)
        body = s.PackagingPickCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        requirement = _requirement(order.pk, data["requirement"])
        pick = services.pick_packaging(
            _user(request),
            order,
            requirement,
            resolve_lot([requirement.material_id], data, requirement.material.code),
            data["quantity"],
            from_location=data.get("from_location"),
            note=data["note"],
        )
        return Response(s.PackagingPickSerializer(pick).data, status=status.HTTP_201_CREATED)

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

    @extend_schema(responses=s.ConsumptionReportSerializer, filters=False)
    @action(detail=True, methods=["get"], pagination_class=None, filter_backends=[])
    def report(self, request: Request, pk: str | None = None) -> Response:
        """Dolum raporu: tamamlanan partilerin teorik / gerçek bulk ve ambalaj tüketimi."""
        order = self.get_object()
        report = selectors.consumption_report(order)
        return Response(s.ConsumptionReportSerializer(report, context={"order": order}).data)


# --- dolum partisi ---------------------------------------------------------------------------


class FillingRunFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=FillingRun.Status.choices)

    class Meta:
        model = FillingRun
        fields = ["order"]


class FillingRunViewSet(
    RolePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Dolum partileri (dolum hattı tableti). Oluşturma partiyi başlatır; bulk tüketimi
    `consume-bulk`, ambalaj lotu okutma `scan`, fire `scrap`, bitiş `finish`."""

    filterset_class = FillingRunFilter
    search_fields = ["output_lot__lot_no", "order__number", "order__finished_product__code"]
    ordering_fields = ["started_at", "sequence"]
    ordering = ["-started_at", "-id"]
    default_roles = (DOLUM,)

    def get_queryset(self) -> QuerySet[FillingRun]:
        return FillingRun.objects.select_related(
            "order__finished_product__base_unit",
            "order__packaging_spec__bulk_product__base_unit",
            "order__packaging_spec__fill_unit",
            "order__filling_line__location",
            "output_lot",
            "operator",
            "finished_by",
        )

    def get_serializer_class(self) -> type[s.FillingRunSerializer]:
        if self.action == "list":
            return s.FillingRunSerializer
        return s.FillingRunDetailSerializer

    def _respond(self, run: FillingRun, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=run.pk)
        return Response(s.FillingRunDetailSerializer(fresh).data, status=code)

    @extend_schema(request=s.RunStartSerializer, responses={201: s.FillingRunDetailSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Partiyi başlatır; dolum lotu karantinada açılır."""
        body = s.RunStartSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = services.start_run(_user(request), body.validated_data["order"])
        return self._respond(run, status.HTTP_201_CREATED)

    @extend_schema(request=s.BulkConsumeSerializer, responses=s.FillingRunDetailSerializer)
    @action(detail=True, methods=["post"], url_path="consume-bulk")
    def consume_bulk(self, request: Request, pk: str | None = None) -> Response:
        """Bulk tüketimi: tank lotunu okut, tüketilen miktar (bulkun temel biriminde)."""
        run = self.get_object()
        body = s.BulkConsumeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        bulk = run.order.packaging_spec.bulk_product
        lot = resolve_lot([bulk.pk], data, bulk.code)
        services.consume_bulk(_user(request), run, lot, data["quantity"])
        return self._respond(run)

    @extend_schema(request=s.LotRefSerializer, responses=s.FillingRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def scan(self, request: Request, pk: str | None = None) -> Response:
        """Ambalaj lotu okutur; yanlış malzemenin lotu 400 `lot_material_mismatch`."""
        run = self.get_object()
        body = s.LotRefSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        materials = run.order.packaging_spec.lines.values_list("material_id", flat=True)
        lot = resolve_lot(list(materials), body.validated_data, "Ambalaj")
        services.scan_packaging_lot(_user(request), run, lot)
        return self._respond(run)

    @extend_schema(request=s.ScrapCreateSerializer, responses=s.FillingRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def scrap(self, request: Request, pk: str | None = None) -> Response:
        """Fire kaydı: bulk, ambalaj ya da mamul (adet)."""
        run = self.get_object()
        body = s.ScrapCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        lot = None
        if data["kind"] != ScrapRecord.Kind.FINISHED:
            spec = run.order.packaging_spec
            materials = (
                [spec.bulk_product_id]
                if data["kind"] == ScrapRecord.Kind.BULK
                else list(spec.lines.values_list("material_id", flat=True))
            )
            lot = resolve_lot(materials, data, "Fire")
        services.record_scrap(
            _user(request),
            run,
            kind=data["kind"],
            quantity=data["quantity"],
            reason_code=data["reason_code"],
            lot=lot,
            note=data["note"],
        )
        return self._respond(run)

    @extend_schema(request=s.RunFinishSerializer, responses=s.FillingRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def finish(self, request: Request, pk: str | None = None) -> Response:
        """Partiyi bitirir: ambalaj tüketimi düşülür, mamul depoya girer, numune açılır."""
        body = s.RunFinishSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = services.finish_run(
            _user(request),
            self.get_object(),
            body.validated_data["good_units"],
            body.validated_data["note"],
        )
        return self._respond(run)

    @extend_schema(request=CancelSerializer, responses=s.FillingRunDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Kaydı olmayan partiyi iptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = services.cancel_run(_user(request), self.get_object(), body.validated_data["reason"])
        return self._respond(run)

    @extend_schema(responses=s.ConsumptionReportSerializer, filters=False)
    @action(detail=True, methods=["get"], pagination_class=None, filter_backends=[])
    def report(self, request: Request, pk: str | None = None) -> Response:
        """Partinin teorik / gerçek tüketimi."""
        run = self.get_object()
        report = selectors.consumption_report(run.order, run)
        return Response(s.ConsumptionReportSerializer(report, context={"order": run.order}).data)
