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

        # Test tanımı kodu serbesttir (PH, AKTIF_MADDE); biçim etkinse karakter kuralı uygulanır.
        from apps.core.coding.registry import register_master_code
        from apps.quality.services import LAB_ROLES

        register_master_code(
            "quality.testdefinition",
            label="Test tanımı",
            model="quality.testdefinition",
            free=True,
            allow_underscore=True,
            write_roles=LAB_ROLES,
        )

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        register_output(
            "quality.coa",
            label="Analiz sertifikası",
            group="Kalite",
            formats=("PDF",),
            suggested_code="FR-KAL-001",
        )
