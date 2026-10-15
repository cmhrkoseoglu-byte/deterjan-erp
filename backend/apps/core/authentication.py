"""API kimlik doğrulama: Django session + CSRF."""

from rest_framework import authentication, exceptions
from rest_framework.request import Request


class CsrfFailed(exceptions.PermissionDenied):
    """CSRF doğrulaması başarısız (403). Rol yetkisi eksikliğinden (`permission_denied`) ayrı kod
    taşır; SPA bu durumda CSRF çerezini yenileyip isteği tekrarlayabilir."""

    default_code = "csrf_failed"
    default_detail = "Güvenlik doğrulaması başarısız. Sayfayı yenileyip tekrar deneyin."


class SessionAuthentication(authentication.SessionAuthentication):
    """DRF session kimlik doğrulaması.

    - Giriş yapılmamış isteklerde 403 yerine 401 döner: DRF, `WWW-Authenticate` başlığı
      üretemeyen kimlik doğrulayıcılarda 401'i 403'e çevirir. Bu başlığı vererek SPA'nın
      "oturum yok" (401) ile "yetki yok" (403) durumunu ayırt etmesi sağlanır.
    - CSRF hatası `csrf_failed` koduyla ve Türkçe mesajla döner.
    """

    def authenticate_header(self, request: Request) -> str:
        return "Session"

    def enforce_csrf(self, request: Request) -> None:
        try:
            super().enforce_csrf(request)
        except exceptions.PermissionDenied as exc:
            raise CsrfFailed() from exc
