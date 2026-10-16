"""Pano sorguları (Faz 4, Adım 4.3): yönetim panosu ve birim panoları.

Her pano tek bir sözlük döner; sorgu sayısı sabittir (satır başına sorgu yok), böylece pano demo
verisiyle 2 saniyenin altında açılır (kabul kriteri, `tests/test_dashboards.py`). Stok değeri
yalnızca `show_costs=True` iken hesaplanır (Karar D-15: yalnızca yonetim ve admin).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Min, Q, Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.roles import ROLE_LABELS
from apps.costing import selectors as costing
from apps.filling.models import FillingOrder, FillingRun, ScrapRecord
from apps.hse import selectors as hse
from apps.inventory import selectors as inventory
from apps.inventory.models import GoodsReceipt, StockBalance
from apps.maintenance import selectors as maintenance
from apps.maintenance.models import Downtime
from apps.masterdata.models import Equipment
from apps.masterdata.services import convert_quantity
from apps.production.models import ProductionBatch, ProductionOrder
from apps.quality import selectors as quality
from apps.quality.models import QualityDecision, Sample
from apps.reporting.selectors import ZERO, day_start, hours, mean, pct
from apps.sales import selectors as sales
from apps.sales.models import SalesOrder, Shipment
from apps.workflow.models import Task

EXPIRY_DAYS = 30
LIST_LIMIT = 10
QUEUE_LIMIT = 50
USER_ASSIGNED = "Kişiye atanmış"

PO = ProductionOrder.Status
FO = FillingOrder.Status
SO = SalesOrder.Status
OPEN_PRODUCTION = (
    PO.DRAFT,
    PO.APPROVED,
    PO.MATERIAL_PREP,
    PO.MATERIAL_READY,
    PO.IN_PRODUCTION,
    PO.QC_PENDING,
)
OPEN_FILLING = (
    FO.DRAFT,
    FO.APPROVED,
    FO.MATERIAL_PREP,
    FO.MATERIAL_READY,
    FO.IN_PROGRESS,
    FO.QC_PENDING,
)
OPEN_SALES = (SO.DRAFT, SO.CONFIRMED, SO.PARTIALLY_SHIPPED)
SHIPPABLE_SALES = (SO.CONFIRMED, SO.PARTIALLY_SHIPPED)


def _periods(today: date) -> dict[str, tuple[date, date]]:
    """Bugün ve bu hafta (pazartesiden bugüne)."""
    return {"today": (today, today), "week": (today - timedelta(days=today.weekday()), today)}


def _between(field: str, start: date, end: date) -> Q:
    return Q(**{f"{field}__gte": day_start(start), f"{field}__lt": day_start(end + timedelta(1))})


def _status_counts(queryset: Any, choices: Any, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    counts = dict(
        queryset.filter(status__in=statuses).values_list("status").annotate(n=Count("id"))
    )
    labels = dict(choices)
    return [{"status": s, "label": labels[s], "count": counts.get(s, 0)} for s in statuses]


def _material(code: str, name: str) -> str:
    return f"{code} — {name}"


# --- yönetim panosu --------------------------------------------------------------------------


def production_output(today: date) -> dict[str, Any]:
    """Bugünkü ve haftalık üretim: biten şarjların gerçek çıktısı (temel birim, çoğunlukla kg) ve
    biten dolum partilerinin sağlam adedi."""
    result: dict[str, Any] = {}
    for key, (start, end) in _periods(today).items():
        bulk = (
            ProductionBatch.objects.filter(status=ProductionBatch.Status.COMPLETED)
            .filter(_between("finished_at", start, end))
            .values("order__product__base_unit__code")
            .annotate(total=Sum("actual_output_quantity"), batches=Count("id"))
            .order_by("order__product__base_unit__code")
        )
        units = FillingRun.objects.filter(status=FillingRun.Status.COMPLETED).filter(
            _between("finished_at", start, end)
        )
        totals = units.aggregate(units=Sum("good_units"), runs=Count("id"))
        result[key] = {
            "bulk": [
                {
                    "unit": row["order__product__base_unit__code"],
                    "quantity": row["total"] or ZERO,
                    "batches": row["batches"],
                }
                for row in bulk
            ],
            "units": totals["units"] or 0,
            "runs": totals["runs"],
        }
    return result


def qc_pending() -> dict[str, Any]:
    """Kararı verilmemiş numuneler: bekleyen lot sayısı, ortalama ve en uzun bekleme (saat)."""
    now = timezone.now()
    queue = quality.sample_queue()
    created = list(queue.values_list("created_at", "lot_id"))
    waits = [hours(now - at) or ZERO for at, _ in created]
    return {
        "sample_count": len(created),
        "lot_count": len({lot for _, lot in created}),
        "avg_wait_hours": mean(waits),
        "max_wait_hours": max(waits, default=None),
    }


def scrap_rate(today: date, days: int = 7) -> dict[str, Any]:
    """Son `days` günde biten dolum partilerinde mamul fire oranı: fire adedi ÷ (sağlam + fire)."""
    start = today - timedelta(days=days - 1)
    runs = FillingRun.objects.filter(status=FillingRun.Status.COMPLETED).filter(
        _between("finished_at", start, today)
    )
    good = Decimal(runs.aggregate(t=Sum("good_units"))["t"] or 0)
    scrap = (
        ScrapRecord.objects.filter(run__in=runs, kind=ScrapRecord.Kind.FINISHED).aggregate(
            t=Sum("quantity")
        )["t"]
        or ZERO
    )
    return {
        "days": days,
        "good_units": good,
        "scrap_units": scrap,
        "rate": pct(scrap, good + scrap),
    }


def critical_stock() -> dict[str, Any]:
    materials = list(inventory.below_min_stock())
    return {
        "count": len(materials),
        "items": [
            {
                "material_id": m.pk,
                "material": _material(m.code, m.name),
                "stock": m.stock_quantity,  # type: ignore[attr-defined]
                "min_stock": m.min_stock,
                "unit": m.base_unit.code,
            }
            for m in materials[:LIST_LIMIT]
        ],
    }


def expiring_lots(today: date) -> dict[str, Any]:
    lots = list(
        inventory.expiring_lots(EXPIRY_DAYS, today=today).select_related("material__base_unit")
    )
    return {
        "days": EXPIRY_DAYS,
        "count": len(lots),
        "expired_count": sum(1 for lot in lots if lot.expiry_date and lot.expiry_date < today),
        "items": [
            {
                "lot_id": lot.pk,
                "lot_no": lot.lot_no,
                "material": _material(lot.material.code, lot.material.name),
                "expiry_date": lot.expiry_date,
                "days_left": (lot.expiry_date - today).days if lot.expiry_date else None,
                "quantity": lot.total_quantity,  # type: ignore[attr-defined]
                "unit": lot.material.base_unit.code,
                "status": lot.get_status_display(),
            }
            for lot in lots[:LIST_LIMIT]
        ],
    }


def overdue_tasks() -> dict[str, Any]:
    """Birim (rol) bazında açık ve gecikmiş (son tarihi geçmiş) görevler."""
    now = timezone.now()
    open_q = Q(status__in=Task.OPEN_STATUSES)
    rows = (
        Task.objects.filter(open_q)
        .values("assigned_role__name")
        .annotate(
            open=Count("id"),
            overdue=Count("id", filter=Q(due_at__lt=now)),
            oldest_due=Min("due_at", filter=Q(due_at__lt=now)),
        )
        .order_by()
    )
    items = [
        {
            "role": row["assigned_role__name"] or "",
            "label": ROLE_LABELS.get(row["assigned_role__name"], row["assigned_role__name"])
            if row["assigned_role__name"]
            else USER_ASSIGNED,
            "open": row["open"],
            "overdue": row["overdue"],
            "max_delay_hours": hours(now - row["oldest_due"]) if row["oldest_due"] else None,
        }
        for row in rows
    ]
    items.sort(key=lambda r: (-r["overdue"], -r["open"], r["label"]))
    return {"overdue_total": sum(r["overdue"] for r in items), "by_role": items}


def maintenance_status(today: date, days: int = 7) -> dict[str, Any]:
    """Bakım özeti: açık iş emri, vadesi gelen plan, açık duruş, son günlerdeki duruş süresi."""
    plans = maintenance.due_plans(today)
    rows = maintenance.downtime_summary(today - timedelta(days=days - 1), today)
    return {
        "days": days,
        "open_work_orders": maintenance.open_work_orders().count(),
        "due_plans": len(plans),
        "overdue_plans": sum(1 for p in plans if p.is_overdue),
        "open_downtimes": Downtime.objects.filter(ended_at__isnull=True).count(),
        "downtime_minutes": sum(r.minutes for r in rows),
    }


def hse_status(today: date, days: int = 30) -> dict[str, Any]:
    """İSG özeti: son günlerdeki olaylar ve yaralanmalı olaylar, açık olaylar."""
    summary = hse.incident_summary(today - timedelta(days=days - 1), today)
    return {
        "days": days,
        "incidents": summary.total,
        "injuries": summary.injury_count,
        "open_incidents": summary.open_count,
    }


def management_dashboard(*, show_costs: bool, today: date | None = None) -> dict[str, Any]:
    """Yönetim panosu."""
    today = today or timezone.localdate()
    data: dict[str, Any] = {
        "date": today,
        "production": production_output(today),
        "open_orders": {
            "production": _status_counts(
                ProductionOrder.objects, ProductionOrder.Status.choices, OPEN_PRODUCTION
            ),
            "filling": _status_counts(
                FillingOrder.objects, FillingOrder.Status.choices, OPEN_FILLING
            ),
            "sales": _status_counts(SalesOrder.objects, SalesOrder.Status.choices, OPEN_SALES),
        },
        "qc_pending": qc_pending(),
        "scrap": scrap_rate(today),
        "critical_stock": critical_stock(),
        "expiring_lots": expiring_lots(today),
        "tasks": overdue_tasks(),
        "maintenance": maintenance_status(today),
        "hse": hse_status(today),
        "stock_value": None,
    }
    if show_costs:
        value = costing.stock_value()
        data["stock_value"] = {
            "total": value["total_value"],
            "by_type": value["by_type"],
            "has_uncosted": any(r["uncosted_quantity"] > 0 for r in value["rows"]),
        }
    return data


# --- depo panosu -----------------------------------------------------------------------------


def warehouse_dashboard(*, today: date | None = None) -> dict[str, Any]:
    """Depo: bekleyen malzeme / ambalaj hazırlama, sevkiyat toplama, taslak mal kabul."""
    today = today or timezone.localdate()
    prep = ProductionOrder.objects.filter(
        status__in=(PO.APPROVED, PO.MATERIAL_PREP)
    ).select_related("product")
    packaging = FillingOrder.objects.filter(
        status__in=(FO.APPROVED, FO.MATERIAL_PREP)
    ).select_related("finished_product")
    picking = Shipment.objects.filter(
        status__in=(Shipment.Status.PLANNED, Shipment.Status.PICKING)
    ).select_related("sales_order__customer")
    now = timezone.now()
    tasks = Task.objects.filter(
        status__in=Task.OPEN_STATUSES, assigned_role__name="depo"
    ).aggregate(open=Count("id"), overdue=Count("id", filter=Q(due_at__lt=now)))
    return {
        "date": today,
        "production_prep": [
            {
                "id": o.pk,
                "number": o.number,
                "product": _material(o.product.code, o.product.name),
                "planned_date": o.planned_date,
                "status": o.status,
                "status_display": ProductionOrder.Status(o.status).label,
                "priority": o.priority,
                "late": o.planned_date < today,
            }
            for o in prep.order_by("planned_date", "-priority", "id")[:QUEUE_LIMIT]
        ],
        "filling_prep": [
            {
                "id": o.pk,
                "number": o.number,
                "product": _material(o.finished_product.code, o.finished_product.name),
                "planned_date": o.planned_date,
                "status": o.status,
                "status_display": FillingOrder.Status(o.status).label,
                "late": o.planned_date < today,
            }
            for o in packaging.order_by("planned_date", "id")[:QUEUE_LIMIT]
        ],
        "shipment_picking": [
            {
                "id": s.pk,
                "number": s.number,
                "customer": _material(s.sales_order.customer.code, s.sales_order.customer.name),
                "planned_date": s.planned_date,
                "status": s.status,
                "status_display": Shipment.Status(s.status).label,
                "late": s.planned_date < today,
            }
            for s in picking.order_by("planned_date", "id")[:QUEUE_LIMIT]
        ],
        "draft_receipts": GoodsReceipt.objects.filter(status=GoodsReceipt.Status.DRAFT).count(),
        "tasks": {"open": tasks["open"], "overdue": tasks["overdue"]},
        "expiring_lot_count": inventory.expiring_lots(EXPIRY_DAYS, today=today).count(),
        "critical_stock_count": inventory.below_min_stock().count(),
    }


# --- laboratuvar panosu ----------------------------------------------------------------------


def lab_dashboard(*, today: date | None = None) -> dict[str, Any]:
    """Laboratuvar: numune kuyruğu (en eski önce), aşama ve duruma göre sayılar, son 30 gün red
    oranı."""
    today = today or timezone.localdate()
    now = timezone.now()
    queue = list(quality.sample_queue()[: QUEUE_LIMIT + 1])
    all_queue = quality.sample_queue()
    by_stage = dict(all_queue.order_by().values_list("stage").annotate(n=Count("id")))
    by_status = dict(all_queue.order_by().values_list("status").annotate(n=Count("id")))
    month = Sample.objects.filter(
        status=Sample.Status.DECIDED, decided_at__gte=day_start(today - timedelta(days=29))
    )
    decided = month.count()
    rejected = (
        QualityDecision.objects.filter(
            sample__in=month,
            decision=QualityDecision.Decision.REJECT,
            approval_status__in=(
                QualityDecision.Approval.NOT_REQUIRED,
                QualityDecision.Approval.APPROVED,
            ),
        )
        .values("sample")
        .distinct()
        .count()
    )
    stage_labels = dict(Sample._meta.get_field("stage").choices or [])
    return {
        "date": today,
        "summary": qc_pending(),
        "by_stage": [
            {"stage": k, "label": stage_labels.get(k, k), "count": v} for k, v in by_stage.items()
        ],
        "by_status": [
            {"status": k, "label": Sample.Status(k).label, "count": v} for k, v in by_status.items()
        ],
        "queue": [
            {
                "id": s.pk,
                "number": s.number,
                "stage": s.get_stage_display(),
                "status": s.status,
                "status_display": Sample.Status(s.status).label,
                "lot_no": s.lot.lot_no,
                "material": _material(s.lot.material.code, s.lot.material.name),
                "created_at": s.created_at,
                "wait_hours": hours(now - s.created_at),
            }
            for s in queue[:QUEUE_LIMIT]
        ],
        "queue_truncated": len(queue) > QUEUE_LIMIT,
        "decided_today": Sample.objects.filter(
            status=Sample.Status.DECIDED, decided_at__gte=day_start(today)
        ).count(),
        "last_30_days": {
            "decided": decided,
            "rejected": rejected,
            "rejection_rate": pct(Decimal(rejected), Decimal(decided)),
        },
    }


# --- üretim panosu ---------------------------------------------------------------------------


def _fill_pct(equipment: Equipment, stock: list[StockBalance]) -> Decimal | None:
    """Tank doluluğu: lokasyondaki stokun kapasite birimine çevrilmiş toplamı ÷ kapasite.
    Dönüşüm yoksa (ör. yoğunluğu girilmemiş ürün) hesaplanmaz."""
    if not equipment.capacity or equipment.capacity_unit is None:
        return None
    total = ZERO
    try:
        for b in stock:
            total += convert_quantity(
                b.material, b.quantity, b.material.base_unit, equipment.capacity_unit
            )
    except BusinessRuleError:
        return None
    return pct(total, equipment.capacity)


def production_dashboard(*, today: date | None = None) -> dict[str, Any]:
    """Üretim: tankların doluluk ve durumu (açık şarj, içindeki ürün), emirlerin durumu."""
    today = today or timezone.localdate()
    tanks = list(
        Equipment.objects.filter(is_active=True, equipment_type__in=Equipment.TANK_TYPES)
        .select_related("capacity_unit", "location")
        .order_by("code")
    )
    open_batches = {
        b.equipment_id: b
        for b in ProductionBatch.objects.filter(
            status=ProductionBatch.Status.IN_PROGRESS, equipment__in=tanks
        ).select_related("order__product")
    }
    downtimes = {
        d.equipment_id: d
        for d in Downtime.objects.filter(ended_at__isnull=True, equipment__in=tanks)
    }
    stock: dict[int, list[StockBalance]] = defaultdict(list)
    for b in StockBalance.objects.filter(
        quantity__gt=0, location__in=[t.location_id for t in tanks if t.location_id]
    ).select_related("material__base_unit", "lot"):
        stock[b.location_id].append(b)
    now = timezone.now()
    rows = []
    for tank in tanks:
        batch = open_batches.get(tank.pk)
        contents = stock.get(tank.location_id or 0, [])
        if batch is not None:
            state, label = "IN_BATCH", "Şarjda"
        elif contents:
            state, label = "FILLED", "Dolu"
        else:
            state, label = "EMPTY", "Boş"
        rows.append(
            {
                "id": tank.pk,
                "code": tank.code,
                "name": tank.name,
                "type": tank.get_equipment_type_display(),
                "capacity": tank.capacity,
                "capacity_unit": tank.capacity_unit.code if tank.capacity_unit else "",
                "fill_pct": _fill_pct(tank, contents),
                "state": state,
                "state_display": label,
                "batch": {
                    "id": batch.pk,
                    "batch_no": batch.batch_no,
                    "order_id": batch.order_id,
                    "order_number": batch.order.number,
                    "product": _material(batch.order.product.code, batch.order.product.name),
                    "started_at": batch.started_at,
                    "running_hours": hours(now - batch.started_at),
                }
                if batch
                else None,
                "contents": [
                    {
                        "lot_no": b.lot.lot_no,
                        "material": _material(b.material.code, b.material.name),
                        "quantity": b.quantity,
                        "unit": b.material.base_unit.code,
                        "lot_status": b.lot.get_status_display(),
                    }
                    for b in contents
                ],
                "downtime": {
                    "reason": downtime.reason,
                    "reason_display": downtime.get_reason_display(),
                    "started_at": downtime.started_at,
                }
                if (downtime := downtimes.get(tank.pk))
                else None,
            }
        )
    orders = ProductionOrder.objects.filter(
        status__in=(PO.MATERIAL_READY, PO.IN_PRODUCTION, PO.QC_PENDING)
    ).select_related("product", "equipment")
    return {
        "date": today,
        "tanks": rows,
        "order_counts": _status_counts(
            ProductionOrder.objects, ProductionOrder.Status.choices, OPEN_PRODUCTION
        ),
        "orders": [
            {
                "id": o.pk,
                "number": o.number,
                "product": _material(o.product.code, o.product.name),
                "equipment": o.equipment.code,
                "planned_date": o.planned_date,
                "status": o.status,
                "status_display": ProductionOrder.Status(o.status).label,
                "priority": o.priority,
            }
            for o in orders.order_by("planned_date", "-priority", "id")[:QUEUE_LIMIT]
        ],
        "output": production_output(today),
    }


# --- sevkiyat panosu -------------------------------------------------------------------------


def shipping_dashboard(*, today: date | None = None) -> dict[str, Any]:
    """Sevkiyat: bugünkü sevkiyatlar, duruma göre sayılar, geciken ve eksiği olan siparişler."""
    today = today or timezone.localdate()
    active = (
        Shipment.Status.PLANNED,
        Shipment.Status.PICKING,
        Shipment.Status.LOADED,
    )
    todays = (
        Shipment.objects.filter(planned_date=today)
        .exclude(status=Shipment.Status.CANCELLED)
        .select_related("sales_order__customer")
        .order_by("status", "number")
    )
    late_orders = (
        SalesOrder.objects.filter(status__in=SHIPPABLE_SALES, requested_delivery_date__lt=today)
        .select_related("customer")
        .order_by("requested_delivery_date", "id")
    )
    return {
        "date": today,
        "status_counts": _status_counts(Shipment.objects, Shipment.Status.choices, active),
        "dispatched_today": Shipment.objects.filter(
            status=Shipment.Status.DISPATCHED, dispatched_at__gte=day_start(today)
        ).count(),
        "today": [
            {
                "id": s.pk,
                "number": s.number,
                "customer": _material(s.sales_order.customer.code, s.sales_order.customer.name),
                "order_number": s.sales_order.number,
                "status": s.status,
                "status_display": Shipment.Status(s.status).label,
                "vehicle_plate": s.vehicle_plate,
            }
            for s in todays[:QUEUE_LIMIT]
        ],
        "waiting_orders": SalesOrder.objects.filter(status__in=SHIPPABLE_SALES).count(),
        "shortage_orders": sales.orders_with_shortage().count(),
        "late_orders": [
            {
                "id": o.pk,
                "number": o.number,
                "customer": _material(o.customer.code, o.customer.name),
                "requested_delivery_date": o.requested_delivery_date,
                "days_late": (today - o.requested_delivery_date).days
                if o.requested_delivery_date
                else None,
                "status_display": SalesOrder.Status(o.status).label,
            }
            for o in late_orders[:QUEUE_LIMIT]
        ],
    }
