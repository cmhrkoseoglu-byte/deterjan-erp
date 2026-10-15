"""Altyapı bağımlılıklarının (veritabanı, Redis) erişilebilirlik kontrolleri."""

import logging

import redis
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)


def check_database() -> bool:
    """Veritabanına basit bir sorgu atar; başarılıysa True döner."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Veritabanı sağlık kontrolü başarısız")
        return False
    return True


def check_redis() -> bool:
    """Redis'e PING gönderir; başarılıysa True döner."""
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        logger.exception("Redis sağlık kontrolü başarısız")
        return False
