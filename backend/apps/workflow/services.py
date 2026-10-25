"""İş akışı servisleri: görev aç/üstlen/kapat, bildirim gönder, yorum yaz, olayları kural
tablosuna göre işle. Tüm yazma işlemleri buradadır."""

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from functools import partial
from typing import Any

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import events, records
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.services import save_with_audit
from apps.workflow import realtime, rules
from apps.workflow.models import Comment, Notification, Task
from apps.workflow.selectors import commentable_content_type, user_can_act_on_task
from apps.workflow.state import task_states

logger = logging.getLogger(__name__)

# Django kullanıcı adı karakterleri: harf, rakam ve @ . + - _
_MENTION_RE = re.compile(r"(?<![\w@.+-])@([\w.@+-]+)")
COMMENT_MAX_LENGTH = 5000
MENTION_EVENT = "comment.mention"


# --- Kayıt referansları -------------------------------------------------------------------------


def resolve_subject(subject: Mapping[str, Any] | None) -> tuple[ContentType, int, str] | None:
    """Olay payload'ındaki `{"model": "app_label.model", "id": ...}` sözlüğünü
    (ContentType, kimlik, görünen ad) üçlüsüne çevirir. Eksik ya da tanımsızsa None."""
    if not subject or not subject.get("model") or subject.get("id") is None:
        return None
    app_label, _, model = str(subject["model"]).lower().partition(".")
    try:
        content_type = ContentType.objects.get_by_natural_key(app_label, model)
    except ContentType.DoesNotExist:
        logger.warning("Olaydaki kayıt türü tanımsız: %s", subject["model"])
        return None
    label = subject.get("repr") or subject.get("number") or subject.get("lot_no") or ""
    return content_type, int(subject["id"]), str(label)[:255]


def _related_filter(content_type: ContentType, object_id: int) -> Q:
    return Q(related_content_type=content_type, related_object_id=object_id)


# --- Bildirim -----------------------------------------------------------------------------------


def role_members(roles: Iterable[str]) -> list[User]:
    """Rollere gerçekten atanmış aktif kullanıcılar (admin ayrıcalığı alıcı yapmaz)."""
    return list(User.objects.filter(is_active=True, groups__name__in=list(roles)).distinct())


def notify(
    recipients: Iterable[User],
    *,
    title: str,
    body: str = "",
    level: str = Notification.Level.INFO,
    related: tuple[ContentType, int, str] | None = None,
    task: Task | None = None,
    event_name: str = "",
    rule_code: str = "",
    exclude_user_id: int | None = None,
) -> list[Notification]:
    """Her alıcıya ayrı bildirim yazar ve commit sonrası WebSocket ile iletir.

    `exclude_user_id` (genellikle olayı tetikleyen kişi) alıcılardan çıkarılır.
    """
    if level not in Notification.Level.values:
        raise ValueError(f"Bilinmeyen bildirim düzeyi: {level}")
    unique = {u.pk: u for u in recipients if u.is_active and u.pk != exclude_user_id}
    if not unique:
        return []
    content_type, object_id, related_repr = related if related else (None, None, "")
    created = Notification.objects.bulk_create(
        [
            Notification(
                recipient=user,
                title=title[:255],
                body=body,
                level=level,
                related_content_type=content_type,
                related_object_id=object_id,
                related_repr=related_repr,
                task=task,
                event_name=event_name,
                rule_code=rule_code,
            )
            for user in unique.values()
        ]
    )
    for notification in created:
        realtime.push_to_users(
            [notification.recipient_id],
            {
                "type": "notification.created",
                "id": notification.pk,
                "title": notification.title,
                "body": notification.body,
                "level": notification.level,
                "task_id": notification.task_id,
            },
        )
    return created


def notify_roles(roles: Iterable[str], **kwargs: Any) -> list[Notification]:
    """Roldeki tüm aktif kullanıcılara bildirim (bkz. `notify`)."""
    return notify(role_members(roles), **kwargs)


def mark_notifications_read(user: User, ids: Iterable[int] | None = None) -> int:
    """Kullanıcının bildirimlerini okundu işaretler (`ids` None ise tümü). Güncellenen sayıyı döner.

    Başka kullanıcının bildirim kimlikleri sessizce yok sayılır.
    """
    queryset = Notification.objects.filter(recipient=user, read_at__isnull=True)
    if ids is not None:
        queryset = queryset.filter(pk__in=list(ids))
    count = queryset.update(read_at=timezone.now())
    if count:
        realtime.push_to_users([user.pk], {"type": "notification.read"})
    return count


# --- Görev --------------------------------------------------------------------------------------


