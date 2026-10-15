from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.workflow.api import views

app_name = "workflow"

router = SimpleRouter()
router.register("tasks", views.TaskViewSet, basename="task")
router.register("notifications", views.NotificationViewSet, basename="notification")
router.register("comments", views.CommentViewSet, basename="comment")

urlpatterns = [
    path("record-history/", views.RecordHistoryView.as_view(), name="record-history"),
    path("mentionable-users/", views.MentionableUserView.as_view(), name="mentionable-users"),
    path("", include(router.urls)),
]
