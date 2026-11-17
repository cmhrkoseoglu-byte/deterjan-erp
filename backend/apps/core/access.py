"""Yetki kataloğu: modüller, bölümler, düzeyler ve rollerin varsayılan paketleri.

`docs/plan/kisi-yetkileri.md` §3 ve §5.1. Bu modül yalnız veri tutar ve hiçbir uygulamayı import
etmez (`core.records` deseni). Her uygulama kendi `access.py` dosyasında bölümlerini ve rol
paketlerini kaydeder; `CoreConfig.ready()` bu dosyaları kendiliğinden yükler, böylece katalog her
süreçte (web, Celery, yönetim komutları) tamdır:

    register_module("production", "Üretim", order=40)
    ORDERS = register_section(
        "production.orders", "Üretim emirleri", levels=(VIEW, CHANGE, APPROVE),
        help={CHANGE: "Emir açar, düzenler, iptal eder", APPROVE: "Emri onaylar"},
        read=ReadScope.OPEN,
    )
    grant(PLANLAMA, ORDERS, VIEW, CHANGE, APPROVE)

Kavramlar:

- **Bölüm** (`modül.bölüm`): yetkinin birimi; bir ekran, sekme ya da işlem grubu.
- **Düzey:** Görür (`view`), Değiştirir (`change`), Onaylar (`approve`). Kayıtları okur (`read`)
  hesaplanır; yalnız modülün "Açık kayıtlar" satırında kişiden kaldırılabilir bir düzeydir.
- **Okuma kapsamı:** bölümün kayıtlarını bugün kimin okuyabildiği (`ReadScope`).
- **Paket:** bir rolün (ya da herkesin, rolü olan herkesin) varsayılan yetkileri.
- **Ön koşul** (`requires`): başka bir yetki olmadan geçersiz olan düzey.
- **KVKK kısıtı** (`restricted_to_role`): yalnız o roldeki kişide geçerli olan bölüm.
- **Yalnız admin** (`admin_only`): kimseye verilemeyen düzey; yalnız sistem yöneticisi yapar.
- **Kilitli** (`locked`): kişiden kaldırılamayan düzey (🔒).

Geçerli yetkinin hesabı `apps.core.effective_access`'tedir.
"""

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from apps.core.roles import ADMIN, ALL_ROLES, SATIN_ALMA, YONETIM

VIEW = "view"
CHANGE = "change"
APPROVE = "approve"
READ = "read"

GRANT_LEVELS: tuple[str, ...] = (VIEW, CHANGE, APPROVE)
ALL_LEVELS: tuple[str, ...] = (READ, VIEW, CHANGE, APPROVE)
LEVEL_LABELS: dict[str, str] = {
    READ: "Kayıtları okur",
    VIEW: "Görür",
    CHANGE: "Değiştirir",
    APPROVE: "Onaylar",
}
# `me` yanıtındaki ve ön yüzdeki kısa gösterim: "rvca".
LEVEL_LETTERS: dict[str, str] = {READ: "r", VIEW: "v", CHANGE: "c", APPROVE: "a"}

# Paket sahipleri: herkes (rolü olmayan dahil her etkin kullanıcı), rolü olan herkes (admin
# dışındaki 8 rolden en az birine sahip olan) ve 8 rol. Admin paket almaz: her yetkiye sahiptir.
EVERYONE = "*"
ANY_ROLE = "+"
ROLES: tuple[str, ...] = tuple(role for role in ALL_ROLES if role != ADMIN)
HOLDERS: tuple[str, ...] = (EVERYONE, ANY_ROLE, *ROLES)
HOLDER_LABELS: dict[str, str] = {EVERYONE: "Herkes", ANY_ROLE: "Rolü olan herkes"}

# Ön koşulun her düzeye uygulandığını gösterir: `requires={ALL: [...]}`.
ALL = "*"

OPEN_RECORDS = "open_records"
_KEY = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*$")
_MODULE_KEY = re.compile(r"^[a-z][a-z_]*$")


class ReadScope(StrEnum):
    """Bölümün kayıtlarını bugün kimin okuyabildiği (API okuması)."""

    VIEW = "view"  # yalnız Görür'ü olan
    SHARED = "shared"  # herkes; seçim listeleri ve etiket basımı için, kişiden kapatılamaz
    ANY_ROLE = "any_role"  # rolü olan herkes; kişiden kapatılamaz
    OPEN = "open"  # açık okuma: herkes; modülün "Açık kayıtlar" satırı kişi için kapatılabilir


