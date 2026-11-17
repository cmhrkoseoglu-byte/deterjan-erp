"""Dolum: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.6).

Ambalaj hazırlama sayfası bugünkü gibi Dolum'un herhangi bir bölümünde Görür ile salt okunur
açılır.
"""

from apps.core.access import (
    APPROVE,
    CHANGE,
    VIEW,
    ReadScope,
    grant,
    register_module,
    register_open_records,
    register_readers,
    register_section,
)
from apps.core.roles import DEPO, DOLUM, PLANLAMA, YONETIM

register_module("filling", "Dolum", order=60)

ORDERS = register_section(
    "filling.orders",
    "Dolum emirleri",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Dolum emirleri.",
        CHANGE: "Emir açar, taslağı düzenler, taslağı iptal eder.",
        APPROVE: "Emri onaylar, onaylı emri iptal eder.",
    },
    read=ReadScope.OPEN,
)
PREP = register_section(
    "filling.prep",
    "Ambalaj hazırlama",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Hazırlama sekmesi.",
        CHANGE: "Hazırlığı başlatır, ambalaj okutur, hazır bildirir.",
    },
    read=ReadScope.OPEN,
)
RUNS = register_section(
    "filling.runs",
    "Dolum hattı",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Dolum partileri ve tüketim raporları.",
        CHANGE: "Parti başlatır, bulk tüketimini ve ambalaj okutmayı kaydeder, fire girer, partiyi "
        "bitirir, kaydı olmayan partiyi iptal eder, dolumu bitirir.",
    },
    read=ReadScope.OPEN,
)
SPECS = register_section(
    "filling.specs",
    "Ambalaj reçeteleri",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Ambalaj reçetesi sürümleri ve satırları.",
        CHANGE: "Ambalaj reçetesi açar ve düzenler.",
        APPROVE: "Ambalaj reçetesi sürümünü onaylar.",
    },
    read=ReadScope.OPEN,
)
# Fiilen yapılmamış dolumu geri alma (DECISIONS 2026-11-14): yalnız admin ve yönetim. Emri
# açamayan geri alamasın diye Dolum emirleri: Görür ön koşuldur.
REVERT = register_section(
    "filling.revert",
    "Dolum emrini geri alma",
    levels=(CHANGE,),
    help={
        CHANGE: "Fiilen yapılmamış dolumu geri alır: emrin stok hareketleri ters kayıtla geri "
        "alınır, partiler ve açık numuneler iptal edilir, emir iptal olur."
    },
    requires={CHANGE: [(ORDERS, VIEW)]},
)
OPEN_RECORDS = register_open_records("filling")

register_readers("filling.fillingorder", ORDERS, PREP, RUNS)
register_readers("filling.fillingrun", ORDERS, PREP, RUNS)
register_readers("filling.packagingspec", SPECS)

for role in (DOLUM, PLANLAMA, DEPO, YONETIM):
    grant(role, ORDERS, VIEW)
    grant(role, RUNS, VIEW)
    grant(role, SPECS, VIEW)
grant(PLANLAMA, ORDERS, CHANGE, APPROVE)
grant(DEPO, PREP, VIEW, CHANGE)
grant(DOLUM, RUNS, CHANGE)
grant(PLANLAMA, SPECS, CHANGE, APPROVE)
grant(YONETIM, REVERT, CHANGE)
