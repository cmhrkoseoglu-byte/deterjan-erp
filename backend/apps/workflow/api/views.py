"""İş akışı API'si: görevler, bildirimler, yorumlar.

Tüm uç noktalar giriş yapmış her kullanıcıya açıktır (her rolün görevi/bildirimi vardır); kimin
neyi göreceği satır düzeyinde süzülür: bildirimler yalnızca alıcısına, görevler
`selectors.tasks_visible_to` kuralına göre. Görev üstlenme/tamamlama yetkisi servis katmanında
denetlenir (yetkisizse 403).
"""

from typing import Any

import django_filters
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.serializers import AuditLogSerializer
from apps.core.models import AuditLog, User
from apps.workflow import selectors, services
from apps.workflow.api.serializers import (
    CommentCreateSerializer,
    CommentEditSerializer,
    CommentSerializer,
    MarkReadResultSerializer,
    MarkReadSerializer,
    NotificationSerializer,
    RecordQuerySerializer,
    TaskCompleteSerializer,
    TaskSerializer,
    UnreadCountSerializer,
    UserBriefSerializer,
)
from apps.workflow.models import Comment, Notification, Task


def _user(request: Request) -> User:
    user = request.user
    assert isinstance(user, User)
    return user


def _record_from_query(request: Request) -> tuple[ContentType, int]:
    """`?content_type=inventory.lot&object_id=5` parametrelerini doğrular."""
    query = RecordQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    content_type = selectors.commentable_content_type(query.validated_data["content_type"])
    return content_type, query.validated_data["object_id"]


