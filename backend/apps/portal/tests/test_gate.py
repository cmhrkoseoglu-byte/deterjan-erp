"""Varsayılan ret: portal kullanıcısı yalnız giriş ve kendi portal uç noktalarını açar; bütün
öteki uç noktalar, yönetim paneli ve bildirim kanalı kapalıdır (docs/plan/musteri-siparis-takibi.md
§4.2). Uç nokta listesi yetki sözleşmesinin sayımından gelir: yeni eklenen her uç nokta bu testte
kendiliğinden yer alır."""

import re
import time

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client

from apps.core.middleware import LAST_ACTIVITY_KEY
from apps.core.models import User
from apps.core.tests.access_contract.endpoints import endpoints
from apps.masterdata.models import Customer
from apps.portal.middleware import is_allowed
from apps.portal.models import PortalAccount
from apps.portal.tests.helpers import session_client

pytestmark = pytest.mark.django_db

PARAM = re.compile(r"{(\w+)}")


def _concrete(path: str) -> str:
    return PARAM.sub("1", path)


@pytest.mark.parametrize("fixture", ["customer_account", "supplier_account"])
def test_every_other_endpoint_is_closed(fixture: str, request: pytest.FixtureRequest) -> None:
    account: PortalAccount = request.getfixturevalue(fixture)
    user = account.user
    client = session_client(user)
    checked = 0
    for method, path, _ in endpoints():
        url = _concrete(path)
        if is_allowed(user, url):
            continue
        response = client.generic(method, url)
        assert response.status_code == 403, (method, url, response.status_code)
        if method != "HEAD":  # HEAD yanıtının gövdesi yok
            assert response.json()["code"] == "portal_forbidden", (method, url)
        checked += 1
    assert checked > 300  # sayım boş dönmesin


def test_allowed_list_is_small(customer_account: PortalAccount) -> None:
    """İzin verilen DRF uç noktaları yalnız giriş, güvenlik, sağlık ve portal uçlarıdır."""
    user = customer_account.user
    allowed = sorted({path for _, path, _ in endpoints() if is_allowed(user, _concrete(path))})
    for path in allowed:
        assert path.startswith(
            (
                "/api/v1/auth/",
                "/api/v1/health/",
                "/api/v1/site/",
                "/api/v1/ops/client-errors/",
                "/api/v1/portal/me/",
                "/api/v1/portal/customer/",
            )
        ), path
    assert "/api/v1/auth/me/access/" not in allowed
    assert "/api/v1/auth/field-device/" not in allowed
    assert not any(path.startswith("/api/v1/portal/accounts/") for path in allowed)


def test_me_and_portal_me(customer_account: PortalAccount, customer: Customer) -> None:
    client = session_client(customer_account.user)

    me = client.get("/api/v1/auth/me/").json()
    assert me["account_type"] == "customer_portal"
    assert me["access"] == {} and me["roles"] == []
    assert me["idle_timeout_seconds"] == 30 * 60

    portal = client.get("/api/v1/portal/me/").json()
    assert portal == {
        "kind": "customer",
        "firm_code": customer.code,
        "firm_name": customer.name,
    }


def test_kind_prefixes_are_separate(
    customer_account: PortalAccount, supplier_account: PortalAccount
) -> None:
    customer_client = session_client(customer_account.user)
    supplier_client = session_client(supplier_account.user)

    blocked = customer_client.get("/api/v1/portal/supplier/orders/")
    assert blocked.status_code == 403 and blocked.json()["code"] == "portal_forbidden"
    assert supplier_client.get("/api/v1/portal/supplier/orders/").status_code == 404  # henüz yok
    assert supplier_client.get("/api/v1/portal/customer/orders/").status_code == 403


def test_staff_cannot_open_portal_me(make_user: type[User]) -> None:
    staff = make_user("sevkiyat")  # type: ignore[operator]
    client = Client()
    client.force_login(staff)
    assert client.get("/api/v1/portal/me/").status_code == 403


def test_temporary_password_comes_first(customer_account: PortalAccount) -> None:
    client = session_client(customer_account.user, password_changed=False)
    response = client.get("/api/v1/portal/me/")
    assert response.status_code == 403
    assert response.json()["code"] == "password_change_required"
    assert client.get("/api/v1/auth/me/").status_code == 200


def test_inactive_firm_locks_account(customer_account: PortalAccount, customer: Customer) -> None:
    client = session_client(customer_account.user)
    Customer.objects.filter(pk=customer.pk).update(is_active=False)

    response = client.get("/api/v1/portal/me/")
    assert response.status_code == 403
    assert response.json()["code"] == "portal_account_inactive"
    assert client.get("/api/v1/auth/me/").json()["code"] == "portal_account_inactive"
    assert client.post("/api/v1/auth/logout/").status_code in (200, 204)


def test_admin_site_is_closed(customer_account: PortalAccount) -> None:
    client = session_client(customer_account.user)
    assert client.get("/admin/").status_code == 403
    assert client.get("/api/schema/").status_code == 403


def test_portal_idle_timeout_is_30_minutes(
    customer_account: PortalAccount, make_user: type[User]
) -> None:
    def idle(user: User, minutes: int) -> int:
        client = session_client(user)
        session = client.session
        session[LAST_ACTIVITY_KEY] = time.time() - minutes * 60
        session.save()
        return client.get("/api/v1/auth/me/").status_code

    assert idle(customer_account.user, 31) == 401
    staff = make_user("sevkiyat")  # type: ignore[operator]
    assert idle(staff, 31) == 200


@pytest.mark.django_db(transaction=True)
def test_websocket_rejects_portal_user(make_user: type[User]) -> None:
    from apps.masterdata.tests.factories import CustomerFactory
    from apps.portal import services
    from config.asgi import application

    admin = make_user("admin", username="ws.admin")  # type: ignore[operator]
    account, _ = services.create_account(
        admin,
        username="ws.portal",
        full_name="WS Portal",
        customer=CustomerFactory.create(),
    )
    client = session_client(account.user)
    cookie = f"sessionid={client.cookies['sessionid'].value}"

    async def scenario() -> bool:
        communicator = WebsocketCommunicator(
            application,
            "/ws/notifications/",
            headers=[
                (b"cookie", cookie.encode()),
                (b"origin", b"http://localhost"),
                (b"host", b"localhost"),
            ],
        )
        connected, _ = await communicator.connect()
        await communicator.disconnect()
        return bool(connected)

    assert async_to_sync(scenario)() is False
