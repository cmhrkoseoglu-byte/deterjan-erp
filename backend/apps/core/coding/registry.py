"""Kod türü kaydı.

Her modül kod türlerini `AppConfig.ready()` içinde kaydeder; `core` hiçbir modülü import etmez
(`core.records` deseni):

    register_master_code("masterdata.material", label="Malzeme", model="masterdata.material",
                         default_prefix="MLZ", default_width=7, scanned=True)
    register_document_type("UE", label="Üretim emri", model="production.productionorder")
    register_lot_type("H", label="Satın alma lotu")

Anahtarlar: ana veri `<app_label>.<model>`, belge `document.<önek>`, lot `lot.<önek>`. Belge ve lot
türünün anahtarındaki önek, çağrı yerlerinin kullandığı varsayılan önektir (`create_document(
prefix="UE")`); admin öneki değiştirse de çağrı yerleri değişmez.
"""

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

# Lot türünün o gün (önek + gün) verilen son numarası; sayaç tablosu lotun modülündedir.
LotCounter = Callable[[str, date], int]
# Kod göçü: kaydın kodunu modülün kendi servisiyle değiştirir (yalnız kod kuralları, denetimli).
# recode(actor, kayıt, yeni_kod, not, göç_no, neden) → kayıt
Recode = Callable[[Any, Any, str, str, int | None, str], Any]

MASTER = "master"
DOCUMENT = "document"
LOT = "lot"
STANDARD = "standard"
KINDS = (MASTER, DOCUMENT, LOT, STANDARD)


@dataclass(frozen=True)
class CodeType:
    """Kayıtlı bir kod türü. Ayarlanabilen alanların varsayılanları burada durur; admin'in
    değiştirdiği değerler `core.CodeScheme` satırındadır."""

    key: str
    kind: str
    label: str
    default_prefix: str = ""
    default_width: int = 5
    # Ana veri ve standart kod
    model: str = ""
    field: str = "code"
    free: bool = False  # serbest kod: öneri yok, yalnızca karakter kuralı
    type_field: str = ""  # önek kaydın bu alanından gelir (ekipman türü)
    type_choices: Sequence[tuple[str, str]] = ()
    default_type_prefixes: Mapping[str, str] = dataclasses.field(default_factory=dict)
    scanned: bool = False  # barkodla okutulur: harfle başlamalı
    allow_underscore: bool = False
    max_length: int = 32
    write_roles: tuple[str, ...] = ()
    recode: Recode | None = dataclasses.field(default=None, compare=False)
    # Belge
    locked: bool = False  # ekrandan değiştirilemez (yasal belge numarası)
    default_year_format: str = "YYYY"
    # Lot
    default_date_format: str = "YYYYMMDD"
    lot_counter: LotCounter | None = dataclasses.field(default=None, compare=False)

    @property
    def configurable(self) -> bool:
        return self.kind != STANDARD and not self.locked

    @property
    def model_label(self) -> str:
        return self.model.lower()


_REGISTRY: dict[str, CodeType] = {}


def _register(code_type: CodeType) -> CodeType:
    _REGISTRY[code_type.key] = code_type
    return code_type


def register_master_code(
    key: str,
    *,
    label: str,
    model: str,
    default_prefix: str = "",
    default_width: int = 5,
    field: str = "code",
    free: bool = False,
    type_field: str = "",
    type_choices: Sequence[tuple[str, str]] = (),
    default_type_prefixes: Mapping[str, str] | None = None,
    scanned: bool = False,
    allow_underscore: bool = False,
    max_length: int = 32,
    write_roles: Sequence[str] = (),
    recode: Recode | None = None,
) -> CodeType:
    """Ana veri kod türünü kaydeder. `free=True`: serbest kod (yalnızca karakter kuralı).
    `type_field` verilirse önek kaydın türünden gelir (`default_type_prefixes`). `recode` verilen
    türün mevcut kodları kod göçüyle yeni biçime taşınabilir."""
    if not free and not type_field and not default_prefix:
        raise ValueError(f"{key}: sıralı kodun varsayılan öneki olmalıdır.")
    return _register(
        CodeType(
            key=key.lower(),
            kind=MASTER,
            label=label,
            default_prefix=default_prefix,
            default_width=default_width,
            model=model.lower(),
            field=field,
            free=free,
            type_field=type_field,
            type_choices=tuple(type_choices),
            default_type_prefixes=MappingProxyType(dict(default_type_prefixes or {})),
            scanned=scanned,
            allow_underscore=allow_underscore,
            max_length=max_length,
            write_roles=tuple(write_roles),
            recode=recode,
        )
    )


