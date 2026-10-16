from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# /api/ altında hata sayfaları HTML değil `{"code", "detail"}` JSON'dur (DEBUG=False iken).
handler404 = "apps.core.api.views.page_not_found"
handler500 = "apps.core.api.views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.api.urls")),
    path("api/v1/masterdata/", include("apps.masterdata.api.urls")),
    path("api/v1/recipes/", include("apps.recipes.api.urls")),
    path("api/v1/inventory/", include("apps.inventory.api.urls")),
    path("api/v1/production/", include("apps.production.api.urls")),
    path("api/v1/quality/", include("apps.quality.api.urls")),
    path("api/v1/filling/", include("apps.filling.api.urls")),
    path("api/v1/workflow/", include("apps.workflow.api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
]

if settings.DEBUG:
    # Geliştirmede admin statik dosyaları uvicorn üzerinden servis edilir.
    urlpatterns += staticfiles_urlpatterns()
