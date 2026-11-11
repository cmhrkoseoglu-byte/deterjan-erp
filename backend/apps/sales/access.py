"""Sevkiyat: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.7).

Satış fiyatları bir hakka bağlı değildir: siparişi gören fiyatını da görür (karar 6). Toplama
sayfası ve toplama önerisi bugünkü gibi Sevkiyatlar ve irsaliye: Görür ile de salt okunur açılır.
"""

from apps.core.access import (
    APPROVE,
    CHANGE,
    VIEW,
    grant,
    register_field_openers,
    register_module,
    register_readers,
    register_section,
)
from apps.core.roles import DEPO, PLANLAMA, SEVKIYAT, YONETIM

register_module("sales", "Sevkiyat", order=70)

ORDERS = register_section(
    "sales.orders",
    "Satış siparişleri",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Siparişler ve fiyatları, Müşteriler sekmesi ve müşteri kartı.",
        CHANGE: "Taslak açar, rezervasyon yapar, siparişi kapatır, taslağı iptal eder.",
        APPROVE: "Siparişi onaylar ve rezerve eder, onaylı siparişi iptal eder.",
    },
)
SHIPMENTS = register_section(
    "sales.shipments",
    "Sevkiyatlar ve irsaliye",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Sevkiyatlar ve irsaliye PDF'i.",
        CHANGE: "Sevkiyat planlar, araç ve şoför bilgisini girer, sevk öncesi iptal eder.",
        APPROVE: "Sevki onaylar.",
    },
)
PICKING = register_section(
    "sales.picking",
    "Toplama ve yükleme",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Toplama sekmesi.",
        CHANGE: "Lot okutur, okutmayı geri alır, yüklemeyi tamamlar.",
    },
)
SHIPPED_LOTS = register_section(
    "sales.shipped_lots",
    "Müşteriye sevk edilen lotlar",
    levels=(VIEW,),
    help={VIEW: "Müşteri kartındaki sevk edilen lotlar paneli."},
)

register_readers("sales.salesorder", ORDERS)
register_readers("sales.shipment", SHIPMENTS, PICKING)
# Sevkiyat'ın Müşteriler sekmesi ve müşteri kartı, siparişleri gören kişide tam kalır (plan §3.1).
register_field_openers("masterdata.customer.contact", ORDERS)

for role in (SEVKIYAT, YONETIM, PLANLAMA, DEPO):
    grant(role, ORDERS, VIEW)
    grant(role, SHIPMENTS, VIEW)
for role in (SEVKIYAT, YONETIM):
    grant(role, ORDERS, CHANGE, APPROVE)
    grant(role, SHIPPED_LOTS, VIEW)
grant(SEVKIYAT, SHIPMENTS, CHANGE, APPROVE)
grant(DEPO, PICKING, VIEW, CHANGE)
