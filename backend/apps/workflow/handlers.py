"""Olay dinleyicileri: kural tablosundaki her olay `services.process_event`'e gider."""

from apps.core import events
from apps.workflow import rules, services

for _event_name in sorted(rules.all_event_names()):
    events.subscribe(_event_name)(services.process_event)
