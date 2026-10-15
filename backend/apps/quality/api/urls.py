from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.quality.api import views

app_name = "quality"

router = SimpleRouter()
router.register("tests", views.TestDefinitionViewSet, basename="test")
router.register("specifications", views.SpecificationViewSet, basename="specification")
router.register("specification-lines", views.SpecificationLineViewSet, basename="spec-line")
router.register("samples", views.SampleViewSet, basename="sample")
router.register("decisions", views.QualityDecisionViewSet, basename="decision")

urlpatterns = [path("", include(router.urls))]
