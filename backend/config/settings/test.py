"""Test ortamı ayarları (pytest)."""

from .base import *  # noqa: F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
# Testlerde giriş sınırı testlerin kendisini engellemesin; sınır testi kendi oranını ayarlar.
LOGIN_RATE_LIMIT = "1000/minute"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
DEMO_USER_PASSWORD = "Demo.12345"
INSTALLED_APPS = [*INSTALLED_APPS, "apps.core.tests.testapp"]  # noqa: F405
