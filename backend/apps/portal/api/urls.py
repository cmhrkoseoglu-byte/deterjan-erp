from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.portal.api import customer, views

router = SimpleRouter()
router.register("accounts", views.PortalAccountViewSet, basename="portal-account")

customer_router = SimpleRouter()
customer_router.register("orders", customer.CustomerOrderViewSet, basename="portal-customer-order")
customer_router.register(
    "shipments", customer.CustomerShipmentViewSet, basename="portal-customer-shipment"
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
    path("customer/", include(customer_router.urls)),
    path("", include(router.urls)),
]
