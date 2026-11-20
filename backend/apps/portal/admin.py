"""Yönetim paneli: portal hesapları yalnızca görüntülenir; hesap servislerle (API) açılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.portal.models import OrderRequest, OutboundEmail, PortalAccount


@admin.register(PortalAccount)
class PortalAccountAdmin(ReadOnlyAdmin):
    list_display = ("user", "customer", "supplier", "created_at")
    search_fields = ("user__username", "customer__code", "supplier__code")
    list_select_related = ("user", "customer", "supplier")


@admin.register(OrderRequest)
class OrderRequestAdmin(ReadOnlyAdmin):
    list_display = ("number", "customer", "status", "requested_delivery_date", "created_at")
    list_filter = ("status",)
    search_fields = ("number", "customer__code", "customer__name", "customer_po_no")
    list_select_related = ("customer",)


@admin.register(OutboundEmail)
class OutboundEmailAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "kind", "related_number", "to_address", "status", "attempts")
    list_filter = ("status", "kind")
    search_fields = ("related_number", "to_address")
