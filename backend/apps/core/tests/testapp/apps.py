from django.apps import AppConfig


class TestAppConfig(AppConfig):
    """Yalnızca testlerde yüklenen, çekirdek soyut modelleri deneyen uygulama."""

    name = "apps.core.tests.testapp"
    label = "core_testapp"
    verbose_name = "Çekirdek test uygulaması"

    def ready(self) -> None:
        from apps.core.records import register_record_type

        # Yorum ve geçmiş testleri: giriş yapmış herkesin okuyabildiği bir kayıt türü.
        register_record_type("core_testapp.widget")
