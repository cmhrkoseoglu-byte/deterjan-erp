"""Kodlama sistematiği uç noktaları (`/api/v1/coding/`).

Biçimleri okuma ve değiştirme yalnız admin içindir; kod önerisi türün yazma rollerine açıktır.
Görünümler incedir: doğrula → `core.coding.services` / `selectors` → yanıt.
"""

from typing import Any, cast

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Q, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.coding import formats, migration, selectors, services
from apps.core.coding.registry import KINDS, MASTER, CodeType, code_type, master_type_for_model
from apps.core.models import CodeHistory, CodeMigrationRun, CodeSchemeRevision, User
from apps.core.pagination import StandardPagination
from apps.core.permissions import HasRole, user_has_role
from apps.core.roles import ADMIN

CODE_KINDS = [(kind, kind) for kind in KINDS]
YEAR_FORMAT_CHOICES = list(formats.YEAR_FORMATS.items())
DATE_FORMAT_CHOICES = list(formats.DATE_FORMATS.items())


class CodeTypeOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    prefix = serializers.CharField()
    format = serializers.CharField()
    next = serializers.CharField()
    last_number = serializers.IntegerField()


class CodeTypeSerializer(serializers.Serializer):
    """Kodlama ekranındaki tür satırı."""

    key = serializers.CharField()
    kind = serializers.ChoiceField(choices=CODE_KINDS)
    label = serializers.CharField()  # type: ignore[assignment]
    configurable = serializers.BooleanField()
    locked = serializers.BooleanField()
    free = serializers.BooleanField()
    scanned = serializers.BooleanField()
    prefix = serializers.CharField(allow_blank=True)
    width = serializers.IntegerField()
    type_field = serializers.CharField(allow_blank=True)
    type_prefixes = serializers.DictField(child=serializers.CharField())
    year_format = serializers.CharField(allow_blank=True)
    date_format = serializers.CharField(allow_blank=True)
    is_active = serializers.BooleanField()
    revision = serializers.IntegerField()
    updated_at = serializers.DateTimeField(allow_null=True)
    updated_by = serializers.CharField(allow_blank=True)
    format = serializers.CharField(allow_blank=True)
    next = serializers.CharField(allow_blank=True)
    longest = serializers.CharField(allow_blank=True)
    last_number = serializers.IntegerField()
    types = CodeTypeOptionSerializer(many=True)
    samples = serializers.ListField(child=serializers.CharField())


class CodeFormatValuesSerializer(serializers.Serializer):
    """İstenen biçim değerleri (verilmeyen değişmez)."""

    prefix = serializers.CharField(required=False, allow_blank=True, max_length=16)
    width = serializers.IntegerField(required=False, min_value=1, max_value=12)
    type_prefixes = serializers.DictField(
        child=serializers.CharField(allow_blank=True, max_length=16), required=False
    )
    year_format = serializers.ChoiceField(choices=YEAR_FORMAT_CHOICES, required=False)
    date_format = serializers.ChoiceField(choices=DATE_FORMAT_CHOICES, required=False)


class CodeSchemeUpdateSerializer(CodeFormatValuesSerializer):
    is_active = serializers.BooleanField(required=False)
    # Ana veride sıradaki numara: {"MLZ": 25}
    counters = serializers.DictField(child=serializers.IntegerField(min_value=1), required=False)
    note = serializers.CharField(allow_blank=True, max_length=1000)


class CodePreviewErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class CodePreviewSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    error = CodePreviewErrorSerializer(allow_null=True)
    example = CodeTypeSerializer(allow_null=True)


