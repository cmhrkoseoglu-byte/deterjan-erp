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


class FakePrinter:
    """Yerelde TCP dinleyen sahte etiket yazıcısı; gelen ham veriyi toplar."""

    def __init__(self) -> None:
        import socket
        import threading

        self.received: list[bytes] = []
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self._server.settimeout(5)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._running = True
        self._thread.start()

    def _serve(self) -> None:
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            chunks = []
            with conn:
                while data := conn.recv(65536):
                    chunks.append(data)
            self.received.append(b"".join(chunks))

    def text(self) -> str:
        import time

        for _ in range(50):
            if self.received:
                break
            time.sleep(0.02)
        return b"".join(self.received).decode("utf-8")

    def close(self) -> None:
        self._running = False
        self._server.close()


@pytest.fixture
def fake_printer() -> Iterator[FakePrinter]:
    printer = FakePrinter()
    yield printer
    printer.close()
