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

Dolum emrini geri alma (ayrı tablolar; DECISIONS 2026-11-14). Fiilen yapılmamış dolum, emrin bütün
stok hareketleri ters kayıtla geri alınarak iptal edilir (`services.revert_order`). Ana tablolar
değişmez: sıradan "Emri iptal et" başlamış emri iptal edemez. Olay adları aynıdır
(`filling_order.cancelled`, `filling_run.cancelled`).

    Emir:   MATERIAL_READY ─┐
            IN_PROGRESS ────┼──► CANCELLED
            QC_PENDING ─────┘

    Parti:  IN_PROGRESS ─┬──► CANCELLED
            COMPLETED ───┘
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


class FillingOrderRevertMachine(StateMachine):
    """Dolum emrini geri alma: yalnızca başlamış (ambalajı hazır, dolumda ya da analiz bekleyen)
    emir iptal olur. Etiketler ana makineden."""

    name = "filling_order"
    initial = "MATERIAL_READY"
    transitions = {
        "MATERIAL_READY": ["CANCELLED"],
        "IN_PROGRESS": ["CANCELLED"],
        "QC_PENDING": ["CANCELLED"],
    }
    labels = FillingOrderStateMachine.labels


class FillingRunRevertMachine(StateMachine):
    """Dolum emrini geri almada partiler: devam eden ve tamamlanmış parti iptal olur."""

    name = "filling_run"
    initial = "IN_PROGRESS"
    transitions = {
        "IN_PROGRESS": ["CANCELLED"],
        "COMPLETED": ["CANCELLED"],
    }
    labels = FillingRunStateMachine.labels


packaging_spec_states = PackagingSpecStateMachine()
filling_order_states = FillingOrderStateMachine()
filling_run_states = FillingRunStateMachine()
filling_order_revert_states = FillingOrderRevertMachine()
filling_run_revert_states = FillingRunRevertMachine()
