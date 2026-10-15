from typing import Any

from django.db.models import Max, Prefetch, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.permissions import HasRole
from apps.core.roles import LABORATUVAR, PLANLAMA
from apps.masterdata.api.views import READ_ACTIONS, MasterDataViewSet
from apps.recipes import services
from apps.recipes.api import serializers as s
from apps.recipes.models import Recipe, RecipeLine, RecipeStep, RecipeVersion

# Reçeteyi yazabilen ve sürüm onaylayabilen roller (admin her yere erişir).
RECIPE_WRITE_ROLES = (PLANLAMA, LABORATUVAR)
# Okuma (ölçekleme dahil) tüm giriş yapmış kullanıcılara açık.
RECIPE_READ_ACTIONS = READ_ACTIONS | {"scale"}


class RecipeWritePermissionMixin:
    def get_permissions(self) -> list[BasePermission]:
        if getattr(self, "action", None) in RECIPE_READ_ACTIONS:
            return [IsAuthenticated()]
        return [HasRole(*RECIPE_WRITE_ROLES)()]


class RecipeViewSet(MasterDataViewSet):
    """Reçeteler. `versions` alt uç noktası sürümleri listeler ve yeni taslak sürüm açar."""

    serializer_class = s.RecipeSerializer
    write_roles = RECIPE_WRITE_ROLES
    filterset_fields = ["is_active", "product"]
    search_fields = ["code", "name", "product__code", "product__name"]
    ordering = ["code"]

    def get_queryset(self) -> QuerySet[Recipe]:
        return (
            Recipe.objects.select_related("product")
            .annotate(latest_version_no=Max("versions__version_no"))
            .prefetch_related(
                Prefetch(
                    "versions",
                    queryset=RecipeVersion.objects.filter(status=RecipeVersion.Status.APPROVED),
                    to_attr="approved_versions",
                )
            )
        )

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.create_recipe(
            self.request.user,  # type: ignore[arg-type]
            serializer.validated_data,
        )

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_recipe(
            self.request.user,  # type: ignore[arg-type]
            serializer.instance,
            serializer.validated_data,
        )

    def _set_active(self, active: bool) -> Response:
        recipe = services.set_recipe_active(
            self.request.user,  # type: ignore[arg-type]
            self.get_object(),
            active,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=recipe.pk)).data)

    @extend_schema(methods=["get"], responses=s.RecipeVersionSerializer(many=True), request=None)
    @extend_schema(
        methods=["post"],
        request=s.RecipeVersionCreateSerializer,
        responses={201: s.RecipeVersionDetailSerializer},
    )
    @action(detail=True, methods=["get", "post"])
    def versions(self, request: Request, pk: str | None = None) -> Response:
        """GET: reçetenin sürümleri (yeniden eskiye). POST: yeni taslak sürüm."""
        recipe = self.get_object()
        if request.method == "GET":
            versions = (
                RecipeVersion.objects.filter(recipe=recipe)
                .select_related(*VERSION_RELATED)
                .order_by("-version_no")
            )
            return Response(s.RecipeVersionSerializer(versions, many=True).data)
        body = s.RecipeVersionCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        version = services.create_version(
            request.user,  # type: ignore[arg-type]
            recipe,
            batch_size=data["batch_size"],
            batch_unit=data["batch_unit"],
            change_note=data.get("change_note", ""),
            lines=data.get("lines", []),
            steps=data.get("steps", []),
        )
        return Response(_version_detail(version, request), status=status.HTTP_201_CREATED)

    def get_permissions(self) -> list[BasePermission]:
        if self.action == "versions" and self.request.method == "GET":
            return [IsAuthenticated()]
        return super().get_permissions()


VERSION_RELATED = ("recipe", "batch_unit", "copied_from", "approved_by", "created_by")


def _version_detail(version: RecipeVersion, request: Request) -> dict[str, Any]:
    fresh = _version_queryset().get(pk=version.pk)
    return s.RecipeVersionDetailSerializer(fresh, context={"request": request}).data


def _version_queryset() -> QuerySet[RecipeVersion]:
    return RecipeVersion.objects.select_related(*VERSION_RELATED).prefetch_related(
        Prefetch("lines", queryset=RecipeLine.objects.select_related("material", "unit")),
        "steps",
    )


