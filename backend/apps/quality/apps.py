from django.apps import AppConfig


class QualityConfig(AppConfig):
    name = "apps.quality"
    label = "quality"
    verbose_name = "Kalite kontrol"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target
        from apps.core.records import register_record_type

        register_attachment_target("quality.sample")
        # Yorum, geçmiş, ek: numuneyi giriş yapmış herkes okur (ekranıyla aynı).
        register_record_type("quality.sample")

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("NM", label="Numune", model="quality.sample")
