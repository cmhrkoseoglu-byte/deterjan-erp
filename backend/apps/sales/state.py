"""Satış siparişi durum makinesi (Faz 3, Adım 3.1).

    DRAFT ─► CONFIRMED ─► PARTIALLY_SHIPPED ─► SHIPPED ─► CLOSED
      │          │  └───────────────────────────────┘            ▲
      │          │                     └─────────────────────────┘
      └──────────┴──► CANCELLED

- Onayda FEFO ile rezervasyon yapılır; iptal ve kapanışta aktif rezervasyonlar bırakılır.
- PARTIALLY_SHIPPED / SHIPPED geçişlerini sevkiyat (Adım 3.2) yapar.
- Kısmen sevk edilmiş sipariş kalan miktar beklenmeden kapatılabilir (CLOSED).
"""

from apps.core.state import StateMachine


class SalesOrderStateMachine(StateMachine):
    name = "sales_order"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["CONFIRMED", "CANCELLED"],
        "CONFIRMED": ["PARTIALLY_SHIPPED", "SHIPPED", "CANCELLED"],
        "PARTIALLY_SHIPPED": ["SHIPPED", "CLOSED"],
        "SHIPPED": ["CLOSED"],
        "CLOSED": [],
        "CANCELLED": [],
    }
    labels = {
        "DRAFT": "Taslak",
        "CONFIRMED": "Onaylandı",
        "PARTIALLY_SHIPPED": "Kısmen sevk edildi",
        "SHIPPED": "Sevk edildi",
        "CLOSED": "Kapandı",
        "CANCELLED": "İptal",
    }


sales_order_states = SalesOrderStateMachine()


class ShipmentStateMachine(StateMachine):
    """Sevkiyat (Adım 3.2): PLANNED ─► PICKING ─► LOADED ─► DISPATCHED; sevk edilmeden iptal.

    İlk lot okutulunca PICKING; depo "Yükleme tamam" ile LOADED; sevkiyat "Sevki onayla" ile
    DISPATCHED (stoktan çıkış). İptalde toplanan lotlar geldikleri yere döner."""

    name = "shipment"
    initial = "PLANNED"
    transitions = {
        "PLANNED": ["PICKING", "CANCELLED"],
        "PICKING": ["LOADED", "CANCELLED"],
        "LOADED": ["DISPATCHED", "CANCELLED"],
        "DISPATCHED": [],
        "CANCELLED": [],
    }
    labels = {
        "PLANNED": "Planlandı",
        "PICKING": "Toplanıyor",
        "LOADED": "Yüklendi",
        "DISPATCHED": "Sevk edildi",
        "CANCELLED": "İptal",
    }


shipment_states = ShipmentStateMachine()
