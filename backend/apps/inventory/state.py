"""Stok modülü durum makineleri.

Lot (kalite kararı, Faz 1'de laboratuvarın elle verdiği):

    QUARANTINE ─► RELEASED ─► BLOCKED ─► RELEASED
        │  └────► BLOCKED       └──────► REJECTED
        └───────► REJECTED

Reddedilen lot son durumdur (iade/imha Faz 4). Mal kabul ve sayım düzeltme:

    DRAFT ─► POSTED
      └────► CANCELLED

Kaydedilmiş belge iptal edilmez; düzeltme sayım düzeltmesi ya da ters kayıtla yapılır.
"""

from apps.core.state import StateMachine


class LotStateMachine(StateMachine):
    name = "lot"
    initial = "QUARANTINE"
    transitions = {
        "QUARANTINE": ["RELEASED", "REJECTED", "BLOCKED"],
        "RELEASED": ["BLOCKED"],
        "BLOCKED": ["RELEASED", "REJECTED"],
        "REJECTED": [],
    }
    labels = {
        "QUARANTINE": "Karantina",
        "RELEASED": "Serbest",
        "REJECTED": "Reddedildi",
        "BLOCKED": "Bloke",
    }


class PostableDocumentStateMachine(StateMachine):
    initial = "DRAFT"
    transitions = {"DRAFT": ["POSTED", "CANCELLED"], "POSTED": [], "CANCELLED": []}
    labels = {"DRAFT": "Taslak", "POSTED": "Kaydedildi", "CANCELLED": "İptal"}


lot_states = LotStateMachine()
goods_receipt_states = PostableDocumentStateMachine(name="goods_receipt")
stock_adjustment_states = PostableDocumentStateMachine(name="stock_adjustment")
