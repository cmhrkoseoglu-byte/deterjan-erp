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

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("SS", label="Satış siparişi", model="sales.salesorder")
        # İrsaliye numarası yasal belge numarasıdır; biçimi ekrandan değiştirilemez.
        register_document_type(
            "SV", label="Sevkiyat (irsaliye no)", model="sales.shipment", locked=True
        )

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        # İrsaliye yasal belgedir: bandı açmadan önce mali müşavire danışılır (ekran uyarır).
        register_output(
            "sales.waybill",
            label="İrsaliye",
            group="Sevkiyat",
            formats=("PDF",),
            legal=True,
            suggested_code="FR-SVK-001",
        )
