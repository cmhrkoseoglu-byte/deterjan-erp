from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.core.api import views

app_name = "core"

router = SimpleRouter()
router.register("users", views.UserViewSet, basename="user")
router.register("audit-log", views.AuditLogViewSet, basename="audit-log")
router.register("attachments", views.AttachmentViewSet, basename="attachment")

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("auth/security/", views.SecurityStatusView.as_view(), name="auth-security"),
    path("auth/password/", views.PasswordChangeView.as_view(), name="auth-password"),
    path("auth/otp/setup/", views.OtpSetupView.as_view(), name="auth-otp-setup"),
    path("auth/otp/confirm/", views.OtpConfirmView.as_view(), name="auth-otp-confirm"),
    path(
        "auth/otp/recovery-codes/",
        views.OtpRecoveryCodesView.as_view(),
        name="auth-otp-recovery-codes",
    ),
    path("auth/otp/disable/", views.OtpDisableView.as_view(), name="auth-otp-disable"),
    path("auth/field-device/", views.FieldDeviceView.as_view(), name="auth-field-device"),
    path("", include(router.urls)),
]
