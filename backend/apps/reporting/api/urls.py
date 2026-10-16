from django.urls import path

from apps.reporting.api import views

app_name = "reporting"

urlpatterns = [
    path("dashboards/", views.DashboardListView.as_view(), name="dashboards"),
    path("dashboards/<slug:code>/", views.DashboardView.as_view(), name="dashboard"),
    path("reports/", views.ReportListView.as_view(), name="reports"),
    path("reports/<slug:code>/", views.ReportView.as_view(), name="report"),
    path("reports/<slug:code>/export/", views.ReportExportView.as_view(), name="report-export"),
    path("jobs/", views.ReportJobListView.as_view(), name="jobs"),
    path("jobs/<int:pk>/", views.ReportJobDetailView.as_view(), name="job"),
    path("jobs/<int:pk>/download/", views.ReportJobDownloadView.as_view(), name="job-download"),
]
