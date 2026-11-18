from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.ledger.api import views

app_name = "ledger"

router = SimpleRouter()
router.register("customers", views.CustomerLedgerViewSet, basename="customer")
router.register("suppliers", views.SupplierLedgerViewSet, basename="supplier")

urlpatterns = [path("", include(router.urls))]
