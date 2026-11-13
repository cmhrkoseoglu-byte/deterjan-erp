"""Uç nokta anlık görüntüsü: her API uç noktası × 14 persona izin kararı (plan §5.5, 1. parça)."""

from collections.abc import Mapping
from typing import Any

import pytest

from apps.core.tests.access_contract import snapshot
from apps.core.tests.access_contract.endpoints import (
    ALLOW,
    FORBIDDEN,
    UNAUTHENTICATED,
    decide,
    endpoints,
)
from apps.core.tests.access_contract.personas import PERSONAS, make_personas

pytestmark = pytest.mark.django_db

NAME = "endpoints"
# Dosyada her uç nokta tek satırdır: personaların kararları PERSONAS sırasıyla bir harf.
CODES = {ALLOW: "a", UNAUTHENTICATED: "u", FORBIDDEN: "f"}
DECISIONS = {code: decision for decision, code in CODES.items()}


def encode(cases: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "_personas": list(PERSONAS),
        "_codes": {code: decision for decision, code in CODES.items()},
    }
    for case, decisions in cases.items():
        data[case] = "".join(CODES[decisions[persona]] for persona in PERSONAS)
    return data


def decode(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    personas = data["_personas"]
    return {
        case: {persona: DECISIONS[code] for persona, code in zip(personas, value, strict=True)}
        for case, value in data.items()
        if not case.startswith("_")
    }


def current_decisions() -> dict[str, dict[str, str]]:
    users = make_personas()
    return {
        f"{method} {path}": {
            persona: decide(method, path, callback, user) for persona, user in users.items()
        }
        for method, path, callback in endpoints()
    }


def test_endpoint_permissions_match_snapshot() -> None:
    snapshot.check(NAME, current_decisions(), encode=encode, decode=decode)


def test_snapshot_covers_every_endpoint() -> None:
    """Anlık görüntü boş değil ve her personanın bir kararı var (kodlama sınaması)."""
    if snapshot.updating():
        pytest.skip("anlık görüntü yazılıyor")
    cases = snapshot.load(NAME, decode)
    assert len(cases) > 100
    for case, decisions in cases.items():
        assert set(decisions) == set(PERSONAS), case
        assert decisions["anonymous"] in (UNAUTHENTICATED, ALLOW), case
