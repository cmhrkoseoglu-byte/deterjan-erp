from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.sales.api import views

app_name = "sales"

router = SimpleRouter()
router.register("orders", views.SalesOrderViewSet, basename="order")

urlpatterns = [path("", include(router.urls))]
