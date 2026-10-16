"""Tüm ortamlar için ortak ayarlar. Değerler ortam değişkenlerinden / .env'den okunur."""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
REPO_DIR = BASE_DIR.parent

env = environ.Env()
# Docker dışında çalışırken depo kökündeki .env okunur; Docker'da değişkenler env_file ile gelir.
environ.Env.read_env(REPO_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "apps.core.admin_site.ERPAdminConfig",  # django.contrib.admin, giriş sınırlı yönetim sitesiyle
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Üçüncü taraf
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "channels",
    # Proje modülleri
    "apps.core",
    "apps.masterdata",
    "apps.recipes",
    "apps.inventory",
    "apps.production",
    "apps.quality",
    "apps.filling",
    "apps.sales",
    "apps.returns",
    "apps.traceability",
    "apps.costing",
    "apps.purchasing",
    "apps.workflow",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.context.RequestContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
AUTH_USER_MODEL = "core.User"
# nginx arkasında istemci IP'si X-Real-IP başlığından okunur (denetim günlüğü için).
# Backend doğrudan dışarı açılırsa False yapılmalıdır.
TRUST_X_REAL_IP = env.bool("DJANGO_TRUST_X_REAL_IP", default=True)
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis / Channels / Celery
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    },
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = None
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = False
# Zamanlanmış işler (Celery Beat, CELERY_TIMEZONE saatine göre)
CELERY_BEAT_SCHEDULE = {
    "daily-check-0700": {
        "task": "core.publish_daily_check",
        "schedule": crontab(hour=7, minute=0),
    },
}

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.core.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

# Kaba kuvvet denemelerine karşı IP başına giriş denemesi sınırı (API ve yönetim paneli ortak).
LOGIN_RATE_LIMIT = env("LOGIN_RATE_LIMIT", default="10/minute")
CSRF_FAILURE_VIEW = "apps.core.api.views.csrf_failure"

# Önbellek: giriş sınırı sayaçları tüm worker'larda ortak olsun diye Redis (ayrı veritabanı).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default="redis://localhost:6379/2"),
    }
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Deterjan ERP API",
    "DESCRIPTION": "Deterjan fabrikası üretim takip sistemi API'si.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "HealthStateEnum": "apps.core.api.serializers.HEALTH_STATES",
        "AuditActionEnum": "apps.core.models.AuditLog.Action",
        "ImportRowActionEnum": "apps.masterdata.api.serializers.IMPORT_ROW_ACTIONS",
        "RecipeVersionStatusEnum": "apps.recipes.models.RecipeVersion.Status",
        "LotStatusEnum": "apps.inventory.models.Lot.Status",
        "StockDocumentStatusEnum": "apps.inventory.models.GoodsReceipt.Status",
        "ProductionBatchStatusEnum": "apps.production.models.ProductionBatch.Status",
        "SampleStageEnum": "apps.quality.models.SampleStage",
        "AttachmentKindEnum": "apps.core.models.Attachment.Kind",
        "LotLabelKindEnum": "apps.inventory.api.serializers.LOT_LABEL_KINDS",
        "FillingOrderStatusEnum": "apps.filling.models.FillingOrder.Status",
        "PackagingSpecStatusEnum": "apps.filling.models.PackagingSpec.Status",
        "ConsumptionKindEnum": "apps.filling.models.ConsumptionKind",
        "ScrapKindEnum": "apps.filling.models.ScrapRecord.Kind",
        "SalesOrderStatusEnum": "apps.sales.models.SalesOrder.Status",
        "CurrencyEnum": "apps.core.models.Currency",
        "StockReservationStatusEnum": "apps.inventory.models.StockReservation.Status",
        "CustomerReturnStatusEnum": "apps.returns.models.CustomerReturn.Status",
        "ReturnDispositionEnum": "apps.returns.models.CustomerReturnLine.Disposition",
        "PurchaseOrderStatusEnum": "apps.purchasing.models.PurchaseOrder.Status",
        "PurchaseRequestStatusEnum": "apps.purchasing.models.PurchaseRequest.Status",
        "PurchaseRequestSourceEnum": "apps.purchasing.models.PurchaseRequest.Source",
        "LotSourceEnum": "apps.inventory.models.Lot.Source",
    },
    # Şema ve dokümantasyon yalnızca giriş yapmış kullanıcılara açık (dev.py'de herkese açık).
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    "SERVE_AUTHENTICATION": ["apps.core.authentication.SessionAuthentication"],
}

# Oturum ve CSRF çerezleri (SPA aynı origin'de; CSRF çerezini JavaScript okur)
SESSION_COOKIE_AGE = env.int("DJANGO_SESSION_COOKIE_AGE", default=60 * 60 * 12)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False

# Demo kullanıcı şifresi (yalnızca create_demo_users komutu, yalnızca DEBUG ortamında)
DEMO_USER_PASSWORD = env("DEMO_USER_PASSWORD", default="")

# Üretim: verim (çıktı / şarj miktarı) bu yüzdenin altındaysa `production.low_yield` olayı.
PRODUCTION_LOW_YIELD_THRESHOLD_PCT = env("PRODUCTION_LOW_YIELD_THRESHOLD_PCT", default="97")

# Ekler (Adım 2.4): en büyük dosya boyutu.
ATTACHMENT_MAX_BYTES = env.int("ATTACHMENT_MAX_BYTES", default=20 * 1024 * 1024)
# Etiket yazıcısına (TCP 9100) bağlantı zaman aşımı, saniye.
PRINTER_TIMEOUT_SECONDS = env.float("PRINTER_TIMEOUT_SECONDS", default=5.0)
# Dolum: gerçek bulk tüketimi teorikten (sağlam adet × dolum miktarı) bu yüzdeden fazla saparsa
# `filling.bulk_variance` olayı (planlama ve yönetime uyarı).
FILL_VARIANCE_THRESHOLD_PCT = env("FILL_VARIANCE_THRESHOLD_PCT", default="1.5")

# Firma bilgileri: irsaliye ve analiz sertifikası başlığı.
COMPANY_NAME = env("COMPANY_NAME", default="")
COMPANY_ADDRESS = env("COMPANY_ADDRESS", default="")
COMPANY_TAX_OFFICE = env("COMPANY_TAX_OFFICE", default="")
COMPANY_TAX_NO = env("COMPANY_TAX_NO", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# E-posta (Faz 4: satın alma siparişi gönderimi). Örnek: EMAIL_URL=smtp+tls://kullanici:sifre@smtp.ornek.com:587
# Tanımsızsa e-postalar konsola yazılır (gönderilmez).
vars().update(env.email_url("EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="erp@localhost")
