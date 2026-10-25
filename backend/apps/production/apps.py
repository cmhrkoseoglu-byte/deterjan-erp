from django.apps import AppConfig


class ProductionConfig(AppConfig):
    name = "apps.production"
    label = "production"
    verbose_name = "Üretim"

    def ready(self) -> None:
        from apps.core.records import register_record_type

        # Yorum ve geçmiş: üretim emri ve şarjı giriş yapmış herkes okur (ekranlarıyla aynı).
        register_record_type("production.productionorder")
        register_record_type("production.productionbatch")
