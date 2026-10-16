from django.urls import path

from apps.traceability.api import views

app_name = "traceability"

urlpatterns = [
    path("lots/<int:pk>/backward/", views.BackwardTraceView.as_view(), name="backward"),
    path("lots/<int:pk>/forward/", views.ForwardTraceView.as_view(), name="forward"),
    path("recall/", views.RecallView.as_view(), name="recall"),
    path("recall/xlsx/", views.RecallExcelView.as_view(), name="recall-xlsx"),
    path("recall/pdf/", views.RecallPdfView.as_view(), name="recall-pdf"),
]
