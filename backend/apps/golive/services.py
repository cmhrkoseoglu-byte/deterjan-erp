"""Canlıya geçiş servisleri (Faz 5, Adım 5.6).

- `create_stock_comparison`: paralel çalışmada Excel stok listesini sistem bakiyesiyle karşılaştırır
  ve sonucu değişmez bir kayıt olarak saklar.
- `report_problem`: "Sorun bildir" butonu; kayıt açar ve `problem_report.created` olayı yayınlar
  (`workflow` admin rolüne görev açar).
- `set_go_live_date`: canlı başlangıç tarihini `inventory` servisine iletir.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import IO, Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.services import next_document_number, save_with_audit
from apps.golive import selectors
from apps.golive.models import ProblemReport, StockComparison, StockComparisonLine
from apps.inventory import services as inventory
from apps.inventory.models import InventorySettings
from apps.masterdata import services as masterdata
from apps.masterdata.importers import (
    CellError,
    Column,
    ImportHasErrors,
    ImportReport,
    RowResult,
    _text,
    code_lookup_parser,
    parse_decimal,
    read_table,
)
from apps.masterdata.models import Location, Material, UnitOfMeasure

ZERO = Decimal(0)
SCREENSHOT_MAX_BYTES = 8 * 1024 * 1024
SCREENSHOT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

COMPARISON_COLUMNS: tuple[Column, ...] = (
    Column(
        "Malzeme kodu",
        "material",
        code_lookup_parser(Material, "Malzeme"),
        required=True,
        example="HM-LAS",
    ),
    Column(
        "Lot no",
        "lot_no",
        lambda value: _text(value).upper(),
        example="H-261015-001",
        help="Doluysa lot bazında karşılaştırılır (tüm satırlarda dolu olmalı)",
    ),
    Column(
        "Lokasyon kodu",
        "location",
        code_lookup_parser(Location, "Lokasyon"),
        example="A-01",
        help="Doluysa lokasyon bazında karşılaştırılır (tüm satırlarda dolu olmalı)",
    ),
    Column("Miktar", "quantity", parse_decimal, required=True, example="1250,5"),
    Column(
        "Birim",
        "unit",
        code_lookup_parser(UnitOfMeasure, "Birim"),
        example="KG",
        help="Boşsa malzemenin temel birimi",
    ),
)


# --- canlı başlangıç tarihi --------------------------------------------------------------------


def set_go_live_date(actor: User, go_live_date: date | None) -> InventorySettings:
    """Canlı başlangıç tarihini girer; o günden itibaren açılış stoku yüklenemez."""
    return inventory.set_go_live_date(actor, go_live_date)


# --- stok karşılaştırması ----------------------------------------------------------------------


@dataclass(frozen=True)
class _FileRow:
    material: Material
    lot_no: str
    location: Location | None
    quantity: Decimal


def _parse_comparison_file(upload: IO[bytes], filename: str) -> tuple[list[_FileRow], ImportReport]:
    rows, file_errors = read_table(upload, filename, COMPARISON_COLUMNS)
    report = ImportReport(kind="stock_comparison", rows=[], file_errors=file_errors)
    parsed: list[_FileRow] = []
    for row_no, cells in rows:
        result = RowResult(row=row_no, code="", action="create")
        report.rows.append(result)
        data: dict[str, Any] = {}
        for column in COMPARISON_COLUMNS:
            raw = cells.get(column.field)
            if _text(raw) == "":
                if column.required:
                    result.errors.append({"column": column.header, "message": "Zorunlu alan boş."})
                continue
            try:
                data[column.field] = column.parse(raw)
            except CellError as exc:
                result.errors.append({"column": column.header, "message": str(exc)})
        material = data.get("material")
        if material is not None:
            result.code = material.code
        if result.errors or material is None:
            continue
        quantity = data["quantity"]
        if quantity < 0:
            result.errors.append({"column": "Miktar", "message": "Miktar negatif olamaz."})
            continue
        try:
            base = masterdata.to_base_quantity(
                material, quantity, data.get("unit") or material.base_unit
            )
        except BusinessRuleError as exc:
            result.errors.append({"column": "Birim", "message": exc.message})
            continue
        parsed.append(
            _FileRow(
                material=material,
                lot_no=data.get("lot_no", ""),
                location=data.get("location"),
                quantity=inventory.quantize(base),
            )
        )
    return parsed, report


def _level(rows: Iterable[_FileRow]) -> str:
    rows = list(rows)
    by_lot = all(row.lot_no for row in rows)
    by_location = all(row.location is not None for row in rows)
    if by_lot and by_location:
        return StockComparison.Level.LOT_LOCATION
    if by_lot:
        return StockComparison.Level.LOT
    if by_location:
        return StockComparison.Level.LOCATION
    return StockComparison.Level.MATERIAL


def end_of_day(day: date) -> datetime:
    """Günün sonu (Türkiye saati): ertesi günün 00:00'ı, hariç."""
    return timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))


