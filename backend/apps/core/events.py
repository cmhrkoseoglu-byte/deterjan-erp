"""Modüller arası olay yayını.

Bir modül "bir şey oldu" bilgisini `publish()` ile yayınlar; ilgilenen modüller (ör. `workflow`)
`@subscribe("production_order.*")` ile dinler. Handler'lar transaction commit edildikten sonra
çalışır; geri alınan işlem olay üretmez. Handler hatası ana işlemi bozmaz, loglanır.

Handler'lar her uygulamanın `handlers.py` modülünde tanımlanır; `CoreConfig.ready()` bu modülleri
otomatik yükler.
"""

import fnmatch
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    """Yayınlanan olay. `payload` JSON'a yazılabilir değerler içermelidir (kimlikler, kodlar)."""

    name: str
    payload: dict[str, Any]
    actor_id: int | None = None
    occurred_at: datetime = field(default_factory=timezone.now)


Handler = Callable[[Event], None]

# Desen ("production_order.*" ya da tam ad) -> handler listesi
_subscribers: dict[str, list[Handler]] = {}


def subscribe(event_name: str) -> Callable[[Handler], Handler]:
    """Handler kaydeden dekoratör. `*` joker karakteri desteklenir (ör. `"production_order.*"`)."""

    def decorator(handler: Handler) -> Handler:
        handlers = _subscribers.setdefault(event_name, [])
        if handler not in handlers:
            handlers.append(handler)
        return handler

    return decorator


def unsubscribe(event_name: str, handler: Handler) -> None:
    """Handler kaydını kaldırır (çoğunlukla testler için)."""
    handlers = _subscribers.get(event_name, [])
    if handler in handlers:
        handlers.remove(handler)


def handlers_for(event_name: str) -> list[Handler]:
    """Olay adıyla eşleşen handler'lar, kayıt sırasıyla."""
    matched: list[Handler] = []
    for pattern, handlers in _subscribers.items():
        if fnmatch.fnmatchcase(event_name, pattern):
            matched.extend(h for h in handlers if h not in matched)
    return matched


def publish(event_name: str, payload: dict[str, Any], actor: User | None = None) -> Event:
    """Olayı yayınlar. Handler'lar geçerli transaction commit edildiğinde çağrılır.

    Transaction dışında çağrılırsa handler'lar hemen çalışır.
    """
    actor_id = actor.pk if actor is not None and actor.is_authenticated else None
    event = Event(name=event_name, payload=dict(payload), actor_id=actor_id)
    transaction.on_commit(lambda: dispatch(event))
    return event


def dispatch(event: Event) -> None:
    """Olayı eşleşen handler'lara iletir. Her handler kendi transaction'ında çalışır;
    hata veren handler loglanır, diğerleri çalışmaya devam eder."""
    for handler in handlers_for(event.name):
        try:
            with transaction.atomic():
                handler(event)
        except Exception:
            logger.exception(
                "Olay handler'ı başarısız: olay=%s handler=%s",
                event.name,
                getattr(handler, "__qualname__", repr(handler)),
            )
