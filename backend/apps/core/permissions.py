"""API ve servis izinleri.

Rol bazlı (bugünkü):

    class StockView(APIView):
        permission_classes = [HasRole("depo", "planlama")]

Bölüm ve düzey bazlı (docs/plan/kisi-yetkileri.md §5.4; modüller adım adım geçer):

    class ProductionOrderViewSet(AccessMixin, viewsets.ModelViewSet):
        read_access = ReadRule(ORDERS, PREP, BATCHES)
        action_access = {"create": HasAccess(ORDERS, CHANGE), "approve": HasAccess(ORDERS, APPROVE)}

    # services.py
    require_access(actor, ORDERS, APPROVE, "Üretim emrini onaylama yetkiniz yok.")

`admin` rolündeki kullanıcılar ve superuser'lar her uç noktaya erişir. Giriş yapılmamışsa 401,
yetki yoksa 403 döner; 403 yanıtı bölüm denetiminde eksik yetkiyi `required` listesinde söyler.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import (
    SAFE_METHODS,
    BasePermission,
    OperandHolder,
    SingleOperandHolder,
)
from rest_framework.request import Request

from apps.core import access
from apps.core.access import READ, VIEW, ReadScope, SectionRef
from apps.core.models import User
from apps.core.roles import ALL_ROLES

DEFAULT_MESSAGE = "Bu işlem için yetkiniz yok."
REQUIRED_ATTR = "_access_required"

# DRF izin sınıfı ya da `A | B`, `A & B`, `~A` birleşimi.
PermissionClass = type[BasePermission] | OperandHolder | SingleOperandHolder


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
        message = DEFAULT_MESSAGE
        required_roles = roles

        def has_permission(self, request: Request, view: Any) -> bool:
            return user_has_role(request.user, roles)

    _HasRole.__name__ = _HasRole.__qualname__ = f"HasRole({', '.join(roles)})"
    return _HasRole


# --- bölüm ve düzey bazlı yetki -------------------------------------------------------------------


def _active_user(user: Any) -> User | None:
    if not isinstance(user, User) or not user.is_authenticated or not user.is_active:
        return None
    return user


def has_access(user: Any, section: SectionRef, level: str = VIEW) -> bool:
    """Kullanıcı aktif, giriş yapmış ve bölümün bu düzeyine sahip mi (admin her zaman)?"""
    active = _active_user(user)
    return active is not None and active.access.allows(section, level)


def can_read(user: Any, *sections: SectionRef) -> bool:
    """Bölümlerden birinin kayıtlarını okuyabilir mi (Görür ya da okuma kapsamı)?"""
    active = _active_user(user)
    return active is not None and active.access.can_read(*sections)


class MissingAccess(PermissionDenied):
    """Servis denetiminde eksik yetki. API 403 döner; `required` eksik yetkiyi söyler."""

    def __init__(self, message: str, required: tuple[tuple[str, str], ...]) -> None:
        super().__init__(message)
        self.required = required


def require_access(
    actor: Any, section: SectionRef, level: str = VIEW, message: str | None = None
) -> None:
    """Servis denetimi: yetki yoksa `MissingAccess` fırlatır. Mesaj rol adı değil işi söyler
    (ör. "Üretim emrini onaylama yetkiniz yok.")."""
    if not has_access(actor, section, level):
        target = access.section(section)
        raise MissingAccess(message or DEFAULT_MESSAGE, ((target.key, level),))


def _note_required(request: Request, allowed: bool, required: tuple[tuple[str, str], ...]) -> None:
    """İzin kararını isteğe yazar; hata işleyici reddedilen isteğin 403 yanıtına eksik yetkiyi
    ekler. Geçen izin listeyi temizler: `A | B`'de A reddedip B geçerse istek izinlidir."""
    if allowed:
        setattr(request, REQUIRED_ATTR, [])
        return
    noted: list[tuple[str, str]] = getattr(request, REQUIRED_ATTR, None) or []
    noted.extend(item for item in required if item not in noted)
    setattr(request, REQUIRED_ATTR, noted)


class AccessPermission(BasePermission):
    """Bölüm denetimi yapan izin sınıflarının ortak atası (sistem denetimi bunu tanır)."""

    message = DEFAULT_MESSAGE
    required_access: ClassVar[tuple[tuple[str, str], ...]] = ()


def HasAccess(section: SectionRef, level: str = VIEW) -> type[BasePermission]:  # noqa: N802
    """Bölümün bu düzeyine sahip kullanıcılara izin veren DRF izin sınıfı üretir."""
    target = access.section(section)
    if level not in target.levels:
        raise ValueError(f"{target.key}: düzey bölümde yok ({level}).")
    required = ((target.key, level),)

    class _HasAccess(AccessPermission):
        required_access = required

        def has_permission(self, request: Request, view: Any) -> bool:
            allowed = has_access(request.user, target, level)
            if _active_user(request.user) is not None:
                _note_required(request, allowed, required)
            return allowed

    _HasAccess.__name__ = _HasAccess.__qualname__ = f"HasAccess({target.key}, {level})"
    return _HasAccess


