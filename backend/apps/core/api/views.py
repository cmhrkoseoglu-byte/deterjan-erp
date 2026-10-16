from typing import Any

from django.db.models import QuerySet
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import defaults
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from apps.core import health, ratelimit, services
from apps.core.api.filters import AuditLogFilter, UserFilter
from apps.core.api.serializers import (
    AttachmentQuerySerializer,
    AttachmentRemoveSerializer,
    AttachmentSerializer,
    AttachmentUploadSerializer,
    AuditLogSerializer,
    HealthSerializer,
    LoginSerializer,
    MeSerializer,
    UserSerializer,
)
from apps.core.attachments import INLINE_TYPES
from apps.core.authentication import CsrfFailed
from apps.core.models import Attachment, AuditLog, User
from apps.core.permissions import HasRole
from apps.core.roles import ADMIN, YONETIM


def _is_api(request: HttpRequest) -> bool:
    return request.path.startswith("/api/")


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """CSRF_FAILURE_VIEW: API'de `{"code": "csrf_failed", ...}` JSON, diğer sayfalarda Django'nun
    kendi sayfası."""
    if _is_api(request):
        return JsonResponse(
            {"code": CsrfFailed.default_code, "detail": str(CsrfFailed.default_detail)},
            status=403,
            json_dumps_params={"ensure_ascii": False},
        )
    return django_csrf_failure(request, reason)


def page_not_found(request: HttpRequest, exception: Exception) -> HttpResponse:
    """handler404: tanımsız /api/ adreslerinde JSON, diğer sayfalarda Django'nun kendi sayfası."""
    if _is_api(request):
        return JsonResponse(
            {"code": "not_found", "detail": "Bulunamadı."},
            status=404,
            json_dumps_params={"ensure_ascii": False},
        )
    return defaults.page_not_found(request, exception)


def server_error(request: HttpRequest) -> HttpResponse:
    """handler500: API'de JSON, diğer sayfalarda Django'nun kendi sayfası."""
    if _is_api(request):
        return JsonResponse(
            {"code": "server_error", "detail": "Sunucu hatası. Lütfen daha sonra tekrar deneyin."},
            status=500,
            json_dumps_params={"ensure_ascii": False},
        )
    return defaults.server_error(request)


class LoginRateThrottle(BaseThrottle):
    """Giriş denemelerini istemci IP'si başına sınırlar (`LOGIN_RATE_LIMIT`).

    IP, denetim günlüğüyle aynı şekilde nginx'in `X-Real-IP` başlığından alınır; istemcinin
    gönderdiği `X-Forwarded-For` dikkate alınmaz. Sayaç paylaşılan önbellekte (Redis) tutulur.
    """

    def allow_request(self, request: Request, view: Any) -> bool:
        return not ratelimit.login_rate_exceeded(request._request)

    def wait(self) -> float:
        return float(ratelimit.login_rate_period())


