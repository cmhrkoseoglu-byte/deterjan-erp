"""Maliyet: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.11).

Bölümlerin hepsi Maliyetleri görür'ü ister. Personel maliyeti ücret ve bordro bilgisini gösterdiği
için Ücretler ve Bordro: Görür'ü de ister ve yalnız yönetim rolündekilere verilebilir (KVKK).
"""

from apps.core.access import (
    ALL,
    CHANGE,
    COSTS,
    VIEW,
    grant,
    register_module,
    register_section,
)
from apps.core.roles import YONETIM
from apps.personnel.access import PAYROLL, WAGES

register_module("costing", "Maliyet", order=110)

LOT_COSTS = register_section(
    "costing.lot_costs",
    "Lot maliyetleri ve maliyet raporları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Lot maliyeti ve maliyet raporları.",
        CHANGE: "Maliyeti hesaplar.",
    },
    requires={ALL: [(COSTS, VIEW)]},
)
RATES = register_section(
    "costing.rates",
    "Gider oranları ve standart maliyetler",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Gider oranları ve standart maliyetler.",
        CHANGE: "Oran ekler ve düzeltir; standart maliyet ekler, düzeltir, pasife alır.",
    },
    requires={ALL: [(COSTS, VIEW)]},
)
PERSONNEL_COST = register_section(
    "costing.personnel_cost",
    "Personel maliyeti",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Personel maliyeti sekmesi ve Excel'i (açılışı bordro erişim günlüğüne yazılır).",
        CHANGE: "Birimlerin maliyet aşamasını değiştirir; onaylı aydan işçilik oranı ekler "
        "(Gider oranları: Değiştirir de ister).",
    },
    requires={ALL: [(COSTS, VIEW), (WAGES, VIEW), (PAYROLL, VIEW)]},
    restricted_to_role=YONETIM,
)

grant(YONETIM, LOT_COSTS, VIEW, CHANGE)
grant(YONETIM, RATES, VIEW, CHANGE)
grant(YONETIM, PERSONNEL_COST, VIEW, CHANGE)
