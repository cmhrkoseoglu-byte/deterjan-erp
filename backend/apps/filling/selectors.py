"""Dolum okuma sorguları: ambalaj hazırlama satırları, hazırlama önerisi, hat başı stoku ve teorik /
gerçek tüketim raporu."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum

from apps.filling import services
from apps.filling.models import (
    ConsumptionKind,
    FillingConsumption,
    FillingOrder,
    FillingRequirement,
    FillingRun,
    PackagingSpecLine,
    ScrapRecord,
)
from apps.inventory import selectors as inventory
from apps.inventory.models import StockBalance
from apps.inventory.services import quantize

ZERO = Decimal(0)


@dataclass(frozen=True)
class RequirementRow:
    requirement: FillingRequirement
    net_quantity: Decimal
    picked: Decimal

    @property
    def is_ready(self) -> bool:
        return self.picked >= self.net_quantity

    @property
    def to_pick(self) -> Decimal:
        """Fire payı dahil ihtiyaca kalan miktar."""
        return max(self.requirement.required_quantity - self.picked, ZERO)


def requirement_rows(order: FillingOrder) -> list[RequirementRow]:
    """Ambalaj hazırlama ekranının satırları: ihtiyaç, fire payı hariç ihtiyaç, hazırlanan."""
    requirements = order.requirements.select_related(
        "material__base_unit", "spec_line", "order"
    ).order_by("sequence")
    return [
        RequirementRow(r, services.net_requirement(r), services.picked_quantity(r))
        for r in requirements
    ]


def pick_suggestions(
    order: FillingOrder, requirement: FillingRequirement
) -> QuerySet[StockBalance]:
    """Hazırlama önerisi: serbest, SKT'si geçmemiş lotlar FEFO sırasıyla (hat başı hariç)."""
    return inventory.available_lots(requirement.material).exclude(
        location=services.line_location(order)
    )


def line_stock(order: FillingOrder) -> QuerySet[StockBalance]:
    """Dolum hattındaki ambalaj stoku (reçetedeki malzemeler)."""
    materials = order.packaging_spec.lines.values_list("material_id", flat=True)
    return inventory.balances().filter(
        location=services.line_location(order), material_id__in=list(materials)
    )


def bulk_lots(order: FillingOrder) -> QuerySet[StockBalance]:
    """Dolumda kullanılabilecek bulk stoku: serbest, SKT'si geçmemiş tank lotları (FEFO)."""
    return inventory.available_lots(order.packaging_spec.bulk_product)


# --- teorik / gerçek tüketim raporu ----------------------------------------------------------


@dataclass
class PackagingRow:
    line: PackagingSpecLine
    theoretical: Decimal = ZERO
    consumed: Decimal = ZERO
    scrap: Decimal = ZERO

    @property
    def actual(self) -> Decimal:
        return self.consumed + self.scrap

    @property
    def variance(self) -> Decimal:
        return self.actual - self.theoretical

    @property
    def variance_pct(self) -> Decimal:
        return services.variance_pct(self.theoretical, self.actual)

    @property
    def over_allowance(self) -> bool:
        """Fark fire payını aşıyor mu?"""
        return self.variance_pct > self.line.scrap_allowance_pct


@dataclass
class BulkRow:
    theoretical: Decimal = ZERO
    consumed: Decimal = ZERO
    scrap: Decimal = ZERO

    @property
    def actual(self) -> Decimal:
        return self.consumed + self.scrap

    @property
    def variance(self) -> Decimal:
        return self.actual - self.theoretical

    @property
    def variance_pct(self) -> Decimal:
        return services.variance_pct(self.theoretical, self.actual)


@dataclass
class ConsumptionReport:
    good_units: int = 0
    scrapped_units: int = 0
    bulk: BulkRow = field(default_factory=BulkRow)
    packaging: list[PackagingRow] = field(default_factory=list)
    runs: list[FillingRun] = field(default_factory=list)

    @property
    def threshold_pct(self) -> Decimal:
        return services.variance_threshold()

    @property
    def bulk_over_threshold(self) -> bool:
        return abs(self.bulk.variance_pct) > self.threshold_pct


def _sum(queryset: QuerySet[Any]) -> Decimal:
    return queryset.aggregate(t=Sum("quantity"))["t"] or ZERO


def consumption_report(order: FillingOrder, run: FillingRun | None = None) -> ConsumptionReport:
    """Teorik ve gerçek tüketim (tamamlanan partiler; `run` verilirse yalnızca o parti).

    - Bulk: teorik = sağlam adet × dolum miktarı; gerçek = tüketilen bulk + bulk firesi.
    - Ambalaj: teorik = sağlam adet × adet başına miktar; gerçek = tüketim + ambalaj firesi. Mamul
      firesindeki ambalaj tüketime dahildir (dolup ayrılan şişe de harcanmıştır).
    """
    runs = order.runs.filter(status=FillingRun.Status.COMPLETED).select_related("output_lot")
    if run is not None:
        runs = runs.filter(pk=run.pk)
    run_list = list(runs.order_by("sequence"))
    report = ConsumptionReport(runs=run_list)
    report.good_units = sum(r.good_units or 0 for r in run_list)
    report.scrapped_units = sum(services.finished_scrap_units(r) for r in run_list)
    consumptions = FillingConsumption.objects.filter(run__in=run_list)
    scraps = ScrapRecord.objects.filter(run__in=run_list)
    report.bulk = BulkRow(
        theoretical=services.theoretical_bulk(order, report.good_units),
        consumed=_sum(consumptions.filter(kind=ConsumptionKind.BULK)),
        scrap=_sum(scraps.filter(kind=ScrapRecord.Kind.BULK)),
    )
    lines = order.packaging_spec.lines.select_related("material__base_unit").order_by("sequence")
    for line in lines:
        report.packaging.append(
            PackagingRow(
                line=line,
                theoretical=quantize(report.good_units * line.quantity_per_unit),
                consumed=_sum(consumptions.filter(kind=ConsumptionKind.PACKAGING, spec_line=line)),
                scrap=_sum(
                    scraps.filter(kind=ScrapRecord.Kind.PACKAGING, material_id=line.material_id)
                ),
            )
        )
    return report
