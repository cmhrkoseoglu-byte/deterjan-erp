"""Üretim modülü durum makineleri.

Üretim emri:

    DRAFT ─► APPROVED ─► MATERIAL_PREP ─► MATERIAL_READY ─► IN_PRODUCTION ─► QC_PENDING ─► COMPLETED
      │          │              │
      └──────────┴──────────────┴──► CANCELLED   (hazırlıkta iptalde hazırlanan malzeme geri döner)

Şarj (Karar D-4: bir emir birden çok şarja bölünebilir):

    IN_PROGRESS ─► COMPLETED
         └───────► CANCELLED   (yalnızca tartım yapılmamışsa)
"""

from apps.core.state import StateMachine


class ProductionOrderStateMachine(StateMachine):
    name = "production_order"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["APPROVED", "CANCELLED"],
        "APPROVED": ["MATERIAL_PREP", "CANCELLED"],
        "MATERIAL_PREP": ["MATERIAL_READY", "CANCELLED"],
        "MATERIAL_READY": ["IN_PRODUCTION"],
        "IN_PRODUCTION": ["QC_PENDING"],
        "QC_PENDING": ["COMPLETED"],
        "COMPLETED": [],
        "CANCELLED": [],
    }
    labels = {
        "DRAFT": "Taslak",
        "APPROVED": "Onaylandı",
        "MATERIAL_PREP": "Malzeme hazırlanıyor",
        "MATERIAL_READY": "Malzeme hazır",
        "IN_PRODUCTION": "Üretimde",
        "QC_PENDING": "Analiz bekliyor",
        "COMPLETED": "Tamamlandı",
        "CANCELLED": "İptal",
    }


class ProductionBatchStateMachine(StateMachine):
    name = "production_batch"
    initial = "IN_PROGRESS"
    transitions = {
        "IN_PROGRESS": ["COMPLETED", "CANCELLED"],
        "COMPLETED": [],
        "CANCELLED": [],
    }
    labels = {"IN_PROGRESS": "Devam ediyor", "COMPLETED": "Tamamlandı", "CANCELLED": "İptal"}


production_order_states = ProductionOrderStateMachine()
production_batch_states = ProductionBatchStateMachine()
