from django.apps import AppConfig


class SalesConfig(AppConfig):
    name = "apps.sales"
    label = "sales"
    verbose_name = "Satış ve sevkiyat"

    def ready(self) -> None:
        from apps.core.records import register_record_type
        from apps.sales.api.views import READ_ROLES

        # Yorum ve geçmiş: sipariş ve sevkiyatı ekranlarını açabilen roller okur.
        register_record_type("sales.salesorder", roles=READ_ROLES)
        register_record_type("sales.shipment", roles=READ_ROLES)
