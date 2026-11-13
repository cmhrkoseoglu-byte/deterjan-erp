"""Ana veriler: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.1)."""

from apps.core.access import (
    CHANGE,
    VIEW,
    ReadScope,
    grant,
    register_field_openers,
    register_module,
    register_open_records,
    register_section,
)
from apps.core.roles import PLANLAMA, YONETIM

register_module("masterdata", "Ana veriler", order=10)

CARDS = register_section(
    "masterdata.cards",
    "Ana veri kartları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Malzeme, tedarikçi, müşteri, depo, lokasyon, ekipman, kategori ve birim dönüşümü "
        "kartları.",
        CHANGE: "Kart açar ve düzenler, Excel'den içe aktarır, GTIN önerisi alır, pasife alır.",
    },
    read=ReadScope.SHARED,
)
REFERENCE = register_section(
    "masterdata.reference",
    "Birimler, yazıcılar ve etiket ayarları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Birim, yazıcı ve etiket ayarı sekmeleri (salt okunur).",
        CHANGE: "Birim, yazıcı ve etiket ayarlarını değiştirir (yalnız sistem yöneticisi).",
    },
    read=ReadScope.SHARED,
    admin_only=(CHANGE,),
)
COMPANY = register_section(
    "masterdata.company",
    "Firma bilgileri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Ticari unvan, adres, vergi ve sicil bilgileri.",
        CHANGE: "Firma bilgilerini düzenler.",
    },
    read=ReadScope.SHARED,
)
# Müşteri ve tedarikçinin vergi, adres ve iletişim bilgileri Ana veriler'in açık kayıtlarıdır
# (plan §3.1). Kapatılan kişi kartı yalnız tam görebilen bir bölümle görür; sales müşteri kartı
# için kendi bölümünü ekler.
OPEN_RECORDS = register_open_records("masterdata")
register_field_openers("masterdata.customer.contact", CARDS)
register_field_openers("masterdata.supplier.contact", CARDS)

grant(PLANLAMA, CARDS, VIEW, CHANGE)
grant(YONETIM, CARDS, VIEW)
grant(PLANLAMA, REFERENCE, VIEW)
grant(YONETIM, REFERENCE, VIEW)
grant(PLANLAMA, COMPANY, VIEW)
grant(YONETIM, COMPANY, VIEW, CHANGE)
