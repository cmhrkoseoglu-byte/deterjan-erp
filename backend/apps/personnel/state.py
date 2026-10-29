"""Puantaj durum makinesi (2026-10-29).

Aylık puantaj:  OPEN ─► APPROVED ─► OPEN (gerekçeyle yeniden açma)
"""

from apps.core.state import StateMachine


class AttendanceMonthStateMachine(StateMachine):
    name = "attendance_month"
    initial = "OPEN"
    transitions = {
        "OPEN": ["APPROVED"],
        "APPROVED": ["OPEN"],
    }
    labels = {"OPEN": "Açık", "APPROVED": "Onaylandı"}


attendance_month_states = AttendanceMonthStateMachine()