class CodeSchemeRevisionSerializer(serializers.ModelSerializer):
    key = serializers.CharField(source="scheme.key", read_only=True)
    label = serializers.SerializerMethodField()  # type: ignore[assignment]
    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CodeSchemeRevision
        fields = [
            "id",
            "key",
            "label",
            "revision",
            "prefix",
            "type_prefixes",
            "width",
            "year_format",
            "date_format",
            "is_active",
            "counters",
            "note",
            "changed_at",
            "changed_by_name",
        ]

    def get_label(self, obj: CodeSchemeRevision) -> str:
        item = code_type(obj.scheme.key)
        return item.label if item is not None else obj.scheme.key

    def get_changed_by_name(self, obj: CodeSchemeRevision) -> str:
        user = obj.changed_by
        return (user.full_name or user.username) if user else ""


class CodeSuggestionSerializer(serializers.Serializer):
    key = serializers.CharField()
    active = serializers.BooleanField()
    code = serializers.CharField(allow_null=True)
    format = serializers.CharField(allow_blank=True)


# --- ana veri uç noktalarında eski kodlar ----------------------------------------------------


class FormerCodeSearchFilter(SearchFilter):
    """`?search=` model alanlarına ek olarak kayıtlı ana veri kod türünün eski kodlarında da arar
    (`core.CodeHistory`); kodu değişen kayıt eski koduyla da bulunur."""

    def filter_queryset(self, request: Request, queryset: QuerySet[Any], view: Any) -> Any:
        filtered = super().filter_queryset(request, queryset, view)
        term = (request.query_params.get(self.search_param) or "").strip()
        item = master_type_for_model(queryset.model._meta.label_lower)
        if not term or item is None or item.kind != MASTER:
            return filtered
        former = CodeHistory.objects.filter(
            content_type=ContentType.objects.get_for_model(queryset.model),
            field=item.field,
            code__icontains=term,
        ).values("object_id")
        return queryset.filter(Q(pk__in=filtered.values("pk")) | Q(pk__in=former))


class FormerCodesListSerializer(serializers.ListSerializer):
    """Liste yanıtında sayfadaki kayıtların eski kodlarını tek sorguyla getirir."""

    def to_representation(self, data: Any) -> list[Any]:
        items = list(data.all() if isinstance(data, models.manager.BaseManager) else data)
        model = self.child.Meta.model  # type: ignore[union-attr]
        context = cast(dict[str, Any], self.context)  # kök serializer'ın bağlamı (değişebilir)
        context["former_codes"] = selectors.former_code_map(model, [i.pk for i in items])
        return super().to_representation(items)


class FormerCodesMixin(serializers.Serializer):
    """Ana veri serializer'larına `former_codes` (eski kodlar, en yeniden eskiye) ekler.

    Kullanan serializer `Meta.fields`'a "former_codes" yazar ve
    `Meta.list_serializer_class = FormerCodesListSerializer` verir.
    """

    former_codes = serializers.SerializerMethodField()

    def get_former_codes(self, obj: Any) -> list[str]:
        cache = self.context.get("former_codes")
        if cache is not None:
            current = getattr(obj, "code", None)
            return [code for code in cache.get(obj.pk, []) if code != current]
        return selectors.former_codes(obj)


def _type_or_404(key: str) -> CodeType:
    found = code_type(key)
    if found is None:
        raise NotFound("Tanımsız kod türü.")
    return found


def _actor(request: Request) -> User:
    return request.user  # type: ignore[return-value]


