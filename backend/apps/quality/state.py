"""Kalite durum makineleri.

Spesifikasyon sürümü (reçete sürümü gibi):

    DRAFT ─► APPROVED ─► OBSOLETE

Numune:

    PENDING ─► IN_TEST ─► DECIDED
       │          │  └──► AWAITING_APPROVAL ─► DECIDED
       │          │              └───────────► IN_TEST   (yönetim şartlı kabulü reddetti)
       │          └─────► CANCELLED
       └─► DECIDED / AWAITING_APPROVAL / CANCELLED

`PENDING`'den doğrudan karar, zorunlu testi olmayan spesifikasyonda olur. Her geçiş
`sample.<durum>` olayı yayınlar.
"""

from apps.core.state import StateMachine


class SpecificationStateMachine(StateMachine):
    name = "specification"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["APPROVED"],
        "APPROVED": ["OBSOLETE"],
        "OBSOLETE": [],
    }
    labels = {"DRAFT": "Taslak", "APPROVED": "Onaylı", "OBSOLETE": "Geçersiz"}


class SampleStateMachine(StateMachine):
    name = "sample"
    initial = "PENDING"
    transitions = {
        "PENDING": ["IN_TEST", "AWAITING_APPROVAL", "DECIDED", "CANCELLED"],
        "IN_TEST": ["AWAITING_APPROVAL", "DECIDED", "CANCELLED"],
        "AWAITING_APPROVAL": ["IN_TEST", "DECIDED"],
        "DECIDED": [],
        "CANCELLED": [],
    }
    labels = {
        "PENDING": "Bekliyor",
        "IN_TEST": "Testte",
        "AWAITING_APPROVAL": "Şartlı kabul onayı bekliyor",
        "DECIDED": "Karar verildi",
        "CANCELLED": "İptal",
    }


specification_states = SpecificationStateMachine()
sample_states = SampleStateMachine()