def register_standard_code(key: str, *, label: str, model: str, field: str = "code") -> CodeType:
    """Standart kod türü (birim, H/P/EUH): ayarlanamaz, ekranda salt okunur listelenir."""
    return _register(
        CodeType(key=key.lower(), kind=STANDARD, label=label, model=model.lower(), field=field)
    )


def register_document_type(
    prefix: str, *, label: str, model: str = "", locked: bool = False
) -> CodeType:
    """Belge türünü kaydeder; `prefix` çağrı yerlerinin kullandığı varsayılan önektir."""
    return _register(
        CodeType(
            key=f"{DOCUMENT}.{prefix}",
            kind=DOCUMENT,
            label=label,
            default_prefix=prefix,
            default_width=5,
            model=model.lower(),
            field="number",
            locked=locked,
        )
    )


def register_lot_type(prefix: str, *, label: str, counter: LotCounter | None = None) -> CodeType:
    """Lot türünü kaydeder; `prefix` çağrı yerlerinin kullandığı varsayılan önektir. `counter`
    (önek, gün) için verilen son numarayı döner (ekranda gösterilir, sıra hanesi denetlenir)."""
    return _register(
        CodeType(
            key=f"{LOT}.{prefix}",
            kind=LOT,
            label=label,
            default_prefix=prefix,
            default_width=3,
            model="inventory.lot",
            field="lot_no",
            lot_counter=counter,
        )
    )


def code_type(key: str) -> CodeType | None:
    """Kayıtlı tür ya da None. Ana veri anahtarı küçük harfe çevrilerek de aranır; belge ve lot
    anahtarındaki önek büyük harftir (`document.UE`)."""
    key = (key or "").strip()
    return _REGISTRY.get(key) or _REGISTRY.get(key.lower())


def get_code_type(key: str) -> CodeType:
    """Kayıtlı tür; yoksa `KeyError`."""
    found = code_type(key)
    if found is None:
        raise KeyError(key)
    return found


def code_types(kind: str | None = None) -> list[CodeType]:
    """Kayıtlı türler (tür sırası: ana veri, belge, lot, standart; içinde etikete göre)."""
    order = {name: index for index, name in enumerate(KINDS)}
    items = [item for item in _REGISTRY.values() if kind is None or item.kind == kind]
    return sorted(items, key=lambda item: (order[item.kind], item.label))


def master_type_for_model(model_label: str) -> CodeType | None:
    """`"app_label.model"` için kayıtlı ana veri ya da standart kod türü."""
    label = model_label.lower()
    for item in _REGISTRY.values():
        if item.kind in (MASTER, STANDARD) and item.model == label:
            return item
    return None


def document_type(prefix: str) -> CodeType | None:
    return _REGISTRY.get(f"{DOCUMENT}.{prefix}")


def lot_type(prefix: str) -> CodeType | None:
    return _REGISTRY.get(f"{LOT}.{prefix}")


# --- çıktı doküman kodları (ISO 9001 md. 7.5) ----------------------------------------------------


@dataclass(frozen=True)
class OutputType:
    """Basılı çıktı (PDF, Excel). Doküman no ve revizyonlar `core.OutputDocument`'tadır;
    `template_version` şablon kodda değişince artırılır (ekran yeni revizyon ister)."""

    key: str
    label: str
    group: str
    formats: tuple[str, ...]
    template_version: int = 1
    legal: bool = False  # yasal belge (irsaliye): bandı açmadan önce mali müşavire danışılır
    suggested_code: str = ""  # Türk KYS geleneğinde öneri (FR-KAL-001); yalnızca öneridir


_OUTPUTS: dict[str, OutputType] = {}


def register_output(
    key: str,
    *,
    label: str,
    group: str,
    formats: Sequence[str],
    template_version: int = 1,
    legal: bool = False,
    suggested_code: str = "",
) -> OutputType:
    """Çıktıyı kaydeder (modülün `AppConfig.ready()`'sinde). `group` ekrandaki başlıktır."""
    item = OutputType(
        key=key,
        label=label,
        group=group,
        formats=tuple(formats),
        template_version=template_version,
        legal=legal,
        suggested_code=suggested_code,
    )
    _OUTPUTS[key] = item
    return item


def output_type(key: str) -> OutputType | None:
    return _OUTPUTS.get((key or "").strip())


def output_types() -> list[OutputType]:
    return sorted(_OUTPUTS.values(), key=lambda item: (item.group, item.label))
