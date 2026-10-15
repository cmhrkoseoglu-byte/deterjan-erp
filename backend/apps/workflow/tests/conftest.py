from collections.abc import Callable
from typing import Any

import pytest

from apps.core import events
from apps.core.models import User


@pytest.fixture
def fire(django_capture_on_commit_callbacks) -> Callable[..., None]:
    """Olayı yayınlar ve commit sonrası işleri (handler, WebSocket) hemen çalıştırır."""

    def _fire(name: str, payload: dict[str, Any], actor: User | None = None) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            events.publish(name, payload, actor)

    return _fire
