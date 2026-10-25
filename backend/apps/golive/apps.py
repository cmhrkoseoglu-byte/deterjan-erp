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
