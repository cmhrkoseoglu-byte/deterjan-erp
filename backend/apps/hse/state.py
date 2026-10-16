"""İSG durum makineleri (Faz 4, Adım 4.5).

Olay kaydı:  OPEN ─► INVESTIGATING ─► CLOSED
               │            │
               └────────────┴──────► CANCELLED

Atık kaydı:  RECORDED ─► CANCELLED
"""

from apps.core.state import StateMachine


class IncidentStateMachine(StateMachine):
    name = "incident"
    initial = "OPEN"
    transitions = {
        "OPEN": ["INVESTIGATING", "CANCELLED"],
        "INVESTIGATING": ["CLOSED", "CANCELLED"],
        "CLOSED": [],
        "CANCELLED": [],
    }
    labels = {
        "OPEN": "Açık",
        "INVESTIGATING": "İnceleniyor",
        "CLOSED": "Kapandı",
        "CANCELLED": "İptal",
    }


class WasteRecordStateMachine(StateMachine):
    name = "waste_record"
    initial = "RECORDED"
    transitions = {
        "RECORDED": ["CANCELLED"],
        "CANCELLED": [],
    }
    labels = {"RECORDED": "Kaydedildi", "CANCELLED": "İptal"}


incident_states = IncidentStateMachine()
waste_record_states = WasteRecordStateMachine()
