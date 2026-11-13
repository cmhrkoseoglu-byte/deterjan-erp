"""Panolar ve raporlar: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.15).

Pano ve rapor yetkileri ayrıdır: bir modülün bölümünü kaldırmak o modülün panodaki özetini
kaldırmaz. Stok değeri ve maliyet sütunları Maliyetleri görür'e, onay bekleyen satın alma
siparişlerinin TL toplamı Fiyatları görür'e bağlıdır. İndirmeler (kişinin kendi rapor dosyaları)
herkese açıktır.
"""

from apps.core.access import VIEW, grant, register_module, register_section
from apps.core.roles import (
    DEPO,
    DOLUM,
    LABORATUVAR,
    PLANLAMA,
    SATIN_ALMA,
    SEVKIYAT,
    URETIM,
    YONETIM,
)

register_module("reporting", "Panolar ve raporlar", order=150)

MANAGEMENT = register_section(
    "reporting.management",
    "Yönetim panosu ve görev süreleri raporu",
    levels=(VIEW,),
    help={VIEW: "Yönetim panosu ve görev süreleri raporu."},
)
WAREHOUSE = register_section(
    "reporting.warehouse", "Depo panosu", levels=(VIEW,), help={VIEW: "Depo panosu."}
)
STOCK = register_section(
    "reporting.stock",
    "Stok raporları",
    levels=(VIEW,),
    help={VIEW: "Stok durumu ve stok hareketleri raporları."},
)
PRODUCTION = register_section(
    "reporting.production",
    "Üretim panosu ve üretim raporu",
    levels=(VIEW,),
    help={VIEW: "Üretim panosu ve üretim raporu."},
)
FILLING = register_section(
    "reporting.filling", "Dolum raporu", levels=(VIEW,), help={VIEW: "Dolum raporu."}
)
LAB = register_section(
    "reporting.lab",
    "Laboratuvar panosu ve kalite raporu",
    levels=(VIEW,),
    help={VIEW: "Laboratuvar panosu ve kalite raporu."},
)
SHIPPING = register_section(
    "reporting.shipping", "Sevkiyat panosu", levels=(VIEW,), help={VIEW: "Sevkiyat panosu."}
)
SHIPPING_REPORT = register_section(
    "reporting.shipping_report",
    "Sevkiyat raporu",
    levels=(VIEW,),
    help={VIEW: "Sevkiyat raporu."},
)

PACKAGES = {
    MANAGEMENT: (YONETIM, PLANLAMA),
    WAREHOUSE: (DEPO, PLANLAMA, YONETIM),
    STOCK: (DEPO, PLANLAMA, YONETIM, SATIN_ALMA),
    PRODUCTION: (URETIM, PLANLAMA, YONETIM),
    FILLING: (DOLUM, PLANLAMA, YONETIM),
    LAB: (LABORATUVAR, PLANLAMA, YONETIM),
    SHIPPING: (SEVKIYAT, DEPO, PLANLAMA, YONETIM),
    SHIPPING_REPORT: (SEVKIYAT, PLANLAMA, YONETIM),
}
for section, roles in PACKAGES.items():
    for role in roles:
        grant(role, section, VIEW)
