from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.golive.api import views

app_name = "golive"

router = SimpleRouter()
router.register("comparisons", views.StockComparisonViewSet, basename="comparison")
router.register("problems", views.ProblemReportViewSet, basename="problem")

urlpatterns = [
    path("readiness/", views.ReadinessView.as_view(), name="readiness"),
    path("go-live/", views.GoLiveView.as_view(), name="go-live"),
    path("", include(router.urls)),
]
