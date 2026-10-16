"""Bakım iş emri durum makinesi (Faz 4, Adım 4.4).

OPEN ─► IN_PROGRESS ─► COMPLETED
  │          │
  ├──────────┴──────► CANCELLED
  └────────────────► COMPLETED (tek adımda kayıt, ör. temizlik)
"""

from apps.core.state import StateMachine


class WorkOrderStateMachine(StateMachine):
    name = "maintenance_work_order"
    initial = "OPEN"
    transitions = {
        "OPEN": ["IN_PROGRESS", "COMPLETED", "CANCELLED"],
        "IN_PROGRESS": ["COMPLETED", "CANCELLED"],
        "COMPLETED": [],
        "CANCELLED": [],
    }
    labels = {
        "OPEN": "Açık",
        "IN_PROGRESS": "Yapılıyor",
        "COMPLETED": "Tamamlandı",
        "CANCELLED": "İptal",
    }


work_order_states = WorkOrderStateMachine()
