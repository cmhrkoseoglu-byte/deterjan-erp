"""Portal kullanıcısı için varsayılan ret (docs/plan/musteri-siparis-takibi.md §4.2).

Müşteri ve tedarikçi yetkilisi yalnız aşağıda adı geçen yolları açar: giriş, çıkış, şifre,
isteğe bağlı iki aşamalı doğrulama, sağlık ve site bilgisi, istemci hata kaydı ve kendi hesap
türünün portal uç noktaları. Geri kalan her istek — herkese açık okumalar, bildirimler, görevler,
ekler, yönetim paneli, API şeması — `403 {"code": "portal_forbidden"}` alır. Uç noktalar tek tek
işaretlenmez; yeni eklenen her uç nokta portal kullanıcısına kendiliğinden kapalıdır
(`portal/tests/test_gate.py` bütün uç noktaları gezer).

Bağlı firma (ya da hesap) pasife alınmışsa portal kullanıcısı yalnız çıkış yapabilir
(`403 {"code": "portal_account_inactive"}`).

`core.middleware.SessionSecurityMiddleware`'den sonra gelir: geçici şifre ve hareketsizlik
kuralları önce uygulanır.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.core.models import User
from apps.portal import selectors

_API = "/api/v1/"
# Portal kullanıcısının açabildiği yollar (tam eşleşme).
ALLOWED_PATHS = frozenset(
    _API + path
    for path in (
        "auth/csrf/",
        "auth/login/",
        "auth/logout/",
        "auth/me/",
        "auth/security/",
        "auth/password/",
        "health/",
        "site/",
        "ops/client-errors/",
        "portal/me/",
    )
)
# Önekle açılanlar: iki aşamalı doğrulama (isteğe bağlı) ve hesap türünün portal uç noktaları.
ALLOWED_PREFIXES = (_API + "auth/otp/",)
KIND_PREFIXES = {
    User.AccountType.CUSTOMER_PORTAL: _API + "portal/customer/",
    User.AccountType.SUPPLIER_PORTAL: _API + "portal/supplier/",
}
# Hesap kapalıyken bile açık kalanlar.
ALWAYS_ALLOWED = frozenset({_API + "auth/csrf/", _API + "auth/logout/", _API + "health/"})


def _json(code: str, detail: str) -> JsonResponse:
    return JsonResponse(
        {"code": code, "detail": detail},
        status=403,
        json_dumps_params={"ensure_ascii": False},
    )


def is_allowed(user: User, path: str) -> bool:
    """Portal kullanıcısı bu yolu açabilir mi (hesap durumundan bağımsız)."""
    if path in ALLOWED_PATHS or path.startswith(ALLOWED_PREFIXES):
        return True
    prefix = KIND_PREFIXES.get(User.AccountType(user.account_type))
    return prefix is not None and path.startswith(prefix)


class PortalGateMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if isinstance(user, User) and user.is_authenticated and user.is_portal:
            blocked = self._check(request, user)
            if blocked is not None:
                return blocked
        return self.get_response(request)

    def _check(self, request: HttpRequest, user: User) -> HttpResponse | None:
        path = request.path
        if path in ALWAYS_ALLOWED:
            return None
        if not is_allowed(user, path):
            return _json("portal_forbidden", "Bu sayfa portal hesabına açık değil.")
        if not selectors.is_usable(selectors.account_of(user)):
            return _json(
                "portal_account_inactive",
                "Portal hesabınız kullanıma kapalı. Firmanızdaki yetkiliye başvurun.",
            )
        return None
