"""Reçete içe aktarma (Excel'den geçiş, Faz 5 Adım 5.6).

Dosyada her satır bir reçete bileşenidir; aynı reçete kodlu satırlar bir sürümü oluşturur.
Reçete sistemde yoksa açılır; her reçete için yeni bir **taslak** sürüm açılır ve satırlar eklenir.
Onay laboratuvarın işidir (içe aktarma onaylı sürüm üretmez). Proses adımları elle girilir.

Ana verilerdeki gibi: önce `preview_import` (hiçbir şey yazılmaz), sonra `run_import`. Hatalı
satır varsa hiçbir reçete yazılmaz. Doğrulama servis fonksiyonlarının kendisiyle, geri alınan
bir işlemde yapılır; önizleme ile aktarma aynı kuralları uygular.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import IO, Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.masterdata.importers import (
    CellError,
    Column,
    ImportHasErrors,
    ImportReport,
    RowResult,
    _text,
    build_template_for,
    code_lookup_parser,
    parse_bool,
    parse_code,
    parse_decimal,
    parse_text,
    read_table,
)
from apps.masterdata.models import Material, UnitOfMeasure
from apps.recipes import services
from apps.recipes.models import Recipe, RecipeVersion

KIND = "recipes"
TITLE = "Reçeteler"
NOTE = "Excel içe aktarma"

COLUMNS: tuple[Column, ...] = (
    Column("Reçete kodu", "recipe_code", parse_code, required=True, example="RC-BULASIK"),
    Column(
        "Reçete adı",
        "recipe_name",
        parse_text,
        example="Bulaşık deterjanı",
        help="Yeni reçetede zorunlu; aynı reçetenin her satırında aynı olmalı",
    ),
    Column(
        "Ürün kodu",
        "product",
        code_lookup_parser(Material, "Ürün"),
        example="YM-BULASIK",
        help="Yarı mamul (dökme) malzeme kodu; yeni reçetede zorunlu",
    ),
    Column("Şarj miktarı", "batch_size", parse_decimal, required=True, example=1000),
    Column(
        "Şarj birimi",
        "batch_unit",
        code_lookup_parser(UnitOfMeasure, "Birim"),
        required=True,
        example="KG",
    ),
    Column(
        "Malzeme kodu",
        "material",
        code_lookup_parser(Material, "Malzeme"),
        required=True,
        example="HM-LAS",
        help="Hammadde ya da yarı mamul",
    ),
    Column("Miktar", "quantity", parse_decimal, required=True, example="120,5"),
    Column(
        "Birim",
        "unit",
        code_lookup_parser(UnitOfMeasure, "Birim"),
        example="KG",
        help="Boşsa malzemenin temel birimi",
    ),
    Column("Tolerans (%)", "tolerance_pct", parse_decimal, example=2, help="Boşsa %2"),
    Column("Şebeke suyu", "is_water", parse_bool, example="Hayır", help="Evet / Hayır"),
    Column("Talimat", "instruction", parse_text, example="Karıştırarak yavaşça ekleyin"),
)

HEADER_FIELDS = ("recipe_name", "product", "batch_size", "batch_unit")
LINE_FIELDS = ("material", "quantity", "unit", "tolerance_pct", "is_water", "instruction")


@dataclass
class _Group:
    code: str
    rows: list[RowResult] = field(default_factory=list)
    header: dict[str, Any] = field(default_factory=dict)


def _error(row: RowResult, message: str, column: str = "") -> None:
    row.errors.append({"column": column, "message": message})


def _messages(exc: Exception) -> list[str]:
    if isinstance(exc, BusinessRuleError):
        return [exc.message]
    if isinstance(exc, ValidationError):
        return [str(m) for messages in exc.message_dict.values() for m in messages]
    return [str(exc)]  # pragma: no cover


def _parse(rows: list[tuple[int, dict[str, Any]]]) -> tuple[list[RowResult], dict[str, _Group]]:
    results: list[RowResult] = []
    groups: dict[str, _Group] = {}
    headers = {c.field: c.header for c in COLUMNS}
    for row_no, cells in rows:
        result = RowResult(row=row_no, code="", action="create")
        for column in COLUMNS:
            raw = cells.get(column.field)
            if _text(raw) == "":
                if column.required:
                    _error(result, "Zorunlu alan boş.", column.header)
                continue
            try:
                result.data[column.field] = column.parse(raw)
            except CellError as exc:
                _error(result, str(exc), column.header)
        results.append(result)
        code = result.data.get("recipe_code")
        if not code:
            continue
        material = result.data.get("material")
        result.code = f"{code} / {material.code}" if material else code
        group = groups.setdefault(code, _Group(code=code))
        group.rows.append(result)
        # Başlık alanları reçetenin ilk dolu değeridir; sonraki satırlar farklıysa hata.
        for name in HEADER_FIELDS:
            if name not in result.data:
                continue
            value = result.data[name]
            first = group.header.setdefault(name, value)
            if first != value:
                _error(result, "Aynı reçetenin satırlarında farklı değer var.", headers[name])
    return results, groups


def _apply_group(actor: User | None, group: _Group) -> None:
    """Grubu servislerle yazar; hataları satırlara ekler (çağıran geri alır)."""
    first = group.rows[0]
    recipe = Recipe.objects.filter(code=group.code).first()
    action = "update" if recipe else "create"
    for row in group.rows:
        row.action = action
    if recipe is not None:
        if RecipeVersion.objects.filter(recipe=recipe, status=RecipeVersion.Status.DRAFT).exists():
            _error(
                first,
                f"{group.code} reçetesinin taslak sürümü var; önce onu onaylayın ya da "
                "reçeteyi dosyadan çıkarın.",
                "Reçete kodu",
            )
            return
    else:
        missing = [
            header
            for name, header in (("recipe_name", "Reçete adı"), ("product", "Ürün kodu"))
            if name not in group.header
        ]
        for header in missing:
            _error(first, "Yeni reçetede zorunlu.", header)
        if missing:
            return
        try:
            recipe = services.create_recipe(
                actor,
                {
                    "code": group.code,
                    "name": group.header["recipe_name"],
                    "product": group.header["product"],
                },
            )
        except (BusinessRuleError, ValidationError) as exc:
            for message in _messages(exc):
                _error(first, message, "Ürün kodu")
            return
    try:
        version = services.create_version(
            actor,
            recipe,
            batch_size=group.header["batch_size"],
            batch_unit=group.header["batch_unit"],
            change_note=NOTE,
        )
    except (BusinessRuleError, ValidationError) as exc:
        for message in _messages(exc):
            _error(first, message, "Şarj birimi")
        return
    for row in group.rows:
        line = {name: row.data[name] for name in LINE_FIELDS if name in row.data}
        line.setdefault("unit", row.data["material"].base_unit)
        line.setdefault("tolerance_pct", Decimal("2.00"))
        try:
            with transaction.atomic():
                services.add_line(actor, version, line)
        except (BusinessRuleError, ValidationError) as exc:
            for message in _messages(exc):
                _error(row, message)


def _build(actor: User | None, upload: IO[bytes], filename: str) -> ImportReport:
    rows, file_errors = read_table(upload, filename, COLUMNS)
    results, groups = _parse(rows)
    report = ImportReport(kind=KIND, rows=results, file_errors=file_errors)
    if report.has_errors:
        return report
    for group in groups.values():
        with transaction.atomic():
            _apply_group(actor, group)
    return report


def preview_import(upload: IO[bytes], filename: str) -> ImportReport:
    """Dosyayı servislerle dener ve geri alır; satır bazlı hata listesini döner."""
    with transaction.atomic():
        report = _build(None, upload, filename)
        transaction.set_rollback(True)
    return report


def run_import(actor: User, upload: IO[bytes], filename: str) -> ImportReport:
    """Hatasızsa her reçete için yeni taslak sürüm yazar (denetim günlüklü); hatalıysa hiçbirini.

    Hatalı satır varsa `ImportHasErrors`.
    """
    with transaction.atomic():
        report = _build(actor, upload, filename)
        if report.has_errors:
            raise ImportHasErrors(report)
    return report


def build_template() -> bytes:
    """İndirilebilir .xlsx şablonu (iki satırlık örnek reçete)."""
    notes = (
        "Her satır bir bileşendir; aynı reçete kodlu satırlar tek sürüm olur.",
        "Her reçete için yeni bir taslak sürüm açılır; onayı laboratuvar verir.",
        "Proses adımları (süre, sıcaklık, devir) reçete ekranından elle girilir.",
        "Hatalı satır varsa hiçbir reçete aktarılmaz.",
    )
    examples = (
        (
            "RC-BULASIK",
            "Bulaşık deterjanı",
            "YM-BULASIK",
            1000,
            "KG",
            "HM-SU",
            700,
            "KG",
            2,
            "Evet",
            "",
        ),
        (
            "RC-BULASIK",
            "Bulaşık deterjanı",
            "YM-BULASIK",
            1000,
            "KG",
            "HM-LAS",
            "120,5",
            "KG",
            1,
            "Hayır",
            "Karıştırarak yavaşça ekleyin",
        ),
    )
    return build_template_for(TITLE, COLUMNS, notes, examples)
