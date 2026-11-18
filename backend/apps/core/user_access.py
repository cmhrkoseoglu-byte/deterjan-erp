"""Kişiye özel yetkilerin kaydı için ortak parçalar (`docs/plan/kisi-yetkileri.md` §5.2, §5.10,
§5.11, §6.1; Paket B).

`core.services.set_user_access` bir kaydı önce planlar (`AccessPlan`), sonra uygular; Yetkiler
ekranının API'si, deneme hesabı (`dry_run`) ve "Kim neyi görür" raporu aynı yardımcıları kullanır.
Buradaki hesaplar kişi etkinmiş gibi yapılır: pasif kişinin satırları etkisiz sayılmaz.

Bu modül veritabanına yazmaz.
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from apps.core import access, coverage, security
from apps.core.access import (
    LEVEL_LABELS,
    READ,
    TASK,
    VIEW,
    Kind,
    ReadScope,
    RiskyPair,
)
from apps.core.effective_access import EffectiveAccess, Entry, compute_access
from apps.core.models import AccessOverride, User
from apps.core.roles import ADMIN, ROLE_LABELS

GRANT = AccessOverride.Effect.GRANT.value
REVOKE = AccessOverride.Effect.REVOKE.value
Reason = AccessOverride.EndReason


@dataclass(frozen=True, order=True)
class OverrideSpec:
    """İstenen bir kişiye özel ayar: bölüm anahtarı, düzey ve etki (`grant` / `revoke`)."""

    key: str
    level: str
    effect: str

    @property
    def entry(self) -> Entry:
        return (self.key, self.level)

    @classmethod
    def of(cls, row: AccessOverride) -> "OverrideSpec":
        """Veritabanındaki satırın ayarı."""
        return cls(key=row.key, level=row.level, effect=row.effect)


@dataclass(frozen=True)
class AccessWarning:
    """Kaydetmeden önce gösterilen uyarı: sabit İngilizce kod ve Türkçe metin (critic §4.4)."""

    code: str
    text: str


@dataclass(frozen=True)
class AccessPlan:
    """Bir Yetkiler kaydının planı: roller önce/sonra, kalan, biten (neden kodu ile) ve yeni
    satırlar, geçerli yetki önce/sonra ve uyarılar. Deneme hesabı ve gerçek kayıt aynı planı
    döner."""

    user: User
    roles_before: tuple[str, ...]
    roles_after: tuple[str, ...]
    keep: tuple[AccessOverride, ...]
    end: tuple[tuple[AccessOverride, str], ...]  # (satır, AccessOverride.EndReason değeri)
    create: tuple[OverrideSpec, ...]
    access_before: EffectiveAccess
    access_after: EffectiveAccess
    warnings: tuple[AccessWarning, ...]

    @property
    def changed(self) -> bool:
        """Kayıt bir şeyi değiştiriyor mu (roller ya da kişiye özel satırlar)?"""
        return self.roles_before != self.roles_after or bool(self.end) or bool(self.create)


def access_version(user: User, active: Sequence[AccessOverride]) -> str:
    """Yetkiler ekranının sürüm belirteci (critic §2.6): roller, etkin satırların numaraları,
    süper kullanıcı ve etkinlik. Ekran açıkken başkası bunlardan birini değiştirirse kayıt
    `access_changed` ile reddedilir. 32 onaltılık karakter."""
    payload = {
        "roles": user.roles,
        "overrides": sorted(row.pk for row in active),
        "is_superuser": bool(user.is_superuser),
        "is_active": bool(user.is_active),
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def default_access(roles: Iterable[str]) -> EffectiveAccess:
    """Rollerin varsayılan yetkisi (kişiye özel ayar olmadan), kişi etkinmiş gibi."""
    return compute_access(roles)


def preview_access(roles: Iterable[str], overrides: Iterable[OverrideSpec]) -> EffectiveAccess:
    """Roller ve istenen ayarlarla geçerli yetki, kişi etkinmiş gibi (veritabanına dokunmaz)."""
    specs = list(overrides)
    return compute_access(
        roles,
        grants=[spec.entry for spec in specs if spec.effect == GRANT],
        revokes=[spec.entry for spec in specs if spec.effect == REVOKE],
    )


def is_ineffective(spec: OverrideSpec, roles: Iterable[str]) -> bool:
    """Ayar etkisiz mi (plan §5.2; critic §2.9)? Ekleme, rol varsayılanında zaten varsa; kaldırma,
    rol varsayılanında yoksa etkisizdir. KVKK bölümündeki kaldırma hiçbir zaman etkisiz sayılmaz
    (kişi role dönerse geçerli olur). Tanımsız bölüm ya da düzey burada etkisiz sayılmaz
    (`retired` olarak ayrıca biter). KVKK ya da eksik ön koşul yüzünden düşen ekleme de etkisiz
    değildir (sahibin 2026-11-17 kararı)."""
    if not access.has_section(spec.key):
        return False
    section = access.section(spec.key)
    if spec.level not in section.levels:
        return False
    in_default = spec.entry in default_access(roles).entries
    if spec.effect == GRANT:
        return in_default
    if section.restricted_to_role is not None or spec.level in section.locked:
        return False
    return not in_default


def mixed_pairs(roles: Iterable[str], entries: frozenset[Entry]) -> list[tuple[RiskyPair, Entry]]:
    """Kişide tamamlanan ve iki yetkisi aynı rol paketinden gelmeyen riskli çiftler (plan §5.11):
    `(çift, tamamlayan ikinci yetki)`. Bir rol ikisini birlikte veriyorsa uyarı çıkmaz."""
    role_list = sorted(set(roles))
    per_role = {role: compute_access([role]).entries for role in role_list}
    found: list[tuple[RiskyPair, Entry]] = []
    for pair in access.risky_pairs():
        if pair.first not in entries:
            continue
        for second in pair.second:
            if second not in entries:
                continue
            if any(pair.first in got and second in got for got in per_role.values()):
                continue
            found.append((pair, second))
    return found


def _cell_label(entry: Entry) -> str:
    key, level = entry
    label = access.section(key).label if access.has_section(key) else key
    return f"{label} ({LEVEL_LABELS.get(level, level)})"


def segregation_text(pair: RiskyPair, second: Entry) -> str:
    """`segregation` uyarısının ve raporun Türkçe metni."""
    return (
        f"Görev ayrılığı: “{_cell_label(pair.first)}” ve “{_cell_label(second)}” aynı kişide. "
        "Kaydedenle onaylayanın ayrı olması önerilir."
    )


def is_sensitive(key: str) -> bool:
    """`sensitive_without_otp` uyarısının kapsamı (sahibin 2026-11-17 kararı): hassas veri
    hakları (fiyat, maliyet) ve KVKK bölümleri."""
    if not access.has_section(key):
        return False
    section = access.section(key)
    return section.kind is Kind.SENSITIVE or section.restricted_to_role is not None


def access_label(entry: Entry) -> str:
    """Yetkinin uyarı ve hata metinlerindeki adı: hassas veri hakkında bölümün adı ("Fiyatları
    görür"), ötekilerde "Modül › Bölüm: Düzey"."""
    key, _level = entry
    if access.has_section(key) and access.section(key).kind is Kind.SENSITIVE:
        return access.section(key).label
    return coverage.requirement_label(entry)


def is_known(spec: OverrideSpec) -> bool:
    """Ayarın bölümü ve düzeyi katalogda var mı (yoksa satır `retired` olarak biter)?"""
    return access.has_section(spec.key) and spec.level in access.section(spec.key).levels


def _plan_access(
    roles: Iterable[str], specs: Iterable[OverrideSpec], *, admin: bool
) -> EffectiveAccess:
    if admin:
        return compute_access((), is_admin=True)
    return preview_access(roles, specs)


def role_change_endings(
    active: Sequence[AccessOverride], before: Iterable[str], after: Iterable[str]
) -> list[tuple[AccessOverride, str]]:
    """Rol kancası (plan §5.2): admin rolü verilince bütün etkin satırlar `admin` nedeniyle biter;
    kaldırılan rolün KVKK bölümlerindeki eklemeler `role_removed` nedeniyle biter (kaldırmalar
    kalır). Tanımsız bölüm satırları burada bitmez."""
    before_set, after_set = set(before), set(after)
    if ADMIN in after_set and ADMIN not in before_set:
        return [(row, Reason.ADMIN.value) for row in active]
    removed = before_set - after_set
    endings: list[tuple[AccessOverride, str]] = []
    for row in active:
        if row.effect != GRANT or not access.has_section(row.key):
            continue
        if access.section(row.key).restricted_to_role in removed:
            endings.append((row, Reason.ROLE_REMOVED.value))
    return endings


def build_plan(
    user: User,
    active: Sequence[AccessOverride],
    *,
    roles_after: Iterable[str],
    desired: Sequence[OverrideSpec],
) -> AccessPlan:
    """Doğrulanmış bir Yetkiler kaydının planı (yazmaz). `active` kişinin etkin satırları,
    `desired` istenen etkin satır kümesinin tamamıdır.

    Biten satırın nedeni öncelik sırasıyla (critic §2.7): `admin` > `role_removed` > `retired`
    (tanımsız bölüm ya da düzey) > `replaced` (etkisi değişti) > `ineffective` (kayıttan önce
    etkisizdi) > `reset` (rol varsayılanına döndü). Kişi kayıttan sonra admin olacaksa bütün
    satırlar `admin` ile biter ve yeni satır açılmaz. Hesaplar kişi etkinmiş gibi yapılır.
    """
    roles_before = tuple(user.roles)
    after_roles = tuple(sorted(set(roles_after)))
    admin_before = bool(user.is_superuser) or ADMIN in roles_before
    admin_after = bool(user.is_superuser) or ADMIN in after_roles
    before_specs = [OverrideSpec.of(row) for row in active]
    keep: list[AccessOverride] = []
    end: list[tuple[AccessOverride, str]] = []
    create: list[OverrideSpec] = []
    if admin_after:
        end = [(row, Reason.ADMIN.value) for row in active]
    else:
        wanted = set(desired)
        cells = {spec.entry for spec in wanted}
        hook = {
            row.pk: reason for row, reason in role_change_endings(active, roles_before, after_roles)
        }
        for row, spec in zip(active, before_specs, strict=True):
            reason = hook.get(row.pk)
            if reason is None:
                if spec in wanted:
                    keep.append(row)
                    continue
                if not is_known(spec):
                    reason = Reason.RETIRED.value
                elif spec.entry in cells:
                    reason = Reason.REPLACED.value
                elif is_ineffective(spec, roles_before):
                    reason = Reason.INEFFECTIVE.value
                else:
                    reason = Reason.RESET.value
            end.append((row, reason))
        create = sorted(wanted - set(before_specs))
    after_specs = [OverrideSpec.of(row) for row in keep] + create
    access_before = _plan_access(roles_before, before_specs, admin=admin_before)
    access_after = _plan_access(after_roles, after_specs, admin=admin_after)
    plan = AccessPlan(
        user=user,
        roles_before=roles_before,
        roles_after=after_roles,
        keep=tuple(keep),
        end=tuple(end),
        create=tuple(create),
        access_before=access_before,
        access_after=access_after,
        warnings=(),
    )
    if not plan.changed:
        return plan
    return replace(plan, warnings=tuple(_warnings(plan, active, before_specs, after_specs)))


def _split(specs: Iterable[OverrideSpec]) -> tuple[list[Entry], list[Entry]]:
    grants: list[Entry] = []
    revokes: list[Entry] = []
    for spec in specs:
        (grants if spec.effect == GRANT else revokes).append(spec.entry)
    return grants, revokes


def _role_list(roles: Iterable[str]) -> str:
    return " / ".join(ROLE_LABELS.get(role, role) for role in roles)


def _warnings(
    plan: AccessPlan,
    active: Sequence[AccessOverride],
    before_specs: Sequence[OverrideSpec],
    after_specs: Sequence[OverrideSpec],
) -> list[AccessWarning]:
    """Kaydı engellemeyen uyarılar (plan §5.10; critic §4.4), sabit sırayla."""
    user = plan.user
    found: list[AccessWarning] = []
    admin_after = plan.access_after.is_admin
    if admin_after:
        if ADMIN in plan.roles_after and ADMIN not in plan.roles_before:
            text = "Sistem yöneticisi rolü veriliyor: kişi her ekranı görür ve her işlemi yapar"
            if active:
                text += f"; kişiye özel {len(active)} ayar biter"
            found.append(AccessWarning("admin_granted", text + "."))
        if not user.is_active:
            found.append(_inactive())
        return found

    before_grants, before_revokes = _split(before_specs)
    after_grants, after_revokes = _split(after_specs)
    for gap in coverage.access_change_gaps(
        user,
        before=(plan.roles_before, before_grants, before_revokes),
        after=(plan.roles_after, after_grants, after_revokes),
    ):
        found.append(AccessWarning("coverage_gap", gap.text))

    new_grants = [spec for spec in plan.create if spec.effect == GRANT]
    new_revokes = [spec for spec in plan.create if spec.effect == REVOKE]
    after_entries = plan.access_after.entries
    if plan.roles_after:
        for spec in new_grants:
            if spec.entry not in after_entries:
                continue
            targets: list[str] = []
            for rule in access.rules():
                if rule.kind != TASK or rule.requires != spec.entry or not rule.roles:
                    continue
                if set(rule.roles) & set(plan.roles_after):
                    continue
                targets.extend(role for role in rule.roles if role not in targets)
            if targets:
                found.append(
                    AccessWarning(
                        "task_not_routed",
                        f"“{coverage.requirement_label(spec.entry)}” yetkisinin görevleri "
                        f"{_role_list(targets)} rolüne gider; bu kişiye görev düşmez.",
                    )
                )
    elif any(spec.effect == GRANT for spec in after_specs):
        found.append(
            AccessWarning(
                "no_role_no_tasks",
                "Rolü olmayan kişi görev almaz; yalnız eklenen yetkileri kullanır.",
            )
        )

    before_pairs = (
        set()
        if plan.access_before.is_admin
        else set(mixed_pairs(plan.roles_before, plan.access_before.entries))
    )
    for pair, second in mixed_pairs(plan.roles_after, after_entries):
        if (pair, second) not in before_pairs:
            found.append(AccessWarning("segregation", segregation_text(pair, second)))

    removed_roles = [role for role in plan.roles_before if role not in plan.roles_after]
    for role in removed_roles:
        restricted = [item for item in access.sections() if item.restricted_to_role == role]
        if not restricted:
            continue
        labels = [
            item.label
            for item in restricted
            if plan.access_before.is_admin
            or any((item.key, level) in plan.access_before.entries for level in item.levels)
        ]
        ended = sum(
            1
            for row, reason in plan.end
            if reason == Reason.ROLE_REMOVED.value
            and access.section(row.key).restricted_to_role == role
        )
        text = f"{ROLE_LABELS.get(role, role)} rolü kaldırılıyor: "
        text += f"{', '.join(labels)} yetkileri düşer" if labels else "KVKK yetkileri düşer"
        if ended:
            text += f"; kişiye özel {ended} ekleme biter"
        found.append(AccessWarning("kvkk_role_removed", text + "."))

    if not user.is_active:
        found.append(_inactive())

    if any(is_sensitive(spec.key) for spec in new_grants) and not security.otp_enabled(user):
        found.append(
            AccessWarning(
                "sensitive_without_otp",
                "Kişiye hassas yetki veriliyor ama iki aşamalı doğrulaması kurulu değil.",
            )
        )

    for spec in new_revokes:
        item = access.section(spec.key)
        if item.kind is not Kind.OPEN_RECORDS:
            continue
        reading = [
            other.label
            for other in access.sections()
            if other.module == item.module
            and other.read is ReadScope.OPEN
            and (other.key, VIEW) in after_entries
        ]
        text = (
            f"{access.module(item.module).label} kayıtları bu kişi için kapanıyor. Okumaya devam "
            f"ettiği bölümler: {', '.join(reading) if reading else 'yok'}."
        )
        effects = access.open_records_effects(item.module)
        if effects:
            text += f" Etkilenebilecek başka ekranlar: {' '.join(effects)}"
        found.append(AccessWarning("open_records_closed", text))

    for spec in new_revokes:
        if access.section(spec.key).kind is Kind.OPEN_RECORDS:
            continue
        without = preview_access(plan.roles_after, [item for item in after_specs if item != spec])
        dropped = sorted(
            entry
            for entry in without.entries - after_entries
            if entry[0] != spec.key and entry[1] != READ
        )
        if dropped:
            found.append(
                AccessWarning(
                    "dependent_dropped",
                    f"“{access_label(spec.entry)}” kaldırıldığı için şunlar da düşer: "
                    f"{', '.join(access_label(entry) for entry in dropped)}.",
                )
            )

    kept = [OverrideSpec.of(row) for row in plan.keep]
    count = sum(
        1
        for spec in kept
        if is_ineffective(spec, plan.roles_after) and not is_ineffective(spec, plan.roles_before)
    ) + sum(1 for spec in plan.create if is_ineffective(spec, plan.roles_after))
    if count:
        found.append(
            AccessWarning(
                "override_ineffective",
                f"{count} kişiye özel ayar etkisiz kalıyor; “Etkisiz ayarları temizle” ile "
                "bitirebilirsiniz.",
            )
        )
    return found


def _inactive() -> AccessWarning:
    return AccessWarning(
        "user_inactive", "Kullanıcı pasif; değişiklik etkinleştirilince geçerli olur."
    )


def override_rows(rows: Iterable[AccessOverride]) -> list[dict[str, object]]:
    """Denetim kaydının `access` değeri için etkin satırlar (critic §2.18): numara, bölüm, düzey
    ve etki; bölüm ve düzeye göre sıralı."""
    return [
        {"id": row.pk, "key": row.key, "level": row.level, "effect": row.effect}
        for row in sorted(rows, key=lambda item: (item.key, item.level, item.pk or 0))
    ]
