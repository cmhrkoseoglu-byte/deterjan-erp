"""Örnek spesifikasyonlar (Karar D-7: örnek listeyle başla, Faz 2 Adım 2.1).

Giriş kontrolü gereken her hammaddeye bir giriş spesifikasyonu, her bulk ürüne bir son kontrol
spesifikasyonu yazar ve onaylar (pH, viskozite, yoğunluk, aktif madde, görünüş, renk, koku).
Laboratuvar değerleri sonradan spesifikasyon ekranında yeni sürümle düzenler. Tekrar
çalıştırılabilir: onaylı sürümü olan malzeme + aşama atlanır. `seed_demo` sonunda çağrılır.

Yalnızca geliştirme ortamında (DEBUG ya da eğitim) çalışır; onay demo `laboratuvar` kullanıcısıyla.
"""

from decimal import Decimal
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.demo import require_demo_allowed
from apps.core.models import User
from apps.core.roles import LABORATUVAR
from apps.masterdata.models import Material
from apps.quality import services
from apps.quality.models import SampleStage, TestDefinition

D = Decimal

# test kodu, alt sınır, üst sınır, hedef, beklenen metin, zorunlu
Line = tuple[str, str | None, str | None, str | None, str, bool]

INCOMING: dict[str, list[Line]] = {
    "LAS": [("AKTIF_MADDE", "95.5", "98", None, "", True), ("RENK", None, None, None, "", True)],
    "SLES": [
        ("AKTIF_MADDE", "68", "72", "70", "", True),
        ("PH", "7", "9.5", None, "", True),
        ("RENK", None, None, None, "", True),
    ],
    "CAPB": [("AKTIF_MADDE", "28", "32", "30", "", True), ("PH", "4.5", "5.5", None, "", True)],
    "NAOH": [("AKTIF_MADDE", "49", "51", "50", "", True)],
    "PARFUM-LIMON": [("KOKU", None, None, None, "", True), ("RENK", None, None, None, "", True)],
    "PARFUM-CAM": [("KOKU", None, None, None, "", True), ("RENK", None, None, None, "", True)],
}
# Tabloda olmayan giriş kontrollü hammaddeler için.
INCOMING_DEFAULT: list[Line] = [
    ("RENK", None, None, None, "", True),
    ("KOKU", None, None, None, "", False),
]

FINAL: dict[str, list[Line]] = {
    "BULASIK-LIMON": [
        ("PH", "7", "8", "7.5", "", True),
        ("VISK", "1500", "3000", "2200", "", True),
        ("YOGUNLUK", "1.030", "1.050", "1.040", "", True),
        ("AKTIF_MADDE", "12", None, None, "", True),
        ("GORUNUS", None, None, None, "Berrak", True),
        ("RENK", None, None, None, "", True),
        ("KOKU", None, None, None, "", True),
    ],
    "YUZEY-CAM": [
        ("PH", "6", "7", "6.5", "", True),
        ("VISK", None, "50", None, "", False),
        ("YOGUNLUK", "1.000", "1.020", "1.010", "", True),
        ("AKTIF_MADDE", "5", None, None, "", True),
        ("GORUNUS", None, None, None, "Berrak", True),
        ("RENK", None, None, None, "", True),
        ("KOKU", None, None, None, "", True),
    ],
}
# Tabloda olmayan bulk ürünler için.
FINAL_DEFAULT: list[Line] = [
    ("PH", "6", "9", None, "", True),
    ("GORUNUS", None, None, None, "Berrak", True),
    ("RENK", None, None, None, "", True),
    ("KOKU", None, None, None, "", True),
]


class Command(BaseCommand):
    help = (
        "Örnek kalite spesifikasyonları: giriş kontrollü hammaddelere giriş, bulk ürünlere son "
        "kontrol spesifikasyonu (onaylı). Yalnızca geliştirme ortamında (DEBUG ya da eğitim)."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        require_demo_allowed()
        if not User.objects.filter(username=LABORATUVAR).exists():
            call_command("create_demo_users", stdout=self.stdout)
        lab = User.objects.get(username=LABORATUVAR)
        with transaction.atomic():
            count = seed_specifications(lab)
        self.stdout.write(self.style.SUCCESS(f"{count} örnek spesifikasyon onaylandı."))


def _lines(rows: list[Line]) -> list[dict[str, Any]]:
    tests = {test.code: test for test in TestDefinition.objects.all()}

    def _d(value: str | None) -> Decimal | None:
        return D(value) if value is not None else None

    return [
        {
            "test": tests[code],
            "min_value": _d(low),
            "max_value": _d(high),
            "target_value": _d(target),
            "text_expected": text,
            "is_mandatory": mandatory,
        }
        for code, low, high, target, text, mandatory in rows
    ]


def seed_specifications(lab: User) -> int:
    """Eksik örnek spesifikasyonları yazıp onaylar; onaylanan sürüm sayısını döner."""
    targets: list[tuple[Material, str, list[Line]]] = []
    raw = Material.objects.filter(
        material_type=Material.Type.RAW, requires_incoming_qc=True, is_active=True
    )
    for material in raw.order_by("code"):
        targets.append(
            (material, SampleStage.INCOMING, INCOMING.get(material.code, INCOMING_DEFAULT))
        )
    bulk = Material.objects.filter(material_type=Material.Type.BULK, is_active=True)
    for material in bulk.order_by("code"):
        targets.append((material, SampleStage.FINAL, FINAL.get(material.code, FINAL_DEFAULT)))
    count = 0
    for material, stage, rows in targets:
        if services.approved_specification(material, stage) is not None:
            continue
        spec = services.create_specification(
            lab,
            material=material,
            sample_stage=stage,
            change_note="Örnek spesifikasyon (D-7)",
            lines=_lines(rows),
        )
        services.approve_specification(lab, spec)
        count += 1
    return count
