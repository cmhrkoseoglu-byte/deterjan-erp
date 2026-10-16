"""Bakım okuma sorguları: plan vadesi, kalibrasyon durumu, duruş özeti, tank ürün geçmişi.

Raporlama (Adım 4.3) bu fonksiyonları kullanır; sözleşme `docs/DECISIONS.md` "Bakım ve İSG okuma
API'si" bölümündedir.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.filling.models import FillingRun
from apps.maintenance.models import (
    ChangeoverRule,
    Downtime,
    MaintenanceKind,
    MaintenancePlan,
    MaintenanceSettings,
    MaintenanceWorkOrder,
)
from apps.masterdata.models import Equipment, Material
from apps.production.models import ProductionBatch

WOStatus = MaintenanceWorkOrder.Status
OPEN_STATUSES = (WOStatus.OPEN, WOStatus.IN_PROGRESS)

# Kalibrasyon durumları
CAL_OK = "OK"
CAL_DUE_SOON = "DUE_SOON"
CAL_OVERDUE = "OVERDUE"
CAL_NO_PLAN = "NO_PLAN"
CALIBRATION_LABELS = {
    CAL_OK: "Geçerli",
    CAL_DUE_SOON: "Yaklaşıyor",
    CAL_OVERDUE: "Süresi geçti",
    CAL_NO_PLAN: "Kalibrasyon planı yok",
}


def get_settings() -> MaintenanceSettings:
    """Tek satırlık bakım ayarı (yoksa varsayılanla oluşturulur)."""
    instance = MaintenanceSettings.objects.order_by("pk").first()
    if instance is None:
        instance = MaintenanceSettings.objects.create()
    return instance


def open_downtime(equipment: Equipment) -> Downtime | None:
    """Ekipmanın açık (bitişi girilmemiş) duruşu."""
    return Downtime.objects.filter(equipment=equipment, ended_at__isnull=True).first()


def runs_since(equipment: Equipment, since: datetime | None) -> int:
    """Ekipmanda `since`'ten sonra biten çalışma sayısı: tankta tamamlanan şarj, dolum hattında
    tamamlanan dolum partisi. `since` boşsa tümü."""
    after = Q(finished_at__gt=since) if since is not None else Q()
    if equipment.equipment_type == Equipment.Type.FILLING_LINE:
        return FillingRun.objects.filter(
            after, order__filling_line=equipment, status=FillingRun.Status.COMPLETED
        ).count()
    return ProductionBatch.objects.filter(
        after, equipment=equipment, status=ProductionBatch.Status.COMPLETED
    ).count()


@dataclass(frozen=True)
class PlanStatus:
    plan: MaintenancePlan
    next_due_date: date | None
    runs_done: int | None
    is_due: bool  # iş emri açılmalı (termin yaklaştı ya da çalışma sayısına ulaşıldı)
    is_overdue: bool  # termin geçti


def plan_status(plan: MaintenancePlan, today: date | None = None) -> PlanStatus:
    """Planın vadesi. Gün bazlı plan, sıradaki tarihine ayarlardaki gün kadar kalınca vadesi gelir;
    çalışma bazlı plan son yapılmadan bu yana biten çalışma periyoda ulaşınca."""
    today = today or timezone.localdate()
    if plan.interval_runs is not None:
        done = runs_since(plan.equipment, plan.last_done_at)
        due = done >= plan.interval_runs
        return PlanStatus(plan, None, done, due, due)
    lead = get_settings().plan_lead_days
    next_due = plan.next_due_date
    due = next_due is not None and next_due <= today + timedelta(days=lead)
    overdue = next_due is not None and next_due < today
    return PlanStatus(plan, next_due, None, due, overdue)


def due_plans(today: date | None = None) -> list[PlanStatus]:
    """Vadesi gelmiş aktif planlar (iş emri açılmış olsun olmasın)."""
    plans = MaintenancePlan.objects.filter(is_active=True, equipment__is_active=True)
    statuses = [plan_status(plan, today) for plan in plans.select_related("equipment")]
    return [status for status in statuses if status.is_due]


def open_work_orders() -> QuerySet[MaintenanceWorkOrder]:
    """Açık ve yapılmakta olan iş emirleri, termine göre."""
    return (
        MaintenanceWorkOrder.objects.filter(status__in=OPEN_STATUSES)
        .select_related("equipment", "plan")
        .order_by("due_date", "created_at")
    )


@dataclass(frozen=True)
class CalibrationStatus:
    equipment: Equipment
    status: str
    next_due_date: date | None
    days_left: int | None
    is_down: bool

    @property
    def label(self) -> str:
        return CALIBRATION_LABELS[self.status]


def scale_calibration(scale: Equipment, today: date | None = None) -> CalibrationStatus:
    """Terazinin kalibrasyon durumu: aktif kalibrasyon planlarının en erken sıradaki tarihi."""
    today = today or timezone.localdate()
    due = (
        MaintenancePlan.objects.filter(
            equipment=scale, kind=MaintenanceKind.CALIBRATION, is_active=True
        )
        .exclude(next_due_date__isnull=True)
        .order_by("next_due_date")
        .values_list("next_due_date", flat=True)
        .first()
    )
    is_down = open_downtime(scale) is not None
    if due is None:
        return CalibrationStatus(scale, CAL_NO_PLAN, None, None, is_down)
    days_left = (due - today).days
    warning = get_settings().calibration_warning_days
    if days_left < 0:
        status = CAL_OVERDUE
    elif days_left <= warning:
        status = CAL_DUE_SOON
    else:
        status = CAL_OK
    return CalibrationStatus(scale, status, due, days_left, is_down)


def calibration_status(today: date | None = None) -> list[CalibrationStatus]:
    """Tüm aktif terazilerin kalibrasyon durumu (tartım ekranı ve raporlar)."""
    scales = Equipment.objects.filter(equipment_type=Equipment.Type.SCALE, is_active=True)
    return [scale_calibration(scale, today) for scale in scales.order_by("code")]


def last_tank_batch(equipment: Equipment) -> ProductionBatch | None:
    """Tankta en son tamamlanan şarj."""
    return (
        ProductionBatch.objects.filter(equipment=equipment, status=ProductionBatch.Status.COMPLETED)
        .select_related("order__product")
        .order_by("-finished_at", "-id")
        .first()
    )


def cleaning_needed(equipment: Equipment, product: Material) -> Material | None:
    """Ürün değişimi temizliği (Karar D-14): temizlik gerekiyorsa tanktaki önceki ürünü döner.

    Gerekmez: tankta hiç şarj yoksa, son şarj aynı üründense, son şarjdan sonra tamamlanmış
    temizlik kaydı varsa ya da önceki → yeni ürün için aktif temizliksiz geçiş kuralı varsa."""
    last = last_tank_batch(equipment)
    if last is None:
        return None
    previous = last.order.product
    if previous.pk == product.pk:
        return None
    cleaned = MaintenanceWorkOrder.objects.filter(
        equipment=equipment,
        kind=MaintenanceKind.CLEANING,
        status=WOStatus.COMPLETED,
        completed_at__gte=last.finished_at,
    ).exists()
    if cleaned:
        return None
    allowed = ChangeoverRule.objects.filter(
        from_product=previous, to_product=product, is_active=True
    ).exists()
    return None if allowed else previous


@dataclass(frozen=True)
class DowntimeRow:
    equipment_id: int
    equipment_code: str
    equipment_name: str
    reason: str
    reason_display: str
    count: int
    minutes: int


def _minutes(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))


def downtime_summary(
    date_from: date, date_to: date, equipment: Equipment | None = None
) -> list[DowntimeRow]:
    """Tarih aralığındaki (iki uç dahil) duruş dakikaları, ekipman ve nedene göre. Aralığa taşan
    duruş aralıkla kırpılır; açık duruş şimdiye kadar sayılır."""
    tz = timezone.get_current_timezone()
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    now = timezone.now()
    queryset = Downtime.objects.filter(
        Q(ended_at__isnull=True) | Q(ended_at__gt=start), started_at__lt=end
    ).select_related("equipment")
    if equipment is not None:
        queryset = queryset.filter(equipment=equipment)
    rows: dict[tuple[int, str], list[int]] = {}
    labels = dict(Downtime.Reason.choices)
    meta: dict[int, Equipment] = {}
    for downtime in queryset:
        finish = min(downtime.ended_at or now, end)
        minutes = _minutes(max(downtime.started_at, start), finish)
        key = (downtime.equipment_id, downtime.reason)
        meta[downtime.equipment_id] = downtime.equipment
        bucket = rows.setdefault(key, [0, 0])
        bucket[0] += 1
        bucket[1] += minutes
    result = [
        DowntimeRow(
            equipment_id=eq_id,
            equipment_code=meta[eq_id].code,
            equipment_name=meta[eq_id].name,
            reason=reason,
            reason_display=labels[reason],
            count=count,
            minutes=minutes,
        )
        for (eq_id, reason), (count, minutes) in rows.items()
    ]
    return sorted(result, key=lambda row: (row.equipment_code, -row.minutes))
