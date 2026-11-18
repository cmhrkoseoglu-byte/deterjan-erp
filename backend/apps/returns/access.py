"""İadeler: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.8).

İade edilen malın akıbeti, iade numunesindeki kalite kararıdır (quality.samples).
"""

from apps.core.access import (
    CHANGE,
    VIEW,
    ReadScope,
    grant,
    register_module,
    register_open_records,
    register_readers,
    register_section,
)
from apps.core.roles import DEPO, LABORATUVAR, SEVKIYAT, YONETIM

register_module("returns", "İadeler", order=80)

RETURNS = register_section(
    "returns.returns",
    "İade kayıtları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "İade listesi ve sayfası.",
        CHANGE: "İade açar, taslağı düzenler, taslağı iptal eder.",
    },
    read=ReadScope.OPEN,
)
RECEIVING = register_section(
    "returns.receiving",
    "İade teslim alma ve imha",
    levels=(CHANGE,),
    help={CHANGE: "İadeyi teslim alır, imha eder."},
    requires={CHANGE: [(RETURNS, VIEW)]},
)
# Açık kayıtlar kapatılınca etkilenen öteki ekranlar (plan §5.1, §5.3; kaydetme özetindeki
# uyarı ve Yetkiler ekranındaki satır notu). Sahip PR'da gözden geçirir.
OPEN_RECORDS = register_open_records(
    "returns",
    affects=(
        "İade yorumlarında bu kişiden bahsedilemez, bahsedilse de bildirim almaz.",
        "Görevlerdeki, bildirimlerdeki ve aramadaki iade bağlantıları değişmez: bunlar zaten "
        "İadeler'de Görür ister.",
        "Cari ekstresindeki iade bağlantıları düz metin olur.",
    ),
)

register_readers("returns.customerreturn", RETURNS)

for role in (SEVKIYAT, LABORATUVAR, DEPO, YONETIM):
    grant(role, RETURNS, VIEW)
grant(SEVKIYAT, RETURNS, CHANGE)
for role in (SEVKIYAT, DEPO):
    grant(role, RECEIVING, CHANGE)
