"""İSG okuma sorguları: GBF durumu ve eksikler, depolama doluluğu, olay ve atık özetleri.

Raporlama (Adım 4.3) bu fonksiyonları kullanır; sözleşme `docs/DECISIONS.md` "Bakım ve İSG okuma
API'si" bölümündedir.
"""

import calendar
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.models import Attachment
from apps.hse.models import (
    HazardClass,
    HseSettings,
    Incident,
    MaterialHazard,
    SafetyDataSheet,
    StorageLimit,
    WasteRecord,
)
from apps.inventory.models import StockBalance
from apps.inventory.services import quantize
from apps.masterdata import services as masterdata
from apps.masterdata.models import Location, Material, UnitOfMeasure

# GBF durumları
SDS_OK = "OK"
SDS_MISSING = "MISSING"
SDS_NO_FILE = "NO_FILE"
SDS_EXPIRED = "EXPIRED"
SDS_OUTDATED = "OUTDATED"
SDS_STATUS_LABELS = {
    SDS_OK: "Geçerli",
    SDS_MISSING: "GBF yok",
    SDS_NO_FILE: "Dosya yok",
    SDS_EXPIRED: "Geçerliliği geçti",
    SDS_OUTDATED: "Revizyonu eski",
}
HAZARD_LABELS = dict(HazardClass.choices)
OPEN_INCIDENT_STATUSES = (Incident.Status.OPEN, Incident.Status.INVESTIGATING)


def get_settings() -> HseSettings:
    """Tek satırlık İSG ayarı (yoksa varsayılanla oluşturulur)."""
    instance = HseSettings.objects.order_by("pk").first()
    if instance is None:
        instance = HseSettings.objects.create()
    return instance


def material_pictograms(material: Material) -> list[str]:
    """Malzemenin GHS piktogramları (tehlike bilgisi yoksa boş)."""
    value = MaterialHazard.objects.filter(material=material).values_list("pictograms", flat=True)
    return list(value.first() or [])


def current_sds(material: Material) -> SafetyDataSheet | None:
    """Malzemenin geçerli (yerine yenisi gelmemiş) GBF'si."""
    return SafetyDataSheet.objects.filter(material=material, superseded_at__isnull=True).first()


# --- GBF durumu --------------------------------------------------------------------------------


@dataclass(frozen=True)
class SdsStatus:
    material_id: int
    material_code: str
    material_name: str
    material_type: str
    material_type_display: str
    is_hazardous: bool
    status: str
    sds_id: int | None
    revision_no: str
    revision_date: date | None
    valid_until: date | None
    has_file: bool

    @property
    def status_display(self) -> str:
        return SDS_STATUS_LABELS[self.status]


def months_before(day: date, months: int) -> date:
    """`day`'den `months` ay öncesi (ayın son gününe kırpılır)."""
    total = day.year * 12 + day.month - 1 - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _files(sheet_ids: Iterable[int]) -> set[int]:
    """Aktif eki (dosyası) olan GBF kimlikleri."""
    ids = list(sheet_ids)
    if not ids:
        return set()
    content_type = ContentType.objects.get_for_model(SafetyDataSheet)
    return set(
        Attachment.objects.filter(
            content_type=content_type, object_id__in=ids, is_active=True
        ).values_list("object_id", flat=True)
    )


def _statuses(materials: Iterable[Material], today: date) -> list[SdsStatus]:
    materials = list(materials)
    sheets = {
        sheet.material_id: sheet
        for sheet in SafetyDataSheet.objects.filter(
            material__in=materials, superseded_at__isnull=True
        )
    }
    with_file = _files(sheet.pk for sheet in sheets.values())
    oldest = months_before(today, get_settings().sds_max_age_months)
    rows = []
    for material in materials:
        sheet = sheets.get(material.pk)
        has_file = sheet is not None and sheet.pk in with_file
        if sheet is None:
            status = SDS_MISSING
        elif not has_file:
            status = SDS_NO_FILE
        elif sheet.valid_until is not None and sheet.valid_until < today:
            status = SDS_EXPIRED
        elif sheet.revision_date < oldest:
            status = SDS_OUTDATED
        else:
            status = SDS_OK
        rows.append(
            SdsStatus(
                material_id=material.pk,
                material_code=material.code,
                material_name=material.name,
                material_type=material.material_type,
                material_type_display=material.get_material_type_display(),
                is_hazardous=material.is_hazardous,
                status=status,
                sds_id=sheet.pk if sheet else None,
                revision_no=sheet.revision_no if sheet else "",
                revision_date=sheet.revision_date if sheet else None,
                valid_until=sheet.valid_until if sheet else None,
                has_file=has_file,
            )
        )
    return rows


def sds_status(material: Material, today: date | None = None) -> SdsStatus:
    """Malzemenin GBF durumu: yok, dosya yok, geçerliliği geçti, revizyonu eski ya da geçerli."""
    return _statuses([material], today or timezone.localdate())[0]


def sds_required_materials() -> QuerySet[Material]:
    """GBF'si aranan malzemeler: aktif hammaddeler ve tehlikeli işaretli tüm aktif malzemeler."""
    return Material.objects.filter(
        Q(material_type=Material.Type.RAW) | Q(is_hazardous=True), is_active=True
    ).order_by("code")


def sds_gaps(today: date | None = None) -> list[SdsStatus]:
    """Eksik / eskimiş GBF raporu: GBF'si aranan malzemelerden durumu "Geçerli" olmayanlar,
    malzeme koduna göre."""
    rows = _statuses(sds_required_materials(), today or timezone.localdate())
    return [row for row in rows if row.status != SDS_OK]


# --- depolama limitleri ------------------------------------------------------------------------


