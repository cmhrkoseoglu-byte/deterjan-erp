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

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("UE", label="Üretim emri", model="production.productionorder")