class Kind(StrEnum):
    SECTION = "section"  # ekranı (sekmesi) olan bölüm; menüde modül açar
    ACTION = "action"  # Görür'ü olmayan işlem bölümü; menüde modül açmaz
    SENSITIVE = "sensitive"  # hassas veri hakkı (fiyat, maliyet)
    OPEN_RECORDS = "open_records"  # modülün "Açık kayıtlar" satırı


@dataclass(frozen=True)
class Module:
    """Bölümleri gruplayan modül. `menu=False`: menüde kendi modülü yoktur, bölümleri menü
    açmaz (Hassas veriler, Görevler, Sistem; Sistem menüsü yalnız admine açıktır)."""

    key: str
    label: str
    order: int
    menu: bool = True


@dataclass(frozen=True, eq=False)
class Section:
    """Yetki bölümü. Düzenlenmez; `register_section` ile kaydedilir. Her bölüm tek nesnedir
    (eşitlik kimlikle), bu yüzden sözlük anahtarı olarak kullanılabilir."""

    key: str
    label: str
    levels: tuple[str, ...]
    kind: Kind
    read: ReadScope
    help: Mapping[str, str] = field(default_factory=dict)
    # (düzey ya da ALL, bölüm anahtarı, gereken düzey)
    requires: tuple[tuple[str, str, str], ...] = ()
    restricted_to_role: str | None = None
    admin_only: tuple[str, ...] = ()
    locked: tuple[str, ...] = ()
    order: int = 0

    @property
    def module(self) -> str:
        return self.key.split(".", 1)[0]

    @property
    def has_view(self) -> bool:
        return VIEW in self.levels

    def requirements(self, level: str) -> tuple[tuple[str, str], ...]:
        """Bu düzeyin ön koşulları: `(bölüm anahtarı, düzey)` çiftleri."""
        return tuple((key, need) for applies, key, need in self.requires if applies in (ALL, level))

    def grantable(self, level: str) -> bool:
        """Kişiye verilebilir mi (paket ya da kişiye özel ekleme)?"""
        return level in self.levels and level not in self.admin_only

    def __str__(self) -> str:
        return self.key


SectionRef = Section | str

_MODULES: dict[str, Module] = {}
_SECTIONS: dict[str, Section] = {}
_PACKAGES: dict[str, set[tuple[str, str]]] = {holder: set() for holder in HOLDERS}
_READERS: dict[str, tuple[str, ...]] = {}
_FIELD_OPENERS: dict[str, tuple[str, ...]] = {}
# Modül anahtarı → "Açık kayıtlar" kapatılınca etkilenen ekranlar (`register_open_records`).
_OPEN_RECORDS_EFFECTS: dict[str, tuple[str, ...]] = {}


def _key_of(section: SectionRef) -> str:
    return section.key if isinstance(section, Section) else section


def register_module(key: str, label: str, *, order: int, menu: bool = True) -> Module:
    """Bölümleri gruplayan modülü kaydeder (anahtar menüdeki modül anahtarıdır)."""
    if not _MODULE_KEY.match(key):
        raise ValueError(f"Geçersiz modül anahtarı: {key!r}")
    if key in _MODULES:
        raise ValueError(f"Modül iki kez kaydedildi: {key}")
    module = Module(key=key, label=label, order=order, menu=menu)
    _MODULES[key] = module
    return module


