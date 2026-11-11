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


def register_open_records(module_key: str) -> Section:
    """Modülün "Açık kayıtlar" satırı (plan §5.2). Herkeste Kayıtları okur vardır; satır yalnız bir
    kişi için kapatılabilir (kaldırma)."""
    section = register_section(
        f"{module_key}.{OPEN_RECORDS}",
        "Açık kayıtlar",
        levels=(READ,),
        kind=Kind.OPEN_RECORDS,
        help={READ: "Bu modülün kayıtlarını giriş yapan herkes okuyabilir."},
    )
    _PACKAGES[EVERYONE].add((section.key, READ))
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
    """Yalnız testler için: blok içinde kaydedilen modül, bölüm ve paketler blok bitince silinir."""
    saved = (
        dict(_MODULES),
        dict(_SECTIONS),
        copy.deepcopy(_PACKAGES),
        dict(_READERS),
        dict(_FIELD_OPENERS),
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
