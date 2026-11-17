"""Yetki ekranlarının okuma modeli (`docs/plan/kisi-yetkileri.md` §5.10, §6.1-6.4; Paket B).

Sistem › Kullanıcılar › Yetkiler matrisi, kaydın özeti, yetki geçmişi, Yetkilerim ve "Kim neyi
görür" raporu (kimde var, Excel) burada hesaplanır. Veritabanına yazmaz; yazma
`core.services.set_user_access`'tedir. Matris ve plan kişi etkinmiş gibi hesaplanır (pasif kişinin
satırları etkisiz görünmez); rapor yalnız etkin kullanıcıları listeler.

Çok kişiyi birlikte hesaplayan yerler (`people`) rolleri ve etkin kişiye özel ayarları önceden
yükler; kişi başına sorgu yapılmaz.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from apps.core import access, security
from apps.core.access import (
    ALL_LEVELS,
    ANY_ROLE,
    APPROVE,
    CHANGE,
    EVERYONE,
    LEVEL_LETTERS,
    READ,
)
from apps.core.effective_access import (
    ADMIN_ACCESS,
    CellSource,
    Entry,
    active_overrides,
    explain_user_access,
)
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AccessOverride, AuditLog, User
from apps.core.user_access import (
    AccessPlan,
    OverrideSpec,
    access_version,
    default_access,
    is_ineffective,
    mixed_pairs,
    preview_access,
    segregation_text,
)

# Kaynak sırası (Yetkilerim ve "Kimde var?"): herkes > rolü olan herkes > rol > kişiye özel.
EVERYONE_SOURCE = "everyone"
ANY_ROLE_SOURCE = "any_role"
ROLE_SOURCE = "role"
GRANTED_SOURCE = "granted"
IMPLIED_SOURCE = "implied"
ADMIN_SOURCE = "admin"
REVOKED_SOURCE = "revoked"
SOURCE_ORDER: tuple[str, ...] = (
    EVERYONE_SOURCE,
    ANY_ROLE_SOURCE,
    ROLE_SOURCE,
    GRANTED_SOURCE,
    IMPLIED_SOURCE,
    ADMIN_SOURCE,
    REVOKED_SOURCE,
)


# --- ortak ------------------------------------------------------------------------------------


def cells_in_order(letters: Mapping[str, str]) -> list[Entry]:
    """ "rvca" harf haritasındaki hücreler, katalog ve düzey sırasıyla. Bilinmeyen bölüm atlanır."""
    found: list[Entry] = []
    for item in access.sections():
        text = letters.get(item.key, "")
        found.extend(
            (item.key, level) for level in ALL_LEVELS if text and LEVEL_LETTERS[level] in text
        )
    return found


def _catalog_cells() -> list[Entry]:
    """Kataloğun bütün hücreleri: bölümlerin düzeyleri (Açık kayıtlar satırında `read`)."""
    return [(item.key, level) for item in access.sections() for level in item.levels]


def is_known(key: str, level: str) -> bool:
    """Bölüm ve düzey katalogda var mı (kaldırılmış bölümün satırı `known: false` görünür)?"""
    return access.has_section(key) and level in access.section(key).levels


def unknown_access(key: str, level: str) -> BusinessRuleError:
    """Tanımsız bölüm ya da düzey (plan §5.10 `unknown_access`)."""
    label = access.section(key).label if access.has_section(key) else key
    return BusinessRuleError(
        "unknown_access", f"Tanımsız yetki: {label} ({access.LEVEL_LABELS.get(level, level)})."
    )


def user_brief(user: User) -> dict[str, Any]:
    return {
        "id": user.pk,
        "username": user.username,
        "full_name": user.full_name,
        "roles": user.roles,
    }


def _sort_name(user: User) -> tuple[str, str]:
    return ((user.full_name or user.username).casefold(), user.username)


def people(user_id: int | None = None) -> list[User]:
    """Raporun kişileri: etkin kullanıcılar (sahibin 2026-11-17 kararı), roller ve etkin kişiye
    özel ayarlar önceden yüklenmiş, ad soyada göre sıralı."""
    found: QuerySet[User] = User.objects.filter(is_active=True).prefetch_related(
        "groups",
        Prefetch(
            "access_overrides",
            queryset=active_overrides().select_related("created_by").order_by("pk"),
        ),
    )
    if user_id is not None:
        found = found.filter(pk=user_id)
    return sorted(found, key=_sort_name)


def _source(cell: CellSource, own: frozenset[str]) -> tuple[str, list[str]]:
    """Hücrenin kendi kaynağı (Görür'ü getiren üst düzeye bakmadan)."""
    if EVERYONE in cell.holders:
        return EVERYONE_SOURCE, []
    if ANY_ROLE in cell.holders:
        return ANY_ROLE_SOURCE, []
    held = sorted(holder for holder in cell.holders if holder in own)
    if held:
        return ROLE_SOURCE, held
    return GRANTED_SOURCE, []


def _parent_source(
    cells: Mapping[Entry, CellSource], key: str, own: frozenset[str]
) -> tuple[str, list[str]]:
    """Değiştirir/Onaylar'ın getirdiği Görür'ün kaynağı: o üst düzeyin kaynağı."""
    found = [
        _source(cells[(key, level)], own)
        for level in (CHANGE, APPROVE)
        if (key, level) in cells and cells[(key, level)].effective
    ]
    if not found:
        return GRANTED_SOURCE, []
    return min(found, key=lambda item: SOURCE_ORDER.index(item[0]))


def _role_holders(cell: CellSource, own: frozenset[str]) -> list[str]:
    return sorted(holder for holder in cell.holders if holder in own)


# --- Yetkiler ekranı: matris ------------------------------------------------------------------


def _active_rows(user: User) -> list[AccessOverride]:
    return list(
        active_overrides().filter(user_id=user.pk).select_related("created_by").order_by("pk")
    )


def matrix(user: User, viewer: User) -> dict[str, Any]:
    """`GET /users/{pk}/access/` gövdesi (critic §4.2): roller, rol varsayılanı, geçerli yetki ve
    etkin kişiye özel ayarlar (gerekçesiyle; yalnız admin görür), kişi etkinmiş gibi."""
    rows = _active_rows(user)
    codes = user.roles
    if user.is_admin:
        default = effective = ADMIN_ACCESS.letters()
        overrides: list[dict[str, Any]] = []
    else:
        specs = [OverrideSpec.of(row) for row in rows]
        default = default_access(codes).letters()
        effective = preview_access(codes, specs).letters()
        overrides = [
            {
                "id": row.pk,
                "key": row.key,
                "level": row.level,
                "effect": row.effect,
                "note": row.note,
                "created_at": row.created_at,
                "created_by_name": str(row.created_by) if row.created_by_id else None,
                "known": is_known(row.key, row.level),
                "ineffective": is_ineffective(spec, codes),
            }
            for row, spec in zip(rows, specs, strict=True)
        ]
    return {
        "user": {
            "id": user.pk,
            "username": user.username,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "otp_enabled": security.otp_enabled(user),
        },
        "roles": codes,
        "is_admin": user.is_admin,
        "is_self": viewer.pk == user.pk,
        "version": access_version(user, rows),
        "catalog_hash": access.catalog_hash(),
        "default": default,
        "effective": effective,
        "overrides": overrides,
        "open_records_effects": {
            key: list(texts) for key, texts in access.all_open_records_effects().items()
        },
    }


def _spec(spec: OverrideSpec) -> dict[str, str]:
    return {"key": spec.key, "level": spec.level, "effect": spec.effect}


def _cell(entry: Entry) -> dict[str, str]:
    return {"key": entry[0], "level": entry[1]}


def save_result(plan: AccessPlan, *, dry_run: bool, fresh: dict[str, Any] | None) -> dict[str, Any]:
    """`PUT /users/{pk}/access/` yanıtı (critic §4.2): deneme hesabında ve kayıtta aynı biçim.
    `fresh` kayıttan sonraki matristir (yalnız gerçekten kaydedilince)."""
    before = plan.access_before.letters()
    after = plan.access_after.letters()
    had = cells_in_order(before)
    has = cells_in_order(after)
    had_set, has_set = set(had), set(has)
    return {
        "dry_run": dry_run,
        "changed": plan.changed,
        "saved": fresh is not None,
        "roles": {"before": list(plan.roles_before), "after": list(plan.roles_after)},
        "overrides": {
            "created": [_spec(spec) for spec in plan.create],
            "ended": [
                {
                    "id": row.pk,
                    "key": row.key,
                    "level": row.level,
                    "effect": row.effect,
                    "reason": reason,
                }
                for row, reason in plan.end
            ],
        },
        "access": {
            "before": before,
            "after": after,
            "granted": [_cell(entry) for entry in has if entry not in had_set],
            "removed": [_cell(entry) for entry in had if entry not in has_set],
        },
        "warnings": [{"code": item.code, "text": item.text} for item in plan.warnings],
        "matrix": fresh,
    }


# --- yetki geçmişi ----------------------------------------------------------------------------


def history_entries(user: User) -> QuerySet[AuditLog]:
    """Kişinin rol ve kişiye özel yetki kayıtları (denetim günlüğünden; adım 9 öncesindeki rol
    değişiklikleri dahil), yeniden eskiye."""
    return (
        AuditLog.objects.filter(
            content_type=ContentType.objects.get_for_model(User),
            object_id=user.pk,
            changes__has_any_keys=["roles", "access"],
        )
        .select_related("actor")
        .order_by("-timestamp", "-id")
    )


def _rows_of(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _row_id(row: Mapping[str, Any]) -> Any:
    return row.get("id") or (row.get("key"), row.get("level"), row.get("effect"))


def history_items(logs: Sequence[AuditLog]) -> list[dict[str, Any]]:
    """Geçmiş satırları (critic §4.3). Biten satırın nedeni, denetim kaydındaki satır numarasıyla
    `AccessOverride`'dan okunur."""
    changes = [log.changes if isinstance(log.changes, dict) else {} for log in logs]
    ended_ids: set[int] = set()
    for value in changes:
        pair = value.get("access")
        if isinstance(pair, list) and len(pair) == 2:
            after = {_row_id(row) for row in _rows_of(pair[1])}
            ended_ids |= {
                row["id"]
                for row in _rows_of(pair[0])
                if isinstance(row.get("id"), int) and _row_id(row) not in after
            }
    reasons = dict(AccessOverride.objects.filter(pk__in=ended_ids).values_list("pk", "end_reason"))
    items: list[dict[str, Any]] = []
    for log, value in zip(logs, changes, strict=True):
        role_pair = value.get("roles")
        lines: list[dict[str, Any]] = []
        pair = value.get("access")
        if isinstance(pair, list) and len(pair) == 2:
            old, new = _rows_of(pair[0]), _rows_of(pair[1])
            old_ids = {_row_id(row) for row in old}
            new_ids = {_row_id(row) for row in new}
            for row in new:
                if _row_id(row) in old_ids:
                    continue
                kind = "granted" if row.get("effect") == AccessOverride.Effect.GRANT else "revoked"
                lines.append({"kind": kind, "key": row.get("key"), "level": row.get("level")})
            for row in old:
                if _row_id(row) in new_ids:
                    continue
                row_id = row.get("id")
                reason = (reasons.get(row_id, "") if isinstance(row_id, int) else "") or ""
                lines.append(
                    {
                        "kind": "ended",
                        "key": row.get("key"),
                        "level": row.get("level"),
                        "effect": row.get("effect"),
                        "reason": reason,
                        "reason_label": _reason_label(reason),
                    }
                )
        items.append(
            {
                "id": log.pk,
                "timestamp": log.timestamp,
                "actor_name": str(log.actor) if log.actor_id else None,
                "note": log.note,
                "roles": (
                    {"before": list(role_pair[0]), "after": list(role_pair[1])}
                    if isinstance(role_pair, list) and len(role_pair) == 2
                    else None
                ),
                "lines": lines,
            }
        )
    return items


def _reason_label(reason: str) -> str:
    try:
        return str(AccessOverride.EndReason(reason).label)
    except ValueError:
        return ""


# --- Yetkilerim -------------------------------------------------------------------------------


def my_access(user: User) -> dict[str, Any]:
    """`GET /auth/me/access/` (critic §4.5): yetkinin kaynağı ve kişiden kaldırılanlar. Gerekçe,
    değiştiren ve tarih yoktur (plan §5.10)."""
    codes = user.roles
    if user.is_admin:
        return {"roles": codes, "is_admin": True, "entries": [], "revoked": []}
    own = frozenset(codes)
    cells = explain_user_access(user)
    entries: list[dict[str, Any]] = []
    revoked: list[dict[str, Any]] = []
    for entry in _catalog_cells():
        cell = cells.get(entry)
        if cell is None:
            continue
        key, level = entry
        if cell.effective and level != READ:
            if cell.implied:
                source, held = _parent_source(cells, key, own)
            else:
                source, held = _source(cell, own)
            entries.append(
                {
                    "key": key,
                    "level": level,
                    "source": source,
                    "roles": held,
                    "implied": cell.implied,
                }
            )
        elif (
            cell.default and not cell.effective and (cell.revoked or cell.dropped == "view_revoked")
        ):
            revoked.append({"key": key, "level": level, "roles": _role_holders(cell, own)})
    return {"roles": codes, "is_admin": False, "entries": entries, "revoked": revoked}


# --- "Kim neyi görür" raporu ------------------------------------------------------------------


@dataclass(frozen=True)
class PairFlag:
    """Kişide tamamlanan riskli çift: iki yetki, kaynakları ve uyarı metni."""

    first: Entry
    second: Entry
    sources: str
    text: str


@dataclass(frozen=True)
class PersonAccess:
    """Bir kişinin rapordaki satırı."""

    user: User
    is_admin: bool
    letters: dict[str, str]
    cells: Mapping[Entry, CellSource] = field(default_factory=dict)
    personal: tuple[AccessOverride, ...] = ()
    pairs: tuple[PairFlag, ...] = ()

    def source(self, entry: Entry) -> tuple[str, list[str]]:
        """Etkin hücrenin kaynağı ("Kimde var?" ve Excel): Görür'ü üst düzeyden gelirse
        `implied`."""
        if self.is_admin:
            return ADMIN_SOURCE, []
        cell = self.cells[entry]
        if cell.implied:
            return IMPLIED_SOURCE, []
        return _source(cell, frozenset(self.user.roles))


def _pair_source(cell: CellSource | None) -> str:
    if cell is None:
        return GRANTED_SOURCE
    return ROLE_SOURCE if cell.holders else GRANTED_SOURCE


def person_access(user: User) -> PersonAccess:
    """Kişinin geçerli yetkisi, hücre kaynakları, kişiye özel ayarları ve riskli çiftleri."""
    personal = tuple(row for row in user.access_overrides.all() if row.ended_at is None)
    if user.is_admin:
        return PersonAccess(user, True, ADMIN_ACCESS.letters(), personal=personal)
    cells = explain_user_access(user)
    entries = user.access.entries
    pairs: list[PairFlag] = []
    for pair, second in mixed_pairs(user.roles, entries):
        sources = f"{_pair_source(cells.get(pair.first))}+{_pair_source(cells.get(second))}"
        pairs.append(PairFlag(pair.first, second, sources, segregation_text(pair, second)))
    return PersonAccess(user, False, user.access.letters(), cells, personal, tuple(pairs))


def report(user_id: int | None = None) -> list[PersonAccess]:
    """Etkin kullanıcıların yetkileri (`?user=` tek kişi). Kişiler etkin olduğundan geçerli yetki
    kişinin kendi hesabıdır (`User.access`, önceden yüklenmiş verilerle)."""
    return [person_access(user) for user in people(user_id)]


def report_body(rows: Iterable[PersonAccess]) -> dict[str, Any]:
    """`GET /access/report/` gövdesi."""
    return {
        "catalog_hash": access.catalog_hash(),
        "generated_at": timezone.now(),
        "users": [
            {
                **user_brief(row.user),
                "is_admin": row.is_admin,
                "access": {} if row.is_admin else row.letters,
                "personal": [
                    {
                        "key": item.key,
                        "level": item.level,
                        "effect": item.effect,
                        "ineffective": is_ineffective(OverrideSpec.of(item), row.user.roles),
                    }
                    for item in row.personal
                ],
                "risky_pairs": [
                    {
                        "a": _cell(flag.first),
                        "b": _cell(flag.second),
                        "sources": flag.sources,
                        "text": flag.text,
                    }
                    for flag in row.pairs
                ],
            }
            for row in rows
        ],
    }


def _segregation(row: PersonAccess, entry: Entry) -> list[str]:
    return [flag.text for flag in row.pairs if entry in (flag.first, flag.second)]


def holders(key: str, level: str) -> dict[str, Any]:
    """ "Kimde var?" (critic §4.7): hücreyi etkin olarak taşıyan kişiler ve kaynakları; rol
    paketinde olduğu hâlde kişiden kaldırılanlar en sonda (`revoked`). Tanımsız hücre
    `unknown_access`."""
    if not is_known(key, level):
        raise unknown_access(key, level)
    entry = (key, level)
    found: list[tuple[int, tuple[str, str], dict[str, Any]]] = []
    for row in report():
        own = frozenset(row.user.roles)
        held: list[str]
        flags: list[str]
        if row.is_admin:
            source, held, flags = ADMIN_SOURCE, [], []
        else:
            cell = row.cells.get(entry)
            if cell is None:
                continue
            if cell.effective:
                source, held = row.source(entry)
                flags = _segregation(row, entry)
            elif cell.default and (cell.revoked or cell.dropped == "view_revoked"):
                source, held, flags = REVOKED_SOURCE, _role_holders(cell, own), []
            else:
                continue
        found.append(
            (
                SOURCE_ORDER.index(source),
                _sort_name(row.user),
                {
                    "user": user_brief(row.user),
                    "source": source,
                    "roles": held,
                    "segregation": flags,
                },
            )
        )
    found.sort(key=lambda item: (item[0], item[1]))
    return {"key": key, "level": level, "holders": [item for _, _, item in found]}