def register_section(
    key: str,
    label: str,
    *,
    levels: Sequence[str],
    help: Mapping[str, str] | None = None,
    kind: Kind | None = None,
    read: ReadScope = ReadScope.VIEW,
    requires: Mapping[str, Iterable[tuple[SectionRef, str]]] | None = None,
    restricted_to_role: str | None = None,
    admin_only: Sequence[str] = (),
    locked: Sequence[str] = (),
) -> Section:
    """Bölümü kaydeder ve döner. Hatalı tanım `ValueError` fırlatır (yazım hatası yüklenirken
    yakalanır).

    `requires` düzey → ön koşullar eşlemesidir; `ALL` anahtarı bölümün her düzeyine uygulanır:
    `requires={CHANGE: [(PRICES, VIEW)]}`.
    """
    if not _KEY.match(key):
        raise ValueError(f"Geçersiz bölüm anahtarı: {key!r}")
    if key in _SECTIONS:
        raise ValueError(f"Bölüm iki kez kaydedildi: {key}")
    module_key = key.split(".", 1)[0]
    if module_key not in _MODULES:
        raise ValueError(f"{key}: modül kayıtlı değil ({module_key}).")
    levels = tuple(levels)
    if kind is Kind.OPEN_RECORDS:
        if levels != (READ,):
            raise ValueError(f"{key}: açık kayıtlar satırının tek düzeyi Kayıtları okur'dur.")
    elif not levels or any(level not in GRANT_LEVELS for level in levels):
        raise ValueError(f"{key}: geçersiz düzeyler {levels}.")
    if len(set(levels)) != len(levels):
        raise ValueError(f"{key}: düzey tekrarlandı.")
    if kind is None:
        kind = Kind.SECTION if VIEW in levels else Kind.ACTION
    if kind in (Kind.SECTION, Kind.SENSITIVE) and VIEW not in levels:
        raise ValueError(f"{key}: ekranı olan bölümün Görür düzeyi olmalıdır.")
    if kind is Kind.SENSITIVE and levels != (VIEW,):
        raise ValueError(f"{key}: hassas veri hakkının tek düzeyi Görür'dür.")
    if kind is Kind.ACTION and VIEW in levels:
        raise ValueError(f"{key}: işlem bölümünün Görür düzeyi olmaz.")
    if read is not ReadScope.VIEW and VIEW not in levels and kind is not Kind.OPEN_RECORDS:
        raise ValueError(f"{key}: okuma kapsamı yalnız Görür'ü olan bölümde verilir.")
    help_map = dict(help or {})
    for level in help_map:
        if level not in levels:
            raise ValueError(f"{key}: açıklaması verilen düzey bölümde yok ({level}).")
    parsed: list[tuple[str, str, str]] = []
    for applies, needs in (requires or {}).items():
        if applies != ALL and applies not in levels:
            raise ValueError(f"{key}: ön koşul verilen düzey bölümde yok ({applies}).")
        for target, need in needs:
            target_key = _key_of(target)
            if target_key == key:
                raise ValueError(f"{key}: bölüm kendisinin ön koşulu olamaz.")
            if need not in GRANT_LEVELS:
                raise ValueError(f"{key}: ön koşul düzeyi geçersiz ({need}).")
            parsed.append((applies, target_key, need))
    if restricted_to_role is not None and restricted_to_role not in ROLES:
        raise ValueError(f"{key}: tanımsız rol {restricted_to_role!r}.")
    for name, values in (("admin_only", admin_only), ("locked", locked)):
        for level in values:
            if level not in levels:
                raise ValueError(f"{key}: {name} düzeyi bölümde yok ({level}).")
    if set(admin_only) & set(locked):
        raise ValueError(f"{key}: bir düzey hem yalnız admin hem kilitli olamaz.")
    order = sum(1 for other in _SECTIONS.values() if other.module == module_key)
    section = Section(
        key=key,
        label=label,
        levels=levels,
        kind=kind,
        read=read,
        help=help_map,
        requires=tuple(parsed),
        restricted_to_role=restricted_to_role,
        admin_only=tuple(admin_only),
        locked=tuple(locked),
        order=order,
    )
    _SECTIONS[key] = section
    return section


def register_open_records(module_key: str, *, affects: Sequence[str] = ()) -> Section:
    """Modülün "Açık kayıtlar" satırı (plan §5.2). Herkeste Kayıtları okur vardır; satır yalnız bir
    kişi için kapatılabilir (kaldırma).

    `affects`: satır kapatılınca etkilenen öteki ekranların Türkçe açıklamaları (plan §5.1, §5.3);
    Yetkiler ekranı ve `open_records_closed` uyarısı gösterir. Katalogun parçası değildir
    (`catalog()` ve özeti değişmez)."""
    section = register_section(
        f"{module_key}.{OPEN_RECORDS}",
        "Açık kayıtlar",
        levels=(READ,),
        kind=Kind.OPEN_RECORDS,
        help={READ: "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."},
    )
    _PACKAGES[EVERYONE].add((section.key, READ))
    texts = tuple(text.strip() for text in affects)
    if any(not text for text in texts):
        raise ValueError(f"{section.key}: etkilenen ekran açıklaması boş olamaz.")
    if texts:
        _OPEN_RECORDS_EFFECTS[module_key] = texts
    return section


def grant(holder: str, section: Section, *levels: str) -> None:
    """Paket sahibine (rol, `EVERYONE` ya da `ANY_ROLE`) bölümün düzeylerini varsayılan verir."""
    if holder not in HOLDERS:
        raise ValueError(f"Tanımsız paket sahibi: {holder!r}")
    if not levels:
        raise ValueError(f"{section.key}: en az bir düzey verilmelidir.")
    if section.kind is Kind.OPEN_RECORDS:
        raise ValueError(f"{section.key}: açık kayıtlar satırı pakete yazılmaz.")
    for level in levels:
        if level not in section.levels:
            raise ValueError(f"{section.key}: düzey bölümde yok ({level}).")
        if level in section.admin_only:
            raise ValueError(f"{section.key}: {level} yalnız sistem yöneticisine aittir.")
    if section.restricted_to_role is not None and holder != section.restricted_to_role:
        raise ValueError(
            f"{section.key}: yalnız {section.restricted_to_role} rolüne verilebilir (KVKK)."
        )
    for level in levels:
        _PACKAGES[holder].add((section.key, level))


