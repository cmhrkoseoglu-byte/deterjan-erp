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

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        # "Kim neyi görür" raporu paketlerin imzalanması ve denetim için kontrollü belgedir
        # (sahibin 2026-11-17 kararı).
        from apps.core.coding.registry import register_output

        register_output(
            "core.access-report",
            label="Kim neyi görür (yetki raporu)",
            group="Sistem",
            formats=("Excel",),
            suggested_code="LS-SIS-001",
        )
