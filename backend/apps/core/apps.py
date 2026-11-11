from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Çekirdek"

    def ready(self) -> None:
        from django.utils.module_loading import autodiscover_modules

        from apps.core import checks, schema, signals  # noqa: F401 - uzantıları ve sinyalleri kaydeder

        # Yetki kataloğu: her uygulamanın access.py dosyası bölümlerini ve rol paketlerini kaydeder
        # (docs/plan/kisi-yetkileri.md §5.1). Görünümler ve servisler bölüm nesnelerini doğrudan
        # import eder; burada yüklemek kataloğun her süreçte tam olmasını sağlar.
        autodiscover_modules("access")
        # Her uygulamanın handlers.py modülündeki @subscribe kayıtlarını yükle.
        autodiscover_modules("handlers")
