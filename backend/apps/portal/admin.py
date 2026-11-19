"""Yönetim paneli: portal hesapları yalnızca görüntülenir; hesap servislerle (API) açılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.portal.models import PortalAccount


@admin.register(PortalAccount)
class PortalAccountAdmin(ReadOnlyAdmin):
    list_display = ("user", "customer", "supplier", "created_at")
    search_fields = ("user__username", "customer__code", "supplier__code")
    list_select_related = ("user", "customer", "supplier")
