from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.maintenance.api import views

app_name = "maintenance"

router = SimpleRouter()
router.register("plans", views.MaintenancePlanViewSet, basename="plan")
router.register("work-orders", views.WorkOrderViewSet, basename="work-order")
router.register("downtimes", views.DowntimeViewSet, basename="downtime")
router.register("changeover-rules", views.ChangeoverRuleViewSet, basename="changeover-rule")

urlpatterns = [
    path("breakdowns/", views.BreakdownView.as_view(), name="breakdowns"),
    path("cleanings/", views.CleaningView.as_view(), name="cleanings"),
    path("cleaning-check/", views.CleaningCheckView.as_view(), name="cleaning-check"),
    path("downtime-summary/", views.DowntimeSummaryView.as_view(), name="downtime-summary"),
    path("calibration/", views.CalibrationStatusView.as_view(), name="calibration"),
    path("settings/", views.MaintenanceSettingsView.as_view(), name="settings"),
    path("", include(router.urls)),
]
