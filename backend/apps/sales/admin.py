"""Yönetim paneli: satış kayıtları yalnızca görüntülenir; değişiklik servislerle (API) yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.sales.models import SalesOrder, SalesOrderLine


@admin.register(SalesOrder)
class SalesOrderAdmin(ReadOnlyAdmin):
    list_display = ("number", "customer", "order_date", "requested_delivery_date", "status")
    list_filter = ("status",)
    search_fields = ("number", "customer__name", "customer__code", "customer_po_no")
    list_select_related = ("customer",)


@admin.register(SalesOrderLine)
class SalesOrderLineAdmin(ReadOnlyAdmin):
    list_display = ("order", "line_no", "product", "quantity", "unit", "base_quantity")
    list_select_related = ("order", "product", "unit")
