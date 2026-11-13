"""Paket denkliği yardımcıları (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Bugünkü her rol denetimi ("bu rollerden biri") yeni bir yetki ifadesine eşlenir. Denklik, admin
dışındaki 8 rolün bütün bileşimlerinde (256 rol kümesi) şu demektir: kişiye özel ayar yokken eski
denetim ile yeni yetki aynı kararı verir. Eski denetimler "rollerden biri" biçiminde, paketler de
birleşim olduğundan bu, her rol bileşimi için tam bir kanıttır (ön koşullar dahil).

    ROWS = [
        Row("production.services.ORDER_ROLES", ("planlama",), level(ORDERS, CHANGE),
            live="apps.production.services:ORDER_ROLES"),
        Row("ProductionOrderViewSet GET", SIGNED_IN, read(ORDERS, PREP, BATCHES)),
    ]

    def test_package_equivalence():
        assert_rows(ROWS)

`live`, bugünkü sabitin yeridir: test, satırdaki rol listesinin koddaki sabitle aynı olduğunu da
denetler. Bir adım sabiti kaldırınca satır `live` olmadan dondurulmuş rol listesiyle kalır.

Ön yüzün rol sabitleri de aynı hesapla sınanır (plan §5.5): `live="frontend:src/modules/
production/config.ts:ORDER_ROLES"` dosyadaki `export const ORDER_ROLES ... = [...]` dizisini okur.
CI'da depo bütün olarak indirildiği için ön yüz kaynakları backend klasörünün yanındadır.
"""

import importlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from apps.core import access
from apps.core.access import READ, ROLES, VIEW, SectionRef
from apps.core.effective_access import EffectiveAccess, compute_access

SIGNED_IN = "*"  # bugün IsAuthenticated: giriş yapan herkes (rolü olmayan dahil)
ANY_ROLE = "+"  # bugün HasRole(*ALL_ROLES): rolü olan herkes
ADMIN_ONLY = "admin"  # bugün yalnız admin

OldRoles = tuple[str, ...] | str


@dataclass(frozen=True)
class Need:
    """Yeni yetki ifadesi: bir düzey, okuma, "herhangi biri", "hepsi" ya da yalnız admin."""

    kind: str
    key: str = ""
    level: str = VIEW
    keys: tuple[str, ...] = ()
    parts: tuple["Need", ...] = field(default_factory=tuple)

    def evaluate(self, effective: EffectiveAccess) -> bool:
        if self.kind == "level":
            return effective.allows(self.key, self.level)
        if self.kind == "read":
            return effective.can_read(*self.keys)
        if self.kind == "any":
            return any(part.evaluate(effective) for part in self.parts)
        if self.kind == "all":
            return all(part.evaluate(effective) for part in self.parts)
        if self.kind == "admin":
            return effective.is_admin
        raise ValueError(self.kind)

    def __str__(self) -> str:
        if self.kind == "level":
            return f"{self.key}:{self.level}"
        if self.kind == "read":
            return "read(" + ", ".join(self.keys) + ")"
        if self.kind in ("any", "all"):
            joiner = " | " if self.kind == "any" else " & "
            return "(" + joiner.join(str(part) for part in self.parts) + ")"
        return "admin"


def level(section: SectionRef, level_: str = VIEW) -> Need:
    target = access.section(section)
    if level_ not in target.levels:
        raise ValueError(f"{target.key}: düzey bölümde yok ({level_}).")
    return Need("level", key=target.key, level=level_)


def read(*sections: SectionRef) -> Need:
    return Need("read", keys=tuple(access.section(item).key for item in sections))


def any_of(*parts: Need) -> Need:
    return Need("any", parts=parts)


def all_of(*parts: Need) -> Need:
    return Need("all", parts=parts)


def admin_only() -> Need:
    return Need("admin")


@dataclass(frozen=True)
class Row:
    """Bir eski denetim ve yeni karşılığı."""

    source: str
    roles: OldRoles
    need: Need
    live: str | None = None


def role_subsets() -> list[frozenset[str]]:
    """Admin dışındaki 8 rolün bütün bileşimleri (boş küme: rolü olmayan kullanıcı)."""
    return [
        frozenset(subset) for size in range(len(ROLES) + 1) for subset in combinations(ROLES, size)
    ]


_EFFECTIVE: dict[frozenset[str], EffectiveAccess] = {}


