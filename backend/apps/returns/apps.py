from django.apps import AppConfig


class ReturnsConfig(AppConfig):
    name = "apps.returns"
    label = "returns"
    verbose_name = "Müşteri iadeleri"

    def ready(self) -> None:
        from apps.core.records import register_record_type

        # Yorum ve geçmiş: iadeyi giriş yapmış herkes okur (ekranıyla aynı).
        register_record_type("returns.customerreturn")

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("IA", label="Müşteri iadesi", model="returns.customerreturn")
