from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.workflow.models import Comment, Notification, Task


@admin.register(Task)
class TaskAdmin(ReadOnlyAdmin):
    list_display = ("title", "status", "priority", "assigned_role", "assigned_user", "created_at")
    list_filter = ("status", "priority", "assigned_role", "rule_code")
    search_fields = ("title", "related_repr")
    date_hierarchy = "created_at"
    list_select_related = ("assigned_role", "assigned_user")


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdmin):
    list_display = ("title", "recipient", "level", "created_at", "read_at")
    list_filter = ("level", "rule_code")
    search_fields = ("title", "recipient__username")
    date_hierarchy = "created_at"
    list_select_related = ("recipient",)


@admin.register(Comment)
class CommentAdmin(ReadOnlyAdmin):
    list_display = ("author", "content_type", "object_id", "created_at", "edited_at")
    list_filter = ("content_type",)
    search_fields = ("body", "author__username")
    list_select_related = ("author", "content_type")
