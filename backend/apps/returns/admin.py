"""Yönetim paneli: iadeler yalnızca görüntülenir; değişiklik servislerle (API) yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.returns.models import CustomerReturn, CustomerReturnLine


@admin.register(CustomerReturn)
class CustomerReturnAdmin(ReadOnlyAdmin):
    list_display = ("number", "customer", "return_date", "status")
    list_filter = ("status",)
    search_fields = ("number", "customer__code", "customer__name")
    list_select_related = ("customer",)


@admin.register(CustomerReturnLine)
class CustomerReturnLineAdmin(ReadOnlyAdmin):
    list_display = ("customer_return", "line_no", "product", "lot", "quantity", "disposition")
    list_filter = ("disposition",)
    search_fields = ("customer_return__number", "lot__lot_no", "product__code")
    list_select_related = ("customer_return", "product", "lot")
