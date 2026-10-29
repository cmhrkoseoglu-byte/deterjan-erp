"""Üretimdeki kanal katmanı (Redis) ayarı: bildirim bağlantısı boş kanalı beklerken kopmamalı.

Testler bellek içi kanal katmanıyla koşar (config/settings/test.py); burada üretim ayarı gerçek
Redis'le denenir. channels_redis kanalı 5 sn bekleyerek dinler (BZPOPMIN). Redis bağlantısının
okuma süresi bundan uzun olmazsa (redis-py 8'de varsayılan 5 sn) her bekleme "Timeout reading
from redis" ile biter ve /ws/notifications/ bağlantısı kopar.
"""

import asyncio
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from channels_redis.core import RedisChannelLayer

from config.settings import base

LAYER_CONFIG: Any = base.CHANNEL_LAYERS["default"]["CONFIG"]


def test_read_timeout_is_longer_than_blocking_receive() -> None:
    assert LAYER_CONFIG["hosts"][0]["socket_timeout"] > RedisChannelLayer.brpop_timeout


def test_waiting_on_idle_channel_does_not_time_out() -> None:
    """Boş kanalda 7 sn beklenir (bir bekleme turundan uzun); yalnızca testin kendi süresi dolar,
    Redis okuma zaman aşımı olmaz."""

    async def wait_on_idle_channel() -> None:
        layer = RedisChannelLayer(**LAYER_CONFIG)
        channel = await layer.new_channel()
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(layer.receive(channel), timeout=7)
        finally:
            await layer.close_pools()

    async_to_sync(wait_on_idle_channel)()
