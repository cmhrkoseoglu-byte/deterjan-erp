from django.apps import AppConfig


class FillingConfig(AppConfig):
    name = "apps.filling"
    label = "filling"
    verbose_name = "Dolum ve ambalaj"

    def ready(self) -> None:
        from apps.core.records import register_record_type

        # Yorum ve geçmiş: dolum kayıtlarını giriş yapmış herkes okur (ekranlarıyla aynı).
        register_record_type("filling.fillingorder")
        register_record_type("filling.fillingrun")
        register_record_type("filling.packagingspec")
