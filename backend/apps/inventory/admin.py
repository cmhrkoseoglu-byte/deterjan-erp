"""Yönetim paneli: stok kayıtları yalnızca görüntülenir. Stok, lot ve belgeler servislerle
(API ekranlarından) değişir; panelden hareket yazmak hareket defterini atlamak olurdu."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    Lot,
    LotLink,
    StockAdjustment,
    StockAdjustmentLine,
    StockBalance,
    StockMovement,
)


@admin.register(Lot)
class LotAdmin(ReadOnlyAdmin):
    list_display = ("lot_no", "material", "status", "source", "expiry_date", "created_at")
    list_filter = ("status", "source", "material__material_type")
    search_fields = ("lot_no", "supplier_lot_no", "material__code", "material__name")
    list_select_related = ("material",)


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = (
        "created_at",
        "movement_type",
        "material",
        "lot",
        "location",
        "quantity",
        "document_number",
    )
    list_filter = ("movement_type",)
    search_fields = ("lot__lot_no", "material__code", "document_number")
    date_hierarchy = "created_at"
    list_select_related = ("material", "lot", "location")


@admin.register(StockBalance)
class StockBalanceAdmin(ReadOnlyAdmin):
    list_display = ("material", "lot", "location", "quantity", "updated_at")
    search_fields = ("lot__lot_no", "material__code", "location__code")
    list_select_related = ("material", "lot", "location")


@admin.register(LotLink)
class LotLinkAdmin(ReadOnlyAdmin):
    list_display = ("parent_lot", "child_lot", "quantity", "created_at")
    search_fields = ("parent_lot__lot_no", "child_lot__lot_no")
    list_select_related = ("parent_lot", "child_lot")


class GoodsReceiptLineInline(admin.TabularInline):
    model = GoodsReceiptLine
    extra = 0
    can_delete = False
    fields = ("line_no", "material", "quantity", "unit", "supplier_lot_no", "created_lot")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(ReadOnlyAdmin):
    list_display = ("number", "supplier", "receipt_date", "status")
    list_filter = ("status",)
    search_fields = ("number", "delivery_note_no", "supplier__name")
    inlines = (GoodsReceiptLineInline,)


class StockAdjustmentLineInline(admin.TabularInline):
    model = StockAdjustmentLine
    extra = 0
    can_delete = False
    fields = ("line_no", "lot", "location", "system_quantity", "counted_quantity", "reason")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(ReadOnlyAdmin):
    list_display = ("number", "adjustment_date", "status")
    list_filter = ("status",)
    search_fields = ("number",)
    inlines = (StockAdjustmentLineInline,)
