"""Bakım demo verisi (Faz 4, Adım 4.4): iki terazi ve kalibrasyon planları (biri yaklaşıyor),
tank ve dolum hattı bakım planları, bir temizliksiz geçiş kuralı. `seed_demo` sonunda çağrılır;
tekrar çalıştırmak güvenlidir."""

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.demo import require_demo_allowed
from apps.core.models import User
from apps.core.roles import LABORATUVAR, URETIM
from apps.maintenance import services
from apps.maintenance.models import ChangeoverRule, MaintenanceKind, MaintenancePlan
from apps.masterdata import services as masterdata
from apps.masterdata.models import Equipment, Material

SCALES = [
    ("TR-01", "Platform terazisi 600 kg", 60),
    ("TR-02", "Masa terazisi 30 kg", 3),
]
TANK_CHECKLIST = ["Karıştırıcı motoru ve kayış", "Conta ve vanalar", "Seviye sensörü"]
LINE_CHECKLIST = ["Dolum nozulları temizliği", "Kapak makinesi ayarı", "Konveyör yağlama"]


def _plan(actor: User, equipment: Equipment, title: str, **data: Any) -> None:
    if MaintenancePlan.objects.filter(equipment=equipment, title=title).exists():
        return
    services.create_plan(actor, {"equipment": equipment, "title": title, **data})


def seed(write: Any = print) -> None:
    lab = User.objects.get(username=LABORATUVAR)
    operator = User.objects.get(username=URETIM)
    today = timezone.localdate()
    for code, name, days_left in SCALES:
        scale = Equipment.objects.filter(code=code).first() or masterdata.create_record(
            lab,
            Equipment,
            {"code": code, "name": name, "equipment_type": Equipment.Type.SCALE},
            note="seed_demo",
        )
        _plan(
            lab,
            scale,
            "Yıllık kalibrasyon",
            kind=MaintenanceKind.CALIBRATION,
            interval_days=365,
            next_due_date=today + timedelta(days=days_left),
            checklist=["Referans ağırlıklarla ölçüm", "Sertifika numarası"],
        )
    for tank in Equipment.objects.filter(equipment_type=Equipment.Type.MIXING_TANK):
        _plan(
            operator,
            tank,
            "Aylık periyodik bakım",
            kind=MaintenanceKind.PERIODIC,
            interval_days=30,
            next_due_date=today + timedelta(days=12),
            checklist=TANK_CHECKLIST,
        )
    for line in Equipment.objects.filter(equipment_type=Equipment.Type.FILLING_LINE):
        _plan(
            User.objects.get(username="dolum"),
            line,
            "Hat bakımı (20 partide bir)",
            kind=MaintenanceKind.PERIODIC,
            interval_runs=20,
            checklist=LINE_CHECKLIST,
        )
    # Aynı yüzey temizleyici bazından bulaşık deterjanına geçiş örneği (Karar D-14).
    first = Material.objects.filter(code="YUZEY-CAM").first()
    second = Material.objects.filter(code="BULASIK-LIMON").first()
    if (
        first
        and second
        and not ChangeoverRule.objects.filter(from_product=first, to_product=second).exists()
    ):
        services.create_changeover_rule(
            lab,
            {
                "from_product": first,
                "to_product": second,
                "note": "Örnek: açık renkten koyuya, aynı yüzey aktif baz.",
            },
        )
    write(f"{len(SCALES)} terazi, {MaintenancePlan.objects.count()} bakım planı.")


class Command(BaseCommand):
    help = (
        "Bakım demo verisi: teraziler, kalibrasyon ve bakım planları. Yalnızca DEBUG ya da eğitim."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        require_demo_allowed()
        with transaction.atomic():
            seed(self.stdout.write)
