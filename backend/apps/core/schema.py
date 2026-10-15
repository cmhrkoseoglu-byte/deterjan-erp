"""drf-spectacular uzantıları (OpenAPI şeması için)."""

from drf_spectacular.authentication import SessionScheme


class CoreSessionScheme(SessionScheme):
    """Projenin session kimlik doğrulamasını şemada `cookieAuth` olarak tanıtır."""

    target_class = "apps.core.authentication.SessionAuthentication"
