"""Basit, önbellek tabanlı istek sınırlayıcı (giriş denemeleri için).

Sayaçlar paylaşılan önbellekte (Redis) tutulur; böylece sınır tüm worker'larda ortaktır.
Önbelleğe ulaşılamazsa sınırlayıcı açık kalır (giriş engellenmez) ve hata loglanır.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

from apps.core.context import client_ip_from_request

logger = logging.getLogger(__name__)

_PERIODS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_rate(rate: str) -> tuple[int, int]:
    """`"10/minute"` → `(10, 60)`."""
    count, _, period = rate.partition("/")
    if not count.isdigit() or not period or period[0] not in _PERIODS:
        raise ValueError(f"Geçersiz oran: {rate!r} (ör. '10/minute')")
    return int(count), _PERIODS[period[0]]


def hit(scope: str, ident: str, rate: str) -> bool:
    """Bir deneme sayar. Sınır aşıldıysa True döner (istek reddedilmeli)."""
    limit, period = parse_rate(rate)
    key = f"ratelimit:{scope}:{ident}"
    try:
        if cache.add(key, 1, timeout=period):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:  # anahtar add ile incr arasında süresi dolup silindi
                cache.set(key, 1, timeout=period)
                count = 1
    except Exception:
        logger.exception("İstek sınırlayıcı önbelleğe ulaşamadı; sınır uygulanmadı")
        return False
    return count > limit


def login_rate_exceeded(request: HttpRequest) -> bool:
    """Giriş denemesini istemci IP'si başına sayar (API ve yönetim paneli girişi ortak)."""
    ident = client_ip_from_request(request) or "unknown"
    return hit("login", ident, settings.LOGIN_RATE_LIMIT)


def login_rate_period() -> int:
    return parse_rate(settings.LOGIN_RATE_LIMIT)[1]
