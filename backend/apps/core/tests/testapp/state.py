from apps.core.state import StateMachine


class SampleDocumentStateMachine(StateMachine):
    name = "sample_document"
    transitions = {
        "DRAFT": ["APPROVED", "CANCELLED"],
        "APPROVED": ["DONE", "CANCELLED"],
        "DONE": [],
    }
    labels = {
        "DRAFT": "Taslak",
        "APPROVED": "Onaylandı",
        "DONE": "Tamamlandı",
        "CANCELLED": "İptal",
    }


sample_document_states = SampleDocumentStateMachine()
