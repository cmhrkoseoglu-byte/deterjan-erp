from django.apps import AppConfig


class TraceabilityConfig(AppConfig):
    name = "apps.traceability"
    label = "traceability"
    verbose_name = "İzlenebilirlik ve geri çağırma"

    def ready(self) -> None:
        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        register_output(
            "traceability.recall",
            label="Geri çağırma raporu",
            group="İzlenebilirlik",
            formats=("PDF", "Excel"),
            suggested_code="FR-KAL-002",
        )
