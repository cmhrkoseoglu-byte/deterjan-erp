"""Üretim: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.4).

Hazırlama sayfası bugünkü gibi Üretim'in herhangi bir bölümünde Görür ile salt okunur açılır;
okutma ve "hazır" düğmeleri Malzeme hazırlama: Değiştirir ister.
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
from apps.core.roles import DEPO, PLANLAMA, URETIM, YONETIM

register_module("production", "Üretim", order=40)

ORDERS = register_section(
    "production.orders",
    "Üretim emirleri",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Emir listesi ve sayfası.",
        CHANGE: "Emir açar, taslağı düzenler, taslağı iptal eder, yeniden işleme emri açar, emri "
        "elle tamamlar.",
        APPROVE: "Emri onaylar, onaylı emri iptal eder.",
    },
    read=ReadScope.OPEN,
)
PREP = register_section(
    "production.prep",
    "Malzeme hazırlama",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Hazırlama sekmesi.",
        CHANGE: "Hazırlığı başlatır, malzeme okutur, hazır bildirir.",
    },
    read=ReadScope.OPEN,
)
BATCHES = register_section(
    "production.batches",
    "Şarj ve tartım",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Şarjlar ve tartımlar.",
        CHANGE: "Şarj başlatır, tartar, bitirir; tartım yapılmamış şarjı iptal eder.",
    },
    read=ReadScope.OPEN,
)
OPEN_RECORDS = register_open_records("production")

register_readers("production.productionorder", ORDERS, PREP, BATCHES)
register_readers("production.productionbatch", ORDERS, PREP, BATCHES)

for role in (URETIM, PLANLAMA, DEPO, YONETIM):
    grant(role, ORDERS, VIEW)
    grant(role, BATCHES, VIEW)
grant(PLANLAMA, ORDERS, CHANGE, APPROVE)
grant(DEPO, PREP, VIEW, CHANGE)
grant(URETIM, BATCHES, CHANGE)
