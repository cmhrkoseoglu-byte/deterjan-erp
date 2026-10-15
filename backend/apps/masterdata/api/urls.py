from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.masterdata.api import views

app_name = "masterdata"

router = SimpleRouter()
router.register("units", views.UnitOfMeasureViewSet, basename="unit")
router.register("categories", views.MaterialCategoryViewSet, basename="category")
router.register("materials", views.MaterialViewSet, basename="material")
router.register("conversions", views.MaterialUnitConversionViewSet, basename="conversion")
router.register("warehouses", views.WarehouseViewSet, basename="warehouse")
router.register("locations", views.LocationViewSet, basename="location")
router.register("equipment", views.EquipmentViewSet, basename="equipment")
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("printers", views.PrinterViewSet, basename="printer")

urlpatterns = [
    path("label-settings/", views.LabelSettingsView.as_view(), name="label-settings"),
    path(
        "import/templates/<str:kind>/",
        views.ImportTemplateView.as_view(),
        name="import-template",
    ),
    path("import/<str:kind>/", views.ImportView.as_view(), name="import"),
    path("", include(router.urls)),
]
