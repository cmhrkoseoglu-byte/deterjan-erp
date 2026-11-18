from django.apps import AppConfig


class LedgerConfig(AppConfig):
    name = "apps.ledger"
    label = "ledger"
    verbose_name = "Cari hesaplar"

    def ready(self) -> None:
        # Kayıt numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("CH", label="Cari hareket", model="ledger.ledgerentry")