@dataclass(frozen=True)
class StorageUtilisation:
    limit_id: int
    location_id: int
    location_code: str
    location_name: str
    hazard_class: str
    hazard_class_display: str
    limit_kg: Decimal
    quantity_kg: Decimal
    pct: Decimal
    exceeded: bool


def _kg() -> UnitOfMeasure:
    return UnitOfMeasure.objects.get(code="KG")


def location_hazard_kg(location_ids: Iterable[int]) -> dict[tuple[int, str], Decimal]:
    """(lokasyon, tehlike sınıfı) → kg. Lokasyondaki pozitif bakiyeler, malzemenin piktogramlarına
    göre toplanır; temel birimden kg'a `convert_quantity` ile çevrilir (litre yoğunlukla).
    Çevrilemeyen malzeme (ör. adet) atlanır."""
    rows = (
        StockBalance.objects.filter(location_id__in=list(location_ids), quantity__gt=0)
        .exclude(material__hazard__isnull=True)
        .exclude(material__hazard__pictograms=[])
        .values("location_id", "material_id")
        .annotate(total=Sum("quantity"))
    )
    totals: dict[tuple[int, int], Decimal] = {
        (row["location_id"], row["material_id"]): row["total"] for row in rows
    }
    if not totals:
        return {}
    materials = {
        m.pk: m
        for m in Material.objects.filter(pk__in={mid for _, mid in totals}).select_related(
            "base_unit", "hazard"
        )
    }
    kg = _kg()
    result: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
    for (location_id, material_id), quantity in totals.items():
        material = materials[material_id]
        try:
            in_kg = masterdata.convert_quantity(material, quantity, material.base_unit, kg)
        except BusinessRuleError:
            continue
        for hazard_class in material.hazard.pictograms:
            result[(location_id, hazard_class)] += in_kg
    return result


def storage_utilisation(location: Location | None = None) -> list[StorageUtilisation]:
    """Aktif depolama limitlerinin doluluğu (lokasyon × tehlike sınıfı), lokasyon koduna göre."""
    limits = StorageLimit.objects.filter(is_active=True).select_related("location")
    if location is not None:
        limits = limits.filter(location=location)
    limits = limits.order_by("location__code", "hazard_class")
    amounts = location_hazard_kg({limit.location_id for limit in limits})
    result = []
    for limit in limits:
        quantity = quantize(amounts.get((limit.location_id, limit.hazard_class), Decimal(0)))
        pct = (quantity * 100 / limit.max_kg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        result.append(
            StorageUtilisation(
                limit_id=limit.pk,
                location_id=limit.location_id,
                location_code=limit.location.code,
                location_name=limit.location.name,
                hazard_class=limit.hazard_class,
                hazard_class_display=HAZARD_LABELS[limit.hazard_class],
                limit_kg=limit.max_kg,
                quantity_kg=quantity,
                pct=pct,
                exceeded=quantity > limit.max_kg,
            )
        )
    return result


# --- olay ve atık özetleri ---------------------------------------------------------------------


@dataclass(frozen=True)
class CountRow:
    code: str
    label: str
    count: int


@dataclass(frozen=True)
class IncidentSummary:
    total: int
    injury_count: int
    open_count: int
    by_type: list[CountRow]
    by_severity: list[CountRow]


def _day_range(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return start, end


def incident_summary(date_from: date, date_to: date) -> IncidentSummary:
    """Tarih aralığında (iki uç dahil, olay zamanına göre) iptal edilmemiş olay kayıtları: tür ve
    ağırlığa göre sayılar, yaralanmalı olay sayısı ve hâlâ açık (açık / inceleniyor) olanlar."""
    start, end = _day_range(date_from, date_to)
    incidents = list(
        Incident.objects.filter(occurred_at__gte=start, occurred_at__lt=end)
        .exclude(status=Incident.Status.CANCELLED)
        .values_list("incident_type", "severity", "injury", "status")
    )
    by_type: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)
    for incident_type, severity, _, _ in incidents:
        by_type[incident_type] += 1
        by_severity[severity] += 1
    return IncidentSummary(
        total=len(incidents),
        injury_count=sum(1 for row in incidents if row[2]),
        open_count=sum(1 for row in incidents if row[3] in OPEN_INCIDENT_STATUSES),
        by_type=[
            CountRow(code, label, by_type.get(code, 0)) for code, label in Incident.Type.choices
        ],
        by_severity=[
            CountRow(code, label, by_severity.get(code, 0))
            for code, label in Incident.Severity.choices
        ],
    )


@dataclass(frozen=True)
class WasteSummaryRow:
    waste_code: str
    description: str
    is_hazardous: bool
    count: int
    quantity_kg: Decimal


def waste_summary(date_from: date, date_to: date) -> list[WasteSummaryRow]:
    """Tarih aralığında (teslim tarihine göre, iki uç dahil) iptal edilmemiş atık teslimleri,
    atık koduna göre: kayıt sayısı ve toplam kg. Tanım en son kayıttandır."""
    records = (
        WasteRecord.objects.filter(delivered_on__gte=date_from, delivered_on__lte=date_to)
        .exclude(status=WasteRecord.Status.CANCELLED)
        .order_by("waste_code", "-delivered_on", "-id")
    )
    rows: dict[str, list] = {}
    for record in records:
        bucket = rows.setdefault(
            record.waste_code, [record.description, record.is_hazardous, 0, Decimal(0)]
        )
        bucket[1] = bucket[1] or record.is_hazardous
        bucket[2] += 1
        bucket[3] += record.quantity_kg
    return [
        WasteSummaryRow(code, description, hazardous, count, quantize(total))
        for code, (description, hazardous, count, total) in rows.items()
    ]
