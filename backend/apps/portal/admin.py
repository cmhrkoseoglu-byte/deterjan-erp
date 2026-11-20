"""Yönetim paneli: portal hesapları yalnızca görüntülenir; hesap servislerle (API) açılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.portal.models import OrderRequest, PortalAccount


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
