"""Üretim ortamı ayarları (Faz 5, Adım 5.4). Hedef: fabrikada yerel sunucu, nginx arkasında
HTTPS (D-20).

Güvensiz bir yapılandırmayla (örnek gizli anahtar, boş ya da `*` içeren ALLOWED_HOSTS, HTTPS olmayan
CSRF origin'i) uygulama başlamaz. `python manage.py check --deploy` uyarısız geçer.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False

# --- açılış denetimleri ------------------------------------------------------------------------
_EXAMPLE_SECRET_KEYS = {"degistir-beni-uzun-ve-rastgele-bir-anahtar", "ci-only-not-secret"}
if SECRET_KEY in _EXAMPLE_SECRET_KEYS or len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5:  # noqa: F405
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY üretim için uygun değil: en az 50 karakterlik rastgele bir değer verin "
        '(ör. python -c "import secrets; print(secrets.token_urlsafe(64))").'
    )
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS üretimde açıkça verilmeli ve '*' içermemeli.")
if not CSRF_TRUSTED_ORIGINS or any(  # noqa: F405
    not origin.startswith("https://")
    for origin in CSRF_TRUSTED_ORIGINS  # noqa: F405
):
    raise ImproperlyConfigured(
        "DJANGO_CSRF_TRUSTED_ORIGINS üretimde https:// ile başlayan adresler."
    )

# --- HTTPS ve çerezler -------------------------------------------------------------------------
# TLS nginx'te sonlanır; nginx `X-Forwarded-Proto` başlığını kendisi yazar (istemcininkini ezer).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
# Django de HSTS ve yönlendirme yapar; nginx aynı başlığı zaten veriyor (çift başlık zararsızdır).
# Konteyner içi sağlık kontrolü HTTP ile geldiği için sağlık ucu yönlendirmeden muaf.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/"]
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 365)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=False)  # noqa: F405
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# HSTS bilinçli olarak alt alan adlarını kapsamaz ve preload listesine girmez (firmanın diğer
# alt alan adlarını etkilemesin; iç ağ sertifikasıyla da çalışsın).
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# --- izleme ------------------------------------------------------------------------------------
OPS_BACKUP_CHECK_ENABLED = env.bool("OPS_BACKUP_CHECK_ENABLED", default=True)  # noqa: F405

# --- günlük ------------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default="INFO")},  # noqa: F405
    "loggers": {
        # Geçersiz Host başlığıyla gelen tarama istekleri günlüğü doldurmasın.
        "django.security.DisallowedHost": {"handlers": [], "propagate": False},
    },
}