class CodeTypeListView(APIView):
    """Kayıtlı bütün kod türleri: biçim, örnek, sıradaki ve verilen son numara (yalnız admin).
    `?kind=master|document|lot|standard` ile süzülür."""

    permission_classes = [HasRole(ADMIN)]

    @extend_schema(
        parameters=[OpenApiParameter("kind", str, enum=list(KINDS), required=False)],
        responses=CodeTypeSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        kind = request.query_params.get("kind") or None
        if kind is not None and kind not in KINDS:
            kind = "__none__"
        items = selectors.overview(kind)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(items, request, view=self)  # type: ignore[arg-type]
        return paginator.get_paginated_response(CodeTypeSerializer(page, many=True).data)


class CodeTypeDetailView(APIView):
    """Tek kod türü: oku ya da biçimini değiştir (yalnız admin; not zorunlu)."""

    permission_classes = [HasRole(ADMIN)]

    @extend_schema(responses=CodeTypeSerializer)
    def get(self, request: Request, key: str) -> Response:
        return Response(CodeTypeSerializer(selectors.describe(_type_or_404(key))).data)

    @extend_schema(request=CodeSchemeUpdateSerializer, responses=CodeTypeSerializer)
    def put(self, request: Request, key: str) -> Response:
        item = _type_or_404(key)
        body = CodeSchemeUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data: dict[str, Any] = dict(body.validated_data)
        services.update_scheme(_actor(request), item.key, **data)
        return Response(CodeTypeSerializer(selectors.describe(item)).data)


class CodeTypePreviewView(APIView):
    """Kaydetmeden istenen biçimin örnekleri ve kural ihlali (yalnız admin)."""

    permission_classes = [HasRole(ADMIN)]

    @extend_schema(request=CodeFormatValuesSerializer, responses=CodePreviewSerializer)
    def post(self, request: Request, key: str) -> Response:
        item = _type_or_404(key)
        body = CodeFormatValuesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(CodePreviewSerializer(selectors.preview(item, body.validated_data)).data)


class CodeSchemeRevisionListView(generics.ListAPIView):
    """Bir kod türünün biçim revizyonları, en yeniden eskiye (yalnız admin)."""

    permission_classes = [HasRole(ADMIN)]
    serializer_class = CodeSchemeRevisionSerializer
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[CodeSchemeRevision]:
        item = _type_or_404(self.kwargs["key"])
        return CodeSchemeRevision.objects.filter(scheme__key=item.key).select_related(
            "scheme", "changed_by"
        )


class AllRevisionsListView(generics.ListAPIView):
    """Bütün kod türlerinin biçim revizyonları, en yeniden eskiye (yalnız admin): kodlama
    ekranının Geçmiş bölümü."""

    permission_classes = [HasRole(ADMIN)]
    serializer_class = CodeSchemeRevisionSerializer
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[CodeSchemeRevision]:
        return CodeSchemeRevision.objects.select_related("scheme", "changed_by")


class CodeSuggestView(APIView):
    """Yeni kayıt için sıradaki kod (biçim etkinse). Türün yazma rollerine ve admin'e açık;
    `?type=` türe göre önekli kodda kaydın türü (ekipman türü)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("type", str, required=False)],
        responses=CodeSuggestionSerializer,
    )
    def get(self, request: Request, key: str) -> Response:
        item = _type_or_404(key)
        if not user_has_role(request.user, item.write_roles or (ADMIN,)):
            raise PermissionDenied("Bu kayıt türünü yazma yetkiniz yok.")
        type_value = request.query_params.get("type") or None
        fmt = selectors.effective_format(item)
        body = {
            "key": item.key,
            "active": selectors.is_active(item),
            "code": selectors.suggest_code(item, type_value=type_value),
            "format": selectors.format_hint(item, fmt, type_value),
        }
        return Response(CodeSuggestionSerializer(body).data)


# --- kod göçü --------------------------------------------------------------------------------


class RecodeRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    label = serializers.CharField()  # type: ignore[assignment]
    old = serializers.CharField(allow_blank=True)
    new = serializers.CharField(allow_blank=True)
    action = serializers.CharField(help_text="keep | change | problem")
    is_active = serializers.BooleanField()
    problem = serializers.CharField(allow_blank=True)


class RecodePreviewSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    active = serializers.BooleanField()
    rows = RecodeRowSerializer(many=True)
    change_count = serializers.IntegerField()
    keep_count = serializers.IntegerField()
    problem_count = serializers.IntegerField()
    checksum = serializers.CharField()


class RecodeApplySerializer(serializers.Serializer):
    checksum = serializers.CharField(max_length=64)
    note = serializers.CharField(allow_blank=True, max_length=1000)


class RecodeNoteSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=True, max_length=1000)


class CodeMigrationRunSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()  # type: ignore[assignment]
    created_by_name = serializers.SerializerMethodField()
    reverted = serializers.SerializerMethodField()
    count = serializers.SerializerMethodField()

    class Meta:
        model = CodeMigrationRun
        fields = [
            "id",
            "key",
            "label",
            "kind",
            "mapping",
            "note",
            "reverts",
            "reverted",
            "count",
            "created_at",
            "created_by_name",
        ]

    def get_label(self, obj: CodeMigrationRun) -> str:
        item = code_type(obj.key)
        return item.label if item is not None else obj.key

    def get_created_by_name(self, obj: CodeMigrationRun) -> str:
        user = obj.created_by
        return (user.full_name or user.username) if user else ""

    def get_reverted(self, obj: CodeMigrationRun) -> bool:
        return obj.kind == CodeMigrationRun.Kind.APPLY and obj.reverted_by.exists()

    def get_count(self, obj: CodeMigrationRun) -> int:
        return len(obj.mapping)


class RevertRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    label = serializers.CharField()  # type: ignore[assignment]
    old = serializers.CharField()
    new = serializers.CharField()
    current = serializers.CharField(allow_blank=True)
    action = serializers.CharField(help_text="revert | skip")


class RevertPreviewSerializer(serializers.Serializer):
    run = serializers.IntegerField()
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    rows = RevertRowSerializer(many=True)
    revert_count = serializers.IntegerField()
    already_reverted = serializers.BooleanField()


class RecodePreviewView(APIView):
    """Kod göçü önizlemesi (yalnız admin, salt okunur): her kaydın eski ve yeni kodu."""

    permission_classes = [HasRole(ADMIN)]

    @extend_schema(responses=RecodePreviewSerializer)
    def get(self, request: Request, key: str) -> Response:
        item = _type_or_404(key)
        return Response(RecodePreviewSerializer(migration.preview_recode(item.key)).data)


class RecodeApplyView(APIView):
    """Önizlemedeki göçü uygular (yalnız admin; not zorunlu; önizlemeden sonra kayıt değiştiyse
    `recode_stale`)."""

    permission_classes = [HasRole(ADMIN)]

    @extend_schema(request=RecodeApplySerializer, responses={201: CodeMigrationRunSerializer})
    def post(self, request: Request, key: str) -> Response:
        item = _type_or_404(key)
        body = RecodeApplySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = migration.apply_recode(_actor(request), item.key, **body.validated_data)
        return Response(CodeMigrationRunSerializer(run).data, status=201)


class CodeMigrationRunListView(generics.ListAPIView):
    """Uygulanan kod göçleri ve geri almaları, en yeniden eskiye (yalnız admin)."""

    permission_classes = [HasRole(ADMIN)]
    serializer_class = CodeMigrationRunSerializer
    filter_backends: list[Any] = []

    def get_queryset(self) -> QuerySet[CodeMigrationRun]:
        return CodeMigrationRun.objects.select_related("created_by").prefetch_related("reverted_by")


class RevertPreviewView(APIView):
    """Geri alma önizlemesi (yalnız admin): hangi kayıt eski koduna döner, hangisi kalır."""

    permission_classes = [HasRole(ADMIN)]

    @extend_schema(responses=RevertPreviewSerializer)
    def get(self, request: Request, run_id: int) -> Response:
        return Response(RevertPreviewSerializer(migration.preview_revert(run_id)).data)


class RevertView(APIView):
    """Göçü geri alır (yalnız admin; not zorunlu; bir göç bir kez geri alınır)."""

    permission_classes = [HasRole(ADMIN)]

    @extend_schema(request=RecodeNoteSerializer, responses={201: CodeMigrationRunSerializer})
    def post(self, request: Request, run_id: int) -> Response:
        body = RecodeNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = migration.revert_recode(_actor(request), run_id, note=body.validated_data["note"])
        return Response(CodeMigrationRunSerializer(run).data, status=201)
