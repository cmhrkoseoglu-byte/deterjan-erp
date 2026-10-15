"""Üretim ortamı ayarları. Faz 5'te barındırma kararıyla birlikte tamamlanacak."""

from .base import *  # noqa: F403

DEBUG = False
SESSION_COOKIE_SECURE = env.bool("DJANGO_SECURE_COOKIES", default=True)  # noqa: F405
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
