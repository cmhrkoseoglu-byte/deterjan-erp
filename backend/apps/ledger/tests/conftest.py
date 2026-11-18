from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest

from apps.core.models import User
from apps.core.roles import DEPO, SATIN_ALMA, SEVKIYAT, YONETIM
from apps.inventory.testing import assert_stock_invariants
from apps.ledger.testing import assert_ledger_invariants


@pytest.fixture
def shipper(make_user: Callable[..., User]) -> User:
    return make_user(SEVKIYAT, username="sevkiyat")


@pytest.fixture
def picker(make_user: Callable[..., User]) -> User:
    return make_user(DEPO, username="depo")


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user(YONETIM, username="yonetim")


@pytest.fixture
def buyer(make_user: Callable[..., User]) -> User:
    return make_user(SATIN_ALMA, username="satinalma")


@pytest.fixture
def commit(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> Callable[[], AbstractContextManager[Any]]:
    """`with commit(): ...` bloğundaki commit sonrası işleri (olaylar) hemen çalıştırır."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def invariants(db: None) -> Iterator[None]:
    """Test sonunda stok ve cari defter değişmezlerini doğrular (CLAUDE.md §7)."""
    yield
    assert_stock_invariants()
    assert_ledger_invariants()
