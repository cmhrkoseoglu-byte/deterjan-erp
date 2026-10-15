"""Görev durum makinesi."""

from apps.core.state import StateMachine


class TaskStateMachine(StateMachine):
    name = "task"
    initial = "OPEN"
    transitions = {
        "OPEN": ["IN_PROGRESS", "DONE", "CANCELLED"],
        "IN_PROGRESS": ["DONE", "CANCELLED"],
    }
    labels = {
        "OPEN": "Açık",
        "IN_PROGRESS": "Devam ediyor",
        "DONE": "Tamamlandı",
        "CANCELLED": "İptal",
    }


task_states = TaskStateMachine()
