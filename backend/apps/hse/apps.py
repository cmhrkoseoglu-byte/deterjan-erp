from django.apps import AppConfig


class HseConfig(AppConfig):
    name = "apps.hse"
    label = "hse"
    verbose_name = "İSG ve çevre"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target
        from apps.hse import services  # stok hareketi kancasını kaydeder

        # GBF PDF'i, atık taşıma formu, olay fotoğrafı.
        register_attachment_target("hse.safetydatasheet", can_add=services.can_attach_sds)
        register_attachment_target("hse.wasterecord", can_add=services.can_attach_waste)
        register_attachment_target("hse.incident", can_add=services.can_attach_incident)
