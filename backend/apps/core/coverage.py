"""Görevi alacak kimse kalmıyor denetimi: her iş akışı kuralını alabilecek biri var mı?
(`docs/plan/kisi-yetkileri.md` §5.7, §5.10, §8 madde 9.)

Bir kuralı alabilecek kişi, kuralın alıcısıyla aynı tanımdır: kuralın rollerinden birinin
**etkin üyesi** ve kuralın gerektirdiği yetkiye (`RuleRequirement.requires`) sahip. Admin rolünün
üyesi her yetkiye sahiptir; admin grubunda olmayan süper kullanıcı hiçbir rolün üyesi değildir,
kural alıcısı olmadığı için kimseyi kapsamaz.

Kurallar core'un kayıt defterindedir (`access.rules()`; workflow `ready()`'de yazar); bu modül
workflow'u import etmez. Rolü olmayan kurallar (raporu isteyen kişiye giden bildirimler) sayılmaz.
Görev kurallarıyla birlikte bildirim ve iptal bildirimi kuralları da denetlenir (§5.7 "bir kural
için"): kapsanmayan görev kimseye düşmez, kapsanmayan bildirim kimseye gitmez. İletiler ikisini
ayrı sayar.

Kullanıcı düzenlenirken uyarı yalnız bu kaydın kapsamsız bıraktığı kurallar içindir (önce ve sonra
karşılaştırması); kaydı engellemez.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from django.db.models import Prefetch

from apps.core import access
from apps.core.access import CANCEL, NOTIFY, TASK, RuleRequirement
from apps.core.effective_access import EffectiveAccess, active_overrides, compute_access
from apps.core.models import AccessOverride, User
from apps.core.roles import ADMIN, ROLE_LABELS


@dataclass(frozen=True)
class Member:
    """Kural kapsaması için bir etkin kullanıcı: rol kodları ve geçerli yetkisi."""

    user_id: int
    groups: frozenset[str]
    access: EffectiveAccess


@dataclass(frozen=True)
class Gap:
    """Aynı rollerde aynı yetkiyi isteyen ve alabilecek kimsesi olmayan kurallar."""

    rule_roles: tuple[str, ...]
    requires: tuple[str, str] | None
    tasks: tuple[str, ...]
    notifications: tuple[str, ...]

    @property
    def text(self) -> str:
        """Türkçe açıklama: "Depo rolünde “Üretim › Malzeme hazırlama: Değiştirir” yetkisi olan
        etkin kimse yok; 1 görev kimseye düşmez."""
        holders = " / ".join(ROLE_LABELS.get(role, role) for role in self.rule_roles)
        who = f"{holders} rolünde"
        if self.requires is not None:
            who += f" “{requirement_label(self.requires)}” yetkisi olan"
        effects = []
        if self.tasks:
            effects.append(f"{len(self.tasks)} görev kimseye düşmez")
        if self.notifications:
            effects.append(f"{len(self.notifications)} bildirim kimseye gitmez")
        return f"{who} etkin kimse yok; {', '.join(effects)}."


def requirement_label(requires: tuple[str, str]) -> str:
    """`("production.prep", "change")` → "Üretim › Malzeme hazırlama: Değiştirir"."""
    key, level = requires
    level_label = access.LEVEL_LABELS.get(level, level)
    if not access.has_section(key):
        return f"{key}: {level_label}"
    item = access.section(key)
    return f"{access.module(item.module).label} › {item.label}: {level_label}"


def _rules() -> list[RuleRequirement]:
    return [rule for rule in access.rules() if rule.roles]


def _allows(member_access: EffectiveAccess, requires: tuple[str, str] | None) -> bool:
    if requires is None:
        return True
    try:
        return member_access.allows(*requires)
    except (KeyError, ValueError):
        # Tanımsız bölüm ya da düzey: sistem denetimi (`access.validate`) ayrıca bildirir.
        return member_access.is_admin


def _access_for(
    groups: Iterable[str], overrides: Iterable[AccessOverride], *, is_superuser: bool
) -> EffectiveAccess:
    """Kişinin geçerli yetkisi verilen rollerle (`effective_access` ile aynı hesap)."""
    names = frozenset(groups)
    grants: list[tuple[str, str]] = []
    revokes: list[tuple[str, str]] = []
    for override in overrides:
        target = grants if override.effect == AccessOverride.Effect.GRANT else revokes
        target.append((override.key, override.level))
    return compute_access(
        names, grants=grants, revokes=revokes, is_admin=is_superuser or ADMIN in names
    )


def _users() -> list[User]:
    return list(
        User.objects.filter(is_active=True, groups__isnull=False)
        .distinct()
        .prefetch_related("groups", Prefetch("access_overrides", queryset=active_overrides()))
        .order_by("pk")
    )


def members(*, replace: tuple[int, Iterable[str]] | None = None) -> list[Member]:
    """Rolü olan etkin kullanıcılar. `replace=(kullanıcı no, roller)`: o kişinin rolleri yerine
    verilenler kullanılır (kaydedilmek üzere olan ya da kaydedilmeden önceki roller). Kişi pasifse
    ya da yoksa değişiklik etkisizdir."""
    result: list[Member] = []
    for user in _users():
        group_names = frozenset(group.name for group in user.groups.all())
        if replace is not None and replace[0] == user.pk:
            group_names = frozenset(replace[1])
        result.append(
            Member(
                user_id=user.pk,
                groups=group_names,
                access=_access_for(
                    group_names,
                    [item for item in user.access_overrides.all() if item.ended_at is None],
                    is_superuser=user.is_superuser,
                ),
            )
        )
    if replace is not None and not any(member.user_id == replace[0] for member in result):
        # Rolsüz olduğu için listede olmayan etkin kişiye rol veriliyor olabilir.
        extra = (
            User.objects.filter(pk=replace[0], is_active=True)
            .prefetch_related(Prefetch("access_overrides", queryset=active_overrides()))
            .first()
        )
        if extra is not None and replace[1]:
            group_names = frozenset(replace[1])
            result.append(
                Member(
                    user_id=extra.pk,
                    groups=group_names,
                    access=_access_for(
                        group_names, extra.access_overrides.all(), is_superuser=extra.is_superuser
                    ),
                )
            )
    return result


def uncovered(people: list[Member]) -> list[RuleRequirement]:
    """Alabilecek kimsesi olmayan kurallar (kayıt sırasıyla)."""
    return [
        rule
        for rule in _rules()
        if not any(
            member.groups.intersection(rule.roles) and _allows(member.access, rule.requires)
            for member in people
        )
    ]


def gaps(rules: Iterable[RuleRequirement]) -> list[Gap]:
    """Kuralları rol ve yetki çiftine göre gruplar (ileti başına bir satır)."""
    grouped: dict[tuple[tuple[str, ...], tuple[str, str] | None], list[RuleRequirement]] = {}
    for rule in rules:
        grouped.setdefault((rule.roles, rule.requires), []).append(rule)
    return [
        Gap(
            rule_roles=key[0],
            requires=key[1],
            tasks=tuple(rule.code for rule in items if rule.kind == TASK),
            notifications=tuple(rule.code for rule in items if rule.kind in (NOTIFY, CANCEL)),
        )
        for key, items in grouped.items()
    ]


def current_gaps() -> list[Gap]:
    """Bugün alabilecek kimsesi olmayan kurallar (canlıya geçiş hazırlık listesi, sistem
    durumu)."""
    return gaps(uncovered(members()))


def role_change_gaps(user: User, before: Iterable[str], after: Iterable[str]) -> list[Gap]:
    """Kişinin rolleri `before`'dan `after`'a değişince alabilecek kimsesi kalmayan kurallar
    (önceden de kapsamsız olanlar sayılmaz). Başka herkes veritabanındaki hâliyle sayılır."""
    before_set, after_set = frozenset(before), frozenset(after)
    if before_set == after_set or user.pk is None:
        return []
    was = {rule.code for rule in uncovered(members(replace=(user.pk, before_set)))}
    now = uncovered(members(replace=(user.pk, after_set)))
    return gaps(rule for rule in now if rule.code not in was)


def role_change_warnings(user: User, before: Iterable[str], after: Iterable[str]) -> list[str]:
    """`role_change_gaps`'in kullanıcıya gösterilen Türkçe uyarıları (kaydı engellemez)."""
    return [gap.text for gap in role_change_gaps(user, before, after)]
