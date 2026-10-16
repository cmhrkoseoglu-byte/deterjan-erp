from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.costing.api import views

app_name = "costing"

router = SimpleRouter()
router.register("lot-costs", views.LotCostViewSet, basename="lot-cost")
router.register("rates", views.CostRateViewSet, basename="rate")
router.register("standard-costs", views.StandardCostViewSet, basename="standard-cost")

REPORTS = {
    "cost-trend": (views.CostTrendView, views.CostTrendExcelView),
    "batch-variance": (views.BatchVarianceView, views.BatchVarianceExcelView),
    "scrap-cost": (views.ScrapCostView, views.ScrapCostExcelView),
    "top-materials": (views.TopMaterialsView, views.TopMaterialsExcelView),
    "stock-value": (views.StockValueView, views.StockValueExcelView),
}

urlpatterns = [
    path("", include(router.urls)),
    path("lots/<int:pk>/", views.LotCostHistoryView.as_view(), name="lot-history"),
    path("lots/<int:pk>/recalculate/", views.LotRecalculateView.as_view(), name="lot-recalculate"),
]
for name, (json_view, excel_view) in REPORTS.items():
    urlpatterns += [
        path(f"reports/{name}/", json_view.as_view(), name=f"report-{name}"),
        path(f"reports/{name}/xlsx/", excel_view.as_view(), name=f"report-{name}-xlsx"),
    ]
