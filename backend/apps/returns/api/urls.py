from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.returns.api import views

app_name = "returns"

router = SimpleRouter()
router.register("", views.CustomerReturnViewSet, basename="return")

urlpatterns = [path("", include(router.urls))]
