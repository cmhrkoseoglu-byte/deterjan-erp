"""Anlık iletim: kullanıcı başına Channels grubu (`user_<id>`) üzerinden WebSocket mesajı.

Mesajlar transaction commit edildikten sonra gönderilir; Redis'e ulaşılamazsa hata loglanır ve
ana işlem etkilenmez (frontend 30 sn'lik yoklamayla yine günceller).
"""

import logging
from collections.abc import Iterable
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)

MESSAGE_TYPE = "workflow.message"


def user_group(user_id: int) -> str:
    return f"user_{user_id}"


def push_to_users(user_ids: Iterable[int], data: dict[str, Any]) -> None:
    """`data` mesajını commit sonrası verilen kullanıcıların WebSocket bağlantılarına gönderir."""
    targets = sorted(set(user_ids))
    if targets:
        transaction.on_commit(lambda: _send(targets, data))


def _send(user_ids: list[int], data: dict[str, Any]) -> None:
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        for user_id in user_ids:
            async_to_sync(layer.group_send)(
                user_group(user_id), {"type": MESSAGE_TYPE, "data": data}
            )
    except Exception:
        logger.exception("WebSocket mesajı gönderilemedi: %s", data.get("type"))
