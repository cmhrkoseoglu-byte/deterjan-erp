from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.filling.api import views

app_name = "filling"

router = SimpleRouter()
router.register("packaging-specs", views.PackagingSpecViewSet, basename="packaging-spec")
router.register(
    "packaging-spec-lines", views.PackagingSpecLineViewSet, basename="packaging-spec-line"
)
router.register("orders", views.FillingOrderViewSet, basename="order")
router.register("runs", views.FillingRunViewSet, basename="run")

urlpatterns = [path("", include(router.urls))]
