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

        # Şarjı bitmemiş dökme lot serbest bırakılamaz, son kontrolü yapılamaz (inventory).
        from apps.inventory.services import register_output_check
        from apps.production.services import unfinished_batch_reason

        register_output_check(unfinished_batch_reason)

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("UE", label="Üretim emri", model="production.productionorder")
