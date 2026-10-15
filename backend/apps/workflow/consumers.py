"""Bildirim WebSocket'i: `/ws/notifications/`.

Oturum çereziyle kimlik doğrulanır (aynı origin). Giriş yapmamış bağlantı 4401 koduyla kapatılır.
Sunucu yalnızca mesaj gönderir; istemciden gelen mesajlar yok sayılır (yalnızca `ping` → `pong`).
"""

from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.workflow.realtime import user_group

UNAUTHENTICATED_CLOSE_CODE = 4401


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    group_name: str | None = None

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not user.is_authenticated or not user.is_active:
            await self.close(code=UNAUTHENTICATED_CLOSE_CODE)
            return
        self.group_name = user_group(user.pk)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def workflow_message(self, event: dict[str, Any]) -> None:
        await self.send_json(event["data"])
