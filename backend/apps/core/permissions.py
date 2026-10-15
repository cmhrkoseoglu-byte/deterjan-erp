"""Rol bazlı API izinleri.

Kullanım:

    class StockView(APIView):
        permission_classes = [HasRole("depo", "planlama")]

`admin` rolündeki kullanıcılar ve superuser'lar rol korumalı her uç noktaya erişir.
Giriş yapılmamışsa 401, rol yetkisi yoksa 403 döner.
"""

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from apps.core.models import User
from apps.core.roles import ALL_ROLES


def user_has_role(user: Any, roles: tuple[str, ...]) -> bool:
    """Kullanıcı aktif, giriş yapmış ve rollerden birine sahip (ya da admin) ise True."""
    if not isinstance(user, User) or not user.is_authenticated or not user.is_active:
        return False
    return user.is_admin or user.has_role(*roles)


def HasRole(*roles: str) -> type[BasePermission]:  # noqa: N802 - sınıf gibi kullanılır
    """Verilen rollerden birine sahip kullanıcılara izin veren DRF izin sınıfı üretir."""
    unknown = set(roles) - set(ALL_ROLES)
    if unknown:
        raise ValueError(f"Tanımsız rol: {', '.join(sorted(unknown))}")
    if not roles:
        raise ValueError("En az bir rol verilmelidir.")

    class _HasRole(BasePermission):
        message = "Bu işlem için yetkiniz yok."
        required_roles = roles

        def has_permission(self, request: Request, view: Any) -> bool:
            return user_has_role(request.user, roles)

    _HasRole.__name__ = _HasRole.__qualname__ = f"HasRole({', '.join(roles)})"
    return _HasRole
