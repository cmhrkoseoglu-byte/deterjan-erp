"""Oturum güvenliği ara katmanı (Faz 5, Adım 5.5).

1. **Hareketsizlik süresi**: son kullanıcı etkinliğinden bu yana `SESSION_IDLE_TIMEOUT_MINUTES`
   (saha tabletinde `FIELD_DEVICE_IDLE_TIMEOUT_MINUTES`) geçtiyse oturum kapatılır; API isteği
   `401 {"code": "session_expired"}` alır. SPA her istekte `X-ERP-Idle-Seconds` başlığıyla
   kullanıcının kaç saniyedir ekrana dokunmadığını bildirir; böylece arka planda kendiliğinden
   yenilenen ekranlar (bildirim zili, panolar) oturumu açık tutmaz. Başlıksız istek (yönetim paneli,
   API istemcisi) etkinlik sayılır. Mutlak süre `SESSION_COOKIE_AGE` (12 saat) ayrıca geçerlidir.
2. **Zorunlu iki aşamalı doğrulama**: rolü gerektiren ama doğrulayıcıyı kurmamış kullanıcı, kurulum
   ve oturum uçları dışındaki API'leri kullanamaz (`403 {"code": "otp_setup_required"}`).

`AuthenticationMiddleware`'den sonra gelmelidir.
"""

import time
from collections.abc import Callable

from django.contrib import auth
from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.core import security
from apps.core.models import User

LAST_ACTIVITY_KEY = "_last_activity"
IDLE_HEADER = "HTTP_X_ERP_IDLE_SECONDS"
# Oturum her istekte yazılmasın: etkinlik zamanı en çok bu sıklıkla güncellenir.
_TOUCH_INTERVAL_SECONDS = 30
# İki aşamalı doğrulama kurulana kadar açık kalan API yolları.
_OTP_SETUP_ALLOWED_PREFIXES = ("/api/v1/auth/", "/api/v1/health/")


def _json(status: int, code: str, detail: str) -> JsonResponse:
    return JsonResponse(
        {"code": code, "detail": detail}, status=status, json_dumps_params={"ensure_ascii": False}
    )


def _reported_idle_seconds(request: HttpRequest) -> float:
    raw = request.META.get(IDLE_HEADER, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, value)


class SessionSecurityMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if isinstance(user, User) and user.is_authenticated:
            expired = self._enforce_idle_timeout(request)
            if expired is not None:
                return expired
            blocked = self._enforce_otp_setup(request, user)
            if blocked is not None:
                return blocked
        return self.get_response(request)

    def _enforce_idle_timeout(self, request: HttpRequest) -> HttpResponse | None:
        now = time.time()
        limit = security.idle_timeout_seconds(request)
        last = request.session.get(LAST_ACTIVITY_KEY)
        if isinstance(last, int | float) and now - last > limit:
            request._logout_reason = "Hareketsizlik nedeniyle oturum kapandı"  # type: ignore[attr-defined]
            auth.logout(request)
            if request.path.startswith("/api/"):
                return _json(
                    401,
                    "session_expired",
                    "Uzun süre işlem yapılmadığı için oturumunuz kapandı. "
                    "Lütfen yeniden giriş yapın.",
                )
            return None  # yönetim paneli kendi giriş sayfasına yönlendirir
        activity = now - _reported_idle_seconds(request)
        if not isinstance(last, int | float) or activity - last >= _TOUCH_INTERVAL_SECONDS:
            request.session[LAST_ACTIVITY_KEY] = activity
        return None

    def _enforce_otp_setup(self, request: HttpRequest, user: User) -> HttpResponse | None:
        path = request.path
        if not path.startswith("/api/") or path.startswith(_OTP_SETUP_ALLOWED_PREFIXES):
            return None
        if security.otp_setup_required(user):
            return _json(
                403,
                "otp_setup_required",
                "Rolünüz için iki aşamalı doğrulama zorunlu. Önce Güvenlik sayfasından kurun.",
            )
        return None
