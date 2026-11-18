"""Cari hesaplar: yetki bölümleri ve rol paketleri (docs/plan/cari-hesaplar.md §2.4).

Görür liste ve ekstreyi açar; tutarlar ayrıca "Fiyatları görür" ister (göremeyene tutar alanları
yanıtta yoktur). Değiştirir elle kayıt girer, kayıt iptal eder ve eksik fiyatı tamamlar.
"""

from typing import Any

from apps.core.access import (
    CHANGE,
    PRICES,
    VIEW,
    grant,
    register_audit_model,
    register_module,
    register_section,
)
from apps.core.roles import SATIN_ALMA, SEVKIYAT, YONETIM

register_module("ledger", "Cari hesaplar", order=105)

CUSTOMERS = register_section(
    "ledger.customers",
    "Müşteri carileri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Müşteri cari listesi, yaşlandırma ve ekstre; tutarlar Fiyatları görür ile.",
        CHANGE: "Tahsilat, iade dekontu, borç/alacak dekontu ve açılış bakiyesi girer, kayıt "
        "iptal eder, fiyatı eksik sevkiyata fiyat girer.",
    },
    requires={CHANGE: [(PRICES, VIEW)]},
)
SUPPLIERS = register_section(
    "ledger.suppliers",
    "Tedarikçi carileri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Tedarikçi cari listesi, yaşlandırma ve ekstre; tutarlar Fiyatları görür ile.",
        CHANGE: "Ödeme, borç/alacak dekontu ve açılış bakiyesi girer, kayıt iptal eder.",
    },
    requires={CHANGE: [(PRICES, VIEW)]},
)

grant(YONETIM, CUSTOMERS, VIEW, CHANGE)
grant(YONETIM, SUPPLIERS, VIEW, CHANGE)
grant(SATIN_ALMA, SUPPLIERS, VIEW, CHANGE)
grant(SEVKIYAT, CUSTOMERS, VIEW)


# Denetim günlüğü: cari hareket ve cari fiyatı tutar taşır (Fiyatları görür); müşteri carisinin
# kaydı Müşteri carileri, tedarikçininki Tedarikçi carileri ister.
def _entry_rows(side: str) -> Any:
    def rows() -> Any:
        from django.db.models import Q

        from apps.ledger.models import LedgerEntry

        ids = LedgerEntry.objects.filter(**{f"{side}__isnull": False}).values("pk")
        return Q(object_id__in=ids)

    return rows


register_audit_model("ledger.ledgerentry", requires=[PRICES])
register_audit_model("ledger.ledgerentry", requires=[CUSTOMERS], rows=_entry_rows("customer"))
register_audit_model("ledger.ledgerentry", requires=[SUPPLIERS], rows=_entry_rows("supplier"))
register_audit_model("ledger.shipmentlineprice", requires=[PRICES, CUSTOMERS])
