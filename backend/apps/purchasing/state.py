"""Satın alma durum makineleri (Faz 4, Adım 4.2).

Sipariş:

    DRAFT ─► PENDING_APPROVAL ─► APPROVED ─► SENT ─► PARTIALLY_RECEIVED ─► RECEIVED
      │   └──────────────────────►  │  └──────────────┴─► (mal kabulle)       ▲
      │            │ (geri)         └──────────────────────────────────────────┘
      └────────────┴──── CANCELLED (mal kabul gelmeden önce: DRAFT, PENDING_APPROVAL,
                                    APPROVED, SENT)

- Onay limiti (D-13): limit girilmiş ve TL tutar limit içindeyse satin_alma doğrudan onaylar;
  değilse "Yönetim onayına gönder" (PENDING_APPROVAL) ve yonetim onaylar ya da taslağa geri yollar.
- PARTIALLY_RECEIVED / RECEIVED geçişlerini mal kabul kaydı yapar; kısmen teslim alınmış sipariş
  "Kalanı kapat" ile gerekçeli olarak RECEIVED olur.

Talep: OPEN ─► ORDERED (siparişe bağlanınca); OPEN ─► CANCELLED. Sipariş iptal edilir ya da
satırdan çıkarılırsa talep yeniden OPEN olur.
"""

from apps.core.state import StateMachine


class PurchaseOrderStateMachine(StateMachine):
    name = "purchase_order"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["PENDING_APPROVAL", "APPROVED", "CANCELLED"],
        "PENDING_APPROVAL": ["APPROVED", "DRAFT", "CANCELLED"],
        "APPROVED": ["SENT", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"],
        "SENT": ["PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"],
        "PARTIALLY_RECEIVED": ["RECEIVED"],
        "RECEIVED": [],
        "CANCELLED": [],
    }
    labels = {
        "DRAFT": "Taslak",
        "PENDING_APPROVAL": "Yönetim onayında",
        "APPROVED": "Onaylandı",
        "SENT": "Gönderildi",
        "PARTIALLY_RECEIVED": "Kısmen teslim alındı",
        "RECEIVED": "Teslim alındı",
        "CANCELLED": "İptal",
    }


purchase_order_states = PurchaseOrderStateMachine()


class PurchaseRequestStateMachine(StateMachine):
    name = "purchase_request"
    initial = "OPEN"
    transitions = {
        "OPEN": ["ORDERED", "CANCELLED"],
        "ORDERED": ["OPEN"],
        "CANCELLED": [],
    }
    labels = {"OPEN": "Açık", "ORDERED": "Siparişe bağlandı", "CANCELLED": "İptal"}


purchase_request_states = PurchaseRequestStateMachine()
