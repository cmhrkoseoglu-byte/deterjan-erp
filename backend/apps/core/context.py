"""İstek bağlamı: denetim kayıtlarına IP adresini ve işlemi yapan kullanıcıyı, servis katmanına
parametre geçmeden taşır (ör. şifre değişikliği sinyali, yönetim paneli)."""

import ipaddress
from collections.abc import Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import HttpRequest, HttpResponse

if TYPE_CHECKING:
    from apps.core.models import User

_current_request: ContextVar[HttpRequest | None] = ContextVar("current_request", default=None)


def client_ip_from_request(request: HttpRequest) -> str | None:
    """İstemci IP'sini çözer. nginx arkasında nginx'in yazdığı `X-Real-IP` başlığı kullanılır
    (istemcinin gönderdiği `X-Forwarded-For` dikkate alınmaz).

    Geçerli bir IP adresi değilse None döner (veritabanı `inet` alanı geçersiz değeri reddeder).
    """
    candidates = []
    if settings.TRUST_X_REAL_IP:
        candidates.append(request.META.get("HTTP_X_REAL_IP", ""))
    candidates.append(request.META.get("REMOTE_ADDR", ""))
    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(candidate.strip()))
        except ValueError:
            continue
    return None


def get_current_request() -> HttpRequest | None:
    """Geçerli HTTP isteği; istek dışında (komut, arka plan işi) None."""
    return _current_request.get()


def get_client_ip() -> str | None:
    """Geçerli isteğin istemci IP adresi; istek dışında None."""
    request = _current_request.get()
    return client_ip_from_request(request) if request is not None else None


def get_current_user() -> "User | None":
    """Geçerli isteği yapan, giriş yapmış kullanıcı; yoksa None."""
    from apps.core.models import User

    request = _current_request.get()
    user = getattr(request, "user", None)
    return user if isinstance(user, User) and user.is_authenticated else None


class RequestContextMiddleware:
    """Her isteği bağlama yazar, istek bitince temizler.

    AuthenticationMiddleware'den sonra gelmelidir (kullanıcı bilgisi için)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)
