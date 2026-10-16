"""Rapor sorguları (Faz 4, Adım 4.3).

Her rapor fonksiyonu filtre sözlüğünü alır ve satır listesi (ya da büyük raporlarda tembel
`QueryRows`) döner. Satırlar düz sözlüklerdir; sütunlar `reports.py`'deki tanımda. Diğer
modüllerin verisi yalnızca okunur; maliyet için `costing.selectors`, kalite kuyruğu için
`quality.selectors`, stok için `inventory.selectors` kullanılır.

Tutar sütunları burada hesaplanır ama kullanıcıya gösterilip gösterilmeyeceğine `reports.py`
(sütunun `sensitive` alanı) karar verir; API ve dosya çıktısı aynı kuralı uygular.
"""

from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import (
    Avg,
    Count,
    DurationField,
    ExpressionWrapper,
    F,
    Max,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
)
from django.utils import timezone

from apps.core.roles import ROLE_LABELS
from apps.filling.models import FillingRun, ScrapRecord
from apps.inventory import selectors as inventory
from apps.inventory.models import StockMovement
from apps.production.models import BatchConsumption, ProductionBatch
from apps.quality.models import QualityDecision, Sample, TestResult
from apps.sales.models import Shipment, ShipmentLine, ShipmentPick
from apps.workflow.models import Task

ZERO = Decimal(0)
HUNDRED = Decimal(100)
HOUR = Decimal(3600)

Row = dict[str, Any]
Filters = dict[str, Any]


# --- yardımcılar -----------------------------------------------------------------------------


def day_start(value: date) -> datetime:
    """Yerel günün başlangıcı (Europe/Istanbul) — tarih filtreleri gün bazındadır."""
    return timezone.make_aware(datetime.combine(value, time.min))


def date_range_q(field: str, filters: Filters) -> Q:
    """`date_from` / `date_to` (ikisi de dahil) için zaman alanı filtresi."""
    q = Q()
    if filters.get("date_from"):
        q &= Q(**{f"{field}__gte": day_start(filters["date_from"])})
    if filters.get("date_to"):
        q &= Q(**{f"{field}__lt": day_start(filters["date_to"] + timedelta(days=1))})
    return q


def hours(delta: timedelta | None) -> Decimal | None:
    """Süreyi saat olarak (2 basamak)."""
    if delta is None:
        return None
    return (Decimal(delta.total_seconds()) / HOUR).quantize(Decimal("0.01"))


def pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if not denominator:
        return None
    return (numerator * HUNDRED / denominator).quantize(Decimal("0.01"))


def mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, ZERO) / len(values)).quantize(Decimal("0.01"))


def material_text(code: str, name: str) -> str:
    return f"{code} — {name}"


@dataclass
class QueryRows:
    """Büyük raporlar için tembel satır kümesi: sayım ve sayfa veritabanında yapılır, dosya
    çıktısı satırları parça parça okur."""

    queryset: QuerySet[Any]
    mapper: Callable[[Any], Row]

    def __len__(self) -> int:
        return self.queryset.count()

    def page(self, offset: int, limit: int) -> list[Row]:
        return [self.mapper(obj) for obj in self.queryset[offset : offset + limit]]

    def __iter__(self) -> Iterator[Row]:
        for obj in self.queryset.iterator(chunk_size=2000):
            yield self.mapper(obj)


Rows = list[Row] | QueryRows


def page_of(rows: Rows, offset: int, limit: int) -> list[Row]:
    if isinstance(rows, QueryRows):
        return rows.page(offset, limit)
    return rows[offset : offset + limit]


# --- stok durumu -----------------------------------------------------------------------------


