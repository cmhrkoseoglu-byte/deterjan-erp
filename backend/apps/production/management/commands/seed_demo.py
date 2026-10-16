"""Demo verisi (Faz 1, Adım 1.8): ana veriler, onaylı reçeteler, tanklar, lokasyonlar, tedarikçiler
ve serbest açılış stoku. Tekrar çalıştırılabilir: var olan kayıt koduyla bulunur, yeniden yazılmaz.

Yalnızca geliştirme ortamında (DEBUG=True) çalışır. Reçete onayı demo `planlama` kullanıcısıyla
yapılır; yoksa önce `create_demo_users` çalıştırılır.
"""

from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import User
from apps.core.roles import PLANLAMA
from apps.inventory import services as inventory
from apps.inventory.models import StockBalance
from apps.masterdata import services as masterdata
from apps.masterdata.models import (
    Equipment,
    Location,
    Material,
    MaterialCategory,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)
from apps.recipes import services as recipes
from apps.recipes.models import Recipe, RecipeVersion

D = Decimal

CATEGORIES = {
    "YUZEY-AKTIF": "Yüzey aktif",
    "ALKALI": "Alkali / pH ayarlayıcı",
    "TUZ": "Tuz / kıvam",
    "PARFUM": "Parfüm",
    "BOYA": "Boya",
    "KORUYUCU": "Koruyucu",
    "YARDIMCI": "Yardımcı madde",
    "SU": "Su",
}

# kod, ad, kategori, raf ömrü (gün), tehlikeli, açılış stoku (kg)
RAW_MATERIALS: list[tuple[str, str, str, int | None, bool, str]] = [
    ("LAS", "LAS %96 (lineer alkil benzen sülfonik asit)", "YUZEY-AKTIF", 365, True, "4000"),
    ("SLES", "SLES %70 (sodyum lauril eter sülfat)", "YUZEY-AKTIF", 365, False, "3000"),
    ("CAPB", "Kokamidopropil betain %30", "YUZEY-AKTIF", 365, False, "1500"),
    ("NAOH", "Sodyum hidroksit %50", "ALKALI", 730, True, "1000"),
    ("SITRIK", "Sitrik asit", "ALKALI", 730, False, "500"),
    ("NACL", "Sodyum klorür (tuz)", "TUZ", None, False, "2000"),
    ("EDTA", "Tetrasodyum EDTA", "YARDIMCI", 730, False, "200"),
    ("GLISERIN", "Gliserin", "YARDIMCI", 730, False, "400"),
    ("ALKOL", "Etil alkol %96", "YARDIMCI", 730, True, "500"),
    ("KORUYUCU", "Koruyucu (MIT/CMIT)", "KORUYUCU", 365, True, "100"),
    ("PARFUM-LIMON", "Limon parfümü", "PARFUM", 365, False, "150"),
    ("PARFUM-CAM", "Çam parfümü", "PARFUM", 365, False, "150"),
    ("BOYA-SARI", "Sarı boya", "BOYA", 730, False, "50"),
    ("BOYA-YESIL", "Yeşil boya", "BOYA", 730, False, "50"),
    ("SU", "Şebeke suyu", "SU", None, False, "60000"),
]

BULK_PRODUCTS = [
    ("BULASIK-LIMON", "Bulaşık deterjanı (limonlu)", D("1.0400")),
    ("YUZEY-CAM", "Yüzey temizleyici (çam)", D("1.0100")),
]

