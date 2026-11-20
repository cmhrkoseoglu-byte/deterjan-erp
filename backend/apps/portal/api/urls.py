from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.portal.api import customer, requests, supplier, views

router = SimpleRouter()
router.register("accounts", views.PortalAccountViewSet, basename="portal-account")
router.register("requests", requests.StaffRequestViewSet, basename="portal-request")

customer_router = SimpleRouter()
customer_router.register("orders", customer.CustomerOrderViewSet, basename="portal-customer-order")
customer_router.register(
    "shipments", customer.CustomerShipmentViewSet, basename="portal-customer-shipment"
)
customer_router.register(
    "requests", requests.CustomerRequestViewSet, basename="portal-customer-request"
)
customer_router.register(
    "products", requests.OrderableProductViewSet, basename="portal-customer-product"
)

supplier_router = SimpleRouter()
supplier_router.register("orders", supplier.SupplierOrderViewSet, basename="portal-supplier-order")
supplier_router.register(
    "receipts", supplier.SupplierReceiptViewSet, basename="portal-supplier-receipt"
)

urlpatterns = [
    path("me/", views.PortalMeView.as_view(), name="portal-me"),
    path(
        "customer/ledger/",
        customer.CustomerBalanceView.as_view(),
        name="portal-customer-ledger",
    ),
    path(
        "customer/ledger/statement/",
        customer.CustomerStatementView.as_view(),
        name="portal-customer-statement",
    ),
    path(
        "customer/ledger/statement-pdf/",
        customer.CustomerStatementPdfView.as_view(),
        name="portal-customer-statement-pdf",
    ),
    path(
        "customer/email-preference/",
        customer.CustomerEmailPreferenceView.as_view(),
        name="portal-customer-email-preference",
    ),
    path("customer/", include(customer_router.urls)),
    path(
        "supplier/ledger/",
        supplier.SupplierBalanceView.as_view(),
        name="portal-supplier-ledger",
    ),
    path(
        "supplier/ledger/statement/",
        supplier.SupplierStatementView.as_view(),
        name="portal-supplier-statement",
    ),
    path(
        "supplier/ledger/statement-pdf/",
        supplier.SupplierStatementPdfView.as_view(),
        name="portal-supplier-statement-pdf",
    ),
    path("supplier/", include(supplier_router.urls)),
    path("", include(router.urls)),
]
