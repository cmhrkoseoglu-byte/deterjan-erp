from django.apps import AppConfig


class ReturnsConfig(AppConfig):
    name = "apps.returns"
    label = "returns"
    verbose_name = "Müşteri iadeleri"

    def ready(self) -> None:
        from apps.core.records import register_record_type

        # Yorum ve geçmiş: iadeyi giriş yapmış herkes okur (ekranıyla aynı).
        register_record_type("returns.customerreturn")
