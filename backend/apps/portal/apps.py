from django.apps import AppConfig


class PortalConfig(AppConfig):
    """Müşteri ve tedarikçi portalı (docs/plan/musteri-siparis-takibi.md §4)."""

    name = "apps.portal"
    label = "portal"
    verbose_name = "Portal"

    def ready(self) -> None:
        from apps.core.records import register_record_type
        from apps.sales.access import ORDERS

        # Sipariş talebi: yorum ve geçmiş, talepleri iç ekranda okuyabilen (Satış siparişleri).
        register_record_type("portal.orderrequest", readers=(ORDERS,))

        # Belge numarası: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("MT", label="Müşteri sipariş talebi", model="portal.orderrequest")
