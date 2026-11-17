import logging
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import health, ratelimit
from apps.core.permissions import AdminOnly, Public, SignedIn
from apps.ops import selectors
from apps.ops.api.serializers import (
    ClientErrorSerializer,
    OpsHealthSerializer,
    SystemStatusSerializer,
)

logger = logging.getLogger("apps.ops.client")
# Şemada giriş gerektirmeyen uç: drf-spectacular bunu yalnız `AllowAny` izninden çıkarır, `Public`
# işaretinde açıkça yazılır (şema bugünkü gibi kalır).
NO_AUTH: Any = [{}]


class SystemStatusView(APIView):
    """Sistem durumu ekranı (yalnızca admin): kontroller, disk, yük, kuyruk, yedek geçmişi."""

    permission_classes = [AdminOnly]

    @extend_schema(responses=SystemStatusSerializer)
    def get(self, request: Request) -> Response:
        return Response(SystemStatusSerializer(selectors.system_status()).data)


class OpsHealthView(APIView):
    """Dış izleme aracı (ör. Uptime Kuma) için: veritabanı, Redis, yedek, geri yükleme testi ve
    arka plan servisleri. Biri `error` ise 503. Kimlik doğrulama gerektirmez; ayrıntı vermez."""

    authentication_classes: list = []
    permission_classes = [Public("dış izleme aracı; ayrıntı vermez")]

    @extend_schema(responses={200: OpsHealthSerializer, 503: OpsHealthSerializer}, auth=NO_AUTH)
    def get(self, request: Request) -> Response:
        body: dict[str, str] = {
            "db": "ok" if health.check_database() else "error",
            "redis": "ok" if health.check_redis() else "error",
        }
        if body["db"] == "ok":
            body.update(selectors.health_summary())
        else:
            body.update({"backup": "unknown", "restore_test": "unknown", "celery": "unknown"})
        healthy = "error" not in body.values()
        body["status"] = "ok" if healthy else "error"
        return Response(
            body, status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        )


class ClientErrorView(APIView):
    """SPA'daki beklenmeyen hatalar sunucu günlüğüne (ve tanımlıysa hata takip aracına) yazılır.
    Kullanıcı başına dakikada 30 kayıt."""

    permission_classes = [SignedIn("arayüz hata kaydı")]

    @extend_schema(request=ClientErrorSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        body = ClientErrorSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        if not ratelimit.hit("client-error", str(request.user.pk), "30/minute"):
            data = body.validated_data
            logger.error(
                "Arayüz hatası: %s (adres: %s, kullanıcı: %s)\n%s",
                data["message"],
                data.get("url", ""),
                request.user.pk,
                data.get("stack", ""),
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