# 1000 kg için reçete satırları: malzeme, kg, tolerans %, talimat
RECIPES: dict[str, tuple[str, str, list[tuple[str, str, str, str]]]] = {
    "BULASIK-LIMON": (
        "REC-BULASIK",
        "Bulaşık deterjanı (limonlu)",
        [
            ("SU", "690", "2", "Tanka suyun tamamını al, karıştırıcıyı 150 devirde çalıştır."),
            ("LAS", "120", "1", "Yavaşça ekle, köpürtme."),
            ("NAOH", "18", "1", "pH 7-8 olana kadar azar azar ekle."),
            ("SLES", "100", "1", "300 devirde 15 dakika karıştır."),
            ("CAPB", "40", "2", ""),
            ("EDTA", "2", "5", ""),
            ("KORUYUCU", "1.5", "5", ""),
            ("PARFUM-LIMON", "3", "5", ""),
            ("BOYA-SARI", "0.5", "10", "Önce az suda çöz."),
            ("NACL", "25", "3", "Kıvam için son olarak, viskoziteye bakarak ekle."),
        ],
    ),
    "YUZEY-CAM": (
        "REC-YUZEY",
        "Yüzey temizleyici (çam)",
        [
            ("SU", "872", "2", "Tanka suyu al."),
            ("SLES", "60", "1", "Yavaşça ekle."),
            ("CAPB", "25", "2", ""),
            ("ALKOL", "20", "2", "Kapalı ağızla ekle (yanıcı)."),
            ("GLISERIN", "10", "2", ""),
            ("SITRIK", "5", "2", "pH 6-7."),
            ("EDTA", "2", "5", ""),
            ("KORUYUCU", "1.5", "5", ""),
            ("PARFUM-CAM", "4", "5", ""),
            ("BOYA-YESIL", "0.5", "10", "Önce az suda çöz."),
        ],
    ),
}

SUPPLIERS = [
    ("T-KIMYA", "Anadolu Kimya San. A.Ş.", "Kartal VD", "1111111111"),
    ("T-ESANS", "Ege Esans ve Aroma Ltd. Şti.", "Bornova VD", "2222222222"),
    ("T-AMBALAJ", "Marmara Ambalaj A.Ş.", "Gebze VD", "3333333333"),
]


