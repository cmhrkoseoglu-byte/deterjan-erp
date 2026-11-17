""" "Kim neyi görür" raporunun Excel çıktısı (plan §6.2; openpyxl). Doküman kontrollü çıktı
`core.access-report` (ISO 9001 md. 7.5). Gerekçe içerdiği için yalnız admin indirir."""

import io
from collections.abc import Mapping, Sequence
from typing import Any

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from apps.core import access
from apps.core.access import ALL_LEVELS, ANY_ROLE, EVERYONE, LEVEL_LABELS, READ
from apps.core.access_report import (
    ANY_ROLE_SOURCE,
    EVERYONE_SOURCE,
    GRANTED_SOURCE,
    IMPLIED_SOURCE,
    ROLE_SOURCE,
    PersonAccess,
)
from apps.core.coding.outputs import document_control
from apps.core.user_access import OverrideSpec, is_ineffective
from apps.core.xlsx import apply_document_control, sheet_text

ACCESS_REPORT_OUTPUT = "core.access-report"

# Ekrandaki gibi Türkçe harfler (G Görür, D Değiştirir, O Onaylar, K Kayıtları okur).
EXCEL_LETTERS: dict[str, str] = {READ: "K", "view": "G", "change": "D", "approve": "O"}
SOURCE_TEXTS: dict[str, str] = {
    EVERYONE_SOURCE: "Herkese açık",
    ANY_ROLE_SOURCE: "Rolü olan herkes",
    GRANTED_SOURCE: "Kişiye özel eklendi",
    IMPLIED_SOURCE: "Görür (Değiştirir ya da Onaylar ile)",
}


def _sheet(workbook: Workbook, title: str, headers: Sequence[str], *, first: bool = False) -> Any:
    if first:
        ws = workbook.active
        assert ws is not None
        ws.title = title
    else:
        ws = workbook.create_sheet(title)
    ws.append(list(headers))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    return ws


def _append(ws: Worksheet, values: Sequence[Any]) -> None:
    """Veri satırı. Kullanıcının yazdığı metin (ad, kullanıcı adı, gerekçe) formül olmasın diye her
    değer `sheet_text`'ten geçer."""
    ws.append([sheet_text(ws, value) for value in values])


def _widths(ws: Worksheet, headers: Sequence[str]) -> None:
    for index, label in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(14, len(label) + 2)


def _module_label(key: str) -> str:
    module = key.split(".", 1)[0]
    try:
        return access.module(module).label
    except KeyError:
        return module


def _section_label(key: str) -> str:
    return access.section(key).label if access.has_section(key) else key


def _cell_text(entry: tuple[str, str]) -> str:
    key, level = entry
    return f"{_module_label(key)} › {_section_label(key)}: {LEVEL_LABELS.get(level, level)}"


def _letters(entries: frozenset[tuple[str, str]], key: str) -> str:
    present = {level for entry_key, level in entries if entry_key == key}
    return " ".join(EXCEL_LETTERS[level] for level in ALL_LEVELS if level in present)


def _role_text(codes: Sequence[str], labels: Mapping[str, str]) -> str:
    return ", ".join(labels.get(code, code) for code in codes)


PAIR_SOURCES: dict[str, str] = {ROLE_SOURCE: "Rol", GRANTED_SOURCE: "Kişiye özel"}


def _sources_text(sources: str) -> str:
    """`role+granted` → "Rol + Kişiye özel"."""
    return " + ".join(PAIR_SOURCES.get(part, part) for part in sources.split("+"))


def access_report_xlsx(rows: Sequence[PersonAccess], holder_labels: Mapping[str, str]) -> bytes:
    """Dört sayfa: rol paketleri, kişilerin yetkileri, kişiye özel ayarlar, görev ayrılığı.
    `holder_labels`: paket sahiplerinin (herkes, rolü olan herkes, roller) Türkçe adları."""
    workbook = Workbook()

    holders = (EVERYONE, ANY_ROLE, *access.ROLES)
    headers = ["Modül", "Bölüm", *(holder_labels.get(holder, holder) for holder in holders)]
    ws = _sheet(workbook, "Rol paketleri", headers, first=True)
    packages = access.packages()
    for item in access.sections():
        _append(
            ws,
            [
                _module_label(item.key),
                item.label,
                *(_letters(packages[holder], item.key) for holder in holders),
            ],
        )
    _widths(ws, headers)

    headers = ["Kullanıcı adı", "Ad soyad", "Roller", "Modül", "Bölüm", "Düzey", "Kaynak"]
    ws = _sheet(workbook, "Kişilerin yetkileri", headers)
    for row in rows:
        user = row.user
        person = [user.username, user.full_name, _role_text(user.roles, holder_labels)]
        if row.is_admin:
            _append(ws, [*person, "Tümü", "Tümü", "Tümü", "Sistem yöneticisi"])
            continue
        for item in access.sections():
            for level in item.levels:
                if level == READ:
                    continue
                cell = row.cells.get((item.key, level))
                if cell is None or not cell.effective:
                    continue
                source, held = row.source((item.key, level))
                text = (
                    f"Rolden ({_role_text(held, holder_labels)})"
                    if source == ROLE_SOURCE
                    else SOURCE_TEXTS.get(source, source)
                )
                _append(
                    ws, [*person, _module_label(item.key), item.label, LEVEL_LABELS[level], text]
                )
    _widths(ws, headers)

    headers = [
        "Kullanıcı",
        "Bölüm",
        "Düzey",
        "Değişiklik",
        "Gerekçe",
        "Değiştiren",
        "Başlangıç",
        "Etkisiz",
    ]
    ws = _sheet(workbook, "Kişiye özel ayarlar", headers)
    for row in rows:
        for override in row.personal:
            ineffective = is_ineffective(OverrideSpec.of(override), row.user.roles)
            _append(
                ws,
                [
                    row.user.username,
                    f"{_module_label(override.key)} › {_section_label(override.key)}",
                    LEVEL_LABELS.get(override.level, override.level),
                    override.get_effect_display(),
                    override.note,
                    str(override.created_by) if override.created_by_id else "",
                    f"{timezone.localtime(override.created_at):%d.%m.%Y %H:%M}",
                    "Evet" if ineffective else "",
                ],
            )
    _widths(ws, headers)

    headers = ["Kullanıcı", "Yetki 1", "Yetki 2", "Kaynaklar"]
    ws = _sheet(workbook, "Görev ayrılığı", headers)
    for row in rows:
        for flag in row.pairs:
            _append(
                ws,
                [
                    row.user.username,
                    _cell_text(flag.first),
                    _cell_text(flag.second),
                    _sources_text(flag.sources),
                ],
            )
    _widths(ws, headers)

    apply_document_control(workbook, document_control(ACCESS_REPORT_OUTPUT))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