@transaction.atomic
def create_stock_comparison(
    actor: User,
    *,
    upload: IO[bytes],
    filename: str,
    as_of_date: date | None = None,
    only_file_materials: bool = False,
    note: str = "",
) -> StockComparison:
    """Excel stok listesini `as_of_date` gün sonundaki sistem bakiyesiyle karşılaştırır.

    Düzey dosyadan çıkar: lot no tüm satırlarda doluysa lot, lokasyon tüm satırlarda doluysa
    lokasyon bazında; değilse malzeme toplamı. Aynı anahtar dosyada birden çok satırdaysa toplanır.
    Hatalı satır varsa `ImportHasErrors` (hiçbir şey yazılmaz).
    """
    today = timezone.localdate()
    as_of_date = as_of_date or today
    if as_of_date > today:
        raise BusinessRuleError("future_date", "Stok tarihi ileri bir tarih olamaz.")
    rows, report = _parse_comparison_file(upload, filename)
    if report.has_errors:
        raise ImportHasErrors(report)

    level = _level(rows)
    by_lot = level in (StockComparison.Level.LOT, StockComparison.Level.LOT_LOCATION)
    by_location = level in (StockComparison.Level.LOCATION, StockComparison.Level.LOT_LOCATION)
    file_totals: dict[selectors.StockKey, Decimal] = defaultdict(lambda: ZERO)
    for row in rows:
        key = selectors.StockKey(
            material_id=row.material.pk,
            lot_no=row.lot_no if by_lot else "",
            location_id=row.location.pk if by_location and row.location else None,
        )
        file_totals[key] += row.quantity
    system = selectors.system_stock(end_of_day(as_of_date), by_lot=by_lot, by_location=by_location)
    keys = set(file_totals) | set(system)
    if only_file_materials:
        materials = {key.material_id for key in file_totals}
        keys = {key for key in keys if key.material_id in materials}

    comparison = StockComparison(
        number=next_document_number("SK"),
        as_of_date=as_of_date,
        level=level,
        only_file_materials=only_file_materials,
        file_name=filename[:255],
        note=note.strip(),
    )
    save_with_audit(comparison, actor)
    lines = [
        StockComparisonLine(
            comparison=comparison,
            material_id=key.material_id,
            lot_no=key.lot_no,
            location_id=key.location_id,
            file_quantity=file_totals.get(key, ZERO),
            system_quantity=system.get(key, ZERO),
            difference=system.get(key, ZERO) - file_totals.get(key, ZERO),
            in_file=key in file_totals,
        )
        for key in keys
    ]
    StockComparisonLine.objects.bulk_create(lines)
    comparison.line_count = len(lines)
    comparison.difference_count = sum(1 for line in lines if line.difference != 0)
    comparison.save(update_fields=["line_count", "difference_count"])
    return comparison


# --- sorun bildir -----------------------------------------------------------------------------


def can_view_problem(user: User, report: ProblemReport) -> bool:
    return user.is_admin or report.created_by_id == user.pk


@transaction.atomic
def report_problem(
    actor: User,
    *,
    description: str,
    page_url: str = "",
    page_title: str = "",
    user_agent: str = "",
    screen: str = "",
    screenshot: UploadedFile | None = None,
) -> ProblemReport:
    """Sorun bildirimi açar; olay commit sonrası yayınlanır ve admin rolüne görev açılır."""
    description = description.strip()
    if not description:
        raise BusinessRuleError("description_required", "Sorunu kısaca anlatın.")
    if screenshot is not None:
        mime = (getattr(screenshot, "content_type", "") or "").split(";")[0]
        if mime not in SCREENSHOT_TYPES:
            raise BusinessRuleError(
                "file_type_not_allowed", "Ekran görüntüsü PNG, JPEG ya da WEBP olmalıdır."
            )
        if (screenshot.size or 0) > SCREENSHOT_MAX_BYTES:
            raise BusinessRuleError("file_too_large", "Ekran görüntüsü en çok 8 MB olabilir.")
    report = ProblemReport(
        number=next_document_number("SB"),
        description=description[:5000],
        page_url=page_url[:500],
        page_title=page_title[:200],
        user_agent=user_agent[:500],
        screen=screen[:32],
    )
    save_with_audit(report, actor)
    if screenshot is not None:
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
        report.screenshot.save(f"{report.number}.{extension}", screenshot, save=False)
        report.save(update_fields=["screenshot"])
    summary = " ".join(description.split())
    events.publish(
        ev.PROBLEM_REPORTED,
        {
            "model": "golive.problemreport",
            "id": report.pk,
            "number": report.number,
            "summary": summary[:120] + ("…" if len(summary) > 120 else ""),
            "reporter": actor.get_full_name() or actor.username,
            "page_url": report.page_url,
            "page_title": report.page_title,
        },
        actor=actor,
    )
    return report
