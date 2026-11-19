"""Portal okumaları. Portal uç noktalarındaki her sorgu buradaki hesap ve firma süzgeciyle başlar
(docs/plan/musteri-siparis-takibi.md §4.7)."""

from decimal import Decimal
from typing import Any

from django.db.models import Prefetch, QuerySet

from apps.core.models import User
from apps.inventory.models import GoodsReceipt, GoodsReceiptLine
from apps.masterdata.models import Customer, Supplier
from apps.portal.models import PortalAccount
from apps.purchasing import selectors as purchasing_selectors
from apps.purchasing.models import PurchaseOrder
from apps.sales import selectors as sales_selectors
from apps.sales.models import SalesOrder, Shipment
from apps.sales.waybill import customer_copy_data


def accounts() -> QuerySet[PortalAccount]:
    """Admin listesi: kullanıcı ve firmayla."""
    return PortalAccount.objects.select_related("user", "customer", "supplier")


def account_of(user: User) -> PortalAccount | None:
    """Portal kullanıcısının hesabı (firmasıyla); çalışanda ya da hesabı yoksa boş."""
    if not getattr(user, "is_portal", False):
        return None
    return PortalAccount.objects.select_related("customer", "supplier").filter(user=user).first()


def is_usable(account: PortalAccount | None) -> bool:
    """Hesap kullanılabilir mi: hesap var, kullanıcı etkin ve bağlı firma etkin."""
    return account is not None and account.user.is_active and account.firm.is_active


# --- müşteri portalı (docs/plan/musteri-siparis-takibi.md §4.3) ------------------------------


def customer_orders(customer: Customer) -> QuerySet[SalesOrder]:
    """Müşterinin onaylanmış siparişleri (sonraki durumlar dahil; onaydan sonra iptal edilen
    "İptal" görünür). Taslak ve hiç onaylanmamış iptal görünmez. Satırlar miktarlarıyla."""
    return (
        SalesOrder.objects.filter(customer=customer, confirmed_at__isnull=False)
        .annotate(due_date=sales_selectors.due_date_expression())
        .prefetch_related(
            Prefetch("lines", queryset=sales_selectors.lines_with_quantities().order_by("line_no"))
        )
        .order_by("-order_date", "-number")
    )


def customer_shipments(customer: Customer) -> QuerySet[Shipment]:
    """Müşterinin onaylı siparişlerinin sevkiyatları (iptaller hariç): planlananlar da görünür."""
    return (
        Shipment.objects.filter(
            sales_order__customer=customer, sales_order__confirmed_at__isnull=False
        )
        .exclude(status=Shipment.Status.CANCELLED)
        .select_related("sales_order")
        .prefetch_related("lines__order_line__product__base_unit", "lines__order_line__unit")
        .order_by("-planned_date", "-number")
    )


def shipment_lines(shipment: Shipment) -> list[dict[str, Any]]:
    """Sevkiyatın satırları (sipariş satırı başına): sevk edildiyse sevk edilen, değilse planlanan
    miktar; temel birimde ve sipariş birimiyle. Lot ve SKT yoktur."""
    if shipment.status == Shipment.Status.DISPATCHED:
        sent = {
            line["line_no"]: line["quantity"]
            for line in customer_copy_data(sales_selectors.waybill_data(shipment))["lines"]
        }
    else:
        sent = None
    rows = []
    for line in sorted(shipment.lines.all(), key=lambda item: item.order_line.line_no):
        order_line = line.order_line
        quantity = line.quantity if sent is None else sent.get(order_line.line_no, Decimal(0))
        rows.append(
            {
                "line_no": order_line.line_no,
                "product_code": order_line.product.code,
                "product_name": order_line.product.name,
                "quantity": quantity,
                "base_unit_code": order_line.product.base_unit.code,
                "quantity_in_unit": sales_selectors.in_order_unit(order_line, quantity),
                "unit_code": order_line.unit.code,
            }
        )
    return rows


# --- tedarikçi portalı (docs/plan/musteri-siparis-takibi.md §4.3a) ---------------------------


def supplier_orders(supplier: Supplier) -> QuerySet[PurchaseOrder]:
    """Tedarikçiye gönderilmiş satın alma siparişleri (`sent_at` dolu): Gönderildi, Kısmen teslim
    alındı, Teslim alındı ve gönderildikten sonra iptal edilen. Satırlar teslim alınan miktarla."""
    return (
        PurchaseOrder.objects.filter(supplier=supplier, sent_at__isnull=False)
        .prefetch_related(
            Prefetch("lines", queryset=purchasing_selectors.order_lines().order_by("line_no"))
        )
        .order_by("-order_date", "-number")
    )


def supplier_receipts(supplier: Supplier) -> QuerySet[GoodsReceipt]:
    """Bu tedarikçiden kaydedilmiş mal kabuller (taslak ve iptal yok); satırlar bağlı sipariş
    satırıyla."""
    return (
        GoodsReceipt.objects.filter(supplier=supplier, status=GoodsReceipt.Status.POSTED)
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=GoodsReceiptLine.objects.select_related(
                    "material", "unit", "purchase_link__order_line__order"
                ).order_by("line_no"),
            )
        )
        .order_by("-receipt_date", "-number")
    )
