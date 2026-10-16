"""Maliyet demo verisi (Faz 4, Adım 4.1): standart maliyetler, gider oranları ve demo lotlarının
maliyeti. `seed_demo` sonunda çağrılır; tekrar çalıştırmak güvenlidir."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.demo import require_demo_allowed
from apps.core.models import User
from apps.core.roles import YONETIM
from apps.costing import services
from apps.costing.models import CostRate, CostStage, LotCost, StandardCost
from apps.inventory.models import Lot
from apps.masterdata.models import Material

D = Decimal

# TL / temel birim (örnek fiyatlar).
STANDARD_COSTS = {
    "LAS": "48",
    "SLES": "42",
    "CAPB": "38",
    "NAOH": "14",
    "SITRIK": "35",
    "NACL": "3.5",
    "EDTA": "95",
    "GLISERIN": "40",
    "ALKOL": "45",
    "KORUYUCU": "180",
    "PARFUM-LIMON": "650",
    "PARFUM-CAM": "620",
    "BOYA-SARI": "900",
    "BOYA-YESIL": "900",
    "SU": "0.03",
    "SISE-750": "4.20",
    "SISE-1000": "5.10",
    "KAPAK-28": "1.10",
    "ETIKET-BL-750": "0.45",
    "ETIKET-YC-1000": "0.50",
    "KOLI-12": "9.50",
    # Açılış stoku olan bulk ve mamuller için.
    "BULASIK-LIMON": "16",
    "YUZEY-CAM": "11",
    "BULASIK-LIMON-750": "21",
    "YUZEY-CAM-1000": "19",
}
# Karar D-15: TL / kg.
RATES = {
    (CostStage.PRODUCTION, CostRate.Kind.ENERGY): "0.45",
    (CostStage.PRODUCTION, CostRate.Kind.LABOR): "0.80",
    (CostStage.PRODUCTION, CostRate.Kind.DEPRECIATION): "0.25",
    (CostStage.FILLING, CostRate.Kind.ENERGY): "0.10",
    (CostStage.FILLING, CostRate.Kind.LABOR): "0.35",
    (CostStage.FILLING, CostRate.Kind.DEPRECIATION): "0.15",
}


def seed(actor: User | None, write: Any = print) -> None:
    standard = 0
    for code, cost in STANDARD_COSTS.items():
        material = Material.objects.filter(code=code).first()
        if material is None or StandardCost.objects.filter(material=material).exists():
            continue
        services.create_standard_cost(
            actor, {"material": material, "unit_cost": D(cost), "note": "Demo"}
        )
        standard += 1
    start = date(timezone.localdate().year, 1, 1)
    for (stage, kind), rate in RATES.items():
        if not CostRate.objects.filter(stage=stage, kind=kind).exists():
            services.create_rate(
                actor, {"stage": stage, "kind": kind, "rate_per_kg": D(rate), "valid_from": start}
            )
    costed = 0
    for lot in Lot.objects.exclude(costs__isnull=False).order_by("created_at", "id"):
        if not LotCost.objects.filter(lot=lot).exists() and services.is_costable(lot):
            services.calculate_lot_cost(actor, lot, note="Demo verisi")
            costed += 1
    write(f"{standard} standart maliyet, {len(RATES)} gider oranı, {costed} lot maliyeti.")


class Command(BaseCommand):
    help = "Maliyet demo verisini yükler (yalnızca DEBUG ya da eğitim)."

    def handle(self, *args: Any, **options: Any) -> None:
        require_demo_allowed()
        actor = User.objects.filter(username=YONETIM).first()
        with transaction.atomic():
            seed(actor, self.stdout.write)
