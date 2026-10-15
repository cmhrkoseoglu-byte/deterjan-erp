from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import health


class HealthView(APIView):
    """Servis sağlık durumu. Kimlik doğrulama gerektirmez (izleme araçları için)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

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
