"""Anlık görüntü aracının kendisi: fark bulma ve izin listesi."""

import pytest

from apps.core.tests.access_contract import allowlist, snapshot
from apps.core.tests.access_contract.allowlist import MISSING, Allowed


def test_changed_value_is_reported() -> None:
    unexpected, allowed = snapshot.differences(
        "endpoints",
        {"GET /api/v1/x/": {"depo": "403", "planlama": "allow"}},
        {"GET /api/v1/x/": {"depo": "allow", "planlama": "allow"}},
    )
    assert unexpected == ["GET /api/v1/x/ [depo]: 403 → allow"]
    assert allowed == []


def test_missing_and_new_cases_are_reported() -> None:
    unexpected, _ = snapshot.differences(
        "endpoints",
        {"GET /api/v1/old/": {"depo": "allow"}},
        {"GET /api/v1/new/": {"depo": "allow"}},
    )
    assert unexpected == [
        f"GET /api/v1/new/ [depo]: {MISSING} → allow",
        f"GET /api/v1/old/ [depo]: allow → {MISSING}",
    ]


def test_allowlist_permits_only_matching_difference(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = Allowed(
        item="yeni uç nokta (plan §5.5)",
        snapshot="endpoints",
        case="GET /api/v1/access/*",
        old=MISSING,
    )
    monkeypatch.setattr(allowlist, "ALLOWED", (rule,))
    unexpected, allowed = snapshot.differences(
        "endpoints",
        {"GET /api/v1/x/": {"depo": "403"}},
        {"GET /api/v1/x/": {"depo": "allow"}, "GET /api/v1/access/catalog/": {"depo": "allow"}},
    )
    assert unexpected == ["GET /api/v1/x/ [depo]: 403 → allow"]
    assert allowed == [
        f"GET /api/v1/access/catalog/ [depo]: {MISSING} → allow (yeni uç nokta (plan §5.5))"
    ]


def test_check_raises_on_unexpected_difference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setattr(snapshot, "DATA_DIR", tmp_path)
    monkeypatch.delenv(snapshot.UPDATE_ENV, raising=False)
    snapshot.save("probe", {"case": {"depo": [1, 2]}})
    snapshot.check("probe", {"case": {"depo": [1, 2]}})
    with pytest.raises(AssertionError, match="1 izinsiz fark"):
        snapshot.check("probe", {"case": {"depo": [1]}})
