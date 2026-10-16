from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest

from apps.core.models import User
from apps.core.roles import DEPO, DOLUM, LABORATUVAR, PLANLAMA, SATIN_ALMA, URETIM, YONETIM
from apps.inventory.testing import assert_stock_invariants


@pytest.fixture
def staff(make_user: Callable[..., User]) -> dict[str, User]:
    return {
        role: make_user(role, username=role)
        for role in (DEPO, URETIM, LABORATUVAR, PLANLAMA, YONETIM, DOLUM, SATIN_ALMA)
    }


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
