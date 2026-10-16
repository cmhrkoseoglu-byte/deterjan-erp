from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest

from apps.core.models import User
from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA, SEVKIYAT
from apps.inventory.testing import assert_stock_invariants
from apps.returns.tests.factories import Setup, build_setup


@pytest.fixture
def shipper(make_user: Callable[..., User]) -> User:
    return make_user(SEVKIYAT, username="sevkiyat")


@pytest.fixture
def depo(make_user: Callable[..., User]) -> User:
    return make_user(DEPO, username="depo")


@pytest.fixture
def lab(make_user: Callable[..., User]) -> User:
    return make_user(LABORATUVAR, username="laboratuvar")


@pytest.fixture
def planner(make_user: Callable[..., User]) -> User:
    return make_user(PLANLAMA, username="planlama")


@pytest.fixture
def setup(db: None) -> Setup:
    return build_setup()


@pytest.fixture
def commit(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> Callable[[], AbstractContextManager[Any]]:
    """`with commit(): ...` bloğundaki commit sonrası işleri (olaylar) hemen çalıştırır."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def invariants(db: None) -> Iterator[None]:
    """Test sonunda stok değişmezlerini doğrular (CLAUDE.md §7)."""
    yield
    assert_stock_invariants()
