"""Maliyet demo verisi (Faz 4, Adım 4.1): standart maliyetler, gider oranları, demo lotlarının
maliyeti; personel kartları varsa örnek brüt ücretler ve birimlerin maliyet aşaması. `seed_demo`
sonunda (personel demosundan sonra) çağrılır; tekrar çalıştırmak güvenlidir."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.demo import require_demo_allowed
from apps.core.models import User
from apps.core.roles import YONETIM
from apps.costing import services
from apps.costing.models import (
    CostRate,
    CostStage,
    DepartmentCostCenter,
    EmployeeWage,
    LotCost,
    StandardCost,
)
from apps.inventory.models import Lot
from apps.masterdata.models import Material
from apps.personnel.models import Employee

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


# Örnek brüt aylık ücretler (TL; eğitim içindir, gerçek kişi ücreti değildir): sicil no → tutar.
# Kartlar `seed_personnel_demo` ile gelir.
WAGES = {
    "S-0001": "120000",
    "S-0002": "62000",
    "S-0003": "52000",
    "S-0004": "68000",
    "S-0005": "58000",
    "S-0006": "60000",
    "S-0007": "50000",
    "S-0008": "55000",
    "S-0010": "36000",
    "S-0011": "38000",
    "S-0012": "36000",
    "S-0013": "34000",
    "S-0014": "38000",
    "S-0015": "42000",
}
# Zam örneği: geçen ayın ilk gününden geçerli.
RAISE = ("S-0012", "39000")
COST_CENTERS = {"Üretim": CostStage.PRODUCTION, "Dolum": CostStage.FILLING}


def _personnel(actor: User, write: Any) -> None:
    """Örnek ücretler (yılbaşından ya da işe girişten geçerli) ve birim eşleştirmesi; ücreti olan
    kişi ve eşleştirmesi olan kurulum atlanır."""
    if not DepartmentCostCenter.objects.exists():
        for department, stage in COST_CENTERS.items():
            services.set_department_cost_center(actor, department, stage)
    today = timezone.localdate()
    previous = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    added = 0
    for employee_no, amount in WAGES.items():
        person = Employee.objects.filter(employee_no=employee_no).first()
        if person is None or EmployeeWage.objects.filter(employee=person).exists():
            continue
        start = max(date(previous.year, 1, 1), person.hire_date or date.min)
        values = {"employee": person, "gross_monthly": D(amount), "note": "Demo"}
        services.add_wage(actor, {**values, "valid_from": start})
        added += 1
        if employee_no == RAISE[0] and previous > start:
            raised = {**values, "gross_monthly": D(RAISE[1]), "note": "Demo zam"}
            services.add_wage(actor, {**raised, "valid_from": previous})
    write(f"{added} personel ücreti.")


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
    if actor is not None:
        _personnel(actor, write)


class Command(BaseCommand):
    help = "Maliyet demo verisini yükler (yalnızca DEBUG ya da eğitim)."

    def handle(self, *args: Any, **options: Any) -> None:
        require_demo_allowed()
        actor = User.objects.filter(username=YONETIM).first()
        with transaction.atomic():
            seed(actor, self.stdout.write)
