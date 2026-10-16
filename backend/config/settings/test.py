"""Test ortamı ayarları (pytest)."""

import tempfile
from pathlib import Path

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
# Ekler testlerde geçici klasöre yazılır.
MEDIA_ROOT = str(Path(tempfile.gettempdir()) / "deterjan-erp-test-media")
# İki aşamalı doğrulama zorunluluğu testlerde kapalı; ilgili testler kendisi açar.
OTP_REQUIRED_ROLES = []
