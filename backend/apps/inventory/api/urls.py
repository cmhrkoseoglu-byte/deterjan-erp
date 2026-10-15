from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.inventory.api import views

app_name = "inventory"

router = SimpleRouter()
router.register("lots", views.LotViewSet, basename="lot")
router.register("movements", views.StockMovementViewSet, basename="movement")
router.register("balances", views.StockBalanceViewSet, basename="balance")
router.register("goods-receipts", views.GoodsReceiptViewSet, basename="goods-receipt")
router.register("adjustments", views.StockAdjustmentViewSet, basename="adjustment")
router.register("pallet-labels", views.PalletLabelViewSet, basename="pallet-label")

urlpatterns = [
    path("scan/", views.ScanView.as_view(), name="scan"),
    path("transfers/", views.TransferView.as_view(), name="transfer"),
    path("opening/import/", views.OpeningImportView.as_view(), name="opening-import"),
    path("opening/template/", views.OpeningTemplateView.as_view(), name="opening-template"),
    path("", include(router.urls)),
]
