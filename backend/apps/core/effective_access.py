"""Geçerli yetki hesabı (`docs/plan/kisi-yetkileri.md` §5.3).

    pasif ya da anonim            → hiçbir şey
    admin ya da süper kullanıcı   → her şey
    P = herkes ∪ (rolü olan herkes) ∪ rol paketleri ∪ kişiye eklenenler
    P = P − kişiden kaldırılanlar (kilitli düzeyler kaldırılamaz)
        Görür kaldırılırsa o bölümün Değiştirir ve Onaylar'ı da düşer.
    Değiştirir ya da Onaylar → Görür   (yalnız Görür düzeyi olan bölümlerde)
    KVKK bölümleri: kişi o rolde değilse düşer
    ön koşulu karşılanmayan düzey düşer (düzey bazında; sabit noktaya kadar)
    bölüm okuması: Görür
           ya da  kapsam = ortak (herkes)
           ya da  kapsam = rolü olan  ve kişinin rolü var
           ya da  kapsam = açık okuma  ve kişiden modülün "Kayıtları okur"u kaldırılmamış

Hesap her çağrıda veritabanının o anki durumundan yapılır; istekler arası önbellek yoktur.
`User.access` aynı kullanıcı nesnesinde hesabı bir kez yapar (`refresh_roles()` temizler).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from apps.core import access
from apps.core.access import (
    ANY_ROLE,
    APPROVE,
    CHANGE,
    EVERYONE,
    READ,
    ROLES,
    VIEW,
    Kind,
    ReadScope,
    Section,
    SectionRef,
)

Entry = tuple[str, str]


@dataclass(frozen=True)
class EffectiveAccess:
    """Bir kişinin geçerli yetkileri: `(bölüm anahtarı, düzey)` çiftleri (okuma `read` dahil)."""

    entries: frozenset[Entry]
    is_admin: bool = False

    def allows(self, section: SectionRef, level: str = VIEW) -> bool:
        """Bölümün bu düzeyine sahip mi? Tanımsız bölüm `KeyError` fırlatır."""
        target = access.section(section)
        if level != READ and level not in target.levels:
            raise ValueError(f"{target.key}: düzey bölümde yok ({level}).")
        if self.is_admin:
            return level != READ or _readable_by_admin(target)
        return (target.key, level) in self.entries

    def can_read(self, *sections: SectionRef) -> bool:
        """Bölümlerden birinin kayıtlarını okuyabilir mi?"""
        return any(self.allows(item, READ) for item in sections)

    def letters(self) -> dict[str, str]:
        """`me` yanıtı için: bölüm → "rvca" harfleri (yetkisi olmayan bölüm yazılmaz)."""
        result: dict[str, str] = {}
        for item in access.sections():
            if self.is_admin:
                present = set(item.levels) | ({READ} if _readable_by_admin(item) else set())
                text = "".join(
                    access.LEVEL_LETTERS[level] for level in access.ALL_LEVELS if level in present
                )
            else:
                text = access.letters(self.entries, item.key)
            if text:
                result[item.key] = text
        return result


NO_ACCESS = EffectiveAccess(frozenset())
ADMIN_ACCESS = EffectiveAccess(frozenset(), is_admin=True)


def _readable_by_admin(item: Section) -> bool:
    return item.has_view or item.kind is Kind.OPEN_RECORDS


def compute_access(
    role_names: Iterable[str],
    *,
    grants: Iterable[Entry] = (),
    revokes: Iterable[Entry] = (),
    is_admin: bool = False,
    is_active: bool = True,
) -> EffectiveAccess:
    """Rollerden ve kişiye özel ayarlardan geçerli yetkiyi hesaplar (veritabanına dokunmaz).

    Tanımsız bölüm ya da düzey taşıyan ayarlar (ör. kaldırılmış bir bölüm) yok sayılır.
    """
    if not is_active:
        return NO_ACCESS
    if is_admin:
        return ADMIN_ACCESS
    roles = set(role_names) & set(ROLES)
    entries: set[Entry] = set(access.package(EVERYONE))
    if roles:
        entries |= access.package(ANY_ROLE)
    for role in roles:
        entries |= access.package(role)

    for key, level in grants:
        item = _known(key, level)
        if item is not None and item.grantable(level) and item.kind is not Kind.OPEN_RECORDS:
            entries.add((key, level))

    revoked_view: set[str] = set()
    for key, level in revokes:
        item = _known(key, level)
        if item is None or level in item.locked:
            continue
        entries.discard((key, level))
        if level == VIEW:
            revoked_view.add(key)

    for key, level in list(entries):
        if level in (CHANGE, APPROVE) and access.section(key).has_view:
            entries.add((key, VIEW))
    for key in revoked_view:
        entries -= {(key, VIEW), (key, CHANGE), (key, APPROVE)}

    entries = {
        (key, level)
        for key, level in entries
        if access.section(key).restricted_to_role in (None, *roles)
    }
    entries = _apply_requirements(entries)

    for item in access.sections():
        if item.kind is Kind.OPEN_RECORDS or not item.has_view:
            continue
        if _reads(item, entries, roles):
            entries.add((item.key, READ))
    return EffectiveAccess(frozenset(entries))


def _known(key: str, level: str) -> Section | None:
    if not access.has_section(key):
        return None
    item = access.section(key)
    return item if level in item.levels else None


def _apply_requirements(entries: set[Entry]) -> set[Entry]:
    """Ön koşulu karşılanmayan düzeyleri sabit noktaya kadar düşürür. Görür'ü düşen bölümün
    Değiştirir ve Onaylar'ı da düşer."""
    result = set(entries)
    changed = True
    while changed:
        changed = False
        for key, level in sorted(result):
            item = access.section(key)
            missing = any(need not in result for need in item.requirements(level))
            blind = level in (CHANGE, APPROVE) and item.has_view and (key, VIEW) not in result
            if missing or blind:
                result.discard((key, level))
                changed = True
    return result


def _reads(item: Section, entries: set[Entry], roles: set[str]) -> bool:
    if (item.key, VIEW) in entries:
        return True
    if item.read is ReadScope.SHARED:
        return True
    if item.read is ReadScope.ANY_ROLE:
        return bool(roles)
    if item.read is ReadScope.OPEN:
        records = access.open_records_section(item.module)
        return records is not None and (records.key, READ) in entries
    return False


def effective_access(user: Any) -> EffectiveAccess:
    """Kullanıcının geçerli yetkisi: rolleri ve etkin kişiye özel ayarları (veritabanından).

    Çok kişiyi birlikte hesaplayan yerler `access_overrides` ilişkisini önceden yükleyebilir
    (`prefetch_related(Prefetch("access_overrides", queryset=active_overrides()))`); o zaman
    sorgu yapılmaz.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return NO_ACCESS
    if not user.is_active:
        return NO_ACCESS
    if user.is_admin:
        return ADMIN_ACCESS
    grants: list[Entry] = []
    revokes: list[Entry] = []
    for override in _active_overrides(user):
        target = grants if override.effect == override.Effect.GRANT else revokes
        target.append((override.key, override.level))
    return compute_access(user.role_names, grants=grants, revokes=revokes)


def _active_overrides(user: Any) -> list[Any]:
    from apps.core.models import AccessOverride

    if user.pk is None:
        return []
    cache = getattr(user, "_prefetched_objects_cache", {})
    if "access_overrides" in cache:
        return [item for item in cache["access_overrides"] if item.ended_at is None]
    return list(AccessOverride.objects.filter(user_id=user.pk, ended_at__isnull=True))
