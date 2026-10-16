from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.hse.api import views

app_name = "hse"

router = SimpleRouter()
router.register("hazard-statements", views.HazardStatementViewSet, basename="hazard-statement")
router.register("material-hazards", views.MaterialHazardViewSet, basename="material-hazard")
router.register("sds", views.SafetyDataSheetViewSet, basename="sds")
router.register("storage-limits", views.StorageLimitViewSet, basename="storage-limit")
router.register("waste-contractors", views.WasteContractorViewSet, basename="waste-contractor")
router.register("waste-records", views.WasteRecordViewSet, basename="waste-record")
router.register("incidents", views.IncidentViewSet, basename="incident")

urlpatterns = [
    path(
        "materials/<int:material_id>/hazard/",
        views.MaterialHazardView.as_view(),
        name="material-hazard-detail",
    ),
    path("sds-gaps/", views.SdsGapsView.as_view(), name="sds-gaps"),
    path("sds-gaps/export/", views.SdsGapsExportView.as_view(), name="sds-gaps-export"),
    path(
        "storage-utilisation/",
        views.StorageUtilisationView.as_view(),
        name="storage-utilisation",
    ),
    path("summary/", views.HseSummaryView.as_view(), name="summary"),
    path("settings/", views.HseSettingsView.as_view(), name="settings"),
    path("", include(router.urls)),
]