def ReadRule(*sections: SectionRef) -> type[BasePermission]:  # noqa: N802
    """Okuma izni: bölümlerden herhangi birinde okuma yeter (ör. emir okuması Üretim emirleri,
    Malzeme hazırlama ya da Şarj ve tartım ile)."""
    if not sections:
        raise ValueError("En az bir bölüm verilmelidir.")
    targets = tuple(access.section(item) for item in sections)
    # Eksik yetki ipucu verilebilecek yetkiyi söyler: bölümde Görür, açık okumalı bölümde ayrıca
    # modülün "Açık kayıtlar" satırı.
    hints: list[tuple[str, str]] = []
    for target in targets:
        hints.append((target.key, VIEW))
        records = access.open_records_section(target.module)
        if target.read is ReadScope.OPEN and records is not None:
            hints.append((records.key, READ))
    required = tuple(dict.fromkeys(hints))

    class _ReadRule(AccessPermission):
        required_access = required

        def has_permission(self, request: Request, view: Any) -> bool:
            allowed = can_read(request.user, *targets)
            if _active_user(request.user) is not None:
                _note_required(request, allowed, required)
            return allowed

    names = ", ".join(target.key for target in targets)
    _ReadRule.__name__ = _ReadRule.__qualname__ = f"ReadRule({names})"
    return _ReadRule


def SignedIn(reason: str) -> type[BasePermission]:  # noqa: N802
    """Giriş yapan herkese açık uç noktanın açık işareti (bugünkü `IsAuthenticated` ile aynı).

    `reason` neden herkese açık olduğunu söyler (ör. "kişinin kendi hesabı"); sistem denetimi
    işaretsiz uç noktayı yakalar.
    """
    if not reason.strip():
        raise ValueError("Herkese açık uç noktanın nedeni yazılmalıdır.")

    class _SignedIn(AccessPermission):
        signed_in_reason = reason

        def has_permission(self, request: Request, view: Any) -> bool:
            return bool(request.user and request.user.is_authenticated)

    _SignedIn.__name__ = _SignedIn.__qualname__ = f"SignedIn({reason})"
    return _SignedIn


class AdminOnly(AccessPermission):
    """Yalnız sistem yöneticisi (admin rolü ya da süper kullanıcı)."""

    def has_permission(self, request: Request, view: Any) -> bool:
        active = _active_user(request.user)
        return active is not None and active.is_admin


class DenyUnknownAction(AccessPermission):
    """`AccessMixin`'de tanımlanmamış yazma eylemi: kapalı varsayılan."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return False


class AccessMixin:
    """ViewSet'lerde eylem ve metot bazında bölüm denetimi; bugünkü kararlar birebir çevrilir.

    İzin şu sırayla aranır:

    1. `action_access["<eylem>:<metot>"]`, ör. `"picks:post"`: aynı eylemde GET ve POST ayrıdır;
    2. `action_access["<eylem>"]`, ör. `"approve"`;
    3. metot `read_methods` içindeyse `read_access` (varsayılan GET, HEAD, OPTIONS; bugün yalnız
       GET'i okuma sayan görünüm `frozenset({"GET"})` verir);
    4. `write_access`: listede olmayan öteki istekler (bugün tek bir yazma rolüyle korunanlar);
    5. hiçbiri yoksa reddedilir; böylece yeni bir eylem yetkisiz açılamaz.

    DRF, HEAD isteğini GET'in eylemine, OPTIONS isteğini `metadata` eylemine gönderir. Değerler
    izin sınıfı ya da `HasAccess(A) | HasAccess(B)` gibi birleşimlerdir.
    """

    read_access: ClassVar[PermissionClass | None] = None
    read_methods: ClassVar[frozenset[str]] = frozenset(SAFE_METHODS)
    write_access: ClassVar[PermissionClass | None] = None
    action_access: ClassVar[Mapping[str, PermissionClass]] = {}

    def get_permissions(self) -> list[Any]:
        request = getattr(self, "request", None)
        method = str(getattr(request, "method", "") or "").upper()
        action = getattr(self, "action", None)
        if action is not None:
            for key in (f"{action}:{method.lower()}", action):
                if key in self.action_access:
                    return [self.action_access[key]()]
        if method in self.read_methods and self.read_access is not None:
            return [self.read_access()]
        if self.write_access is not None:
            return [self.write_access()]
        return [DenyUnknownAction()]
