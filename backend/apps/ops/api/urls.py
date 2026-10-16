from django.urls import path

from apps.ops.api import views

app_name = "ops"

urlpatterns = [
    path("status/", views.SystemStatusView.as_view(), name="status"),
    path("health/", views.OpsHealthView.as_view(), name="health"),
    path("client-errors/", views.ClientErrorView.as_view(), name="client-errors"),
]
