"""İSG demo verisi (Faz 4, Adım 4.5): tehlikeli hammaddelerin tehlike bilgisi, GBF kayıtları
(biri eski, biri eksik), hammadde deposu limitleri, bir atık firması ve teslimi, bir ramak kala
bildirimi. `seed_demo` sonunda çağrılır; tekrar çalıştırmak güvenlidir."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import User
from apps.core.roles import DEPO, LABORATUVAR, YONETIM
from apps.hse import services
from apps.hse.models import (
    HazardStatement,
    Incident,
    MaterialHazard,
    SafetyDataSheet,
    SignalWord,
    StorageLimit,
    WasteContractor,
    WasteRecord,
)
from apps.masterdata.models import Location, Material, Supplier

# malzeme kodu: (piktogramlar, uyarı kelimesi, ifadeler)
HAZARDS = {
    "LAS": (["GHS05", "GHS07"], SignalWord.DANGER, ["H302", "H315", "H318", "H412", "P280"]),
    "NAOH": (["GHS05"], SignalWord.DANGER, ["H290", "H314", "P260", "P280", "P310"]),
    "ALKOL": (["GHS02", "GHS07"], SignalWord.DANGER, ["H225", "H319", "P210", "P233"]),
    "KORUYUCU": (
        ["GHS05", "GHS06", "GHS09"],
        SignalWord.DANGER,
        ["H301", "H314", "H317", "H410", "P273", "P280"],
    ),
}
# malzeme kodu: revizyon kaç gün önce (KORUYUCU bilerek GBF'siz: eksik GBF raporunda çıkar)
SDS = {"LAS": 120, "NAOH": 400, "ALKOL": 4 * 365 + 30}
LIMITS = [("HM-DEPO", "GHS05", "8000"), ("HM-DEPO", "GHS02", "1000")]


def seed(write: Any = print) -> None:
    manager = User.objects.get(username=YONETIM)
    lab = User.objects.get(username=LABORATUVAR)
    today = timezone.localdate()
    for code, (pictograms, signal_word, statements) in HAZARDS.items():
        material = Material.objects.filter(code=code).first()
        if material is None or MaterialHazard.objects.filter(material=material).exists():
            continue
        services.set_material_hazard(
            lab,
            material,
            {
                "pictograms": pictograms,
                "signal_word": signal_word,
                "statements": list(HazardStatement.objects.filter(code__in=statements)),
            },
        )
    supplier = Supplier.objects.filter(code="T-KIMYA").first()
    for code, days_ago in SDS.items():
        material = Material.objects.filter(code=code).first()
        if material is None or supplier is None:
            continue
        if SafetyDataSheet.objects.filter(material=material).exists():
            continue
        services.create_sds(
            manager,
            {
                "material": material,
                "supplier": supplier,
                "revision_no": "1.0",
                "revision_date": today - timedelta(days=days_ago),
                "language": "tr",
            },
        )
    for location_code, hazard_class, max_kg in LIMITS:
        location = Location.objects.filter(code=location_code).first()
        if location is None:
            continue
        if StorageLimit.objects.filter(location=location, hazard_class=hazard_class).exists():
            continue
        services.create_storage_limit(
            manager,
            {"location": location, "hazard_class": hazard_class, "max_kg": Decimal(max_kg)},
        )
    contractor = WasteContractor.objects.filter(license_no="ATK-34-0001").first()
    if contractor is None:
        contractor = services.create_contractor(
            manager,
            {
                "name": "Marmara Atık Geri Kazanım Ltd. Şti.",
                "license_no": "ATK-34-0001",
                "license_valid_until": today + timedelta(days=300),
                "phone": "0262 000 00 00",
            },
        )
    if not WasteRecord.objects.exists():
        services.record_waste(
            manager,
            {
                "waste_code": "15 01 10*",
                "description": "Tehlikeli madde bulaşmış ambalaj (boş LAS varilleri)",
                "quantity_kg": Decimal("240"),
                "contractor": contractor,
                "delivered_on": today - timedelta(days=5),
                "document_no": "UATF-0001",
            },
        )
    if not Incident.objects.exists():
        services.report_incident(
            User.objects.get(username=DEPO),
            {
                "incident_type": Incident.Type.NEAR_MISS,
                "occurred_at": timezone.now() - timedelta(days=2),
                "place": "Hammadde deposu, NaOH bidonları",
                "description": "Forklift manevrasında bidon devrilmek üzereydi; sızıntı olmadı.",
                "severity": Incident.Severity.LOW,
            },
        )
    write(
        f"{MaterialHazard.objects.count()} tehlike bilgisi, "
        f"{SafetyDataSheet.objects.count()} GBF, {StorageLimit.objects.count()} depolama limiti."
    )


class Command(BaseCommand):
    help = "İSG demo verisi: tehlike bilgisi, GBF, depolama limitleri, atık. Yalnızca DEBUG=True."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("Demo verisi yalnızca geliştirme ortamında (DEBUG=True) yüklenir.")
        with transaction.atomic():
            seed(self.stdout.write)
