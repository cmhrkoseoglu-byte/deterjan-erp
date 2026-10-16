from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Stok ve lot"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target

        # Tedarikçi CoA'sı, fotoğraf, irsaliye görüntüsü (Adım 2.4).
        register_attachment_target("inventory.lot")
        register_attachment_target("inventory.goodsreceipt")
