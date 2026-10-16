from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    name = "apps.maintenance"
    label = "maintenance"
    verbose_name = "Bakım"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target
        from apps.maintenance import services  # noqa: F401 - ekipman kancasını kaydeder

        # Servis raporu, fotoğraf, kalibrasyon sertifikası.
        register_attachment_target("maintenance.maintenanceworkorder")
