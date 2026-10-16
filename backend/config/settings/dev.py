"""Geliştirme ortamı ayarları."""

from .base import *  # noqa: F403

DEBUG = True

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.AllowAny"]  # noqa: F405
# Demo kullanıcılarla denemeyi kolaylaştırmak için geliştirmede 2FA zorunlu değil (Güvenlik
# sayfasından isteğe bağlı açılabilir). Üretimde varsayılan: admin ve yonetim.
OTP_REQUIRED_ROLES = env.list("OTP_REQUIRED_ROLES", default=[])  # noqa: F405