def register_readers(name: str, *sections: SectionRef) -> None:
    """Bir kayıt türünü (`"production.productionorder"`) okuyabilen bölümler (plan §5.1 tablosu):
    bölümlerden birinde okuma (`can_read`) yeter. API'deki okuma kuralı aynı listedir."""
    _append(_READERS, name, sections)


def register_field_openers(name: str, *sections: SectionRef) -> None:
    """Bir alan grubunu (`"masterdata.customer.contact"`) tam gösteren bölümler (plan §3.1, §5.6):
    bölümlerden birinde Görür ya da grubun modülünün "Açık kayıtlar" satırı yeter
    (`EffectiveAccess.sees_fields`). Başka bir modül, kendi bölümünü ekleyebilir (ör. sales
    müşteri kartı için Satış siparişleri)."""
    _append(_FIELD_OPENERS, name, sections)


def _append(
    registry: dict[str, tuple[str, ...]], name: str, sections: Iterable[SectionRef]
) -> None:
    keys = tuple(_key_of(section) for section in sections)
    if not keys:
        raise ValueError(f"{name}: en az bir bölüm verilmelidir.")
    previous = registry.get(name, ())
    registry[name] = previous + tuple(key for key in keys if key not in previous)


# --- denetim günlüğü süzmesi (plan §5.1, §5.6) ---------------------------------------------------


@dataclass(frozen=True)
class AuditRule:
    """Denetim günlüğünde bir modelin kayıtlarını ya da alanlarını görmek için gereken yetki.

    `requires`'ın hepsi gerekir (`admin_only`: yalnız sistem yöneticisi). Yetkisi olmayana:

    - alan ve not verilmemişse kural kayıtları gizler: `rows` verilmişse yalnız o kayıtları
      (`AuditLog` üzerinde bir `Q`), verilmemişse modelin bütün kayıtlarını;
    - `fields` değişikliklerde gizlenir (`nested`: iç içe kayıtların içinde de); yalnız gizli
      alanları değiştiren kayıt hiç listelenmez (kayıt geçmişi gibi);
    - `note` (düzenli ifade, PostgreSQL ve Python'da aynı anlamda) eşleşen not gizlenir;
      `note_with_fields`: gizli alanlardan birini değiştiren kaydın notu da gizlenir (ör. fiyat
      düzeltmesinin kopyası). Değişikliği olmayan ve notu gizlenen kayıt listelenmez.

    `rows` verilirse alan ve not gizlemesi de yalnız o kayıtlara uygulanır. `label` olmayan kural
    içerik türü olmayan kayıtlar içindir (ör. bordrosu açılmamış ayın bordro erişimi).
    """

    label: str | None
    requires: tuple[tuple[str, str], ...] = ()
    admin_only: bool = False
    rows: Any = None  # django `Q` ya da `Q` döndüren çağrılabilir (model import etmemek için)
    fields: frozenset[str] = frozenset()
    nested: bool = False
    note: str | None = None
    note_with_fields: bool = False
    name: str = ""

    @property
    def hides_rows(self) -> bool:
        """Kural kayıtları mı gizler (alan ya da not değil)?"""
        return not self.fields and self.note is None


_AUDIT_RULES: list[AuditRule] = []
# Bağlı olduğu kaydı izleyen model (yorum, ek) → (içerik türü alanı, kayıt no alanı).
_AUDIT_PARENTS: dict[str, tuple[str, str]] = {}

AuditNeed = SectionRef | tuple[SectionRef, str]


def _audit_needs(items: Iterable[AuditNeed]) -> tuple[tuple[str, str], ...]:
    needs: list[tuple[str, str]] = []
    for item in items:
        target, level = item if isinstance(item, tuple) else (item, VIEW)
        needs.append((_key_of(target), level))
    return tuple(needs)


_MODEL_LABEL = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _check_audit_label(label: str) -> str:
    if not _MODEL_LABEL.match(label):
        raise ValueError(f"Geçersiz model etiketi: {label!r}")
    return label


