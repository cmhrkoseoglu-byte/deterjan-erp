from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Çekirdek"

    def ready(self) -> None:
        from django.utils.module_loading import autodiscover_modules

        from apps.core import schema, signals  # noqa: F401 - uzantıları ve sinyalleri kaydeder

        # Her uygulamanın handlers.py modülündeki @subscribe kayıtlarını yükle.
        autodiscover_modules("handlers")
