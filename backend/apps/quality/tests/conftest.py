from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest

from apps.core import events
from apps.core.models import User
from apps.core.roles import LABORATUVAR, PLANLAMA, YONETIM
from apps.inventory.testing import assert_stock_invariants


@pytest.fixture
def lab(make_user: Callable[..., User]) -> User:
    return make_user(LABORATUVAR, username="laboratuvar")


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user(YONETIM, username="yonetim")


@pytest.fixture
def planner(make_user: Callable[..., User]) -> User:
    return make_user(PLANLAMA, username="planlama")


@pytest.fixture
def published() -> list[events.Event]:
    """Yayınlanan olaylar (commit sonrası çalışan handler'larla toplanır)."""
    received: list[events.Event] = []
    events.subscribe("*")(received.append)
    return received


@pytest.fixture
def commit(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> Callable[[], AbstractContextManager[Any]]:
    """`with commit(): ...` bloğundaki commit sonrası işleri (olaylar) hemen çalıştırır."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture(autouse=True)
def invariants(db: None) -> Iterator[None]:
    """Her kalite testinin sonunda stok değişmezlerini doğrular (CLAUDE.md §7)."""
    yield
    assert_stock_invariants()