def _task_audience(task: Task) -> set[int]:
    """Görevi ekranında görecek kullanıcılar (WebSocket ile haber verilecekler)."""
    ids: set[int] = set()
    if task.assigned_role_id:
        ids.update(
            User.objects.filter(is_active=True, groups=task.assigned_role_id).values_list(
                "pk", flat=True
            )
        )
    ids.update(pk for pk in (task.assigned_user_id, task.claimed_by_id) if pk)
    return ids


def _push_task(task: Task) -> None:
    realtime.push_to_users(
        _task_audience(task), {"type": "task.changed", "id": task.pk, "status": task.status}
    )


def create_task(
    actor: User | None,
    *,
    title: str,
    description: str = "",
    role: str | None = None,
    user: User | None = None,
    priority: int = Task.Priority.NORMAL,
    due_at: Any = None,
    related: tuple[ContentType, int, str] | None = None,
    event_name: str = "",
    rule_code: str = "",
) -> Task:
    """Görev açar, atananlara bildirim gönderir ve `task.open` olayını yayınlar.

    Rol ya da kişiden en az biri zorunludur. İşlemi yapan kişiye (`actor`) bildirim gitmez.
    """
    if not role and user is None:
        raise BusinessRuleError("task_assignee_required", "Görev bir role ya da kişiye atanmalı.")
    group = None
    if role:
        group = Group.objects.filter(name=role).first()
        if group is None:
            raise BusinessRuleError("unknown_role", f"Tanımsız rol: {role}")
    content_type, object_id, related_repr = related if related else (None, None, "")
    with transaction.atomic():
        task = save_with_audit(
            Task(
                title=title[:255],
                description=description,
                assigned_role=group,
                assigned_user=user,
                priority=priority,
                due_at=due_at,
                related_content_type=content_type,
                related_object_id=object_id,
                related_repr=related_repr,
                event_name=event_name,
                rule_code=rule_code,
            ),
            actor,
        )
        recipients = role_members([role]) if role else []
        if user is not None:
            recipients.append(user)
        notify(
            recipients,
            title=f"Yeni görev: {task.title}",
            body=description,
            related=related,
            task=task,
            event_name=event_name,
            rule_code=rule_code,
            exclude_user_id=actor.pk if actor is not None else None,
        )
        _push_task(task)
        events.publish(task_states.event_name(Task.Status.OPEN), _task_payload(task), actor)
    return task


def _task_payload(task: Task) -> dict[str, Any]:
    return {
        "model": task._meta.label_lower,
        "id": task.pk,
        "repr": task.title,
        "status": task.status,
        "rule_code": task.rule_code,
    }


def _transition_task(
    task: Task,
    to_status: str,
    actor: User | None,
    *,
    note: str = "",
    extra: Mapping[str, Any] | None = None,
) -> Task:
    actor = actor if actor is not None and actor.is_authenticated else None
    extra = dict(extra or {})
    with transaction.atomic():
        current = Task.objects.select_for_update().get(pk=task.pk)
        from_status = current.status
        task_states.assert_can_transition(from_status, to_status)
        task.status = to_status
        task.updated_by = actor
        for name, value in extra.items():
            setattr(task, name, value)
        task.save(update_fields=["status", "updated_by", "updated_at", *extra])
        action = (
            AuditLog.Action.CANCEL
            if to_status == Task.Status.CANCELLED
            else AuditLog.Action.STATUS_CHANGE
        )
        log_change(actor, task, action, {"status": [from_status, to_status]}, note)
        _push_task(task)
        events.publish(
            task_states.event_name(to_status),
            {**_task_payload(task), "from_status": from_status},
            actor,
        )
    return task


def claim_task(actor: User, task: Task) -> Task:
    """Role atanmış açık görevi üstlenir: görev `IN_PROGRESS` olur, `claimed_by` = actor.

    Yalnızca görevin rolündeki (ya da atanan) kullanıcı veya admin üstlenebilir.
    """
    if not user_can_act_on_task(actor, task):
        raise PermissionDenied("Bu görev size ya da rolünüze atanmamış.")
    if task.status == Task.Status.IN_PROGRESS:
        raise BusinessRuleError("task_already_claimed", "Görevi başka biri üstlenmiş.")
    return _transition_task(
        task,
        Task.Status.IN_PROGRESS,
        actor,
        extra={"claimed_by": actor, "claimed_at": timezone.now()},
    )


