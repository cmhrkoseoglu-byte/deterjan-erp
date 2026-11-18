from django.apps import AppConfig


class LedgerConfig(AppConfig):
    name = "apps.ledger"
    label = "ledger"
    verbose_name = "Cari hesaplar"

    def ready(self) -> None:
        # Kayıt numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("CH", label="Cari hareket", model="ledger.ledgerentry")

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        register_output(
            "ledger.statement",
            label="Cari hesap ekstresi",
            group="Cari hesaplar",
            formats=("PDF", "Excel"),
            suggested_code="FR-MUH-001",
        )
        register_output(
            "ledger.partners",
            label="Cari listesi",
            group="Cari hesaplar",
            formats=("Excel",),
            suggested_code="LS-MUH-001",
        )
