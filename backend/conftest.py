"""Tüm modüllerin testlerinde ortak pytest fixture'ları."""

from collections.abc import Callable, Iterator

import pytest
from rest_framework.test import APIClient

from apps.core import events
from apps.core.management.commands.seed_roles import seed_roles
from apps.core.models import User
from apps.core.tests.factories import UserFactory


@pytest.fixture
def roles(db: None) -> None:
    """Sistem rollerini oluşturur."""
    seed_roles()


@pytest.fixture
def make_user(roles: None) -> Callable[..., User]:
    """`make_user("depo", "planlama")` → bu rollere sahip kullanıcı."""

    def _make(*role_names: str, **kwargs: object) -> User:
        return UserFactory(roles=list(role_names), **kwargs)

    return _make


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def client_for(make_user: Callable[..., User]) -> Callable[..., APIClient]:
    """`client_for("depo")` → bu rollere sahip, giriş yapmış API istemcisi."""

    def _client(*role_names: str, **kwargs: object) -> APIClient:
        client = APIClient()
        client.force_authenticate(make_user(*role_names, **kwargs))
        return client

    return _client


@pytest.fixture(autouse=True)
def isolated_event_subscribers() -> Iterator[None]:
    """Testte eklenen olay handler'larının diğer testlere sızmasını önler."""
    saved = {name: list(handlers) for name, handlers in events._subscribers.items()}
    yield
    events._subscribers.clear()
    events._subscribers.update(saved)
