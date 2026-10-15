"""İş akışı okuma sorguları ve yetki yardımcıları."""

from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, QuerySet

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.roles import YONETIM
from apps.workflow.models import Comment, Notification, Task

# Yorum yapılamayan / geçmişi panelde gösterilmeyen kayıt türleri.
_NOT_COMMENTABLE = frozenset(
    {
        "core.user",
        "core.auditlog",
        "core.documentsequence",
        "workflow.notification",
        "workflow.comment",
    }
)


def commentable_content_type(label: str) -> ContentType:
    """`"app_label.model"` → ContentType. Yalnızca proje modülleri (`apps.*`) kabul edilir;
    kullanıcı, denetim günlüğü, bildirim gibi iç kayıtlar reddedilir."""
    label = (label or "").strip().lower()
    app_label, _, model = label.partition(".")
    invalid = BusinessRuleError("invalid_record_type", "Geçersiz kayıt türü.")
    if label in _NOT_COMMENTABLE or not model:
        raise invalid
    try:
        app_config = django_apps.get_app_config(app_label)
        content_type = ContentType.objects.get_by_natural_key(app_label, model)
    except (LookupError, ContentType.DoesNotExist):
        raise invalid from None
    if not app_config.name.startswith("apps.") or content_type.model_class() is None:
        raise invalid
    return content_type


def user_can_act_on_task(user: User, task: Task) -> bool:
    """Görevi üstlenebilir/tamamlayabilir mi: admin, atanan kişi, üstlenen ya da görevin rolünde."""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_admin or user.pk in (task.assigned_user_id, task.claimed_by_id):
        return True
    return task.assigned_role is not None and user.has_role(task.assigned_role.name)


def assigned_to_q(user: User) -> Q:
    """Bana, rollerimden birine atanmış ya da üstlendiğim görevler."""
    return (
        Q(assigned_role__name__in=list(user.role_names))
        | Q(assigned_user=user)
        | Q(claimed_by=user)
    )


def tasks_visible_to(user: User) -> QuerySet[Task]:
    """Kullanıcının görebildiği görevler: `yonetim` ve admin hepsini, diğerleri kendine,
    rollerine atanmış ya da üstlendiği görevleri."""
    queryset = Task.objects.select_related(
        "assigned_role", "assigned_user", "claimed_by", "completed_by", "related_content_type"
    )
    if user.is_admin or user.has_role(YONETIM):
        return queryset
    return queryset.filter(assigned_to_q(user))


def my_tasks(user: User) -> QuerySet[Task]:
    """Görevlerim: bana ya da rollerime atanmış, ya da üstlendiğim görevler (her rol için)."""
    return tasks_visible_to(user).filter(assigned_to_q(user))


def notifications_for(user: User) -> QuerySet[Notification]:
    return Notification.objects.filter(recipient=user).select_related("related_content_type")


def unread_count(user: User) -> int:
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def comments_for(content_type: ContentType, object_id: int) -> QuerySet[Comment]:
    return (
        Comment.objects.filter(content_type=content_type, object_id=object_id)
        .select_related("author")
        .prefetch_related("mentions")
    )


def record_history(content_type: ContentType, object_id: int) -> QuerySet[AuditLog]:
    """Kaydın denetim geçmişi, yeniden eskiye."""
    return AuditLog.objects.filter(content_type=content_type, object_id=object_id).select_related(
        "actor"
    )


def mentionable_users(search: str = "", limit: int = 10) -> QuerySet[User]:
    """@bahsetme önerisi için aktif kullanıcılar."""
    queryset = User.objects.filter(is_active=True)
    search = search.strip()
    if search:
        queryset = queryset.filter(Q(username__istartswith=search) | Q(full_name__icontains=search))
    return queryset.order_by("username")[:limit]
