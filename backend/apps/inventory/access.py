"""Depo ve stok: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.3).

Lotu serbest bırakma ve reddetme yalnız kalite kararıyla olur (quality.samples).
"""

from apps.core.access import (
    APPROVE,
    CHANGE,
    COSTS,
    EVERYONE,
    PRICES,
    VIEW,
    ReadScope,
    grant,
    register_audit_model,
    register_module,
    register_open_records,
    register_readers,
    register_section,
)
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

register_module("inventory", "Depo ve stok", order=30)

STOCK = register_section(
    "inventory.stock",
    "Stok sorgu, hareketler ve transfer",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Stok ve hareket listeleri.",
        CHANGE: "Transfer, ters kayıt ve açılış stoku içe aktarma.",
    },
    locked=(VIEW,),
)
LOTS = register_section(
    "inventory.lots",
    "Lotlar",
    levels=(VIEW,),
    help={VIEW: "Lot sayfası, soy ağacı, lot etiketi ve analiz sertifikası PDF'i."},
    locked=(VIEW,),
)
PALLETS = register_section(
    "inventory.pallets",
    "Palet etiketleri (SSCC)",
    levels=(VIEW, CHANGE),
    help={VIEW: "Palet listesi.", CHANGE: "Palet oluşturur."},
    locked=(VIEW,),
)
RECEIPTS = register_section(
    "inventory.receipts",
    "Mal kabul",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Mal kabul belgeleri (fiyatsız).",
        CHANGE: "Hazırlar, taslağı düzenler, kaydeder ve stoka alır, taslağı iptal eder.",
    },
    read=ReadScope.OPEN,
)
RECEIPT_PRICES = register_section(
    "inventory.receipt_prices",
    "Mal kabul fiyat ve masrafları",
    levels=(CHANGE,),
    help={CHANGE: "Birim fiyat, para birimi, kur ve ek masraf girer ve düzeltir."},
    requires={CHANGE: [(RECEIPTS, VIEW), (PRICES, VIEW)]},
)
ADJUSTMENTS = register_section(
    "inventory.adjustments",
    "Sayım düzeltme",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Sayım düzeltme belgeleri.",
        CHANGE: "Hazırlar, taslağı düzenler, taslağı iptal eder.",
        APPROVE: "Kaydeder ve stoka alır (D-3).",
    },
    read=ReadScope.OPEN,
)
LOT_BLOCK = register_section(
    "inventory.lot_block",
    "Lot bloke etme",
    levels=(APPROVE,),
    help={APPROVE: "Lotu gerekçeyle bloke eder."},
)
MANUAL_RELEASE = register_section(
    "inventory.manual_release",
    "Elle serbest bırakma (D-5)",
    levels=(APPROVE,),
    help={APPROVE: "Lotu kalite kararı olmadan serbest bırakır (yalnız sistem yöneticisi)."},
    admin_only=(APPROVE,),
)
# Açık kayıtlar kapatılınca etkilenen öteki ekranlar (plan §5.1, §5.3; kaydetme özetindeki
# uyarı ve Yetkiler ekranındaki satır notu). Sahip PR'da gözden geçirir.
OPEN_RECORDS = register_open_records(
    "inventory",
    affects=(
        "Lot sayfasındaki, satın alma sipariş sayfasındaki, izlenebilirlikteki ve cari "
        "ekstresindeki mal kabul bağlantıları düz metin olur.",
    ),
)

register_readers("inventory.lot", LOTS)
register_readers("inventory.goodsreceipt", RECEIPTS)
register_readers("inventory.stockadjustment", ADJUSTMENTS)

grant(EVERYONE, STOCK, VIEW)
grant(DEPO, STOCK, CHANGE)
grant(EVERYONE, LOTS, VIEW)
grant(EVERYONE, PALLETS, VIEW)
for role in (DEPO, DOLUM, SEVKIYAT, URETIM):
    grant(role, PALLETS, CHANGE)
for role in (DEPO, PLANLAMA, YONETIM, SATIN_ALMA, LABORATUVAR):
    grant(role, RECEIPTS, VIEW)
grant(DEPO, RECEIPTS, CHANGE)
for role in (SATIN_ALMA, YONETIM):
    grant(role, RECEIPT_PRICES, CHANGE)
grant(DEPO, ADJUSTMENTS, VIEW, CHANGE, APPROVE)
grant(YONETIM, ADJUSTMENTS, VIEW)
grant(LABORATUVAR, LOT_BLOCK, APPROVE)

# Denetim günlüğü (plan §5.6, §8 madde 7): lot maliyeti Maliyetleri görür'e, mal kabul fiyatları,
# masrafları ve fiyat düzeltmesi notları (lot ve satır kayıtlarına geçen kopyaları dahil) Fiyatları
# görür'e bağlıdır. Alan adları servis ve serializer'daki listelerle aynıdır (testi denetler).
LOT_COST_FIELDS = ("unit_cost", "cost_is_estimated")
RECEIPT_PRICE_FIELDS = ("unit_price", "currency", "exchange_rate")
PRICE_CORRECTION_NOTE = r"^Fiyat düzeltmesi:"

register_audit_model(
    "inventory.lot", requires=[COSTS], fields=LOT_COST_FIELDS, note_with_fields=True
)
register_audit_model(
    "inventory.goodsreceipt",
    requires=[PRICES],
    fields=(*RECEIPT_PRICE_FIELDS, "amount", "extra_cost"),
    nested=True,
    note=PRICE_CORRECTION_NOTE,
)
register_audit_model(
    "inventory.goodsreceiptline",
    requires=[PRICES],
    fields=RECEIPT_PRICE_FIELDS,
    note_with_fields=True,
)
# Ek masrafın kendisi (adı tutarı taşır) bütünüyle.
register_audit_model("inventory.goodsreceiptextracost", requires=[PRICES])
