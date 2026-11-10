from django.apps import AppConfig


class GoLiveConfig(AppConfig):
    name = "apps.golive"
    label = "golive"
    verbose_name = "Canlıya geçiş"

    def ready(self) -> None:
        from apps.core.records import register_record_type
        from apps.golive import selectors

        # Yorum ve geçmiş: sorun bildirimini bildiren ve admin görür (ekranıyla aynı).
        register_record_type("golive.problemreport", visible=selectors.problem_reports_visible_to)

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("SK", label="Stok karşılaştırması", model="golive.stockcomparison")
        register_document_type("SB", label="Sorun bildirimi", model="golive.problemreport")