def complete_task(actor: User, task: Task, *, note: str = "") -> Task:
    """Görevi elle tamamlar. Görevin rolündeki/atanan/üstlenen kullanıcı ya da admin yapabilir."""
    if not user_can_act_on_task(actor, task):
        raise PermissionDenied("Bu görev size ya da rolünüze atanmamış.")
    return _transition_task(
        task,
        Task.Status.DONE,
        actor,
        note=note.strip(),
        extra={
            "completed_by": actor,
            "completed_at": timezone.now(),
            "completion_note": note.strip(),
        },
    )


def cancel_task(actor: User | None, task: Task, *, reason: str) -> Task:
    """Görevi iptal eder (görevler silinmez). İptal nedeni zorunludur."""
    reason = reason.strip()
    if not reason:
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    return _transition_task(
        task,
        Task.Status.CANCELLED,
        actor,
        note=reason,
        extra={"completed_at": timezone.now(), "completion_note": reason},
    )


def auto_close_tasks(
    actor: User | None,
    *,
    related: tuple[ContentType, int, str],
    rule_codes: Iterable[str],
    event_name: str,
) -> list[Task]:
    """Kayda bağlı, verilen kurallardan doğmuş açık görevleri `DONE` yapar (kapanış olayı geldi)."""
    content_type, object_id, _ = related
    open_tasks = Task.objects.filter(
        _related_filter(content_type, object_id),
        rule_code__in=list(rule_codes),
        status__in=Task.OPEN_STATUSES,
    )
    note = f"Otomatik kapandı: {event_name}"
    return [
        _transition_task(
            task,
            Task.Status.DONE,
            actor,
            note=note,
            extra={"completed_by": actor, "completed_at": timezone.now(), "completion_note": note},
        )
        for task in open_tasks
    ]


# --- Olay işleme (kural tablosu) ----------------------------------------------------------------


def process_event(event: events.Event) -> None:
    """Olayı kural tablosuna göre işler: önce bu olayla kapanan görevler kapanır, sonra yeni
    görev/bildirimler oluşur. Her kural kendi savepoint'inde çalışır; biri hata verirse loglanır,
    diğerleri etkilenmez."""
    actor = User.objects.filter(pk=event.actor_id).first() if event.actor_id else None
    for task_rule, close in rules.closing_rules_for(event.name):
        _run_rule(task_rule.code, event, partial(_apply_close, task_rule, close, event, actor))
    for rule in rules.rules_for(event.name):
        _run_rule(rule.code, event, partial(_apply_rule, rule, event, actor))


def _run_rule(code: str, event: events.Event, apply: Callable[[], object]) -> None:
    try:
        with transaction.atomic():
            apply()
    except Exception:
        logger.exception("İş akışı kuralı başarısız: kural=%s olay=%s", code, event.name)


def _apply_close(
    rule: rules.TaskRule, close: rules.CloseOn, event: events.Event, actor: User | None
) -> None:
    related = resolve_subject(close.subject(event.payload))
    if related is not None:
        auto_close_tasks(actor, related=related, rule_codes=[rule.code], event_name=event.name)


def _apply_rule(rule: rules.Rule, event: events.Event, actor: User | None) -> None:
    payload = event.payload
    if isinstance(rule, rules.TaskRule):
        for subject in rule.subjects(payload):
            _open_task_from_rule(rule, subject, event, actor)
    elif isinstance(rule, rules.NotifyRule):
        if rule.when(payload):
            extra = list(User.objects.filter(pk__in=rule.users(payload)))
            notify(
                role_members(rule.roles) + extra,
                title=rules.render(rule.title, payload),
                body=rules.render(rule.body, payload),
                level=rule.level,
                related=resolve_subject(payload),
                event_name=event.name,
                rule_code=rule.code,
                exclude_user_id=event.actor_id,
            )
    elif isinstance(rule, rules.CancelTasksRule):
        _cancel_related_tasks(rule, event, actor)


def _priority_from(subject: Mapping[str, Any]) -> int:
    value = subject.get("priority")
    return value if value in Task.Priority.values else Task.Priority.NORMAL


def _open_task_from_rule(
    rule: rules.TaskRule, subject: Mapping[str, Any], event: events.Event, actor: User | None
) -> Task | None:
    related = resolve_subject(subject)
    if related is not None:
        # Aynı kayıt için aynı kuraldan açık görev varsa yenisi açılmaz (olay tekrarı).
        duplicate = Task.objects.filter(
            _related_filter(related[0], related[1]),
            rule_code=rule.code,
            status__in=Task.OPEN_STATUSES,
        ).exists()
        if duplicate:
            return None
    return create_task(
        actor,
        title=rules.render(rule.title, subject),
        description=rules.render(rule.description, subject),
        role=rule.role,
        priority=_priority_from(subject),
        related=related,
        event_name=event.name,
        rule_code=rule.code,
    )


