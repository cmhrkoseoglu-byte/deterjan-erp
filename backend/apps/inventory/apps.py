from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Stok ve lot"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target
        from apps.core.models import User
        from apps.core.permissions import user_has_role
        from apps.core.records import register_record_type
        from apps.core.roles import YONETIM

        # Tedarikçi CoA'sı, fotoğraf, irsaliye görüntüsü (Adım 2.4).
        register_attachment_target("inventory.lot")
        register_attachment_target("inventory.goodsreceipt")

        def lot_cost_fields(user: User) -> set[str]:
            # Lot maliyetini yalnızca yönetim görür (Karar D-15, costing.COST_ROLES).
            return set() if user_has_role(user, (YONETIM,)) else {"unit_cost", "cost_is_estimated"}

        # Yorum, geçmiş, ek: lot ve stok belgelerini giriş yapmış herkes okur (ekranlarıyla aynı).
        register_record_type("inventory.lot", hidden_fields=lot_cost_fields)
        register_record_type("inventory.goodsreceipt")
        register_record_type("inventory.stockadjustment")
