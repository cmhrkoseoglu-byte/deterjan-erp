from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.portal.api import views

router = SimpleRouter()
router.register("accounts", views.PortalAccountViewSet, basename="portal-account")

urlpatterns = [
    path("me/", views.PortalMeView.as_view(), name="portal-me"),
    path("", include(router.urls)),
]
