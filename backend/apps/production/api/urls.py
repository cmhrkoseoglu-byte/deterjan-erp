from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.production.api import views

app_name = "production"

router = SimpleRouter()
router.register("orders", views.ProductionOrderViewSet, basename="order")
router.register("batches", views.ProductionBatchViewSet, basename="batch")

urlpatterns = [path("", include(router.urls))]
