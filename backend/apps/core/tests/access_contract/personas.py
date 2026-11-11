"""Sözleşme testinin kullanıcı tipleri (persona).

Sıra sabittir: anlık görüntüler bu sırayla yazılır. Persona eklemek ya da çıkarmak bütün anlık
görüntüleri değiştirir; bu da sahibin onayını ister.
"""

from typing import Any, cast

from rest_framework.test import APIClient

from apps.core.management.commands.seed_roles import seed_roles
from apps.core.models import User
from apps.core.roles import ADMIN, ALL_ROLES
from apps.core.tests.factories import UserFactory

# Admin dışındaki 8 rol (yonetim, planlama, depo, uretim, laboratuvar, dolum, sevkiyat, satin_alma).
ROLES: tuple[str, ...] = tuple(role for role in ALL_ROLES if role != ADMIN)

PERSONAS: tuple[str, ...] = (
    "anonymous",
    "inactive",
    "no_role",
    *ROLES,
    "admin",
    "superuser",
    "depo+sevkiyat",
)


def _user(**kwargs: Any) -> User:
    return cast(User, UserFactory(**kwargs))


def make_personas() -> dict[str, User | None]:
    """Her persona için bir kullanıcı (anonim: `None`). Rolleri oluşturur; `db` erişimi ister.

    - `inactive`: depo rolündeki pasif kullanıcı;
    - `no_role`: rolü olmayan etkin kullanıcı;
    - `superuser`: rolü olmayan süper kullanıcı;
    - `depo+sevkiyat`: iki rollü kullanıcı (paketlerin birleşimi).
    """
    seed_roles()
    users: dict[str, User | None] = {"anonymous": None}
    users["inactive"] = _user(username="persona_inactive", roles=["depo"], is_active=False)
    users["no_role"] = _user(username="persona_no_role")
    for role in ROLES:
        users[role] = _user(username=f"persona_{role}", roles=[role])
    users["admin"] = _user(username="persona_admin", roles=[ADMIN])
    users["superuser"] = _user(username="persona_superuser", is_superuser=True, is_staff=True)
    users["depo+sevkiyat"] = _user(username="persona_depo_sevkiyat", roles=["depo", "sevkiyat"])
    assert tuple(users) == PERSONAS
    return users


def persona_client(user: User | None) -> APIClient:
    """Personanın API istemcisi, canlıdaki gibi: pasif kullanıcı giriş yapamaz, anonim sayılır.

    Canlıda Django oturum doğrulaması (`ModelBackend.get_user`) ve DRF'nin SessionAuthentication'ı
    pasif kullanıcıyı düşürür; `force_authenticate` ikisini de atlar. Bu yüzden pasif kullanıcıya
    kimlik verilmez.
    """
    client = APIClient()
    if user is not None and user.is_active:
        client.force_authenticate(user)
    return client
