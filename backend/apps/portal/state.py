"""Sipariş talebi durum makinesi (docs/plan/musteri-siparis-takibi.md §4.4).

SUBMITTED ─► CONVERTED   (sevkiyat siparişe çevirir)
    │──────► REJECTED    (sevkiyat gerekçeyle reddeder)
    └──────► WITHDRAWN   (müşteri geri çeker)
"""

from apps.core.state import StateMachine


class OrderRequestStateMachine(StateMachine):
    name = "order_request"
    initial = "SUBMITTED"
    transitions = {
        "SUBMITTED": ["CONVERTED", "REJECTED", "WITHDRAWN"],
        "CONVERTED": [],
        "REJECTED": [],
        "WITHDRAWN": [],
    }
    labels = {
        "SUBMITTED": "Gönderildi",
        "CONVERTED": "Siparişe çevrildi",
        "REJECTED": "Reddedildi",
        "WITHDRAWN": "Geri çekildi",
    }


order_request_states = OrderRequestStateMachine()
