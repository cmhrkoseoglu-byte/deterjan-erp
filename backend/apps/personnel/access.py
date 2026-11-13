"""Personel: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.14).

Bütün bölümler yalnız yönetim rolündekilere verilebilir (KVKK).
"""

from apps.core.access import (
    ALL,
    APPROVE,
    CHANGE,
    VIEW,
    grant,
    register_module,
    register_section,
)
from apps.core.roles import YONETIM

register_module("personnel", "Personel", order=140)

CARDS = register_section(
    "personnel.cards",
    "Personel kartları ve özlük belgeleri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Personel kartları, özlük bilgileri ve belgeleri.",
        CHANGE: "Kart açar ve düzenler, belge ekler.",
    },
    restricted_to_role=YONETIM,
)
ATTENDANCE = register_section(
    "personnel.attendance",
    "Puantaj ve tatil takvimi",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Puantaj ve tatil takvimi.",
        CHANGE: "Gün ve aralık girişi, tatiller.",
        APPROVE: "Ayı onaylar ve yeniden açar.",
    },
    restricted_to_role=YONETIM,
)
WAGES = register_section(
    "personnel.wages",
    "Ücretler",
    levels=(VIEW, CHANGE),
    help={VIEW: "Ücret geçmişi.", CHANGE: "Ücret girer ve düzeltir."},
    restricted_to_role=YONETIM,
)
PAYROLL = register_section(
    "personnel.payroll",
    "Bordro",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Ön bordro, pusulalar, PDF ve Excel.",
        CHANGE: "Kalemler, devirler, dış bordro tutarları; yeniden açılan ayda karta geçirme.",
        APPROVE: "Onaylar, yeniden açar, onaylı bordronun ödeme tarihini düzeltir.",
    },
    requires={ALL: [(WAGES, VIEW)]},
    restricted_to_role=YONETIM,
)
SETTINGS = register_section(
    "personnel.settings",
    "Personel ayarları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Bordro parametreleri (asgari ücret, SGK oranları, vergi dilimleri) ve hafta tatili "
        "günleri.",
        CHANGE: "Bordro parametrelerini ve hafta tatili günlerini değiştirir.",
    },
    restricted_to_role=YONETIM,
)

grant(YONETIM, CARDS, VIEW, CHANGE)
grant(YONETIM, ATTENDANCE, VIEW, CHANGE, APPROVE)
grant(YONETIM, WAGES, VIEW, CHANGE)
grant(YONETIM, PAYROLL, VIEW, CHANGE, APPROVE)
grant(YONETIM, SETTINGS, VIEW, CHANGE)