def register_audit_model(
    label: str,
    *,
    requires: Iterable[AuditNeed] = (),
    admin_only: bool = False,
    rows: Any = None,
    fields: Iterable[str] = (),
    nested: bool = False,
    note: str | None = None,
    note_with_fields: bool = False,
) -> None:
    """Modelin (`"personnel.employeewage"`) denetim günlüğü kuralını kaydeder (`AuditRule`). Bir
    model birden çok kural alabilir; her kural kendi yetkisiyle ayrı uygulanır."""
    needs = _audit_needs(requires)
    if not needs and not admin_only:
        raise ValueError(f"{label}: gereken yetki ya da admin_only verilmelidir.")
    hidden = frozenset(fields)
    if (nested or note_with_fields) and not hidden:
        raise ValueError(f"{label}: nested ve note_with_fields gizli alan ister.")
    if note is not None:
        re.compile(note)
    _AUDIT_RULES.append(
        AuditRule(
            label=_check_audit_label(label),
            requires=needs,
            admin_only=admin_only,
            rows=rows,
            fields=hidden,
            nested=nested,
            note=note,
            note_with_fields=note_with_fields,
        )
    )


def register_audit_rows(
    name: str, rows: Any, *, requires: Iterable[AuditNeed] = (), admin_only: bool = False
) -> None:
    """İçerik türü olmayan kayıtlardan `rows`'a uyanları (ör. bordro erişimi) gereken yetkiye
    bağlar. `name` kuralın adıdır (ör. `"personnel.payroll_access"`)."""
    needs = _audit_needs(requires)
    if not needs and not admin_only:
        raise ValueError(f"{name}: gereken yetki ya da admin_only verilmelidir.")
    if rows is None:
        raise ValueError(f"{name}: kayıt koşulu verilmelidir.")
    _AUDIT_RULES.append(
        AuditRule(label=None, requires=needs, admin_only=admin_only, rows=rows, name=name)
    )


def register_audit_parent(
    label: str, *, content_type_field: str = "content_type", object_id_field: str = "object_id"
) -> None:
    """Denetim günlüğünde bağlı olduğu kaydı izleyen model (yorum, ek): bağlı kaydın modeli
    bütünüyle gizleniyorsa onun kayıtları da gizlenir (plan §5.6)."""
    _AUDIT_PARENTS[_check_audit_label(label)] = (content_type_field, object_id_field)


def audit_rules() -> tuple[AuditRule, ...]:
    return tuple(_AUDIT_RULES)


def audit_parents() -> dict[str, tuple[str, str]]:
    return dict(_AUDIT_PARENTS)


# --- iş akışı kurallarının gerektirdiği yetkiler (plan §5.1, §5.7) -------------------------------

TASK = "task"
NOTIFY = "notify"
CANCEL = "cancel"
RULE_KINDS: tuple[str, ...] = (TASK, NOTIFY, CANCEL)


@dataclass(frozen=True)
class RuleRequirement:
    """Bir iş akışı kuralının alıcıları: kuralın rollerinin etkin üyelerinden `requires`
    (`(bölüm anahtarı, düzey)`) yetkisi olanlar. `roles` boşsa kural role gitmez (ör. raporu
    isteyen kişiye giden bildirim); `requires` yalnız planın muaf tuttuğu kurallarda `None`'dır.

    workflow her kuralı `ready()`'de kaydeder; "kimse kalmıyor" denetimi (`core.coverage`), canlıya
    geçiş hazırlık listesi ve sistem durumu bu kayıttan okur, workflow'u import etmez. Katalogun
    parçası değildir (`catalog()` ve özeti değişmez).
    """

    code: str
    kind: str
    roles: tuple[str, ...]
    requires: tuple[str, str] | None


_RULES: dict[str, RuleRequirement] = {}


def register_rule(
    code: str, kind: str, roles: tuple[str, ...], requires: tuple[str, str] | None
) -> None:
    """İş akışı kuralının rollerini ve gerektirdiği yetkiyi kaydeder (`kind`: `"task"`, `"notify"`
    ya da `"cancel"`; iptal kuralında roller bildirim alan rollerdir). Bölüm anahtarı yüklenme
    sırasından bağımsız olsun diye burada değil `validate()`'te denetlenir."""
    if not code:
        raise ValueError("Kural kodu boş olamaz.")
    if code in _RULES:
        raise ValueError(f"Kural iki kez kaydedildi: {code}")
    if kind not in RULE_KINDS:
        raise ValueError(f"{code}: geçersiz kural türü {kind!r}.")
    unknown = [role for role in roles if role not in ALL_ROLES]
    if unknown:
        raise ValueError(f"{code}: tanımsız rol {', '.join(unknown)}.")
    if requires is not None and (len(requires) != 2 or not all(requires)):
        raise ValueError(f"{code}: gereken yetki (bölüm, düzey) çifti olmalıdır.")
    _RULES[code] = RuleRequirement(
        code=code,
        kind=kind,
        roles=tuple(dict.fromkeys(roles)),
        requires=None if requires is None else (requires[0], requires[1]),
    )


def rules() -> tuple[RuleRequirement, ...]:
    """Kayıtlı iş akışı kuralları, kayıt sırasıyla."""
    return tuple(_RULES.values())


