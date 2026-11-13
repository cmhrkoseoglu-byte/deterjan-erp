"""Bakım: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.12).

İş emri görevi bugünkü gibi sorumlu role gider. Tartım ve şarj başlatma, kalibrasyon ve tank
temizliği durumunu Bakım yetkisi olmadan da okur. Bakım ayarlarının değerlerini Bakım'ı gören
herkes okuyabilir.
"""

from apps.core.access import (
    ANY_ROLE,
    CHANGE,
    VIEW,
    ReadScope,
    grant,
    register_module,
    register_readers,
    register_section,
)
from apps.core.roles import DOLUM, LABORATUVAR, PLANLAMA, URETIM, YONETIM

register_module("maintenance", "Bakım", order=120)

WORK_ORDERS = register_section(
    "maintenance.work_orders",
    "Bakım iş emirleri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Bakım iş emirleri.",
        CHANGE: "Kişinin kendi biriminin (sorumlu rol) iş emirlerinde işe başlar, parça ekler, "
        "tamamlar, iptal eder.",
    },
)
ANY_UNIT = register_section(
    "maintenance.any_unit",
    "Tüm birimlerin iş emirlerini yürütme",
    levels=(CHANGE,),
    help={CHANGE: "Sorumlu birim kuralının istisnası: her birimin iş emrini yürütür."},
    requires={CHANGE: [(WORK_ORDERS, CHANGE)]},
)
PLANS = register_section(
    "maintenance.plans",
    "Bakım planları ve iş emri açma",
    levels=(VIEW, CHANGE),
    help={VIEW: "Bakım planları.", CHANGE: "Plan açar ve düzenler, elle iş emri açar."},
)
BREAKDOWNS = register_section(
    "maintenance.breakdowns",
    "Arıza bildirimi",
    levels=(CHANGE,),
    help={CHANGE: "Arıza bildirir."},
    locked=(CHANGE,),
)
DOWNTIMES = register_section(
    "maintenance.downtimes",
    "Duruşlar",
    levels=(VIEW, CHANGE),
    help={VIEW: "Duruş kayıtları.", CHANGE: "Duruş başlatır ve bitirir."},
    read=ReadScope.ANY_ROLE,
)
CLEANINGS = register_section(
    "maintenance.cleanings",
    "Tank temizliği",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Tank temizliği kayıtları.",
        CHANGE: "Temizlik kaydeder; tamamlanmış temizlik iş emri açar.",
    },
)
CALIBRATION = register_section(
    "maintenance.calibration",
    "Kalibrasyon",
    levels=(VIEW,),
    help={VIEW: "Terazi kalibrasyon durumu."},
)
UNCLEANED = register_section(
    "maintenance.uncleaned",
    "Temizliksiz geçişler (D-14)",
    levels=(VIEW, CHANGE),
    help={VIEW: "Temizliksiz geçiş kayıtları.", CHANGE: "Temizliksiz geçişe izin verir."},
)
SETTINGS = register_section(
    "maintenance.settings",
    "Bakım ayarları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Kalibrasyon uyarı süresi ve iş emri açma süresi.",
        CHANGE: "Bakım ayarlarını değiştirir.",
    },
)

register_readers("maintenance.maintenanceworkorder", WORK_ORDERS)

UNITS = (URETIM, DOLUM, LABORATUVAR, PLANLAMA, YONETIM)
for role in UNITS:
    grant(role, WORK_ORDERS, VIEW, CHANGE)
    grant(role, PLANS, VIEW)
    grant(role, DOWNTIMES, VIEW, CHANGE)
    grant(role, CLEANINGS, VIEW)
    grant(role, CALIBRATION, VIEW)
    grant(role, UNCLEANED, VIEW)
for role in (URETIM, DOLUM, LABORATUVAR, YONETIM):
    grant(role, PLANS, CHANGE)
grant(YONETIM, ANY_UNIT, CHANGE)
grant(ANY_ROLE, BREAKDOWNS, CHANGE)
for role in (URETIM, YONETIM):
    grant(role, CLEANINGS, CHANGE)
grant(LABORATUVAR, UNCLEANED, CHANGE)
grant(YONETIM, SETTINGS, VIEW, CHANGE)