class Command(BaseCommand):
    help = (
        "Demo verisi: 15 hammadde, 2 bulk ürün, onaylı reçeteler, 2 karıştırma tankı, lokasyonlar, "
        "3 tedarikçi ve serbest açılış stoku. Yalnızca geliştirme ortamında (DEBUG=True)."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("Demo verisi yalnızca geliştirme ortamında (DEBUG=True) yüklenir.")
        if not User.objects.filter(username=PLANLAMA).exists():
            call_command("create_demo_users", stdout=self.stdout)
        approver = User.objects.get(username=PLANLAMA)
        with transaction.atomic():
            seed(approver, self.stdout.write)
        # Örnek kalite spesifikasyonları (Faz 2, D-7); kalite modülünün kendi komutu.
        call_command("seed_quality_demo", stdout=self.stdout)
        # Ambalaj, mamul, dolum hattı ve ambalaj reçeteleri (Faz 2, Adım 2.2).
        call_command("seed_filling_demo", stdout=self.stdout)
        # Müşteriler, mamul açılış stoku ve örnek siparişler (Faz 3, Adım 3.1).
        call_command("seed_sales_demo", stdout=self.stdout)
        # Standart maliyetler, gider oranları ve lot maliyetleri (Faz 4, Adım 4.1).
        call_command("seed_costing_demo", stdout=self.stdout)
        # Teraziler, kalibrasyon ve bakım planları (Faz 4, Adım 4.4).
        call_command("seed_maintenance_demo", stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Demo verisi hazır."))


def _get_or_create(actor: User, model: Any, code: str, data: dict[str, Any]) -> Any:
    existing = model.objects.filter(code=code).first()
    if existing is not None:
        return existing
    return masterdata.create_record(actor, model, {"code": code, **data}, note="seed_demo")


def seed(actor: User, write: Any = print) -> None:
    """Demo verisini yükler (komutun gövdesi; testlerde doğrudan çağrılır)."""
    kg = UnitOfMeasure.objects.get(code="KG")
    categories = {
        code: _get_or_create(actor, MaterialCategory, code, {"name": name})
        for code, name in CATEGORIES.items()
    }
    warehouse = _get_or_create(actor, Warehouse, "ANA", {"name": "Ana depo"})
    locations = {
        code: _get_or_create(
            actor,
            Location,
            code,
            {"warehouse": warehouse, "name": name, "location_type": kind},
        )
        for code, name, kind in [
            ("HM-DEPO", "Hammadde deposu", Location.Type.STORAGE),
            ("KARANTINA", "Karantina alanı", Location.Type.QUARANTINE),
            ("URETIM-1", "Üretim alanı (tank başı)", Location.Type.PRODUCTION),
            ("TANK-1", "Karıştırma tankı 1", Location.Type.TANK),
            ("TANK-2", "Karıştırma tankı 2", Location.Type.TANK),
            ("SEVK", "Sevkiyat alanı", Location.Type.SHIPPING),
        ]
    }
    for code, name, location in [
        ("KT-01", "Karıştırma tankı 1 (2 ton)", "TANK-1"),
        ("KT-02", "Karıştırma tankı 2 (2 ton)", "TANK-2"),
    ]:
        _get_or_create(
            actor,
            Equipment,
            code,
            {
                "name": name,
                "equipment_type": Equipment.Type.MIXING_TANK,
                "capacity": D("2000"),
                "capacity_unit": kg,
                "location": locations[location],
            },
        )
    for code, name, tax_office, tax_number in SUPPLIERS:
        _get_or_create(
            actor,
            Supplier,
            code,
            {"name": name, "tax_office": tax_office, "tax_number": tax_number},
        )

    materials: dict[str, Material] = {}
    for code, name, category, shelf_life, hazardous, _stock in RAW_MATERIALS:
        materials[code] = _get_or_create(
            actor,
            Material,
            code,
            {
                "name": name,
                "material_type": Material.Type.RAW,
                "base_unit": kg,
                "category": categories[category],
                "shelf_life_days": shelf_life,
                "is_hazardous": hazardous,
                "requires_incoming_qc": code != "SU",
                "density": D("1.0000") if code == "SU" else None,
            },
        )
    for code, name, density in BULK_PRODUCTS:
        materials[code] = _get_or_create(
            actor,
            Material,
            code,
            {
                "name": name,
                "material_type": Material.Type.BULK,
                "base_unit": kg,
                "density": density,
                "shelf_life_days": 730,
            },
        )

    for product_code, (recipe_code, recipe_name, lines) in RECIPES.items():
        recipe = Recipe.objects.filter(code=recipe_code).first() or recipes.create_recipe(
            actor, {"code": recipe_code, "name": recipe_name, "product": materials[product_code]}
        )
        if recipe.versions.filter(status=RecipeVersion.Status.APPROVED).exists():
            continue
        version = recipes.create_version(
            actor,
            recipe,
            batch_size=D("1000"),
            batch_unit=kg,
            change_note="İlk sürüm (demo)",
            lines=[
                {
                    "material": materials[code],
                    "quantity": D(quantity),
                    "unit": kg,
                    "tolerance_pct": D(tolerance),
                    "instruction": instruction,
                    "is_water": code == "SU",
                }
                for code, quantity, tolerance, instruction in lines
            ],
        )
        recipes.approve_version(actor, version, "Demo reçetesi")
        write(f"Reçete onaylandı: {recipe_code} v{version.version_no}")

    storage = locations["HM-DEPO"]
    today = timezone.localdate()
    for code, _name, _category, _shelf, _hazardous, stock in RAW_MATERIALS:
        material = materials[code]
        if StockBalance.objects.filter(material=material).exists():
            continue
        inventory.post_opening_balance(
            actor,
            material=material,
            lot_no=f"ACILIS-{code}",
            location=storage,
            quantity=D(stock),
            manufactured_at=today,
        )
    write(f"{len(RAW_MATERIALS)} hammadde, {len(BULK_PRODUCTS)} bulk ürün, 2 tank, 3 tedarikçi.")