# --- riskli yetki çiftleri (plan §5.11) -----------------------------------------------------------


@dataclass(frozen=True)
class RiskyPair:
    """Aynı kişide birlikte bulunması riskli iki yetki (görevler ayrılığı, plan §5.11).

    `first` ile `second`'dan herhangi biri ("ya da") birlikteyse çift tamamlanır. İki yetki aynı
    rol paketinden geliyorsa uyarı çıkmaz (`user_access.mixed_pairs`). Çiftler tek yerde
    (`apps/workflow/access.py`) kaydedilir; katalogun parçası değildir (`catalog()` ve özeti
    değişmez).
    """

    first: tuple[str, str]  # (bölüm anahtarı, düzey)
    second: tuple[tuple[str, str], ...]


_RISKY_PAIRS: list[RiskyPair] = []


def register_risky_pair(first: tuple[SectionRef, str], *second: tuple[SectionRef, str]) -> None:
    """Riskli yetki çiftini kaydeder: `first` ile `second`'dan biri. Bölüm anahtarları yüklenme
    sırasından bağımsız olsun diye burada değil `validate()`'te denetlenir."""
    if not second:
        raise ValueError(f"{_key_of(first[0])}: riskli çiftin ikinci yetkisi verilmelidir.")
    pair = RiskyPair(
        first=(_key_of(first[0]), first[1]),
        second=tuple((_key_of(target), level) for target, level in second),
    )
    if pair.first in pair.second:
        raise ValueError(f"{pair.first[0]}: yetki kendisiyle riskli çift olamaz.")
    if pair in _RISKY_PAIRS:
        raise ValueError(f"{pair.first[0]}: riskli çift iki kez kaydedildi.")
    _RISKY_PAIRS.append(pair)


def risky_pairs() -> tuple[RiskyPair, ...]:
    """Kayıtlı riskli yetki çiftleri, kayıt sırasıyla."""
    return tuple(_RISKY_PAIRS)


def open_records_effects(module_key: str) -> tuple[str, ...]:
    """Modülün "Açık kayıtlar" satırı kapatılınca etkilenen öteki ekranlar (yoksa boş)."""
    return _OPEN_RECORDS_EFFECTS.get(module_key, ())


def all_open_records_effects() -> dict[str, tuple[str, ...]]:
    """Bütün modüllerin etkilenen ekran açıklamaları (Yetkiler ekranının GET yanıtı için)."""
    return dict(_OPEN_RECORDS_EFFECTS)


def _ordered(keys: Iterable[str]) -> tuple[str, ...]:
    """Bölüm anahtarları katalog sırasıyla: kayıt sırası (hangi modülün önce yüklendiği) çıktıyı
    ve katalog özetini değiştirmez."""
    order = {item.key: index for index, item in enumerate(sections())}
    return tuple(sorted(keys, key=lambda key: (order.get(key, len(order)), key)))


# --- okuma ----------------------------------------------------------------------------------------


def module(key: str) -> Module:
    return _MODULES[key]


def modules() -> list[Module]:
    return sorted(_MODULES.values(), key=lambda item: (item.order, item.key))


def section(key: SectionRef) -> Section:
    """Bölüm; bilinmeyen anahtar `KeyError` fırlatır."""
    if isinstance(key, Section):
        return key
    try:
        return _SECTIONS[key]
    except KeyError:
        raise KeyError(f"Tanımsız yetki bölümü: {key}") from None


def has_section(key: str) -> bool:
    return key in _SECTIONS


def sections(module_key: str | None = None) -> list[Section]:
    """Bölümler; modül ve bölüm sırasıyla."""
    order = {item.key: index for index, item in enumerate(modules())}
    found = [item for item in _SECTIONS.values() if module_key in (None, item.module)]
    return sorted(found, key=lambda item: (order.get(item.module, 0), item.order))


def open_records_section(module_key: str) -> Section | None:
    return _SECTIONS.get(f"{module_key}.{OPEN_RECORDS}")


def package(holder: str) -> frozenset[tuple[str, str]]:
    return frozenset(_PACKAGES[holder])


def packages() -> dict[str, frozenset[tuple[str, str]]]:
    return {holder: frozenset(entries) for holder, entries in _PACKAGES.items()}


def readers(name: str) -> tuple[Section, ...]:
    return tuple(section(key) for key in _ordered(_READERS.get(name, ())))


def reader_names() -> list[str]:
    return sorted(_READERS)


def field_openers(name: str) -> tuple[Section, ...]:
    return tuple(section(key) for key in _ordered(_FIELD_OPENERS.get(name, ())))


def field_opener_names() -> list[str]:
    return sorted(_FIELD_OPENERS)


def has_field_group(name: str) -> bool:
    return name in _FIELD_OPENERS


