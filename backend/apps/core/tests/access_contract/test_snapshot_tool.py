"""Anlık görüntü aracının kendisi: fark bulma ve izin listesi."""

import pytest

from apps.core.tests.access_contract import allowlist, snapshot
from apps.core.tests.access_contract.allowlist import MISSING, Allowed


def test_changed_value_is_reported() -> None:
    unexpected, allowed, _used = snapshot.differences(
        "endpoints",
        {"GET /api/v1/x/": {"depo": "403", "planlama": "allow"}},
        {"GET /api/v1/x/": {"depo": "allow", "planlama": "allow"}},
    )
    assert unexpected == ["GET /api/v1/x/ [depo]: 403 → allow"]
    assert allowed == []


def test_missing_and_new_cases_are_reported() -> None:
    unexpected, _, _used = snapshot.differences(
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
    unexpected, allowed, _used = snapshot.differences(
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


def test_brackets_in_case_names_match_literally() -> None:
    case = "quality.conditional_release.approve [kendi önerisi]"

    assert allowlist.matches(case, case)
    assert not allowlist.matches(case, "quality.conditional_release.approve k")
    assert allowlist.matches("quality.conditional_release.* [kendi önerisi]", case)
    assert not allowlist.matches(
        "quality.conditional_release.* [kendi önerisi]",
        "quality.conditional_release.approve [başkasının önerisi]",
    )
    assert allowlist.matches("? /api/*", "X /api/v1/")


def test_rules_of_a_later_step_are_not_active(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = Allowed(item="§8 madde 5", snapshot="probe_rules", case="a [b]", step=4)
    monkeypatch.setattr(allowlist, "ALLOWED", (rule,))
    monkeypatch.setattr(allowlist, "CURRENT_STEP", 3)

    unexpected, _, _ = snapshot.differences("probe_rules", {"a [b]": {"x": 1}}, {"a [b]": {"x": 2}})
    assert unexpected == ["a [b] [x]: 1 → 2"]

    monkeypatch.setattr(allowlist, "CURRENT_STEP", 4)
    unexpected, allowed, used = snapshot.differences(
        "probe_rules", {"a [b]": {"x": 1}}, {"a [b]": {"x": 2}}
    )
    assert unexpected == []
    assert used == [rule]


def test_required_rule_must_match(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setattr(snapshot, "DATA_DIR", tmp_path)
    monkeypatch.delenv(snapshot.UPDATE_ENV, raising=False)
    rule = Allowed(item="§8 madde 12", snapshot="probe", case="job", old=200, new=403)
    monkeypatch.setattr(allowlist, "ALLOWED", (rule,))
    snapshot.save("probe", {"job": {"uretim": 200}})

    snapshot.check("probe", {"job": {"uretim": 403}})
    with pytest.raises(AssertionError, match="hiçbir farkla eşleşmedi"):
        snapshot.check("probe", {"job": {"uretim": 200}})

    optional = Allowed(item="x", snapshot="probe", case="job", required=False)
    monkeypatch.setattr(allowlist, "ALLOWED", (optional,))
    snapshot.check("probe", {"job": {"uretim": 200}})


def test_rules_end_after_their_last_step(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = Allowed(item="yeni model: deneme", snapshot="probe", case="a", step=1, until=5)
    monkeypatch.setattr(allowlist, "ALLOWED", (rule,))

    monkeypatch.setattr(allowlist, "CURRENT_STEP", 5)
    assert allowlist.required_for("probe") == [rule]
    assert snapshot.differences("probe", {"a": {"x": 1}}, {"a": {"x": 2}})[0] == []

    monkeypatch.setattr(allowlist, "CURRENT_STEP", 6)
    assert allowlist.required_for("probe") == []
    assert snapshot.differences("probe", {"a": {"x": 1}}, {"a": {"x": 2}})[0] == ["a [x]: 1 → 2"]