def stock_status(filters: Filters) -> list[Row]:
    """Lot × lokasyon bakiyeleri: rezerve, kullanılabilir; tutar sütunları lotun güncel birim
    maliyetinden (costing kuralı: bakiye × `Lot.unit_cost`)."""
    qs = inventory.balances()
    if filters.get("material"):
        qs = qs.filter(material=filters["material"])
    if filters.get("material_type"):
        qs = qs.filter(material__material_type=filters["material_type"])
    if filters.get("warehouse"):
        qs = qs.filter(location__warehouse=filters["warehouse"])
    if filters.get("location"):
        qs = qs.filter(location=filters["location"])
    if filters.get("lot_status"):
        qs = qs.filter(lot__status=filters["lot_status"])
    if filters.get("expiring_days") is not None:
        limit = timezone.localdate() + timedelta(days=filters["expiring_days"])
        qs = qs.filter(lot__expiry_date__lte=limit)
    rows = []
    for b in qs.order_by("material__code", "lot__expiry_date", "lot__lot_no", "location__code"):
        lot = b.lot
        value = (
            (b.quantity * lot.unit_cost).quantize(Decimal("0.01"))
            if lot.unit_cost is not None
            else None
        )
        rows.append(
            {
                "material": material_text(b.material.code, b.material.name),
                "material_type": b.material.get_material_type_display(),
                "lot_no": lot.lot_no,
                "lot_status": lot.get_status_display(),
                "expiry_date": lot.expiry_date,
                "warehouse": b.location.warehouse.name,
                "location": b.location.code,
                "quantity": b.quantity,
                "reserved": b.reserved_quantity,  # type: ignore[attr-defined]
                "available": b.available_quantity,  # type: ignore[attr-defined]
                "unit": b.material.base_unit.code,
                "unit_cost": lot.unit_cost,
                "value": value,
                "cost_is_estimated": lot.cost_is_estimated if lot.unit_cost is not None else None,
            }
        )
    return rows


def stock_status_summary(rows: Rows) -> list[tuple[str, Any, str]]:
    assert isinstance(rows, list)
    values = [r["value"] for r in rows if r["value"] is not None]
    return [
        ("row_count", len(rows), "number"),
        ("lot_count", len({r["lot_no"] for r in rows}), "number"),
        ("stock_value", sum(values, ZERO), "money"),
    ]


# --- stok hareketleri ------------------------------------------------------------------------


def _movement_row(m: StockMovement) -> Row:
    return {
        "created_at": m.created_at,
        "movement_type": m.get_movement_type_display(),
        "document_number": m.document_number,
        "material": material_text(m.material.code, m.material.name),
        "lot_no": m.lot.lot_no,
        "warehouse": m.location.warehouse.name,
        "location": m.location.code,
        "quantity": m.quantity,
        "unit": m.material.base_unit.code,
        "user": m.created_by.get_full_name() or m.created_by.username if m.created_by else "",
        "note": m.note,
    }


def movement_queryset(filters: Filters) -> QuerySet[StockMovement]:
    qs = StockMovement.objects.filter(date_range_q("created_at", filters)).select_related(
        "material__base_unit", "lot", "location__warehouse", "created_by"
    )
    if filters.get("material"):
        qs = qs.filter(material=filters["material"])
    if filters.get("material_type"):
        qs = qs.filter(material__material_type=filters["material_type"])
    if filters.get("warehouse"):
        qs = qs.filter(location__warehouse=filters["warehouse"])
    if filters.get("location"):
        qs = qs.filter(location=filters["location"])
    if filters.get("movement_type"):
        qs = qs.filter(movement_type=filters["movement_type"])
    if filters.get("lot_no"):
        qs = qs.filter(lot__lot_no__icontains=filters["lot_no"])
    return qs.order_by("-created_at", "-id")


def stock_movements(filters: Filters) -> QueryRows:
    return QueryRows(movement_queryset(filters), _movement_row)


def stock_movements_summary(rows: Rows) -> list[tuple[str, Any, str]]:
    assert isinstance(rows, QueryRows)
    totals = rows.queryset.order_by().aggregate(
        inbound=Sum("quantity", filter=Q(quantity__gt=0)),
        outbound=Sum("quantity", filter=Q(quantity__lt=0)),
        units=Count("material__base_unit", distinct=True),
    )
    summary: list[tuple[str, Any, str]] = [("row_count", len(rows), "number")]
    # Farklı birimler toplanmaz; tek birimde (ör. tek malzeme) giriş/çıkış toplamı gösterilir.
    if totals["units"] == 1:
        summary += [
            ("inbound", totals["inbound"] or ZERO, "number"),
            ("outbound", totals["outbound"] or ZERO, "number"),
        ]
    return summary


# --- üretim ----------------------------------------------------------------------------------


