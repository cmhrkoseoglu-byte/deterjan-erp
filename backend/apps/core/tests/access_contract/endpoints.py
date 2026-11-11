"""API uç noktalarının izin kararları (sözleşme testinin 1. parçası, plan §5.5).

Her uç nokta için DRF'nin izin katmanı gerçek istek akışıyla çalıştırılır: görünüm sınıfı
yönlendiricinin verdiği ayarlarla kurulur, istek personayla doğrulanır ve `check_permissions`
çağrılır. Böylece karar, iznin nasıl yazıldığından (`HasRole`, `get_permissions`, eylem
bazında izin) bağımsız olarak dondurulur. Görünümün gövdesindeki ya da servisteki denetimler
burada değil, sondalarda ve paket denkliğinde sınanır.
"""

import re
from typing import Any

from django.contrib.auth.models import AnonymousUser
from rest_framework import exceptions
from rest_framework.schemas.generators import EndpointEnumerator
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

API_PREFIX = "/api/v1/"
PARAM = re.compile(r"{(\w+)}")

ALLOW = "allow"
UNAUTHENTICATED = "401"
FORBIDDEN = "403"


class _AllEndpoints(EndpointEnumerator):
    """Şemadan çıkarılanlar dahil, `/api/v1/` altındaki bütün DRF uç noktaları."""

    def should_include_endpoint(self, path: str, callback: Any) -> bool:
        cls = getattr(callback, "cls", None)
        if cls is None or not issubclass(cls, APIView):
            return False
        if path.endswith(".{format}") or path.endswith(".{format}/"):
            return False
        return path.startswith(API_PREFIX)


def endpoints() -> list[tuple[str, str, Any]]:
    """`(metot, yol, callback)` üçlüleri; yol ve metoda göre sıralı, tekrarsız.

    GET'i olan her yola HEAD, her yola OPTIONS eklenir: izin katmanı bunları da denetler ve bazı
    görünümler yalnız `GET`'i okuma sayar (HEAD ve OPTIONS yazma rolleriyle denetlenir).
    """
    seen: dict[tuple[str, str], Any] = {}
    for path, method, callback in _AllEndpoints().get_api_endpoints():
        seen.setdefault((method.upper(), path), callback)
    for (method, path), callback in list(seen.items()):
        if method == "GET":
            seen.setdefault(("HEAD", path), callback)
        seen.setdefault(("OPTIONS", path), callback)
    return sorted(
        ((method, path, callback) for (method, path), callback in seen.items()),
        key=lambda item: (item[1], item[0]),
    )


_factory = APIRequestFactory()


def decide(method: str, path: str, callback: Any, user: Any) -> str:
    """Personanın bu uç noktadaki izin kararı: `allow`, `401` ya da `403`.

    Kimlik canlıdaki gibi doğrulanır: oturum ara katmanı kullanıcıyı isteğe yazar, görünümün kendi
    kimlik doğrulayıcısı (SessionAuthentication) onu kabul eder ya da düşürür. Pasif kullanıcı bu
    yüzden anonim sayılır; `force_authenticate` bunu atlardı.
    """
    request = _factory.generic(method, PARAM.sub("1", path))
    request.user = user if user is not None else AnonymousUser()
    view = callback.cls(**getattr(callback, "initkwargs", {}))
    view.args = ()
    view.kwargs = {name: "1" for name in PARAM.findall(path)}
    view.headers = {}
    actions = dict(getattr(callback, "actions", None) or {})
    if actions:
        # DRF'nin yönlendiricisi gibi: HEAD, GET'in eylemine gider; OPTIONS `metadata` eylemidir.
        if "get" in actions and "head" not in actions:
            actions["head"] = actions["get"]
        view.action_map = actions
    drf_request = view.initialize_request(request, *view.args, **view.kwargs)
    view.request = drf_request
    view.format_kwarg = None
    try:
        view.perform_authentication(drf_request)
        view.check_permissions(drf_request)
    except (exceptions.NotAuthenticated, exceptions.AuthenticationFailed):
        return UNAUTHENTICATED
    except exceptions.PermissionDenied:
        return FORBIDDEN
    return ALLOW
