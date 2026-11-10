from django.apps import AppConfig


class FillingConfig(AppConfig):
    name = "apps.filling"
    label = "filling"
    verbose_name = "Dolum ve ambalaj"

    def ready(self) -> None:
        from apps.core.records import register_record_type

        # Yorum ve geçmiş: dolum kayıtlarını giriş yapmış herkes okur (ekranlarıyla aynı).
        register_record_type("filling.fillingorder")
        register_record_type("filling.fillingrun")
        register_record_type("filling.packagingspec")

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("DO", label="Dolum emri", model="filling.fillingorder")
