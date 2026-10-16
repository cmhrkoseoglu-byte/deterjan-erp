from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.sales.api import views

app_name = "sales"

router = SimpleRouter()
router.register("orders", views.SalesOrderViewSet, basename="order")
router.register("shipments", views.ShipmentViewSet, basename="shipment")
router.register("shipped-lots", views.ShippedLotViewSet, basename="shipped-lot")

urlpatterns = [
    # Spesifikasyondaki yol (sonda eğik çizgi yok): /api/v1/sales/shipments/{id}/waybill.pdf
    path(
        "shipments/<int:pk>/waybill.pdf",
        views.ShipmentViewSet.as_view({"get": "waybill_pdf"}),
        name="shipment-waybill-pdf-file",
    ),
    path("", include(router.urls)),
]
