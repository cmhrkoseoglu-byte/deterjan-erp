from django.apps import AppConfig


class QualityConfig(AppConfig):
    name = "apps.quality"
    label = "quality"
    verbose_name = "Kalite kontrol"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target

        register_attachment_target("quality.sample")
