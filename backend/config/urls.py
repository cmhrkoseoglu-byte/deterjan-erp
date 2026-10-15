from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.api.urls")),
]

if settings.DEBUG:
    # Geliştirmede admin statik dosyaları uvicorn üzerinden servis edilir.
    urlpatterns += staticfiles_urlpatterns()