class _ContentTypeFilterMixin:
    def filter_content_type(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        app_label, _, model = value.lower().partition(".")
        try:
            content_type = ContentType.objects.get_by_natural_key(app_label, model)
        except ContentType.DoesNotExist:
            return queryset.none()
        return queryset.filter(related_content_type=content_type)


class TaskFilter(_ContentTypeFilterMixin, django_filters.FilterSet):
    mine = django_filters.BooleanFilter(method="filter_mine", label="Yalnızca bana/rollerime")
    open = django_filters.BooleanFilter(method="filter_open", label="Açık (OPEN, IN_PROGRESS)")
    status = django_filters.MultipleChoiceFilter(choices=Task.Status.choices)
    assigned_role = django_filters.CharFilter(field_name="assigned_role__name", label="Rol")
    content_type = django_filters.CharFilter(
        method="filter_content_type", label="İlgili kayıt türü (ör. inventory.lot)"
    )
    object_id = django_filters.NumberFilter(field_name="related_object_id", label="İlgili kayıt no")

    class Meta:
        model = Task
        fields = ["mine", "open", "status", "priority", "assigned_role", "rule_code"]

    def filter_mine(self, queryset: QuerySet, name: str, value: bool) -> QuerySet:
        if not value:
            return queryset
        return queryset.filter(selectors.assigned_to_q(self.request.user))

    def filter_open(self, queryset: QuerySet, name: str, value: bool) -> QuerySet:
        if value:
            return queryset.filter(status__in=Task.OPEN_STATUSES)
        return queryset.exclude(status__in=Task.OPEN_STATUSES)


class TaskViewSet(viewsets.ReadOnlyModelViewSet):
    """Görevler. `?mine=true&open=true` → Görevlerim. Görev elle oluşturulmaz, kurallardan doğar."""

    queryset = Task.objects.none()  # şema için; gerçek sorgu get_queryset'te
    serializer_class = TaskSerializer
    filterset_class = TaskFilter
    search_fields = ["title", "description", "related_repr"]
    ordering_fields = ["created_at", "priority", "due_at", "status"]
    ordering = ["-priority", "created_at", "id"]

    def get_queryset(self) -> QuerySet[Task]:
        return selectors.tasks_visible_to(_user(self.request))

    @extend_schema(request=None, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def claim(self, request: Request, pk: Any = None) -> Response:
        task = services.claim_task(_user(request), self.get_object())
        return Response(self.get_serializer(task).data)

    @extend_schema(request=TaskCompleteSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: Any = None) -> Response:
        body = TaskCompleteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        task = services.complete_task(
            _user(request), self.get_object(), note=body.validated_data.get("note", "")
        )
        return Response(self.get_serializer(task).data)


class NotificationFilter(django_filters.FilterSet):
    unread = django_filters.BooleanFilter(
        field_name="read_at", lookup_expr="isnull", label="Okunmamış"
    )

    class Meta:
        model = Notification
        fields = ["unread", "level"]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Bana gelen bildirimler (yeniden eskiye)."""

    queryset = Notification.objects.none()  # şema için; gerçek sorgu get_queryset'te
    serializer_class = NotificationSerializer
    filterset_class = NotificationFilter
    search_fields = ["title", "body"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self) -> QuerySet[Notification]:
        return selectors.notifications_for(_user(self.request))

    @extend_schema(responses=UnreadCountSerializer)
    @action(detail=False, methods=["get"], url_path="unread-count", filter_backends=[])
    def unread_count(self, request: Request) -> Response:
        return Response({"count": selectors.unread_count(_user(request))})

    @extend_schema(request=MarkReadSerializer, responses=MarkReadResultSerializer)
    @action(detail=False, methods=["post"], url_path="mark-read", filter_backends=[])
    def mark_read(self, request: Request) -> Response:
        body = MarkReadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        ids = None if body.validated_data.get("all") else body.validated_data["ids"]
        updated = services.mark_notifications_read(_user(request), ids)
        return Response({"updated": updated})


_RECORD_PARAMS = [
    OpenApiParameter("content_type", str, required=True, description="ör. inventory.lot"),
    OpenApiParameter("object_id", int, required=True),
]


class CommentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Kayda bağlı yorumlar. Liste için `content_type` ve `object_id` zorunludur.
    Yorum silinmez; yalnızca yazarı düzenleyebilir (PATCH/PUT `{"body": ...}`)."""

    queryset = Comment.objects.none()  # şema için; gerçek sorgu get_queryset'te
    serializer_class = CommentSerializer
    filter_backends: list = []
    http_method_names = ["get", "post", "patch", "put", "head", "options"]

    def get_queryset(self) -> QuerySet[Comment]:
        if self.action == "list":
            content_type, object_id = _record_from_query(self.request)
            return selectors.comments_for(content_type, object_id)
        return Comment.objects.select_related("author", "content_type").prefetch_related("mentions")

    @extend_schema(parameters=_RECORD_PARAMS)
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=CommentCreateSerializer, responses={201: CommentSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = CommentCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        comment = services.add_comment(_user(request), **body.validated_data)
        return Response(self.get_serializer(comment).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CommentEditSerializer, responses=CommentSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = CommentEditSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        comment = services.edit_comment(
            _user(request), self.get_object(), body=body.validated_data["body"]
        )
        return Response(self.get_serializer(comment).data)

    @extend_schema(request=CommentEditSerializer, responses=CommentSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.update(request, *args, **kwargs)


class RecordHistoryView(generics.ListAPIView):
    """Bir kaydın denetim geçmişi (yorum panelindeki "Geçmiş" sekmesi)."""

    serializer_class = AuditLogSerializer
    filter_backends: list = []

    def get_queryset(self) -> QuerySet[AuditLog]:
        content_type, object_id = _record_from_query(self.request)
        return selectors.record_history(content_type, object_id)

    @extend_schema(parameters=_RECORD_PARAMS)
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class MentionableUserView(generics.ListAPIView):
    """@bahsetme önerisi: kullanıcı adı ya da ad soyadla arama, en fazla 10 kişi (sayfasız)."""

    serializer_class = UserBriefSerializer
    filter_backends: list = []
    pagination_class = None

    def get_queryset(self) -> QuerySet[User]:
        return selectors.mentionable_users(self.request.query_params.get("search", ""))

    @extend_schema(parameters=[OpenApiParameter("search", str)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)
