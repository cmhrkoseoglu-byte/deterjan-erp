from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.core.api import views

app_name = "core"

router = SimpleRouter()
router.register("users", views.UserViewSet, basename="user")
router.register("audit-log", views.AuditLogViewSet, basename="audit-log")

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("", include(router.urls)),
]
