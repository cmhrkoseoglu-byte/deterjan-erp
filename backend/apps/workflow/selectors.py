"""İş akışı okuma sorguları ve yetki yardımcıları."""

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q, QuerySet

from apps.core import records
from apps.core.models import AuditLog, User
from apps.core.permissions import has_access, is_admin
from apps.workflow import rules
from apps.workflow.access import ALL_TASKS
from apps.workflow.models import Comment, Notification, Task


def commentable_content_type(label: str) -> ContentType:
    """`"app_label.model"` → ContentType. Yalnızca yorum ve geçmiş paneli açılabilen, okuma
    kuralıyla kayıtlı türler kabul edilir (`core.records`); diğerleri `invalid_record_type`."""
    return records.content_type_for(label, commentable=True)


def visible_record_for(user: User, content_type: ContentType, object_id: int) -> models.Model:
    """Kullanıcının görebildiği kayıt; yoksa ya da göremiyorsa `record_not_found`."""
    return records.visible_record(user, content_type, object_id)


def task_requirement(task: Task) -> tuple[str, str] | None:
    """Görevin kuralının gerektirdiği yetki: `(bölüm anahtarı, düzey)`.

    Kuralsız görev (`rule_code` boş) ya da artık tabloda olmayan kuralın görevi yetki istemez;
    bunlarda bugünkü gibi yalnız rol ya da atanan kişi bakılır."""
    if not task.rule_code:
        return None
    rule = rules.rule_by_code(task.rule_code)
    if not isinstance(rule, rules.TaskRule):
        return None
    return rule.requires


def _lacked_rule_codes(user: User) -> list[str]:
    """Kişinin gerektirdiği yetkisi olmadığı görev kurallarının kodları (admin için boş)."""
    return [
        rule.code
        for rule in rules.RULES
        if isinstance(rule, rules.TaskRule)
        and rule.requires is not None
        and not has_access(user, *rule.requires)
    ]


def user_can_act_on_task(user: User, task: Task) -> bool:
    """Görevi üstlenebilir/tamamlayabilir mi (karar 5, plan §5.7)?

    Admin her görevde. Öteki kişi görevin rolündeyse ya da görev ona atanmışsa, ve kuralın
    gerektirdiği yetkisi varsa. Görevi üstlenmiş olmak tek başına yetmez: rolünü ya da yetkisini
    kaybeden üstlenen tamamlayamaz, yetkili başka bir üye tamamlar."""
    if not user.is_authenticated or not user.is_active:
        return False
    if is_admin(user):
        return True
    requirement = task_requirement(task)
    if requirement is not None and not has_access(user, *requirement):
        return False
    if user.pk == task.assigned_user_id:
        return True
    return task.assigned_role is not None and user.has_role(task.assigned_role.name)


def assigned_to_q(user: User) -> Q:
    """Görevlerim: bana atanmış görevler ve rollerimden birine atanmış, kuralın gerektirdiği
    yetkisi olduğum görevler (karar 5). Üstlenmiş olmak tek başına görev göstermez."""
    own_roles = Q(assigned_role__name__in=list(user.role_names))
    lacked = _lacked_rule_codes(user)
    if lacked:
        own_roles &= ~Q(rule_code__in=lacked)
    return own_roles | Q(assigned_user=user)


def tasks_visible_to(user: User) -> QuerySet[Task]:
    """Kullanıcının görebildiği görevler (plan §5.7).

    Admin hepsini görür. Öteki kişi Görevlerim'deki görevleri (`assigned_to_q`) görür; "Tüm
    birimlerin görevleri: Görür" yetkisi olan, rollerinde olmayan görevleri de bağlı kayda göre
    süzülmeden görür (rolsüz, kişiye atanmış görevler dahil). Kişinin kendi rollerinin
    görevlerinde karar 5 geçerlidir: kuralın yetkisi yoksa görmez."""
    queryset = Task.objects.select_related(
        "assigned_role", "assigned_user", "claimed_by", "completed_by", "related_content_type"
    )
    if is_admin(user):
        return queryset
    visible = assigned_to_q(user)
    if has_access(user, ALL_TASKS):
        visible |= Q(assigned_role__isnull=True) | ~Q(assigned_role__name__in=list(user.role_names))
    return queryset.filter(visible)


def my_tasks(user: User) -> QuerySet[Task]:
    """Görevlerim: bana atanmış ve rollerime atanmış, yetkisi olduğum görevler."""
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
    """@bahsetme önerisi için aktif çalışanlar (portal kullanıcıları hariç)."""
    queryset = User.objects.filter(is_active=True, account_type=User.AccountType.STAFF)
    search = search.strip()
    if search:
        queryset = queryset.filter(Q(username__istartswith=search) | Q(full_name__icontains=search))
    return queryset.order_by("username")[:limit]


def mentionable_users_for(record: models.Model, search: str = "", limit: int = 10) -> list[User]:
    """Bu kayıtta @bahsedilebilecek kişiler: kaydı kendi ekranında görebilen aktif kullanıcılar."""
    candidates = mentionable_users(search, limit=limit * 5).prefetch_related("groups")
    return [user for user in candidates if records.can_view(user, record)][:limit]
