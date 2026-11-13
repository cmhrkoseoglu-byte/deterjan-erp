"""Canlıya geçiş: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.16).

Sorun bildirmek ve kişinin kendi bildirdiklerini görmesi herkese açıktır; bütün bildirimlerin
listesi yalnız sistem yöneticisinindir.
"""

from apps.core.access import CHANGE, VIEW, grant, register_module, register_section
from apps.core.roles import DEPO, PLANLAMA, YONETIM

register_module("golive", "Canlıya geçiş", order=160)

READINESS = register_section(
    "golive.readiness",
    "Hazırlık listesi",
    levels=(VIEW,),
    help={VIEW: "Canlıya geçiş hazırlık kontrol listesi."},
)
SETTINGS = register_section(
    "golive.settings",
    "Canlıya geçiş ayarları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Canlı başlangıç tarihi.",
        CHANGE: "Tarihi kaydeder ya da kaldırır (o günden açılış stoku yüklenemez).",
    },
)
COMPARISONS = register_section(
    "golive.comparisons",
    "Stok karşılaştırma",
    levels=(VIEW, CHANGE),
    help={VIEW: "Stok karşılaştırmaları.", CHANGE: "Yeni karşılaştırma yükler (Excel)."},
)
PROBLEMS = register_section(
    "golive.problems",
    "Sorun bildirimleri listesi",
    levels=(VIEW,),
    help={VIEW: "Bütün sorun bildirimleri (yalnız sistem yöneticisi)."},
    admin_only=(VIEW,),
)

for role in (YONETIM, PLANLAMA, DEPO):
    grant(role, READINESS, VIEW)
    grant(role, SETTINGS, VIEW)
    grant(role, COMPARISONS, VIEW)
grant(YONETIM, SETTINGS, CHANGE)
for role in (DEPO, YONETIM):
    grant(role, COMPARISONS, CHANGE)
