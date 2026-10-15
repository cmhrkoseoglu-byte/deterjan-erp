from typing import Any, ClassVar

import django_filters
from django.db.models import Count, Prefetch, QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import HasRole
from apps.core.roles import LABORATUVAR, YONETIM
from apps.masterdata.api.views import MasterDataViewSet
from apps.quality import coa, selectors, services
from apps.quality.api import serializers as s
from apps.quality.models import (
    QualityDecision,
    Sample,
    SampleStage,
    Specification,
    SpecificationLine,
    TestDefinition,
)

# Kalite verisini yazan rol laboratuvardır; şartlı kabulü yönetim onaylar. Okuma herkese açık.
# Admin her yere erişir (Faz 0 kararı).
LAB_ROLES = (LABORATUVAR,)
APPROVAL_ROLES = (YONETIM,)
READ_ACTIONS = frozenset({"list", "retrieve", "metadata", "coa", "queue"})
PDF = "application/pdf"


def _user(request: Request) -> Any:
    return request.user


class RolePermissionMixin:
    """Okuma eylemleri giriş yapmış herkese, diğerleri `write_roles`'a açık."""

    write_roles: ClassVar[tuple[str, ...]] = LAB_ROLES
    action_roles: ClassVar[dict[str, tuple[str, ...]]] = {}

    def get_permissions(self) -> list[BasePermission]:
        name = getattr(self, "action", None)
        if name in READ_ACTIONS:
            return [IsAuthenticated()]
        return [HasRole(*self.action_roles.get(name or "", self.write_roles))()]


# --- test tanımı -----------------------------------------------------------------------------


class TestDefinitionViewSet(MasterDataViewSet):
    """Test tanımları (laboratuvar yazar, herkes okur). Silinmez; `deactivate` ile pasife alınır."""

    serializer_class = s.TestDefinitionSerializer
    queryset = TestDefinition.objects.all()
    write_roles = LAB_ROLES
    filterset_fields = ["is_active", "result_type"]
    ordering = ["code"]

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.create_test_definition(
            self.request.user,  # type: ignore[arg-type]
            serializer.validated_data,
        )

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_test_definition(
            self.request.user,  # type: ignore[arg-type]
            serializer.instance,
            serializer.validated_data,
        )

    def _set_active(self, active: bool) -> Response:
        test = services.set_test_active(
            self.request.user,  # type: ignore[arg-type]
            self.get_object(),
            active,
        )
        return Response(self.get_serializer(test).data)


# --- spesifikasyon ---------------------------------------------------------------------------


def _spec_queryset() -> QuerySet[Specification]:
    return Specification.objects.select_related(
        "material", "copied_from", "approved_by", "created_by"
    ).prefetch_related(Prefetch("lines", queryset=SpecificationLine.objects.select_related("test")))


class SpecificationFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=Specification.Status.choices)
    sample_stage = django_filters.MultipleChoiceFilter(choices=SampleStage.choices)

    class Meta:
        model = Specification
        fields = ["material"]