def letters(entries: Iterable[tuple[str, str]], key: str) -> str:
    """Bir bölümün düzeylerini "rvca" sırasıyla harf olarak yazar."""
    present = {level for entry_key, level in entries if entry_key == key}
    return "".join(LEVEL_LETTERS[level] for level in ALL_LEVELS if level in present)


def catalog() -> dict[str, Any]:
    """Katalogun JSON'a yazılabilen tam hâli (API, `export_access` ve sürüm kopyası için)."""
    all_packages = packages()
    return {
        "modules": [
            {
                "key": item.key,
                "label": item.label,
                "order": item.order,
                "menu": item.menu,
                "sections": [
                    {
                        "key": entry.key,
                        "label": entry.label,
                        "kind": str(entry.kind),
                        "levels": list(entry.levels),
                        "help": {
                            level: entry.help[level]
                            for level in entry.levels
                            if level in entry.help
                        },
                        "read": str(entry.read),
                        "requires": [
                            {"level": applies, "key": key, "need": need}
                            for applies, key, need in entry.requires
                        ],
                        "restricted_to_role": entry.restricted_to_role,
                        "admin_only": list(entry.admin_only),
                        "locked": list(entry.locked),
                    }
                    for entry in sections(item.key)
                ],
            }
            for item in modules()
        ],
        "packages": {
            holder: {key: letters(entries, key) for key in sorted({key for key, _ in entries})}
            for holder, entries in all_packages.items()
        },
        "readers": {name: list(_ordered(_READERS[name])) for name in sorted(_READERS)},
        "field_openers": {
            name: list(_ordered(_FIELD_OPENERS[name])) for name in sorted(_FIELD_OPENERS)
        },
    }


