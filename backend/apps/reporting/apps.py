from django.apps import AppConfig


class ReportingConfig(AppConfig):
    name = "apps.reporting"
    label = "reporting"
    verbose_name = "Raporlama"

    def ready(self) -> None:
        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output
        from apps.reporting.reports import REPORTS
        from apps.reporting.services import output_key

        for number, definition in enumerate(REPORTS.values(), start=1):
            register_output(
                output_key(definition),
                label=definition.title,
                group="Raporlar",
                formats=("PDF", "Excel"),
                suggested_code=f"LS-RAP-{number:03d}",
            )
