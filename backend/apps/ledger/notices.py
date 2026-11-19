"""Cari ekranlarında ve çıktılarında gösterilen dönem notu (DECISIONS 2026-11-20).

Tedarikçi carilerindeki bakiyeler 20.11.2026 itibarıyla sıfırlandı: her tedarikçi ve para birimi
için 19.11.2026 tarihli devir sıfırlama kaydı yazıldı (`close_supplier_balances`). Not, ön yüzde
`frontend/src/modules/ledger/strings.ts` içindeki `supplierNotice` ile aynı metindir.
"""

from datetime import date, timedelta

from apps.ledger.models import Side

SUPPLIER_BALANCE_START = date(2026, 11, 20)
SUPPLIER_CLOSING_DATE = SUPPLIER_BALANCE_START - timedelta(days=1)
SUPPLIER_NOTICE = (
    "Cari bakiyeler 20 Kasım 2026 itibarıyla sıfırdan başlatılmıştır. Gösterilen bakiye bu tarih "
    "ve sonrasındaki hareketlerden oluşur; önceki dönem kapatılmıştır."
)
SUPPLIER_CLOSING_DESCRIPTION = "Devir sıfırlama: 20.11.2026 öncesi bakiye kapatıldı"


def notice_for(side: str) -> str:
    """Carinin tarafına göre ekran ve çıktı notu (yoksa boş)."""
    return SUPPLIER_NOTICE if side == Side.SUPPLIER else ""