class HealthView(APIView):
    """Servis sağlık durumu. Kimlik doğrulama gerektirmez (izleme araçları için)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: HealthSerializer, 503: HealthSerializer})
    def get(self, request: Request) -> Response:
        checks = {
            "db": "ok" if health.check_database() else "error",
            "redis": "ok" if health.check_redis() else "error",
        }
        healthy = all(value == "ok" for value in checks.values())
        body = {"status": "ok" if healthy else "error", **checks}
        return Response(
            body, status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        )


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """SPA açılışında çağrılır; `csrftoken` çerezini ayarlar."""

    permission_classes = [AllowAny]

    @extend_schema(responses={204: None})
    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


# DRF, giriş yapmamış istekte CSRF kontrolü yapmaz; giriş formu CSRF saldırısına karşı
# (login CSRF) burada açıkça korunur.
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    @extend_schema(
        request=LoginSerializer,
        responses={200: MeSerializer, 400: OpenApiResponse(description="invalid_credentials")},
    )
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.login_user(
            request._request,
            serializer.validated_data["username"],
            serializer.validated_data["password"],
        )
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        services.logout_user(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveAPIView):
    serializer_class = MeSerializer

    def get_object(self) -> User:
        return self.request.user  # type: ignore[return-value]


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Kullanıcı listesi (yalnızca admin)."""

    serializer_class = UserSerializer
    permission_classes = [HasRole(ADMIN)]
    filterset_class = UserFilter
    search_fields = ["username", "full_name", "email"]
    ordering_fields = ["username", "full_name", "date_joined", "last_login"]
    ordering = ["username"]

    def get_queryset(self) -> QuerySet[User]:
        return User.objects.prefetch_related("groups")


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Denetim günlüğü (admin, yonetim). Salt okunur."""

    serializer_class = AuditLogSerializer
    permission_classes = [HasRole(ADMIN, YONETIM)]
    filterset_class = AuditLogFilter
    search_fields = ["object_repr", "note"]
    ordering_fields = ["timestamp"]
    ordering = ["-timestamp", "-id"]

    def get_queryset(self) -> QuerySet[AuditLog]:
        return AuditLog.objects.select_related("actor", "content_type")


class AttachmentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Kayda bağlı dosya ekleri (lot, mal kabul, numune, yorum).

    Liste `?content_type=inventory.lot&object_id=5` ister. Yükleme `multipart/form-data`.
    Dosyalar açık `/media` yolundan değil, giriş yapmış kullanıcıya `download` ucundan verilir.
    Ekler silinmez; `remove` ile kaldırılır (yükleyen ya da admin).
    """

    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None

    def get_queryset(self) -> QuerySet[Attachment]:
        return Attachment.objects.select_related("content_type", "created_by", "removed_by")

    @extend_schema(parameters=[AttachmentQuerySerializer])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query = AttachmentQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        content_type, target = services.attachment_target(
            query.validated_data["content_type"], query.validated_data["object_id"]
        )
        queryset = self.get_queryset().filter(content_type=content_type, object_id=target.pk)
        if not query.validated_data["include_removed"]:
            queryset = queryset.filter(is_active=True)
        return Response(self.get_serializer(queryset, many=True).data)

    @extend_schema(
        request={"multipart/form-data": AttachmentUploadSerializer},
        responses={201: AttachmentSerializer},
    )
    def create(self, request: Request) -> Response:
        body = AttachmentUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        attachment = services.add_attachment(
            request.user,  # type: ignore[arg-type]
            target_type=data["content_type"],
            object_id=data["object_id"],
            file=data["file"],
            kind=data["kind"],
            note=data.get("note", ""),
        )
        return Response(self.get_serializer(attachment).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=AttachmentRemoveSerializer, responses=AttachmentSerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request: Request, pk: str | None = None) -> Response:
        body = AttachmentRemoveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        attachment = services.remove_attachment(
            request.user,  # type: ignore[arg-type]
            self.get_object(),
            body.validated_data.get("reason", ""),
        )
        return Response(self.get_serializer(attachment).data)

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> FileResponse:
        """Dosyayı verir: PDF ve resimler tarayıcıda açılır, diğerleri indirilir.
        `?download=1` her zaman indirir. Kaldırılmış ek yalnızca admin'e verilir."""
        attachment = self.get_object()
        user: User = request.user  # type: ignore[assignment]
        if not attachment.is_active and not user.is_admin:
            raise NotFound("Ek kaldırılmış.")
        try:
            handle = attachment.file.open("rb")
        except FileNotFoundError:
            raise NotFound("Dosya bulunamadı.") from None
        inline = (
            attachment.mime_type in INLINE_TYPES and request.query_params.get("download") != "1"
        )
        response = FileResponse(
            handle,
            as_attachment=not inline,
            filename=attachment.original_name,
            content_type=attachment.mime_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        )
        return response
