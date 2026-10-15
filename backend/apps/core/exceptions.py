"""İş kuralı hataları ve API hata biçimi.

Tüm API hataları `{"code": "...", "detail": "..."}` biçimindedir; alan doğrulama hatalarında
ek olarak `"errors": {"alan": ["mesaj", ...]}` döner.
"""

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler as drf_exception_handler


class BusinessRuleError(Exception):
    """İş kuralı ihlali. `code` sabit İngilizce kod, `message` kullanıcıya görünen Türkçe metin."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


VALIDATION_DETAIL = "Gönderilen bilgiler geçersiz."
PARSE_ERROR_DETAIL = "İstek gövdesi okunamadı (geçersiz JSON)."


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF hata işleyicisi: hataları `{"code", "detail"}` biçimine çevirir."""
    if isinstance(exc, BusinessRuleError):
        return Response(
            {"code": exc.code, "detail": exc.message}, status=status.HTTP_400_BAD_REQUEST
        )

    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(as_serializer_error(exc))
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None or not isinstance(exc, exceptions.APIException):
        return response

    if isinstance(exc, exceptions.ValidationError):
        errors = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
        response.data = {"code": "validation_error", "detail": VALIDATION_DETAIL, "errors": errors}
        return response

    if isinstance(exc, exceptions.ParseError):
        # DRF'nin ayrıştırma mesajı İngilizce ve teknik; kullanıcıya sabit Türkçe metin gösterilir.
        response.data = {"code": "parse_error", "detail": PARSE_ERROR_DETAIL}
        return response

    if isinstance(exc, exceptions.NotAuthenticated | exceptions.AuthenticationFailed):
        # Giriş yapılmamış istekler her zaman 401 döner (403 yetki eksikliği içindir).
        response.status_code = status.HTTP_401_UNAUTHORIZED

    codes = exc.get_codes()
    code = codes if isinstance(codes, str) else exc.default_code
    response.data = {"code": code, "detail": str(exc.detail)}
    return response
