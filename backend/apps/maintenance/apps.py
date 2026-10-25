from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    name = "apps.maintenance"
    label = "maintenance"
    verbose_name = "Bakım"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target
        from apps.core.records import register_record_type
        from apps.maintenance import services

        # Servis raporu, fotoğraf, kalibrasyon sertifikası.
        register_attachment_target("maintenance.maintenanceworkorder")
        # Yorum, geçmiş, ek: iş emrini bakım ekranlarını açabilen roller okur.
        register_record_type("maintenance.maintenanceworkorder", roles=services.READ_ROLES)
