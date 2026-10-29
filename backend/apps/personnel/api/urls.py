from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.personnel.api import views

app_name = "personnel"

router = SimpleRouter()
router.register("employees", views.EmployeeViewSet, basename="employee")
router.register("documents", views.EmployeeDocumentViewSet, basename="document")
router.register("attendance/holidays", views.PublicHolidayViewSet, basename="holiday")

MONTH = "attendance/<int:year>/<int:month>"

urlpatterns = [
    path("departments/", views.DepartmentListView.as_view(), name="departments"),
    path("linkable-users/", views.LinkableUserListView.as_view(), name="linkable-users"),
    path("attendance/days/", views.AttendanceDayView.as_view(), name="attendance-day"),
    path("attendance/ranges/", views.AttendanceRangeView.as_view(), name="attendance-range"),
    path(
        "attendance/settings/",
        views.AttendanceSettingsView.as_view(),
        name="attendance-settings",
    ),
    path(f"{MONTH}/", views.AttendanceGridView.as_view(), name="attendance-grid"),
    path(f"{MONTH}/approve/", views.AttendanceApproveView.as_view(), name="attendance-approve"),
    path(f"{MONTH}/reopen/", views.AttendanceReopenView.as_view(), name="attendance-reopen"),
    path(f"{MONTH}/export/", views.AttendanceExportView.as_view(), name="attendance-export"),
    path("", include(router.urls)),
]
