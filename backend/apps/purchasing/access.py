"""Satın alma: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.10).

D-13: Limit üstü sipariş onayı her tutarı onaylar; Satın alma siparişleri: Onaylar yalnız limit
girilmişse ve tutar limit içindeyse onaylar. Satın alma ayarlarının değerlerini sipariş yazan kişi
de okuyabilir (sekmeyi görmez).
"""

from apps.core.access import (
    APPROVE,
    CHANGE,
    PRICES,
    VIEW,
    grant,
    register_audit_model,
    register_module,
    register_readers,
    register_section,
)
from apps.core.roles import DEPO, PLANLAMA, SATIN_ALMA, URETIM, YONETIM

register_module("purchasing", "Satın alma", order=100)

REQUESTS = register_section(
    "purchasing.requests",
    "Satın alma talepleri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Talepler sekmesi.",
        CHANGE: "Talep açar; kişi kendi talebini düzenler ve iptal eder.",
    },
)
SUGGESTIONS = register_section(
    "purchasing.suggestions",
    "Talep önerileri",
    levels=(VIEW,),
    help={VIEW: "Öneriler sekmesi."},
)
ORDERS = register_section(
    "purchasing.orders",
    "Satın alma siparişleri",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Siparişler (fiyatlar yalnız Fiyatları görür ile).",
        CHANGE: "Sipariş yazar, yönetim onayına ve tedarikçiye gönderir, kalanı kapatır, taslağı "
        "ya da onay bekleyeni iptal eder, başkasının talebini düzenler ve iptal eder.",
        APPROVE: "D-13 limiti içinde onaylar, onaylı siparişi iptal eder.",
    },
    requires={CHANGE: [(PRICES, VIEW)], APPROVE: [(PRICES, VIEW)]},
)
OVER_LIMIT = register_section(
    "purchasing.over_limit",
    "Limit üstü sipariş onayı",
    levels=(APPROVE,),
    help={APPROVE: "Limit üstü ya da limit girilmemişken onaylar; taslağa geri gönderir."},
    requires={APPROVE: [(ORDERS, VIEW), (PRICES, VIEW)]},
)
DELIVERIES = register_section(
    "purchasing.deliveries",
    "Beklenen teslimatlar ve siparişten mal kabul",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Açık sipariş satırları (fiyatsız) ve mal kabullerin sipariş bağlantıları.",
        CHANGE: "Siparişten mal kabul taslağı açar.",
    },
    requires={CHANGE: [(ORDERS, VIEW)]},
)
PERFORMANCE = register_section(
    "purchasing.performance",
    "Tedarikçi performansı",
    levels=(VIEW,),
    help={VIEW: "Tedarikçi performans raporu."},
)
SETTINGS = register_section(
    "purchasing.settings",
    "Satın alma ayarları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Onay limiti ve fazla teslim toleransı.",
        CHANGE: "Onay limitini ve fazla teslim toleransını değiştirir.",
    },
)

register_readers("purchasing.purchaseorder", ORDERS)

for role in (PLANLAMA, DEPO, URETIM, SATIN_ALMA, YONETIM):
    grant(role, REQUESTS, VIEW, CHANGE)
for role in (SATIN_ALMA, YONETIM, PLANLAMA):
    grant(role, SUGGESTIONS, VIEW)
for role in (SATIN_ALMA, YONETIM, DEPO):
    grant(role, ORDERS, VIEW)
    grant(role, DELIVERIES, VIEW, CHANGE)
for role in (SATIN_ALMA, YONETIM):
    grant(role, ORDERS, CHANGE, APPROVE)
    grant(role, PERFORMANCE, VIEW)
grant(YONETIM, OVER_LIMIT, APPROVE)
grant(YONETIM, SETTINGS, VIEW, CHANGE)

# Denetim günlüğü (plan §5.6, §8 madde 7): siparişin tutarları (silinen satırın içindekiler dahil)
# ve eski onaya gönderme ve onay notlarındaki tutarlar Fiyatları görür'e bağlıdır. Alan adları
# serializer'ın `PRICE_FIELDS`'iyle, not kalıbı kayıt geçmişininkiyle aynıdır (testi denetler).
ORDER_PRICE_FIELDS = (
    "unit_price",
    "line_total",
    "total",
    "total_try",
    "exchange_rate",
    "approval_total_try",
    "approval_limit_try",
)
AMOUNT_NOTE = r"^(Tutar [0-9.]+,[0-9]{2} TL|Onay: tutar [0-9.]+,[0-9]{2} TL \(kur .*)$"

register_audit_model(
    "purchasing.purchaseorder",
    requires=[PRICES],
    fields=ORDER_PRICE_FIELDS,
    nested=True,
    note=AMOUNT_NOTE,
)
register_audit_model("purchasing.purchaseorderline", requires=[PRICES], fields=ORDER_PRICE_FIELDS)