def effective_for(roles: Iterable[str]) -> EffectiveAccess:
    key = frozenset(roles)
    if key not in _EFFECTIVE:
        _EFFECTIVE[key] = compute_access(key)
    return _EFFECTIVE[key]


def old_allows(roles: OldRoles, subset: frozenset[str]) -> bool:
    """Bugünkü denetimin kararı (admin olmayan, etkin kullanıcı için)."""
    if roles == SIGNED_IN:
        return True
    if roles == ANY_ROLE:
        return bool(subset)
    if roles == ADMIN_ONLY:
        return False
    return bool(subset & set(roles))


REPO_ROOT = Path(__file__).resolve().parents[4]
_STRING = re.compile(r"[\"']([a-z_]+)[\"']")


def frontend_roles(path: str, name: str) -> tuple[str, ...]:
    """Ön yüz dosyasındaki `[export] const NAME ... = [...]` rol dizisinin elemanları."""
    file = REPO_ROOT / "frontend" / path
    if not file.exists():
        raise AssertionError(f"Ön yüz kaynağı bulunamadı: {file}")
    text = file.read_text(encoding="utf-8")
    match = re.search(
        rf"(?:export\s+)?const\s+{re.escape(name)}\b[^=]*=\s*\[(?P<body>[^\]]*)\]", text
    )
    if match is None:
        raise AssertionError(f"{path}: {name} dizisi bulunamadı.")
    return tuple(_STRING.findall(match.group("body")))


# Canlı sabitin işaretlere karşılığı: boş dizi giriş yapan herkes (ön yüzde `[]`), ALL_ROLES rolü
# olan herkes (HasRole(*ALL_ROLES)), ("admin",) yalnız admin.
_MARKER_FORMS: dict[str, list[set[str]]] = {
    SIGNED_IN: [set()],
    ANY_ROLE: [set(ROLES), set(ROLES) | {"admin"}],
    ADMIN_ONLY: [{"admin"}],
}


def _live_value(path: str) -> tuple[str, ...]:
    if path.startswith("frontend:"):
        _, file, name = path.split(":", 2)
        return frontend_roles(file, name)
    module_name, _, name = path.partition(":")
    value = getattr(importlib.import_module(module_name), name)
    return tuple(value)


def row_errors(rows: Sequence[Row]) -> list[str]:
    """Denk olmayan satırlar (okunur metin). Boş liste: hepsi denk."""
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.source in seen:
            errors.append(f"{row.source}: satır iki kez yazıldı.")
        seen.add(row.source)
        if row.live is not None:
            if isinstance(row.roles, str):
                live_set = set(_live_value(row.live))
                if live_set not in _MARKER_FORMS[row.roles]:
                    errors.append(
                        f"{row.source}: {row.live} {sorted(live_set)}, satır {row.roles} diyor."
                    )
            elif set(_live_value(row.live)) != set(row.roles):
                errors.append(
                    f"{row.source}: satırdaki roller {sorted(row.roles)}, koddaki "
                    f"{row.live} {sorted(_live_value(row.live))}."
                )
        if not isinstance(row.roles, str):
            unknown = set(row.roles) - set(ROLES)
            if unknown:
                errors.append(f"{row.source}: tanımsız rol {sorted(unknown)}.")
        mismatches = []
        for subset in role_subsets():
            old = old_allows(row.roles, subset)
            new = row.need.evaluate(effective_for(subset))
            if old != new:
                mismatches.append(f"{'+'.join(sorted(subset)) or 'rolsüz'}: eski {old}, yeni {new}")
        if mismatches:
            shown = "; ".join(mismatches[:6])
            errors.append(
                f"{row.source} ({row.need}): {len(mismatches)} rol bileşiminde fark — {shown}"
            )
    return errors


def assert_rows(rows: Sequence[Row]) -> None:
    errors = row_errors(rows)
    assert not errors, "Paket denkliği bozuk:\n" + "\n".join(errors)


__all__ = [
    "ADMIN_ONLY",
    "ANY_ROLE",
    "READ",
    "SIGNED_IN",
    "Need",
    "Row",
    "admin_only",
    "all_of",
    "any_of",
    "assert_rows",
    "effective_for",
    "frontend_roles",
    "level",
    "old_allows",
    "read",
    "role_subsets",
    "row_errors",
]