class SpecificationViewSet(
    RolePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Sürümlü spesifikasyonlar. Durum yalnızca `approve` ile değişir; taslak dışındaki sürüm
    değiştirilmez (`copy` ile yeni taslak açılır)."""

    filterset_class = SpecificationFilter
    search_fields = ["material__code", "material__name", "change_note"]
    ordering_fields = ["version_no", "created_at", "approved_at"]
    ordering = ["material__code", "sample_stage", "-version_no"]

    def get_queryset(self) -> QuerySet[Specification]:
        if self.action == "list":
            return Specification.objects.select_related(
                "material", "copied_from", "approved_by", "created_by"
            ).annotate(line_count=Count("lines"))
        return _spec_queryset()

    def get_serializer_class(self) -> type[s.SpecificationSerializer]:
        if self.action == "list":
            return s.SpecificationSerializer
        return s.SpecificationDetailSerializer

    def _detail(self, spec: Specification, code: int = status.HTTP_200_OK) -> Response:
        fresh = _spec_queryset().get(pk=spec.pk)
        return Response(s.SpecificationDetailSerializer(fresh).data, status=code)

    @extend_schema(
        request=s.SpecificationCreateSerializer, responses={201: s.SpecificationDetailSerializer}
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Malzeme + aşama için yeni taslak sürüm (satırlarıyla)."""
        body = s.SpecificationCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        spec = services.create_specification(
            _user(request),
            material=data["material"],
            sample_stage=data["sample_stage"],
            change_note=data.get("change_note", ""),
            lines=data.get("lines", []),
        )
        return self._detail(spec, status.HTTP_201_CREATED)

    @extend_schema(request=s.SpecificationSerializer, responses=s.SpecificationDetailSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Taslak sürümün değişiklik notu."""
        kwargs.pop("partial", None)
        spec = self.get_object()
        data: Any = request.data
        body = s.QualityNoteSerializer(data={"note": data.get("change_note", "")})
        body.is_valid(raise_exception=True)
        services.update_specification(
            _user(request), spec, {"change_note": body.validated_data["note"]}
        )
        return self._detail(spec)

    @extend_schema(
        request=s.QualityNoteSerializer, responses={201: s.SpecificationDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def copy(self, request: Request, pk: str | None = None) -> Response:
        """Sürümü yeni taslak sürüme kopyalar (gövde: `note` = değişiklik notu)."""
        body = s.QualityNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        spec = services.copy_specification(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._detail(spec, status.HTTP_201_CREATED)

    @extend_schema(request=s.QualityNoteSerializer, responses=s.SpecificationDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sürümü onaylar; aynı malzeme ve aşamanın önceki onaylı sürümü geçersiz olur."""
        body = s.QualityNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        spec = services.approve_specification(
            _user(request), self.get_object(), body.validated_data["note"]
        )
        return self._detail(spec)

    @extend_schema(
        request=s.SpecificationLineSerializer, responses={201: s.SpecificationLineSerializer}
    )
    @action(detail=True, methods=["post"])
    def lines(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sürüme satır ekler."""
        body = s.SpecificationLineSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        line = services.add_spec_line(_user(request), self.get_object(), body.validated_data)
        return Response(s.SpecificationLineSerializer(line).data, status=status.HTTP_201_CREATED)


class SpecificationLineViewSet(
    RolePermissionMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Taslak sürüm satırı: güncelle ve kaldır (onaylı sürümde 400 `specification_locked`)."""

    queryset = SpecificationLine.objects.select_related("test", "specification")
    serializer_class = s.SpecificationLineSerializer

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_spec_line(
            self.request.user,  # type: ignore[arg-type]
            serializer.instance,
            serializer.validated_data,
        )

    def perform_destroy(self, instance: SpecificationLine) -> None:
        services.remove_spec_line(self.request.user, instance)  # type: ignore[arg-type]


# --- numune ----------------------------------------------------------------------------------


class SampleFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=Sample.Status.choices)
    stage = django_filters.MultipleChoiceFilter(choices=SampleStage.choices)
    material = django_filters.NumberFilter(field_name="lot__material")
    open = django_filters.BooleanFilter(method="filter_open")

    class Meta:
        model = Sample
        fields = ["lot", "origin"]

    def filter_open(self, queryset: QuerySet[Sample], name: str, value: bool) -> QuerySet[Sample]:
        if value is None:
            return queryset
        if value:
            return queryset.filter(status__in=selectors.QUEUE_STATUSES)
        return queryset.exclude(status__in=selectors.QUEUE_STATUSES)


class SampleViewSet(
    RolePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Numuneler (`NM-`). Durum yalnızca eylem uç noktalarıyla değişir. Lot serbest bırakma ve
    reddin tek yolu `decide`'dır."""

    filterset_class = SampleFilter
    search_fields = ["number", "lot__lot_no", "lot__material__code", "lot__material__name"]
    ordering_fields = ["created_at", "number", "decided_at"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self) -> QuerySet[Sample]:
        queryset = selectors.sample_queryset()
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "decisions",
                    queryset=QualityDecision.objects.select_related(
                        "decided_by", "approved_by", "release_location", "sample__lot__material"
                    ).order_by("-decided_at", "-id"),
                )
            )
        return queryset

    def get_serializer_class(self) -> type[s.SampleSerializer]:
        if self.action == "list" or self.action == "queue":
            return s.SampleSerializer
        return s.SampleDetailSerializer

    def _detail(self, sample: Sample, code: int = status.HTTP_200_OK) -> Response:
        self.action = "retrieve"
        fresh = self.get_queryset().get(pk=sample.pk)
        return Response(s.SampleDetailSerializer(fresh).data, status=code)

    @extend_schema(responses=s.SampleSerializer(many=True))
    @action(detail=False, methods=["get"])
    def queue(self, request: Request) -> Response:
        """Laboratuvar kuyruğu: kararı verilmemiş numuneler, en eski önce (sayfalı)."""
        queryset = self.filter_queryset(selectors.sample_queue()).order_by("created_at", "id")
        page = self.paginate_queryset(queryset)
        rows = s.SampleSerializer(page if page is not None else queryset, many=True).data
        return self.get_paginated_response(rows) if page is not None else Response(rows)

    @extend_schema(request=s.SampleCreateSerializer, responses={201: s.SampleDetailSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Laboratuvarın elle açtığı numune (ör. şarj sırası kontrolü ya da bloke lotun yeniden
        analizi)."""
        body = s.SampleCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        sample = services.create_sample(
            _user(request),
            data["lot"],
            data["stage"],
            taken_at=data["taken_at"],
            retain_location=data["retain_location"],
            note=data["note"],
        )
        return self._detail(sample, status.HTTP_201_CREATED)

    @extend_schema(request=s.SampleSerializer, responses=s.SampleDetailSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Numune alma bilgileri: alan, zaman, şahit numune yeri, not."""
        kwargs.pop("partial", None)
        sample = self.get_object()
        body = s.SampleSerializer(sample, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        allowed = {"taken_by", "taken_at", "retain_location", "note"}
        values = {k: v for k, v in body.validated_data.items() if k in allowed}
        return self._detail(services.update_sample(_user(request), sample, values))

    @extend_schema(request=s.AssignSpecificationSerializer, responses=s.SampleDetailSerializer)
    @action(detail=True, methods=["post"], url_path="assign-specification")
    def assign_specification(self, request: Request, pk: str | None = None) -> Response:
        """Numuneye onaylı spesifikasyon atar (sonuç girilmeden önce)."""
        body = s.AssignSpecificationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        sample = services.assign_specification(
            _user(request), self.get_object(), body.validated_data["specification"]
        )
        return self._detail(sample)

    @extend_schema(request=s.ResultInputSerializer, responses={201: s.SampleDetailSerializer})
    @action(detail=True, methods=["post"])
    def results(self, request: Request, pk: str | None = None) -> Response:
        """Test sonucu girer; satırda sonuç varsa düzeltmedir (not zorunlu)."""
        body = s.ResultInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        sample = self.get_object()
        services.record_result(
            _user(request),
            sample,
            data.pop("spec_line"),
            **data,
        )
        return self._detail(sample, status.HTTP_201_CREATED)

    @extend_schema(request=s.DecisionInputSerializer, responses=s.SampleDetailSerializer)
    @action(detail=True, methods=["post"])
    def decide(self, request: Request, pk: str | None = None) -> Response:
        """Kalite kararı: serbest, ret, yeniden işleme ya da şartlı kabul (yönetim onaylar)."""
        body = s.DecisionInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        sample = self.get_object()
        services.decide(
            _user(request),
            sample,
            body.validated_data["decision"],
            body.validated_data["reason"],
            release_location=body.validated_data["release_location"],
        )
        return self._detail(sample)

    @extend_schema(request=s.SampleCancelSerializer, responses=s.SampleDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Yanlış açılan numuneyi iptal eder (neden zorunlu)."""
        body = s.SampleCancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        sample = services.cancel_sample(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._detail(sample)

    @extend_schema(responses={(200, PDF): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], url_path="coa.pdf")
    def coa(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Analiz sertifikası (PDF): yalnızca bu numuneyle serbest bırakılan lot için."""
        sample = self.get_object()
        response = HttpResponse(coa.coa_pdf(sample), content_type=PDF)
        response["Content-Disposition"] = f'inline; filename="CoA-{sample.lot.lot_no}.pdf"'
        return response


# --- karar (şartlı kabul onayı) --------------------------------------------------------------


class QualityDecisionViewSet(
    RolePermissionMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Kalite kararları (salt okunur). Şartlı kabul `review` ile yönetim tarafından onaylanır ya
    da reddedilir."""

    serializer_class = s.QualityDecisionSerializer
    filterset_fields = ["sample", "decision", "approval_status"]
    ordering = ["-decided_at", "-id"]
    action_roles = {"review": APPROVAL_ROLES}

    def get_queryset(self) -> QuerySet[QualityDecision]:
        return QualityDecision.objects.select_related(
            "sample__lot__material", "decided_by", "approved_by", "release_location"
        )

    @extend_schema(request=s.ReviewSerializer, responses=s.QualityDecisionSerializer)
    @action(detail=True, methods=["post"])
    def review(self, request: Request, pk: str | None = None) -> Response:
        """Şartlı kabulü onaylar (`approve: true`) ya da reddeder (not zorunlu)."""
        body = s.ReviewSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        decision = services.review_conditional_release(
            _user(request),
            self.get_object(),
            approve=body.validated_data["approve"],
            note=body.validated_data["note"],
        )
        return Response(s.QualityDecisionSerializer(self.get_queryset().get(pk=decision.pk)).data)
