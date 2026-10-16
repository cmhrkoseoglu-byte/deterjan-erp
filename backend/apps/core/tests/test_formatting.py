from decimal import Decimal

import pytest

from apps.core.formatting import format_money


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1250000"), "1.250.000,00"),
        (Decimal("999.5"), "999,50"),
        (Decimal("-12345.678"), "-12.345,68"),
        ("125000.00", "125.000,00"),
        (None, ""),
        ("", ""),
        ("abc", "abc"),
    ],
)
def test_format_money(value, expected):
    assert format_money(value) == expected
