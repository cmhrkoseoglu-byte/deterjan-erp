"""Yönetim paneli: satın alma kayıtları yalnızca görüntülenir; değişiklik servislerle yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(ReadOnlyAdmin):
    list_display = ("number", "supplier", "order_date", "currency", "status")
    list_filter = ("status", "currency")
    search_fields = ("number", "supplier__name", "supplier__code")
    list_select_related = ("supplier",)


@admin.register(PurchaseOrderLine)
class PurchaseOrderLineAdmin(ReadOnlyAdmin):
    list_display = ("order", "line_no", "material", "quantity", "unit", "expected_date")
    list_select_related = ("order", "material", "unit")


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(ReadOnlyAdmin):
    list_display = ("number", "material", "quantity", "need_date", "source", "status")
    list_filter = ("status", "source")
    search_fields = ("number", "material__code", "material__name")
    list_select_related = ("material",)