def production(filters: Filters) -> list[Row]:
    """Biten şarjlar: plan / gerçek çıktı, verim ve tartım sapmaları (tolerans dışı tartım
    satırları, en büyük sapma)."""
    qs = (
        ProductionBatch.objects.filter(status=ProductionBatch.Status.COMPLETED)
        .filter(date_range_q("finished_at", filters))
        .select_related("order__product__base_unit", "equipment", "output_lot")
    )
    if filters.get("material"):
        qs = qs.filter(order__product=filters["material"])
    if filters.get("equipment"):
        qs = qs.filter(equipment=filters["equipment"])
    batches = list(qs.order_by("-finished_at", "-id"))
    deviations: dict[int, list[BatchConsumption]] = defaultdict(list)
    weighings: dict[int, int] = defaultdict(int)
    for c in BatchConsumption.objects.filter(batch__in=batches).select_related("requirement"):
        weighings[c.batch_id] += 1
        if abs(c.deviation_pct) > c.requirement.tolerance_pct:
            deviations[c.batch_id].append(c)
    rows = []
    for b in batches:
        devs = deviations.get(b.pk, [])
        rows.append(
            {
                "batch_no": b.batch_no,
                "order_number": b.order.number,
                "product": material_text(b.order.product.code, b.order.product.name),
                "equipment": b.equipment.code,
                "started_at": b.started_at,
                "finished_at": b.finished_at,
                "duration_hours": hours(b.finished_at - b.started_at) if b.finished_at else None,
                "planned_quantity": b.planned_quantity,
                "actual_quantity": b.actual_output_quantity,
                "unit": b.order.product.base_unit.code,
                "yield_pct": b.yield_pct,
                "weighing_count": weighings.get(b.pk, 0),
                "deviation_count": len(devs),
                "max_deviation_pct": max((abs(c.deviation_pct) for c in devs), default=None),
                "deviation_notes": "; ".join(c.deviation_note for c in devs if c.deviation_note),
                "lot_status": b.output_lot.get_status_display(),
            }
        )
    return rows


def production_summary(rows: Rows) -> list[tuple[str, Any, str]]:
    assert isinstance(rows, list)
    yields = [r["yield_pct"] for r in rows if r["yield_pct"] is not None]
    return [
        ("batch_count", len(rows), "number"),
        ("avg_yield", mean(yields), "percent"),
        ("batches_with_deviation", sum(1 for r in rows if r["deviation_count"]), "number"),
    ]


# --- dolum -----------------------------------------------------------------------------------


