from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.purchasing.api import views

app_name = "purchasing"

router = SimpleRouter()
router.register("requests", views.PurchaseRequestViewSet, basename="request")
router.register("orders", views.PurchaseOrderViewSet, basename="order")

urlpatterns = [
    path(
        "expected-deliveries/", views.ExpectedDeliveriesView.as_view(), name="expected-deliveries"
    ),
    path("suggestions/", views.SuggestionsView.as_view(), name="suggestions"),
    path(
        "supplier-performance/",
        views.SupplierPerformanceView.as_view(),
        name="supplier-performance",
    ),
    path("receipt-links/", views.ReceiptLinksView.as_view(), name="receipt-links"),
    path("settings/", views.PurchasingSettingsView.as_view(), name="settings"),
    path("", include(router.urls)),
]
