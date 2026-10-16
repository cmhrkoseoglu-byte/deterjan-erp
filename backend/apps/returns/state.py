"""İade durum makinesi:

    DRAFT ─► RECEIVED ─► CLOSED
      └────► CANCELLED

Teslim alınan iade iptal edilmez (stok hareketi yazılmıştır); her satır sonuçlanınca kapanır.
"""

from apps.core.state import StateMachine


class CustomerReturnStateMachine(StateMachine):
    name = "customer_return"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["RECEIVED", "CANCELLED"],
        "RECEIVED": ["CLOSED"],
        "CLOSED": [],
        "CANCELLED": [],
    }
    labels = {
        "DRAFT": "Taslak",
        "RECEIVED": "Teslim alındı",
        "CLOSED": "Sonuçlandı",
        "CANCELLED": "İptal",
    }


customer_return_states = CustomerReturnStateMachine()