def catalog_hash() -> str:
    """Katalogun özeti: paketler ya da bölümler değişince değişir (sürüm kopyası için)."""
    text = json.dumps(catalog(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate() -> list[str]:
    """Kataloğun bütünlük hataları (sistem denetimi kullanır; boş liste = sağlam)."""
    errors: list[str] = []
    for entry in _SECTIONS.values():
        for _applies, key, need in entry.requires:
            target = _SECTIONS.get(key)
            if target is None:
                errors.append(f"{entry.key}: ön koşul tanımsız bölüm ({key}).")
            elif need not in target.levels:
                errors.append(f"{entry.key}: ön koşul düzeyi {key} bölümünde yok ({need}).")
        if entry.read is ReadScope.OPEN and open_records_section(entry.module) is None:
            errors.append(f"{entry.key}: açık okumalı bölümün modülünde Açık kayıtlar satırı yok.")
    for module_key in _MODULES:
        if not any(item.module == module_key for item in _SECTIONS.values()):
            errors.append(f"{module_key}: modülde bölüm yok.")
    for name, keys in _READERS.items():
        for key in keys:
            if key not in _SECTIONS:
                errors.append(f"{name}: okuyan bölüm tanımsız ({key}).")
    for name, keys in _FIELD_OPENERS.items():
        if open_records_section(name.split(".", 1)[0]) is None:
            errors.append(f"{name}: alan grubunun modülünde Açık kayıtlar satırı yok.")
        for key in keys:
            target = _SECTIONS.get(key)
            if target is None:
                errors.append(f"{name}: alanları açan bölüm tanımsız ({key}).")
            elif not target.has_view:
                errors.append(f"{name}: alanları açan bölümün Görür düzeyi yok ({key}).")
    for rule in _AUDIT_RULES:
        name = rule.label or rule.name
        for key, level in rule.requires:
            target = _SECTIONS.get(key)
            if target is None:
                errors.append(f"{name}: denetim günlüğü kuralı tanımsız bölüm ({key}).")
            elif level not in target.levels:
                errors.append(f"{name}: denetim günlüğü kuralının düzeyi {key}'de yok ({level}).")
    for requirement in _RULES.values():
        if requirement.requires is None:
            continue
        key, level = requirement.requires
        target = _SECTIONS.get(key)
        if target is None:
            errors.append(f"{requirement.code}: iş akışı kuralı tanımsız bölüm ister ({key}).")
        elif level not in GRANT_LEVELS or level not in target.levels:
            errors.append(
                f"{requirement.code}: iş akışı kuralının düzeyi {key} bölümünde yok ({level})."
            )
    for pair in _RISKY_PAIRS:
        for key, level in (pair.first, *pair.second):
            target = _SECTIONS.get(key)
            if target is None:
                errors.append(f"Riskli çift tanımsız bölüm içeriyor ({key}).")
            elif level not in GRANT_LEVELS or level not in target.levels:
                errors.append(f"Riskli çiftin düzeyi {key} bölümünde yok ({level}).")
    for module_key in _OPEN_RECORDS_EFFECTS:
        if open_records_section(module_key) is None:
            errors.append(f"{module_key}: etkilenen ekranlar verilen modülde Açık kayıtlar yok.")
    errors.extend(_requirement_cycles())
    return errors


def _requirement_cycles() -> list[str]:
    graph = {key: {target for _, target, _ in item.requires} for key, item in _SECTIONS.items()}
    errors: list[str] = []
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for target in sorted(graph.get(node, ())):
            if state.get(target) == 1:
                cycle = [*path[path.index(target) :], target] if target in path else [node, target]
                errors.append("Döngülü ön koşul: " + " → ".join(cycle))
            elif state.get(target) is None and target in graph:
                visit(target, [*path, target])
        state[node] = 2

    for node in sorted(graph):
        if state.get(node) is None:
            visit(node, [node])
    return errors


@contextmanager
def temporary_catalog() -> Iterator[None]:
    """Yalnız testler için: blok içinde kaydedilen modül, bölüm, paket, denetim günlüğü ve iş
    akışı kuralları, riskli çiftler ve etkilenen ekran açıklamaları blok bitince silinir."""
    saved = (
        dict(_MODULES),
        dict(_SECTIONS),
        copy.deepcopy(_PACKAGES),
        dict(_READERS),
        dict(_FIELD_OPENERS),
        list(_AUDIT_RULES),
        dict(_AUDIT_PARENTS),
        dict(_RULES),
        list(_RISKY_PAIRS),
        dict(_OPEN_RECORDS_EFFECTS),
    )
    try:
        yield
    finally:
        _MODULES.clear()
        _MODULES.update(saved[0])
        _SECTIONS.clear()
        _SECTIONS.update(saved[1])
        _PACKAGES.clear()
        _PACKAGES.update(saved[2])
        _READERS.clear()
        _READERS.update(saved[3])
        _FIELD_OPENERS.clear()
        _FIELD_OPENERS.update(saved[4])
        _AUDIT_RULES[:] = saved[5]
        _AUDIT_PARENTS.clear()
        _AUDIT_PARENTS.update(saved[6])
        _RULES.clear()
        _RULES.update(saved[7])
        _RISKY_PAIRS[:] = saved[8]
        _OPEN_RECORDS_EFFECTS.clear()
        _OPEN_RECORDS_EFFECTS.update(saved[9])


# --- core'un bölümleri: hassas veriler ve sistem --------------------------------------------------

register_module("sensitive", "Hassas veriler", order=5, menu=False)
register_module("system", "Sistem", order=920, menu=False)

PRICES = register_section(
    "sensitive.prices",
    "Fiyatları görür",
    levels=(VIEW,),
    kind=Kind.SENSITIVE,
    help={
        VIEW: "Alış fiyatları: mal kabul fiyat ve masrafları, satın alma tutarları ve sipariş "
        "PDF'i. Satış fiyatları bu hakka bağlı değildir."
    },
)
COSTS = register_section(
    "sensitive.costs",
    "Maliyetleri görür",
    levels=(VIEW,),
    kind=Kind.SENSITIVE,
    help={VIEW: "Lot maliyeti, stok değeri ve raporların maliyet sütunları."},
    requires={ALL: [(PRICES, VIEW)]},
)
AUDIT_LOG = register_section(
    "system.audit_log",
    "Denetim günlüğü",
    levels=(VIEW,),
    help={VIEW: "Bütün kayıtların değişiklik geçmişi (API)."},
    restricted_to_role=YONETIM,
)

grant(SATIN_ALMA, PRICES, VIEW)
grant(YONETIM, PRICES, VIEW)
grant(YONETIM, COSTS, VIEW)
grant(YONETIM, AUDIT_LOG, VIEW)


# --- core'un denetim günlüğü kuralları (plan §5.6 "Yetki kayıtları") -----------------------------

# Kişiye özel yetkilerin önce ve sonra hâli kullanıcı kaydında bu alanlardadır (Paket B'deki
# `set_user_access` yazar); gerekçe notu da yalnız admine görünür. Rollerin önce ve sonra hâli
# (`roles`) bugünkü gibi yönetime de görünür.
USER_ACCESS_FIELDS: tuple[str, ...] = ("access",)

register_audit_model("core.accessoverride", admin_only=True)
register_audit_model("core.accesscatalogsnapshot", admin_only=True)
register_audit_model("core.user", admin_only=True, fields=USER_ACCESS_FIELDS, note_with_fields=True)
# Dosya eki bağlı olduğu kaydı izler (yorumun eki yorumun kaydını; workflow yorumu kaydeder).
register_audit_parent("core.attachment")
