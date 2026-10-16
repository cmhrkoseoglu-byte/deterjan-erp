from datetime import date, timedelta
from typing import Any

import django_filters
from django.db.models import Q, QuerySet
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
from apps.core.roles import ALL_ROLES
from apps.inventory.api.serializers import CancelSerializer
from apps.maintenance import selectors, services
from apps.maintenance.api import serializers as s
from apps.maintenance.models import (
    ChangeoverRule,
    Downtime,
    MaintenanceKind,
    MaintenancePlan,
    MaintenanceWorkOrder,
)
from apps.masterdata.models import Equipment, Material


def _user(request: Request) -> Any:
    return request.user


def _date_param(request: Request, name: str) -> date | None:
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: ["Geçerli bir tarih girin (YYYY-AA-GG)."]}) from exc


def _object_param(request: Request, name: str, model: Any, *, required: bool = False) -> Any:
    value = request.query_params.get(name)
    if not value:
        if required:
            raise ValidationError({name: ["Bu alan zorunlu."]})
        return None
    if not value.isdigit():
        raise ValidationError({name: ["Geçerli bir kimlik girin."]})
    obj = model.objects.filter(pk=value).first()
    if obj is None:
        raise ValidationError({name: ["Kayıt bulunamadı."]})
    return obj


# --- plan --------------------------------------------------------------------------------------


class PlanFilter(django_filters.FilterSet):
    kind = django_filters.ChoiceFilter(choices=MaintenanceKind.choices)

    class Meta:
        model = MaintenancePlan
        fields = ["equipment", "is_active", "responsible_role"]


class MaintenancePlanViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Bakım planları. Okuma bakımla ilgili birimlere, yazma üretim, dolum, laboratuvar ve
    yönetime. Planlar silinmez, pasife alınır."""

    serializer_class = s.MaintenancePlanSerializer
    filterset_class = PlanFilter
    search_fields = ["title", "equipment__code", "equipment__name"]
    ordering_fields = ["next_due_date", "equipment__code", "title"]
    ordering = ["equipment__code", "kind", "id"]

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [HasRole(*services.READ_ROLES)()]
        return [HasRole(*services.PLAN_ROLES)()]

    def get_queryset(self) -> QuerySet[MaintenancePlan]:
        return MaintenancePlan.objects.select_related("equipment")

    def _respond(self, plan: MaintenancePlan, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=plan.pk)
        return Response(self.get_serializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Bakım planı açar."""
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            services.create_plan(_user(request), body.validated_data), status.HTTP_201_CREATED
        )

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Planı günceller."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        body = self.get_serializer(instance, data=request.data, partial=partial)
        body.is_valid(raise_exception=True)
        return self._respond(services.update_plan(_user(request), instance, body.validated_data))

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """Planı aktif yapar."""
        return self._respond(services.set_plan_active(_user(request), self.get_object(), True))

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """Planı pasife alır."""
        return self._respond(services.set_plan_active(_user(request), self.get_object(), False))


# --- iş emri -----------------------------------------------------------------------------------


class WorkOrderFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=MaintenanceWorkOrder.Status.choices)
    kind = django_filters.ChoiceFilter(choices=MaintenanceKind.choices)
    source = django_filters.ChoiceFilter(choices=MaintenanceWorkOrder.Source.choices)
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = MaintenanceWorkOrder
        fields = ["equipment", "plan", "responsible_role"]


class WorkOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Bakım iş emirleri (`BK-`). Okuma bakımla ilgili birimlere; iş emrini sorumlu birim ya da
    yönetim yürütür (servis denetler)."""

    serializer_class = s.WorkOrderSerializer
    filterset_class = WorkOrderFilter
    search_fields = ["number", "title", "equipment__code", "equipment__name", "description"]
    ordering_fields = ["created_at", "due_date", "number", "completed_at"]
    ordering = ["-created_at", "-id"]

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [HasRole(*services.READ_ROLES)()]
        if self.action == "create":
            return [HasRole(*services.PLAN_ROLES)()]
        return [HasRole(*services.READ_ROLES)()]

    def get_queryset(self) -> QuerySet[MaintenanceWorkOrder]:
        return MaintenanceWorkOrder.objects.select_related(
            "equipment",
            "plan",
            "previous_product",
            "created_by",
            "started_by",
            "completed_by",
        ).prefetch_related("parts__material", "parts__lot", "parts__location", "downtimes")

    def _respond(self, order: MaintenanceWorkOrder, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=order.pk)
        return Response(s.WorkOrderSerializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Elle iş emri açar."""
        body = s.WorkOrderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = {k: v for k, v in body.validated_data.items() if k in services.WORK_ORDER_FIELDS}
        return self._respond(
            services.create_work_order(_user(request), data), status.HTTP_201_CREATED
        )

    @extend_schema(request=None, responses=s.WorkOrderSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request: Request, pk: str | None = None) -> Response:
        """İşe başlar."""
        return self._respond(services.start_work_order(_user(request), self.get_object()))

    @extend_schema(request=s.CompleteSerializer, responses=s.WorkOrderSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        """İş emrini tamamlar (yapılan iş zorunlu, kontrol listesi tam)."""
        body = s.CompleteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        order = services.complete_work_order(
            _user(request),
            self.get_object(),
            work_done=data["work_done"],
            duration_minutes=data.get("duration_minutes"),
            checklist=data.get("checklist"),
            calibration_result=data.get("calibration_result", ""),
            certificate_no=data["certificate_no"],
        )
        return self._respond(order)

    @extend_schema(request=CancelSerializer, responses=s.WorkOrderSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """İş emrini iptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            services.cancel_work_order(
                _user(request), self.get_object(), body.validated_data["reason"]
            )
        )

    @extend_schema(request=s.PartCreateSerializer, responses=s.WorkOrderSerializer)
    @action(detail=True, methods=["post"])
    def parts(self, request: Request, pk: str | None = None) -> Response:
        """Yedek parça ekler; stoklu parça lottan düşülür."""
        body = s.PartCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        services.add_part(
            _user(request),
            self.get_object(),
            quantity=data["quantity"],
            material=data.get("material"),
            lot=data.get("lot"),
            location=data.get("location"),
            description=data["description"],
            unit_text=data["unit_text"],
        )
        return self._respond(self.get_object())


class BreakdownView(APIView):
    """Arıza bildirimi (her rol): onarım iş emri açar, istenirse duruşu başlatır."""

    permission_classes = [HasRole(*ALL_ROLES)]

    @extend_schema(request=s.BreakdownSerializer, responses={201: s.WorkOrderSerializer})
    def post(self, request: Request) -> Response:
        body = s.BreakdownSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        order = services.report_breakdown(
            _user(request),
            data["equipment"],
            data["description"],
            stop_equipment=data["stop_equipment"],
        )
        return Response(s.WorkOrderSerializer(order).data, status=status.HTTP_201_CREATED)


class CleaningView(APIView):
    """Tank temizliği kaydı (üretim): ürün değişimi temizliği kuralını karşılar."""

    permission_classes = [HasRole(*services.READ_ROLES)]

    @extend_schema(request=s.CleaningSerializer, responses={201: s.WorkOrderSerializer})
    def post(self, request: Request) -> Response:
        body = s.CleaningSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        order = services.record_cleaning(
            _user(request),
            data["equipment"],
            work_done=data["work_done"],
            checklist=data["checklist"],
            duration_minutes=data.get("duration_minutes"),
        )
        return Response(s.WorkOrderSerializer(order).data, status=status.HTTP_201_CREATED)


class CleaningCheckView(APIView):
    """Şarj başlatma ekranı için: bu ürüne geçmeden tank temizliği gerekiyor mu, tank duruşta mı."""

    permission_classes = [HasRole(*services.READ_ROLES)]

    @extend_schema(
        parameters=[
            OpenApiParameter("equipment", int, required=True),
            OpenApiParameter("product", int, required=True),
        ],
        responses=s.CleaningCheckSerializer,
    )
    def get(self, request: Request) -> Response:
        equipment = _object_param(request, "equipment", Equipment, required=True)
        product = _object_param(request, "product", Material, required=True)
        previous = selectors.cleaning_needed(equipment, product) if equipment.is_tank else None
        downtime = selectors.open_downtime(equipment)
        data = {
            "required": previous is not None,
            "previous_product_code": previous.code if previous else None,
            "previous_product_name": previous.name if previous else None,
            "is_down": downtime is not None,
            "downtime_reason": downtime.get_reason_display() if downtime else None,
        }
        return Response(s.CleaningCheckSerializer(data).data)


# --- duruş -------------------------------------------------------------------------------------


class DowntimeFilter(django_filters.FilterSet):
    reason = django_filters.ChoiceFilter(choices=Downtime.Reason.choices)
    is_open = django_filters.BooleanFilter(field_name="ended_at", lookup_expr="isnull")
    date_from = django_filters.DateFilter(method="filter_from")
    date_to = django_filters.DateFilter(method="filter_to")

    class Meta:
        model = Downtime
        fields = ["equipment", "work_order"]

    def filter_from(self, queryset: QuerySet[Downtime], name: str, value: date) -> Any:
        return queryset.filter(Q(ended_at__isnull=True) | Q(ended_at__date__gte=value))

    def filter_to(self, queryset: QuerySet[Downtime], name: str, value: date) -> Any:
        return queryset.filter(started_at__date__lte=value)


class DowntimeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Ekipman duruşları. Açık duruştaki ekipman emre atanamaz ve çalıştırılamaz."""

    serializer_class = s.DowntimeSerializer
    filterset_class = DowntimeFilter
    search_fields = ["equipment__code", "equipment__name", "note"]
    ordering_fields = ["started_at", "ended_at"]
    ordering = ["-started_at", "-id"]

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [HasRole(*ALL_ROLES)()]
        return [HasRole(*services.DOWNTIME_ROLES)()]

    def get_queryset(self) -> QuerySet[Downtime]:
        return Downtime.objects.select_related("equipment", "work_order", "created_by", "ended_by")

    def _respond(self, downtime: Downtime, code: int = status.HTTP_200_OK) -> Response:
        return Response(
            s.DowntimeSerializer(self.get_queryset().get(pk=downtime.pk)).data, status=code
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Duruş başlatır."""
        body = s.DowntimeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        downtime = services.start_downtime(
            _user(request),
            data["equipment"],
            data["reason"],
            started_at=data.get("started_at"),
            note=data["note"],
        )
        return self._respond(downtime, status.HTTP_201_CREATED)

    @extend_schema(request=s.EndDowntimeSerializer, responses=s.DowntimeSerializer)
    @action(detail=True, methods=["post"])
    def end(self, request: Request, pk: str | None = None) -> Response:
        """Açık duruşu bitirir."""
        body = s.EndDowntimeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        downtime = services.end_downtime(
            _user(request), self.get_object(), ended_at=data.get("ended_at"), note=data["note"]
        )
        return self._respond(downtime)


class DowntimeSummaryView(APIView):
    """Duruş özeti: ekipman ve nedene göre dakika (varsayılan son 30 gün)."""

    permission_classes = [HasRole(*services.READ_ROLES)]

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", date),
            OpenApiParameter("date_to", date),
            OpenApiParameter("equipment", int),
        ],
        responses=s.DowntimeSummarySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        date_to = _date_param(request, "date_to") or timezone.localdate()
        date_from = _date_param(request, "date_from") or date_to - timedelta(days=30)
        if date_from > date_to:
            raise ValidationError({"date_from": ["Başlangıç bitişten sonra olamaz."]})
        equipment = _object_param(request, "equipment", Equipment)
        rows = selectors.downtime_summary(date_from, date_to, equipment)
        return Response(s.DowntimeSummarySerializer(rows, many=True).data)


# --- kalibrasyon, geçiş kuralları, ayarlar -------------------------------------------------------


class CalibrationStatusView(APIView):
    """Terazilerin kalibrasyon durumu (tartım ekranı uyarısı)."""

    permission_classes = [HasRole(*services.READ_ROLES)]

    @extend_schema(responses=s.CalibrationStatusSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(
            s.CalibrationStatusSerializer(selectors.calibration_status(), many=True).data
        )


class ChangeoverRuleViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Temizliksiz ürün geçişleri (Karar D-14). Yazma laboratuvara."""

    serializer_class = s.ChangeoverRuleSerializer
    filterset_fields = ["is_active", "from_product", "to_product"]
    search_fields = ["from_product__code", "to_product__code", "note"]
    ordering = ["from_product__code", "to_product__code"]

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [HasRole(*services.READ_ROLES)()]
        return [HasRole(*services.CHANGEOVER_ROLES)()]

    def get_queryset(self) -> QuerySet[ChangeoverRule]:
        return ChangeoverRule.objects.select_related("from_product", "to_product")

    def _respond(self, rule: ChangeoverRule, code: int = status.HTTP_200_OK) -> Response:
        return Response(
            s.ChangeoverRuleSerializer(self.get_queryset().get(pk=rule.pk)).data, status=code
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Geçiş kuralı tanımlar."""
        body = s.ChangeoverRuleSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            services.create_changeover_rule(_user(request), body.validated_data),
            status.HTTP_201_CREATED,
        )

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """Kuralı aktif yapar."""
        return self._respond(
            services.set_changeover_active(_user(request), self.get_object(), True)
        )

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """Kuralı pasife alır."""
        return self._respond(
            services.set_changeover_active(_user(request), self.get_object(), False)
        )


class MaintenanceSettingsView(APIView):
    """Kalibrasyon uyarı süresi ve iş emri açma süresi. Okuma bakım birimlerine, değiştirme
    yönetime."""

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET":
            return [HasRole(*services.READ_ROLES)()]
        return [HasRole(*services.SETTINGS_ROLES)()]

    @extend_schema(responses=s.MaintenanceSettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.MaintenanceSettingsSerializer(selectors.get_settings()).data)

    @extend_schema(
        request=s.MaintenanceSettingsSerializer, responses=s.MaintenanceSettingsSerializer
    )
    def patch(self, request: Request) -> Response:
        body = s.MaintenanceSettingsSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        instance = services.update_settings(_user(request), body.validated_data)
        return Response(s.MaintenanceSettingsSerializer(instance).data)
