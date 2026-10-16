"""Dolum demo verisi (Faz 2, Adım 2.2): ambalaj malzemeleri, mamuller (koli / palet dönüşümüyle),
dolum hattı DH-01, ambalaj ve mamul depoları, onaylı ambalaj reçeteleri, mamul son kontrol
spesifikasyonları (görünüş, dolum miktarı, sızdırmazlık, etiket; D-7) ve ambalaj açılış stoku.

`seed_demo` sonunda çağrılır; bulk ürünler ve ANA depo oradan gelir. Tekrar çalıştırılabilir: var
olan kayıt koduyla bulunur. Yalnızca geliştirme ortamında (DEBUG ya da eğitim) çalışır.
"""

from decimal import Decimal
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.demo import require_demo_allowed
from apps.core.models import User
from apps.core.roles import LABORATUVAR, PLANLAMA
from apps.filling import services
from apps.inventory import services as inventory
from apps.inventory.models import StockBalance
from apps.masterdata import services as masterdata
from apps.masterdata.models import (
    Equipment,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    UnitOfMeasure,
    Warehouse,
)
from apps.quality import services as quality
from apps.quality.models import SampleStage, TestDefinition

D = Decimal

# kod, ad, açılış stoku (adet)
PACKAGING = [
    ("SISE-750", "Şişe 750 ml (PET, şeffaf)", "20000"),
    ("SISE-1000", "Şişe 1 lt (PET, yeşil)", "15000"),
    ("KAPAK-28", "Kapak 28 mm (klik)", "40000"),
    ("ETIKET-BL-750", "Etiket: Bulaşık limon 750 ml", "20000"),
    ("ETIKET-YC-1000", "Etiket: Yüzey çam 1 lt", "15000"),
    ("KOLI-12", "Koli 12'li", "3000"),
]

# mamul kodu, ad, bulk, dolum miktarı, dolum birimi, koli içi, palet koli, ambalaj satırları
# (malzeme, adet başı miktar, fire payı %)
FINISHED: list[tuple[str, str, str, str, str, int, int, list[tuple[str, str, str]]]] = [
    (
        "BULASIK-LIMON-750",
        "Bulaşık deterjanı limonlu 750 ml",
        "BULASIK-LIMON",
        "750",
        "ML",
        12,
        60,
        [
            ("SISE-750", "1", "2"),
            ("KAPAK-28", "1", "2"),
            ("ETIKET-BL-750", "1", "3"),
            ("KOLI-12", "0.083333", "1"),
        ],
    ),
    (
        "YUZEY-CAM-1000",
        "Yüzey temizleyici çam 1 lt",
        "YUZEY-CAM",
        "1",
        "LT",
        12,
        50,
        [
            ("SISE-1000", "1", "2"),
            ("KAPAK-28", "1", "2"),
            ("ETIKET-YC-1000", "1", "3"),
            ("KOLI-12", "0.083333", "1"),
        ],
    ),
]


