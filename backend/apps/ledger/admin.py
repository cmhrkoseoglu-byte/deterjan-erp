"""Yönetim paneli: cari hareketler yalnızca görüntülenir; kayıt servislerle (API) yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.ledger.models import LedgerEntry, ShipmentLinePrice


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("number", "entry_date", "kind", "customer", "supplier", "currency", "debit")
    list_filter = ("kind", "currency")
    search_fields = ("number", "customer__code", "customer__name", "supplier__code")
    list_select_related = ("customer", "supplier")


@admin.register(ShipmentLinePrice)
class ShipmentLinePriceAdmin(ReadOnlyAdmin):
    list_display = ("shipment_line", "unit_price", "currency")
    list_select_related = ("shipment_line",)