class RecipeVersionViewSet(
    RecipeWritePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Reçete sürümleri. Durum yalnızca `approve` ile değişir; taslak dışındaki sürüm
    değiştirilemez (`copy` ile yeni taslak açılır)."""

    filterset_fields = {
        "recipe": ["exact"],
        "status": ["exact", "in"],
        "recipe__product": ["exact"],
    }
    search_fields = ["recipe__code", "recipe__name", "change_note"]
    ordering_fields = ["version_no", "created_at", "approved_at"]
    ordering = ["recipe__code", "-version_no"]

    def get_queryset(self) -> QuerySet[RecipeVersion]:
        if self.action == "list":
            return RecipeVersion.objects.select_related(*VERSION_RELATED)
        return _version_queryset()

    def get_serializer_class(self) -> type[s.RecipeVersionSerializer]:
        if self.action == "list":
            return s.RecipeVersionSerializer
        return s.RecipeVersionDetailSerializer

    @extend_schema(request=s.RecipeVersionSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        version = self.get_object()
        body = s.RecipeVersionSerializer(version, data=request.data, partial=partial)
        body.is_valid(raise_exception=True)
        services.update_version(
            request.user,  # type: ignore[arg-type]
            version,
            body.validated_data,
        )
        return Response(_version_detail(version, request))

    @extend_schema(
        request=s.VersionActionSerializer, responses={201: s.RecipeVersionDetailSerializer}
    )
    @action(detail=True, methods=["post"])
    def copy(self, request: Request, pk: str | None = None) -> Response:
        """Sürümü yeni taslak sürüme kopyalar (gövde: `note` = değişiklik notu)."""
        body = s.VersionActionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        version = services.copy_version(
            request.user,  # type: ignore[arg-type]
            self.get_object(),
            body.validated_data["note"],
        )
        return Response(_version_detail(version, request), status=status.HTTP_201_CREATED)

    @extend_schema(request=s.VersionActionSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sürümü onaylar; önceki onaylı sürüm geçersiz olur."""
        body = s.VersionActionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        version = services.approve_version(
            request.user,  # type: ignore[arg-type]
            self.get_object(),
            body.validated_data["note"],
        )
        return Response(_version_detail(version, request))

    @extend_schema(
        parameters=[
            OpenApiParameter("qty", str, required=True, description="Hedef miktar"),
            OpenApiParameter("unit", str, required=True, description="Birim kodu ya da kimliği"),
        ],
        responses=s.ScaledRequirementSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def scale(self, request: Request, pk: str | None = None) -> Response:
        """Sürümü hedef miktara ölçekler; ihtiyaçlar malzemenin temel biriminde döner."""
        query = s.ScaleQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        requirements = services.scale_requirements(
            self.get_object(), query.validated_data["qty"], query.validated_data["unit"]
        )
        return Response(s.ScaledRequirementSerializer(requirements, many=True).data)

    @extend_schema(request=s.RecipeLineSerializer, responses={201: s.RecipeLineSerializer})
    @action(detail=True, methods=["post"])
    def lines(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sürüme satır ekler."""
        body = s.RecipeLineSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        line = services.add_line(
            request.user,  # type: ignore[arg-type]
            self.get_object(),
            body.validated_data,
        )
        return Response(s.RecipeLineSerializer(line).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.RecipeStepSerializer, responses={201: s.RecipeStepSerializer})
    @action(detail=True, methods=["post"])
    def steps(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sürüme proses adımı ekler."""
        body = s.RecipeStepSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        step = services.add_step(
            request.user,  # type: ignore[arg-type]
            self.get_object(),
            body.validated_data,
        )
        return Response(s.RecipeStepSerializer(step).data, status=status.HTTP_201_CREATED)


class _DraftItemViewSet(
    RecipeWritePermissionMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Taslak sürüm satırı / adımı: güncelle ve kaldır. Kaldırma yalnızca taslakta yapılır ve
    silinen kayıt sürümün denetim geçmişine yazılır (onaylı sürümde 400 `version_locked`)."""

    def perform_update(self, serializer: Any) -> None:
        raise NotImplementedError

    def perform_destroy(self, instance: Any) -> None:
        raise NotImplementedError


class RecipeLineViewSet(_DraftItemViewSet):
    queryset = RecipeLine.objects.select_related("material", "unit", "version")
    serializer_class = s.RecipeLineSerializer

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_line(
            self.request.user,  # type: ignore[arg-type]
            serializer.instance,
            serializer.validated_data,
        )

    def perform_destroy(self, instance: RecipeLine) -> None:
        services.remove_line(self.request.user, instance)  # type: ignore[arg-type]


class RecipeStepViewSet(_DraftItemViewSet):
    queryset = RecipeStep.objects.select_related("version")
    serializer_class = s.RecipeStepSerializer

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_step(
            self.request.user,  # type: ignore[arg-type]
            serializer.instance,
            serializer.validated_data,
        )

    def perform_destroy(self, instance: RecipeStep) -> None:
        services.remove_step(self.request.user, instance)  # type: ignore[arg-type]