class Command(BaseCommand):
    help = (
        "Dolum demo verisi: ambalaj malzemeleri, mamuller, dolum hattı, ambalaj reçeteleri, mamul "
        "son kontrol spesifikasyonları ve ambalaj stoku. Yalnızca geliştirme ortamında."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        require_demo_allowed()
        if not User.objects.filter(username=PLANLAMA).exists():
            call_command("create_demo_users", stdout=self.stdout)
        planner = User.objects.get(username=PLANLAMA)
        lab = User.objects.get(username=LABORATUVAR)
        with transaction.atomic():
            seed(planner, lab, self.stdout.write)
        self.stdout.write(self.style.SUCCESS("Dolum demo verisi hazır."))


def _get_or_create(actor: User, model: Any, code: str, data: dict[str, Any]) -> Any:
    existing = model.objects.filter(code=code).first()
    if existing is not None:
        return existing
    return masterdata.create_record(actor, model, {"code": code, **data}, note="seed_demo")


def seed(planner: User, lab: User, write: Any = print) -> None:
    """Dolum demo verisini yükler. Bulk ürünler ve ANA depo yoksa (seed_demo çalışmadıysa) hata."""
    warehouse = Warehouse.objects.filter(code="ANA").first()
    if warehouse is None:
        raise CommandError("Önce seed_demo çalıştırılmalı (ANA depo yok).")
    units = {unit.code: unit for unit in UnitOfMeasure.objects.all()}
    packaging_category = _get_or_create(planner, MaterialCategory, "AMBALAJ", {"name": "Ambalaj"})
    finished_category = _get_or_create(planner, MaterialCategory, "MAMUL", {"name": "Mamul"})
    locations = {
        code: _get_or_create(
            planner,
            Location,
            code,
            {"warehouse": warehouse, "name": name, "location_type": kind},
        )
        for code, name, kind in [
            ("AMB-DEPO", "Ambalaj deposu", Location.Type.STORAGE),
            ("DOLUM-1", "Dolum hattı 1 (hat başı)", Location.Type.PRODUCTION),
            ("MAMUL-DEPO", "Mamul deposu", Location.Type.STORAGE),
        ]
    }
    _get_or_create(
        planner,
        Equipment,
        "DH-01",
        {
            "name": "Dolum hattı 1",
            "equipment_type": Equipment.Type.FILLING_LINE,
            "location": locations["DOLUM-1"],
        },
    )

    materials: dict[str, Material] = {}
    for code, name, _stock in PACKAGING:
        materials[code] = _get_or_create(
            planner,
            Material,
            code,
            {
                "name": name,
                "material_type": Material.Type.PACKAGING,
                "base_unit": units["ADET"],
                "category": packaging_category,
                "requires_incoming_qc": False,
            },
        )
    tests = {test.code: test for test in TestDefinition.objects.all()}
    for code, name, bulk_code, fill, fill_unit, per_case, per_pallet, lines in FINISHED:
        bulk = Material.objects.filter(code=bulk_code).first()
        if bulk is None:
            raise CommandError(f"Önce seed_demo çalıştırılmalı ({bulk_code} yok).")
        finished = _get_or_create(
            planner,
            Material,
            code,
            {
                "name": name,
                "material_type": Material.Type.FINISHED,
                "base_unit": units["ADET"],
                "category": finished_category,
                "shelf_life_days": 730,
                "requires_incoming_qc": False,
            },
        )
        for unit_code, factor in (("KOLI", per_case), ("PALET", per_case * per_pallet)):
            if not MaterialUnitConversion.objects.filter(
                material=finished, unit=units[unit_code]
            ).exists():
                masterdata.create_record(
                    planner,
                    MaterialUnitConversion,
                    {"material": finished, "unit": units[unit_code], "factor_to_base": D(factor)},
                    note="seed_demo",
                )
        if services.approved_spec(finished) is None:
            spec = services.create_spec(
                planner,
                {
                    "finished_product": finished,
                    "bulk_product": bulk,
                    "fill_quantity": D(fill),
                    "fill_unit": units[fill_unit],
                    "fill_tolerance_pct": D("1.5"),
                    "units_per_case": per_case,
                    "cases_per_pallet": per_pallet,
                    "change_note": "İlk sürüm (demo)",
                    "lines": [
                        {
                            "material": materials[material],
                            "quantity_per_unit": D(per_unit),
                            "scrap_allowance_pct": D(allowance),
                        }
                        for material, per_unit, allowance in lines
                    ],
                },
            )
            services.approve_spec(planner, spec, "Demo ambalaj reçetesi")
            write(f"Ambalaj reçetesi onaylandı: {code} v{spec.version_no}")
        if quality.approved_specification(finished, SampleStage.FINAL) is None:
            # Dolum miktarı ml cinsinden, ambalaj reçetesinin %1,5 toleransıyla.
            fill_ml = D(fill) * (1000 if fill_unit == "LT" else 1)
            low, high = fill_ml * D("0.985"), fill_ml * D("1.015")
            rows: list[tuple[str, Decimal | None, Decimal | None, Decimal | None, str]] = [
                ("GORUNUS", None, None, None, "Berrak, tortusuz"),
                ("DOLUM_MIKTARI", low, high, fill_ml, ""),
                ("SIZDIRMAZLIK", None, None, None, ""),
                ("ETIKET", None, None, None, ""),
            ]
            specification = quality.create_specification(
                lab,
                material=finished,
                sample_stage=SampleStage.FINAL,
                change_note="Örnek mamul spesifikasyonu (D-7)",
                lines=[
                    {
                        "test": tests[test],
                        "min_value": minimum,
                        "max_value": maximum,
                        "target_value": target,
                        "text_expected": text,
                        "is_mandatory": True,
                    }
                    for test, minimum, maximum, target, text in rows
                ],
            )
            quality.approve_specification(lab, specification)

    today = timezone.localdate()
    for code, _name, stock in PACKAGING:
        material = materials[code]
        if StockBalance.objects.filter(material=material).exists():
            continue
        inventory.post_opening_balance(
            planner,
            material=material,
            lot_no=f"ACILIS-{code}",
            location=locations["AMB-DEPO"],
            quantity=D(stock),
            manufactured_at=today,
        )
    write(f"{len(PACKAGING)} ambalaj malzemesi, {len(FINISHED)} mamul, dolum hattı DH-01.")