def _finished_scrap() -> Subquery:
    scrap = (
        ScrapRecord.objects.filter(run=OuterRef("pk"), kind=ScrapRecord.Kind.FINISHED)
        .values("run")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return Subquery(scrap)


def filling(filters: Filters) -> list[Row]:
    """Biten dolum partileri: teorik / gerçek bulk tüketimi, sağlam adet, mamul firesi."""
    qs = (
        FillingRun.objects.filter(status=FillingRun.Status.COMPLETED)
        .filter(date_range_q("finished_at", filters))
        .select_related(
            "order__finished_product",
            "order__packaging_spec__bulk_product__base_unit",
            "order__filling_line",
            "output_lot",
        )
        .annotate(finished_scrap=_finished_scrap())
    )
    if filters.get("material"):
        qs = qs.filter(order__finished_product=filters["material"])
    if filters.get("equipment"):
        qs = qs.filter(order__filling_line=filters["equipment"])
    rows = []
    for r in qs.order_by("-finished_at", "-id"):
        good = Decimal(r.good_units or 0)
        scrap = r.finished_scrap or ZERO
        spec = r.order.packaging_spec
        product = r.order.finished_product
        rows.append(
            {
                "lot_no": r.output_lot.lot_no,
                "order_number": r.order.number,
                "product": material_text(product.code, product.name),
                "line": r.order.filling_line.code,
                "finished_at": r.finished_at,
                "good_units": r.good_units,
                "scrap_units": scrap,
                "scrap_rate": pct(scrap, good + scrap),
                "theoretical_bulk": r.theoretical_bulk,
                "actual_bulk": r.actual_bulk,
                "bulk_unit": spec.bulk_product.base_unit.code,
                "bulk_variance_pct": r.bulk_variance_pct,
            }
        )
    return rows


def filling_summary(rows: Rows) -> list[tuple[str, Any, str]]:
    assert isinstance(rows, list)
    good = sum((Decimal(r["good_units"] or 0) for r in rows), ZERO)
    scrap = sum((r["scrap_units"] for r in rows), ZERO)
    variances = [r["bulk_variance_pct"] for r in rows if r["bulk_variance_pct"] is not None]
    return [
        ("run_count", len(rows), "number"),
        ("good_units", good, "number"),
        ("scrap_rate", pct(scrap, good + scrap), "percent"),
        ("avg_bulk_variance", mean(variances), "percent"),
    ]


# --- kalite ----------------------------------------------------------------------------------

EFFECTIVE_APPROVALS = (
    QualityDecision.Approval.NOT_REQUIRED,
    QualityDecision.Approval.APPROVED,
)


def _effective_decision() -> Subquery:
    """Numunenin yürürlükteki kararı (`quality.services.effective_decision` ile aynı kural)."""
    decisions = QualityDecision.objects.filter(
        sample=OuterRef("pk"), approval_status__in=EFFECTIVE_APPROVALS
    ).order_by("-decided_at", "-id")
    return Subquery(decisions.values("decision")[:1])


def quality(filters: Filters) -> list[Row]:
    """Karar verilen numuneler: bekleme süresi, karar, spesifikasyon dışı sonuçlar."""
    qs = (
        Sample.objects.filter(status=Sample.Status.DECIDED)
        .filter(date_range_q("decided_at", filters))
        .select_related("lot__material")
        .annotate(effective=_effective_decision())
    )
    if filters.get("material"):
        qs = qs.filter(lot__material=filters["material"])
    if filters.get("stage"):
        qs = qs.filter(stage=filters["stage"])
    if filters.get("decision"):
        qs = qs.filter(effective=filters["decision"])
    samples = list(qs.order_by("-decided_at", "-id"))
    out_of_spec: dict[int, list[str]] = defaultdict(list)
    for result in TestResult.objects.filter(
        sample__in=samples, superseded_by__isnull=True, is_within_spec=False
    ).select_related("spec_line__test"):
        out_of_spec[result.sample_id].append(result.spec_line.test.name)
    labels = dict(QualityDecision.Decision.choices)
    rows = []
    for s in samples:
        failed = out_of_spec.get(s.pk, [])
        started = s.taken_at or s.created_at
        rows.append(
            {
                "number": s.number,
                "stage": s.get_stage_display(),
                "lot_no": s.lot.lot_no,
                "material": material_text(s.lot.material.code, s.lot.material.name),
                "created_at": s.created_at,
                "decided_at": s.decided_at,
                "wait_hours": hours(s.decided_at - started) if s.decided_at else None,
                "decision": labels.get(s.effective, ""),
                "decision_code": s.effective or "",
                "out_of_spec_count": len(failed),
                "out_of_spec_tests": ", ".join(failed),
            }
        )
    return rows


def quality_summary(rows: Rows) -> list[tuple[str, Any, str]]:
    assert isinstance(rows, list)
    rejected = sum(1 for r in rows if r["decision_code"] == QualityDecision.Decision.REJECT)
    waits = [r["wait_hours"] for r in rows if r["wait_hours"] is not None]
    return [
        ("sample_count", len(rows), "number"),
        ("rejected_count", rejected, "number"),
        ("rejection_rate", pct(Decimal(rejected), Decimal(len(rows))), "percent"),
        ("out_of_spec_samples", sum(1 for r in rows if r["out_of_spec_count"]), "number"),
        ("avg_wait_hours", mean(waits), "duration"),
    ]


# --- sevkiyat --------------------------------------------------------------------------------


def shipments(filters: Filters) -> list[Row]:
    """Sevk edilen sevkiyat satırları: sevk edilen miktar, lotlar, istenen tarihe göre zamanında
    mı."""
    qs = (
        ShipmentLine.objects.filter(shipment__status=Shipment.Status.DISPATCHED)
        .filter(date_range_q("shipment__dispatched_at", filters))
        .select_related(
            "shipment__sales_order__customer",
            "order_line__product__base_unit",
        )
    )
    if filters.get("customer"):
        qs = qs.filter(shipment__sales_order__customer=filters["customer"])
    if filters.get("material"):
        qs = qs.filter(order_line__product=filters["material"])
    lines = list(qs.order_by("-shipment__dispatched_at", "shipment__number", "id"))
    picks: dict[int, list[ShipmentPick]] = defaultdict(list)
    for pick in (
        ShipmentPick.objects.filter(line__in=lines, returned_at__isnull=True)
        .select_related("lot")
        .order_by("id")
    ):
        picks[pick.line_id].append(pick)
    rows = []
    for line in lines:
        shipment = line.shipment
        order = shipment.sales_order
        product = line.order_line.product
        line_picks = picks.get(line.pk, [])
        dispatched = timezone.localdate(shipment.dispatched_at) if shipment.dispatched_at else None
        requested = order.requested_delivery_date
        rows.append(
            {
                "number": shipment.number,
                "dispatched_at": shipment.dispatched_at,
                "customer": material_text(order.customer.code, order.customer.name),
                "order_number": order.number,
                "product": material_text(product.code, product.name),
                "planned_quantity": line.quantity,
                "shipped_quantity": sum((p.quantity for p in line_picks), ZERO),
                "unit": product.base_unit.code,
                "lots": ", ".join(dict.fromkeys(p.lot.lot_no for p in line_picks)),
                "vehicle_plate": shipment.vehicle_plate,
                "requested_date": requested,
                "on_time": (dispatched <= requested) if dispatched and requested else None,
            }
        )
    return rows


def shipments_summary(rows: Rows) -> list[tuple[str, Any, str]]:
    assert isinstance(rows, list)
    with_date = [r for r in rows if r["on_time"] is not None]
    on_time = sum(1 for r in with_date if r["on_time"])
    return [
        ("shipment_count", len({r["number"] for r in rows}), "number"),
        ("customer_count", len({r["customer"] for r in rows}), "number"),
        ("on_time_rate", pct(Decimal(on_time), Decimal(len(with_date))), "percent"),
    ]


# --- görev süreleri --------------------------------------------------------------------------

MANUAL_TASK = "Elle açılan görev"
USER_ASSIGNED = "Kişiye atanmış"


def task_kind(rule_code: str, title: str) -> str:
    """Görev türü adı: kural kodlu görevlerde başlığın belge numarası öncesi kısmı
    (ör. "Toplama yap: SV-2026-00001" → "Toplama yap"); kuralsız görev elle açılmıştır."""
    if not rule_code:
        return MANUAL_TASK
    return title.split(":")[0].strip() or rule_code


def task_durations(filters: Filters) -> list[Row]:
    """Görev türü × rol bazında bekleme süreleri: üstlenilene kadar, kapanana kadar; açık ve
    gecikmiş görevler. Süreç darboğazı en uzun ortalama kapanma süresidir."""
    now = timezone.now()
    qs = Task.objects.filter(date_range_q("created_at", filters))
    if filters.get("role"):
        qs = qs.filter(assigned_role__name=filters["role"])
    open_q = Q(status__in=Task.OPEN_STATUSES)
    done_q = Q(status=Task.Status.DONE)
    to_claim = ExpressionWrapper(F("claimed_at") - F("created_at"), output_field=DurationField())
    to_close = ExpressionWrapper(F("completed_at") - F("created_at"), output_field=DurationField())
    grouped = (
        qs.values("rule_code", "assigned_role__name")
        .annotate(
            total=Count("id"),
            done=Count("id", filter=done_q),
            open=Count("id", filter=open_q),
            overdue=Count("id", filter=open_q & Q(due_at__lt=now)),
            avg_claim=Avg(to_claim, filter=Q(claimed_at__isnull=False)),
            avg_close=Avg(to_close, filter=done_q),
            max_close=Max(to_close, filter=done_q),
            sample_title=Max("title"),
            oldest_open=Max(
                ExpressionWrapper(now - F("created_at"), output_field=DurationField()),
                filter=open_q,
            ),
        )
        .order_by()
    )
    rows = [
        {
            "task_kind": task_kind(g["rule_code"], g["sample_title"]),
            "role": ROLE_LABELS.get(g["assigned_role__name"], g["assigned_role__name"])
            if g["assigned_role__name"]
            else USER_ASSIGNED,
            "total": g["total"],
            "done": g["done"],
            "open": g["open"],
            "overdue": g["overdue"],
            "avg_claim_hours": hours(g["avg_claim"]),
            "avg_close_hours": hours(g["avg_close"]),
            "max_close_hours": hours(g["max_close"]),
            "oldest_open_hours": hours(g["oldest_open"]),
        }
        for g in grouped
    ]
    rows.sort(key=lambda r: (r["avg_close_hours"] is None, -(r["avg_close_hours"] or ZERO)))
    return rows


def task_durations_summary(rows: Rows) -> list[tuple[str, Any, str]]:
    assert isinstance(rows, list)
    bottleneck = next((r for r in rows if r["avg_close_hours"] is not None), None)
    return [
        ("task_count", sum(r["total"] for r in rows), "number"),
        ("open_count", sum(r["open"] for r in rows), "number"),
        ("overdue_count", sum(r["overdue"] for r in rows), "number"),
        (
            "bottleneck",
            f"{bottleneck['task_kind']} ({bottleneck['role']})" if bottleneck else "",
            "text",
        ),
    ]
