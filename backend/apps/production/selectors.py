"""Üretim okuma sorguları: ihtiyaç özetleri, hazırlama önerileri (FEFO), şarj tartım satırları."""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import QuerySet, Sum

from apps.inventory import selectors as inventory_selectors
from apps.inventory.models import StockBalance
from apps.masterdata.models import Location
from apps.production import services
from apps.production.models import ProductionBatch, ProductionOrder, ProductionRequirement

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class RequirementRow:
    """Emir ihtiyaç satırı ve hazırlama/tüketim durumu (temel birimde)."""

    requirement: ProductionRequirement
    picked: Decimal
    consumed: Decimal
    lower_limit: Decimal

    @property
    def is_ready(self) -> bool:
        return self.requirement.is_water or self.picked >= self.lower_limit

    @property
    def to_pick(self) -> Decimal:
        if self.requirement.is_water:
            return Decimal(0)
        return max(self.requirement.required_quantity - self.picked, Decimal(0))


def requirement_rows(order: ProductionOrder) -> list[RequirementRow]:
    """Emrin ihtiyaçları: hazırlanan (iade edilmemiş) ve tüm şarjlarda tüketilen miktarlarla."""
    requirements = list(
        order.requirements.select_related("material__base_unit", "recipe_line").order_by("sequence")
    )
    picked = dict(
        order.picks.filter(returned_at__isnull=True)
        .values_list("requirement_id")
        .annotate(t=Sum("quantity"))
    )
    consumed = dict(
        ProductionRequirement.objects.filter(order=order)
        .values_list("id")
        .annotate(t=Sum("consumptions__actual_quantity"))
    )
    rows = []
    for requirement in requirements:
        lower = requirement.required_quantity * (1 - requirement.tolerance_pct / HUNDRED)
        rows.append(
            RequirementRow(
                requirement=requirement,
                picked=picked.get(requirement.pk) or Decimal(0),
                consumed=consumed.get(requirement.pk) or Decimal(0),
                lower_limit=lower,
            )
        )
    return rows


def pick_suggestions(
    order: ProductionOrder, requirement: ProductionRequirement
) -> QuerySet[StockBalance]:
    """Hazırlama için FEFO sıralı öneri: serbest, SKT'si geçmemiş, karantina ve emrin üretim
    lokasyonu dışındaki stoklar."""
    return (
        inventory_selectors.available_lots(requirement.material)
        .exclude(location=order.production_location)
        .exclude(location__location_type=Location.Type.QUARANTINE)
    )


def consumable_balances(
    order: ProductionOrder, requirement: ProductionRequirement
) -> QuerySet[StockBalance]:
    """Tartımda kullanılabilecek stok (FEFO): su için tüm serbest stok, diğerleri için emrin
    üretim lokasyonundaki serbest stok."""
    balances = inventory_selectors.available_lots(requirement.material).exclude(
        location__location_type=Location.Type.QUARANTINE
    )
    if requirement.is_water:
        return balances
    return balances.filter(location=order.production_location)


@dataclass(frozen=True)
class BatchLine:
    """Şarjda bir ihtiyaç satırının tartım durumu."""

    requirement: ProductionRequirement
    planned: Decimal
    consumed: Decimal
    deviation_pct: Decimal

    @property
    def state(self) -> str:
        """`pending` (tartılmadı), `under` (toleransın altında), `ok`, `over` (üstünde)."""
        if self.consumed == 0:
            return "pending"
        tolerance = self.requirement.tolerance_pct
        if self.deviation_pct > tolerance:
            return "over"
        if self.deviation_pct < -tolerance:
            return "under"
        return "ok"


def batch_lines(batch: ProductionBatch) -> list[BatchLine]:
    """Şarjın tartım satırları reçete sırasıyla: bu şarja düşen plan, tartılan ve sapma."""
    consumed = dict(
        batch.consumptions.values_list("requirement_id").annotate(t=Sum("actual_quantity"))
    )
    lines = []
    for requirement in batch.order.requirements.select_related(
        "material__base_unit", "recipe_line"
    ).order_by("sequence"):
        planned = services.batch_line_quantity(requirement, batch)
        actual = consumed.get(requirement.pk) or Decimal(0)
        lines.append(
            BatchLine(
                requirement=requirement,
                planned=planned,
                consumed=actual,
                deviation_pct=services.deviation_pct(planned, actual),
            )
        )
    return lines
