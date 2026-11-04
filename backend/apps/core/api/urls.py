from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.core.api import coding, views

app_name = "core"

router = SimpleRouter()
router.register("users", views.UserViewSet, basename="user")
router.register("audit-log", views.AuditLogViewSet, basename="audit-log")
router.register("attachments", views.AttachmentViewSet, basename="attachment")

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("site/", views.SiteInfoView.as_view(), name="site-info"),
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
    path("coding/types/", coding.CodeTypeListView.as_view(), name="coding-types"),
    path("coding/types/<str:key>/", coding.CodeTypeDetailView.as_view(), name="coding-type"),
    path(
        "coding/types/<str:key>/preview/",
        coding.CodeTypePreviewView.as_view(),
        name="coding-type-preview",
    ),
    path(
        "coding/types/<str:key>/revisions/",
        coding.CodeSchemeRevisionListView.as_view(),
        name="coding-type-revisions",
    ),
    path("coding/suggest/<str:key>/", coding.CodeSuggestView.as_view(), name="coding-suggest"),
    path("", include(router.urls)),
]
