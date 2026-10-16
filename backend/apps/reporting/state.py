"""Rapor işinin durum makinesi (CLAUDE.md §4.5)."""

from apps.reporting.models import ReportJob

S = ReportJob.Status

TRANSITIONS: dict[str, frozenset[str]] = {
    S.QUEUED: frozenset({S.RUNNING, S.FAILED}),
    S.RUNNING: frozenset({S.DONE, S.FAILED}),
    S.DONE: frozenset({S.EXPIRED}),
    S.FAILED: frozenset(),
    S.EXPIRED: frozenset(),
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, frozenset())
