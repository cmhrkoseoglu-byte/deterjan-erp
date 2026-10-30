from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.costing.api import views

app_name = "costing"

router = SimpleRouter()
router.register("lot-costs", views.LotCostViewSet, basename="lot-cost")
router.register("rates", views.CostRateViewSet, basename="rate")
router.register("standard-costs", views.StandardCostViewSet, basename="standard-cost")
router.register("wages", views.EmployeeWageViewSet, basename="wage")

PERSONNEL_MONTH = "personnel-costs/<int:year>/<int:month>"

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
    path(f"{PERSONNEL_MONTH}/", views.PersonnelCostView.as_view(), name="personnel-cost"),
    path(
        f"{PERSONNEL_MONTH}/xlsx/",
        views.PersonnelCostExcelView.as_view(),
        name="personnel-cost-xlsx",
    ),
    path(
        f"{PERSONNEL_MONTH}/labor-rate/",
        views.PersonnelLaborRateView.as_view(),
        name="personnel-cost-labor-rate",
    ),
    path("cost-centers/", views.CostCenterView.as_view(), name="cost-centers"),
    path(
        "personnel-cost-settings/",
        views.PersonnelCostSettingsView.as_view(),
        name="personnel-cost-settings",
    ),
]
for name, (json_view, excel_view) in REPORTS.items():
    urlpatterns += [
        path(f"reports/{name}/", json_view.as_view(), name=f"report-{name}"),
        path(f"reports/{name}/xlsx/", excel_view.as_view(), name=f"report-{name}-xlsx"),
    ]
