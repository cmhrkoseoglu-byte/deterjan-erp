"""Puantaj (2026-10-29) ve bordro (2026-11-03) durum makineleri.

Aylık puantaj:  OPEN ─► APPROVED ─► OPEN (gerekçeyle yeniden açma)
Aylık bordro:   OPEN ─► APPROVED ─► OPEN (gerekçeyle yeniden açma; aylar sırayla onaylanır, sondan
                başa açılır)
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


class PayrollRunStateMachine(StateMachine):
    name = "payroll_run"
    initial = "OPEN"
    transitions = {
        "OPEN": ["APPROVED"],
        "APPROVED": ["OPEN"],
    }
    labels = {"OPEN": "Açık", "APPROVED": "Onaylandı"}


payroll_run_states = PayrollRunStateMachine()
