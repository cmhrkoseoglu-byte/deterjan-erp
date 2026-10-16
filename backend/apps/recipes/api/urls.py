from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.recipes.api import views

app_name = "recipes"

router = SimpleRouter()
router.register("recipes", views.RecipeViewSet, basename="recipe")
router.register("versions", views.RecipeVersionViewSet, basename="version")
router.register("lines", views.RecipeLineViewSet, basename="line")
router.register("steps", views.RecipeStepViewSet, basename="step")

urlpatterns = [
    path("import/template/", views.RecipeImportTemplateView.as_view(), name="import-template"),
    path("import/", views.RecipeImportView.as_view(), name="import"),
    path("", include(router.urls)),
]