def _cancel_related_tasks(
    rule: rules.CancelTasksRule, event: events.Event, actor: User | None
) -> None:
    related = resolve_subject(event.payload)
    if related is None:
        return
    open_tasks = list(
        Task.objects.filter(
            _related_filter(related[0], related[1]), status__in=Task.OPEN_STATUSES
        ).select_related("assigned_role")
    )
    reason = rules.render(rule.title, event.payload)
    for task in open_tasks:
        cancel_task(actor, task, reason=reason)
    roles = {t.assigned_role.name for t in open_tasks if t.assigned_role} | set(rule.notify_roles)
    recipients = role_members(roles)
    recipients += [t.assigned_user for t in open_tasks if t.assigned_user]
    recipients += [t.claimed_by for t in open_tasks if t.claimed_by]
    notify(
        recipients,
        title=reason,
        body=rules.render(rule.body, event.payload),
        level=rule.level,
        related=related,
        event_name=event.name,
        rule_code=rule.code,
        exclude_user_id=event.actor_id,
    )


# --- Yorum --------------------------------------------------------------------------------------


def parse_mentions(body: str) -> list[User]:
    """Metindeki `@kullanıcıadı` ifadelerinden aktif kullanıcıları bulur (büyük/küçük harfe
    duyarsız)."""
    names = {m.rstrip(".") for m in _MENTION_RE.findall(body)}
    if not names:
        return []
    query = Q()
    for name in names:
        query |= Q(username__iexact=name)
    return list(User.objects.filter(query, is_active=True))


def _clean_body(body: str) -> str:
    body = body.strip()
    if not body:
        raise BusinessRuleError("comment_empty", "Yorum boş olamaz.")
    if len(body) > COMMENT_MAX_LENGTH:
        raise BusinessRuleError(
            "comment_too_long", f"Yorum en fazla {COMMENT_MAX_LENGTH} karakter olabilir."
        )
    return body


def _notify_mentions(comment: Comment, users: Iterable[User]) -> None:
    author_name = comment.author.full_name or comment.author.username
    related_repr = str(comment.related_object or "")[:255]
    notify(
        users,
        title=f"{author_name} sizden bahsetti: {related_repr}".rstrip(": "),
        body=comment.body[:500],
        related=(comment.content_type, comment.object_id, related_repr),
        event_name=MENTION_EVENT,
        exclude_user_id=comment.author_id,
    )


def add_comment(actor: User, *, content_type: str, object_id: int, body: str) -> Comment:
    """Kayda yorum ekler; bahsedilen kullanıcılara bildirim gider.

    `content_type` "app_label.model" biçimindedir (ör. "inventory.lot"). Kayıt yoksa, yazan kaydı
    kendi ekranında göremiyorsa ya da yorum yapılabilen bir tür değilse `BusinessRuleError`.
    Kaydı göremeyen kişiden bahsedilmez (bildirim gitmez).
    """
    ct = commentable_content_type(content_type)
    target = records.visible_record(
        actor, ct, object_id, message="Yorum yapılacak kayıt bulunamadı."
    )
    body = _clean_body(body)
    with transaction.atomic():
        comment = save_with_audit(
            Comment(content_type=ct, object_id=object_id, author=actor, body=body), actor
        )
        mentioned = _visible_mentions(body, target)
        comment.mentions.set(mentioned)
        _notify_mentions(comment, mentioned)
    return comment


def _visible_mentions(body: str, record: Any) -> list[User]:
    """Metinde bahsedilenlerden kaydı kendi ekranında görebilenler (diğerlerine bildirim gitmez)."""
    return [user for user in parse_mentions(body) if records.can_view(user, record)]


def edit_comment(actor: User, comment: Comment, *, body: str) -> Comment:
    """Yorumu düzenler (yalnızca yazarı). Eski metin denetim günlüğüne yazılır; yeni eklenen
    bahsedilenlere bildirim gider."""
    if comment.author_id != actor.pk:
        raise PermissionDenied("Yalnızca kendi yorumunuzu düzenleyebilirsiniz.")
    body = _clean_body(body)
    if body == comment.body:
        return comment
    with transaction.atomic():
        previous = set(comment.mentions.values_list("pk", flat=True))
        comment.body = body
        comment.edited_at = timezone.now()
        save_with_audit(comment, actor, note="Yorum düzenlendi")
        mentioned = _visible_mentions(body, comment.related_object)
        comment.mentions.set(mentioned)
        _notify_mentions(comment, [u for u in mentioned if u.pk not in previous])
    return comment
