from django.apps import AppConfig


class CostingConfig(AppConfig):
    name = "apps.costing"
    label = "costing"
    verbose_name = "Maliyet"

    def ready(self) -> None:
        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        for key, label, code in (
            ("costing.cost-trend", "Maliyet trendi", "LS-MAL-001"),
            ("costing.batch-variance", "Şarj maliyeti (teorik ve fiili)", "LS-MAL-002"),
            ("costing.scrap-cost", "Fire maliyeti", "LS-MAL-003"),
            ("costing.top-materials", "En pahalı kalemler", "LS-MAL-004"),
            ("costing.stock-value", "Stok değeri", "LS-MAL-005"),
            ("costing.personnel-cost", "Personel maliyeti", "LS-MAL-006"),
        ):
            register_output(
                key, label=label, group="Maliyet", formats=("Excel",), suggested_code=code
            )
