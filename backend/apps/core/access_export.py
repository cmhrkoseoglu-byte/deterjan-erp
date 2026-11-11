"""Yetki kataloğunun dışa aktarımı: ön yüz için TypeScript, belgeler için Markdown.

`python manage.py export_access --format=ts` ön yüzün `src/auth/access.gen.ts` dosyasını yazar; CI
`--check` ile dosyanın güncel olduğunu denetler (docs/plan/kisi-yetkileri.md §5.1). Böylece bölüm
anahtarları, adları ve rol paketlerinin tek kaynağı backend'deki `access.py` dosyalarıdır.
"""

import json
import re
from typing import Any

from apps.core import access
from apps.core.roles import ROLE_LABELS

TS_HEADER = """\
// Bu dosya üretilir; elle değiştirmeyin.
// Kaynak: backend/apps/*/access.py (docs/plan/kisi-yetkileri.md §5.1).
// Yeniden üretmek için (backend klasöründe):
//   python manage.py export_access --format=ts --output ../frontend/src/auth/access.gen.ts
"""


def perm_name(key: str) -> str:
    """`production.orders` → `PRODUCTION_ORDERS`."""
    return re.sub(r"[^A-Z0-9]+", "_", key.upper())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _section_meta(entry: access.Section) -> dict[str, Any]:
    return {
        "key": entry.key,
        "module": entry.module,
        "label": entry.label,
        "kind": str(entry.kind),
        "levels": list(entry.levels),
        "help": {level: entry.help[level] for level in entry.levels if level in entry.help},
        "read": str(entry.read),
        "requires": [
            {"level": applies, "key": key, "need": need} for applies, key, need in entry.requires
        ],
        "restrictedToRole": entry.restricted_to_role,
        "adminOnly": list(entry.admin_only),
        "locked": list(entry.locked),
    }


def to_typescript() -> str:
    """Ön yüzün `access.gen.ts` dosyasının içeriği."""
    data = access.catalog()
    perms = {perm_name(entry.key): entry.key for entry in access.sections()}
    modules = [
        {
            "key": item["key"],
            "label": item["label"],
            "menu": item["menu"],
            "sections": [section["key"] for section in item["sections"]],
        }
        for item in data["modules"]
    ]
    sections = {entry.key: _section_meta(entry) for entry in access.sections()}
    holders = {
        access.EVERYONE: access.HOLDER_LABELS[access.EVERYONE],
        access.ANY_ROLE: access.HOLDER_LABELS[access.ANY_ROLE],
        **{role: ROLE_LABELS[role] for role in access.ROLES},
    }
    parts = [
        TS_HEADER,
        f'export const ACCESS_CATALOG_HASH = "{access.catalog_hash()}";\n',
        'export type AccessLevel = "read" | "view" | "change" | "approve";',
        'export type ReadScope = "view" | "shared" | "any_role" | "open";',
        'export type SectionKind = "section" | "action" | "sensitive" | "open_records";\n',
        "export interface SectionMeta {",
        "  key: string;",
        "  module: string;",
        "  label: string;",
        "  kind: SectionKind;",
        "  levels: readonly AccessLevel[];",
        "  help: Readonly<Partial<Record<AccessLevel, string>>>;",
        "  read: ReadScope;",
        '  /** Düzey (ya da "*" her düzey) için gereken bölüm ve düzey. */',
        "  requires: readonly { level: string; key: string; need: AccessLevel }[];",
        "  restrictedToRole: string | null;",
        "  adminOnly: readonly AccessLevel[];",
        "  locked: readonly AccessLevel[];",
        "}\n",
        "export interface ModuleMeta {",
        "  key: string;",
        "  label: string;",
        "  /** false: menüde kendi modülü yok, bölümleri menü açmaz. */",
        "  menu: boolean;",
        "  sections: readonly PermKey[];",
        "}\n",
        f"export const LEVEL_LABELS: Readonly<Record<AccessLevel, string>> = "
        f"{_json(access.LEVEL_LABELS)};\n",
        '/** Paket sahipleri: "*" herkes, "+" rolü olan herkes ve 8 rol. */',
        f"export const HOLDER_LABELS: Readonly<Record<string, string>> = {_json(holders)};\n",
        f"export const PERM = {_json(perms)} as const;\n",
        "export type PermKey = (typeof PERM)[keyof typeof PERM];\n",
        f"export const MODULES: readonly ModuleMeta[] = {_json(modules)};\n",
        f"export const SECTIONS: Readonly<Record<PermKey, SectionMeta>> = {_json(sections)};\n",
        '/** Paket sahibi → bölüm → "vca" harfleri (rol varsayılanları). */',
        "export const PACKAGES: Readonly<Record<string, Readonly<Record<string, string>>>> = "
        f"{_json(data['packages'])};\n",
        "/** Kayıt türü ya da alan grubu → okuyabilen bölümler. */",
        "export const READERS: Readonly<Record<string, readonly PermKey[]>> = "
        f"{_json(data['readers'])};",
    ]
    return "\n".join(parts) + "\n"


def to_markdown() -> str:
    """Rol paketleri tablosu (belgeler için): bölüm × paket sahibi, hücrede "vca" harfleri."""
    holders = access.HOLDERS
    labels = {**access.HOLDER_LABELS, **ROLE_LABELS}
    packages = access.packages()
    lines = [
        "| Modül | Bölüm | " + " | ".join(labels[holder] for holder in holders) + " | Not |",
        "|---|---|" + "---|" * len(holders) + "---|",
    ]
    for module in access.modules():
        for entry in access.sections(module.key):
            cells = [access.letters(packages[holder], entry.key) or "" for holder in holders]
            notes = []
            if entry.restricted_to_role:
                notes.append(f"yalnız {ROLE_LABELS[entry.restricted_to_role]} (KVKK)")
            if entry.admin_only:
                notes.append(
                    "yalnız admin: "
                    + ", ".join(access.LEVEL_LABELS[level] for level in entry.admin_only)
                )
            if entry.locked:
                notes.append(
                    "kilitli: " + ", ".join(access.LEVEL_LABELS[level] for level in entry.locked)
                )
            if entry.read is not access.ReadScope.VIEW:
                notes.append(f"okuma: {entry.read}")
            row = [module.label, entry.label, *cells, "; ".join(notes)]
            lines.append("| " + " | ".join(row) + " |")
    legend = "Harfler: r kayıtları okur, v görür, c değiştirir, a onaylar."
    return "\n".join(lines) + "\n\n" + legend + "\n"
