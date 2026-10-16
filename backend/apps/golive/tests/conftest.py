from collections.abc import Iterator

import pytest

from apps.inventory.testing import assert_stock_invariants


@pytest.fixture
def invariants(db: None) -> Iterator[None]:
    yield
    assert_stock_invariants()
