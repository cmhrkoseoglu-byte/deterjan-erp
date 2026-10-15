"""Dolum modülü durum makineleri.

Ambalaj reçetesi sürümü (reçete sürümü gibi):

    DRAFT ─► APPROVED ─► OBSOLETE

Dolum emri:

    DRAFT ─► APPROVED ─► MATERIAL_PREP ─► MATERIAL_READY ─► IN_PROGRESS ─► QC_PENDING ─► COMPLETED
      │          │              │
      └──────────┴──────────────┴──► CANCELLED   (hazırlıkta iptalde hazırlanan ambalaj geri döner)

Dolum partisi:

    IN_PROGRESS ─► COMPLETED
         └───────► CANCELLED   (yalnızca tüketim ve fire kaydı yoksa)
"""

from apps.core.state import StateMachine


class PackagingSpecStateMachine(StateMachine):
    name = "packaging_spec"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["APPROVED"],
        "APPROVED": ["OBSOLETE"],
        "OBSOLETE": [],
    }
    labels = {"DRAFT": "Taslak", "APPROVED": "Onaylı", "OBSOLETE": "Eski sürüm"}


class FillingOrderStateMachine(StateMachine):
    name = "filling_order"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["APPROVED", "CANCELLED"],
        "APPROVED": ["MATERIAL_PREP", "CANCELLED"],
        "MATERIAL_PREP": ["MATERIAL_READY", "CANCELLED"],
        "MATERIAL_READY": ["IN_PROGRESS"],
        "IN_PROGRESS": ["QC_PENDING"],
        "QC_PENDING": ["COMPLETED"],
        "COMPLETED": [],
        "CANCELLED": [],
    }
    labels = {
        "DRAFT": "Taslak",
        "APPROVED": "Onaylandı",
        "MATERIAL_PREP": "Ambalaj hazırlanıyor",
        "MATERIAL_READY": "Ambalaj hazır",
        "IN_PROGRESS": "Dolumda",
        "QC_PENDING": "Analiz bekliyor",
        "COMPLETED": "Tamamlandı",
        "CANCELLED": "İptal",
    }


class FillingRunStateMachine(StateMachine):
    name = "filling_run"
    initial = "IN_PROGRESS"
    transitions = {
        "IN_PROGRESS": ["COMPLETED", "CANCELLED"],
        "COMPLETED": [],
        "CANCELLED": [],
    }
    labels = {"IN_PROGRESS": "Devam ediyor", "COMPLETED": "Tamamlandı", "CANCELLED": "İptal"}


packaging_spec_states = PackagingSpecStateMachine()
filling_order_states = FillingOrderStateMachine()
filling_run_states = FillingRunStateMachine()
