from django.apps import AppConfig


class TestAppConfig(AppConfig):
    """Yalnızca testlerde yüklenen, çekirdek soyut modelleri deneyen uygulama."""

    name = "apps.core.tests.testapp"
    label = "core_testapp"
    verbose_name = "Çekirdek test uygulaması"
