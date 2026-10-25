from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    name = "apps.purchasing"
    label = "purchasing"
    verbose_name = "Satın alma"

    def ready(self) -> None:
        from apps.core.models import User
        from apps.core.permissions import user_has_role
        from apps.core.records import register_record_type
        from apps.purchasing import services
        from apps.purchasing.api.serializers import PRICE_FIELDS
        from apps.purchasing.api.views import ORDER_READ_ROLES

        def price_fields(user: User) -> frozenset[str]:
            # Siparişi görüp fiyatı göremeyen (depo) geçmişte de tutarları görmez.
            return frozenset() if user_has_role(user, services.ORDER_ROLES) else PRICE_FIELDS

        register_record_type(
            "purchasing.purchaseorder", roles=ORDER_READ_ROLES, hidden_fields=price_fields
        )
