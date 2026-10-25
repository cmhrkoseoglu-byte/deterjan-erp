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
