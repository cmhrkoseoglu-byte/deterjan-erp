from django.apps import AppConfig


class PortalConfig(AppConfig):
    """Müşteri ve tedarikçi portalı (docs/plan/musteri-siparis-takibi.md §4)."""

    name = "apps.portal"
    label = "portal"
    verbose_name = "Portal"
