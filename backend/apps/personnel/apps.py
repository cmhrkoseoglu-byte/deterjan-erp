from django.apps import AppConfig


class PersonnelConfig(AppConfig):
    name = "apps.personnel"
    label = "personnel"
    verbose_name = "Personel"

    def ready(self) -> None:
        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("PU", label="Puantaj", model="personnel.attendancemonth")
        register_document_type("BR", label="Bordro", model="personnel.payrollrun")
