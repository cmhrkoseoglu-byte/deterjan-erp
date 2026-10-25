from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.personnel.api import views

app_name = "personnel"

router = SimpleRouter()
router.register("employees", views.EmployeeViewSet, basename="employee")

urlpatterns = [
    path("departments/", views.DepartmentListView.as_view(), name="departments"),
    path("linkable-users/", views.LinkableUserListView.as_view(), name="linkable-users"),
    path("", include(router.urls)),
]
