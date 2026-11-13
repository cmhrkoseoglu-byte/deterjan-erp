"""Anlık görüntü dosyaları: kaydetme, karşılaştırma ve okunur fark çıktısı.

Bir anlık görüntü iki düzeyli bir eşlemedir: `{durum: {persona: değer}}`. Durum bir uç nokta
(`"GET /api/v1/..."`) ya da bir sondanın adıdır; değer JSON'a yazılabilen bir değerdir.

`ACCESS_SNAPSHOT_UPDATE=1` ile çalışan test dosyayı bugünkü sonuçla yeniden yazar. Bu yalnız 1.
adımda ya da sahibin onayı ve DECISIONS kaydıyla yapılır (plan §5.5).

`ACCESS_SNAPSHOT_OBSERVE=<klasör>` anlık görüntüye dokunmaz: bugünkü sonucu o klasöre
`{durum: {persona: değer}}` olarak yazar. Bir adım açılınca izin listesindeki açık değerler bu
gözlemle sabitlenir.
"""

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from apps.core.tests.access_contract.allowlist import MISSING, Allowed, permitted, required_for

DATA_DIR = Path(__file__).resolve().parent / "data"
UPDATE_ENV = "ACCESS_SNAPSHOT_UPDATE"
OBSERVE_ENV = "ACCESS_SNAPSHOT_OBSERVE"

Cases = Mapping[str, Mapping[str, Any]]
Encode = Callable[[Cases], dict[str, Any]]
Decode = Callable[[dict[str, Any]], dict[str, dict[str, Any]]]


def updating() -> bool:
    return os.environ.get(UPDATE_ENV) == "1"


def path_for(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def _plain(cases: Cases) -> dict[str, Any]:
    return {case: dict(values) for case, values in cases.items()}


def save(name: str, cases: Cases, encode: Encode | None = None) -> None:
    data = encode(cases) if encode else _plain(cases)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    path_for(name).write_text(text + "\n", encoding="utf-8")


def load(name: str, decode: Decode | None = None) -> dict[str, dict[str, Any]]:
    data = json.loads(path_for(name).read_text(encoding="utf-8"))
    return decode(data) if decode else data


def differences(
    name: str, expected: Cases, actual: Cases
) -> tuple[list[str], list[str], list[Allowed]]:
    """(izinsiz farklar, izin listesindeki farklar, eşleşen kayıtlar); farklar okunur satırlar."""
    unexpected: list[str] = []
    allowed: list[str] = []
    used: list[Allowed] = []
    for case in sorted(set(expected) | set(actual)):
        old_values = expected.get(case)
        new_values = actual.get(case)
        personas = set(old_values or {}) | set(new_values or {})
        for persona in sorted(personas):
            old = MISSING if old_values is None else old_values.get(persona, MISSING)
            new = MISSING if new_values is None else new_values.get(persona, MISSING)
            if old == new:
                continue
            line = f"{case} [{persona}]: {_short(old)} → {_short(new)}"
            rule = permitted(name, case, persona, old, new)
            if rule is None:
                unexpected.append(line)
            else:
                allowed.append(f"{line} ({rule.item})")
                used.append(rule)
    return unexpected, allowed, used


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 200 else text[:197] + "..."


def check(
    name: str,
    actual: Cases,
    *,
    encode: Encode | None = None,
    decode: Decode | None = None,
) -> None:
    """Bugünkü sonucu dondurulmuş anlık görüntüyle karşılaştırır; izinsiz farkta testi kırar."""
    observe = os.environ.get(OBSERVE_ENV)
    if observe:
        folder = Path(observe)
        folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(_plain(actual), ensure_ascii=False, indent=1, sort_keys=True)
        (folder / f"{name}.json").write_text(text + "\n", encoding="utf-8")
    if updating():
        save(name, actual, encode)
        return
    if not path_for(name).exists():
        raise AssertionError(
            f"Anlık görüntü yok: {path_for(name)}. 1. adımda {UPDATE_ENV}=1 ile üretilir."
        )
    unexpected, _allowed, used = differences(name, load(name, decode), actual)
    if unexpected:
        shown = "\n".join(unexpected[:80])
        more = f"\n... ve {len(unexpected) - 80} fark daha" if len(unexpected) > 80 else ""
        raise AssertionError(
            f"Yetki sözleşmesi bozuldu ({name}): {len(unexpected)} izinsiz fark.\n"
            f"{shown}{more}\n"
            "Fark bilerek yapıldıysa allowlist.py'de planın bir maddesine bağlanmalıdır."
        )
    unused = [rule for rule in required_for(name) if not any(rule is item for item in used)]
    if unused:
        listed = "\n".join(str(rule) for rule in unused[:40])
        raise AssertionError(
            f"İzin listesindeki {len(unused)} kayıt hiçbir farkla eşleşmedi ({name}).\n"
            f"{listed}\n"
            "Onaylı değişiklik geri alınmış ya da kayıt artık gereksiz."
        )
