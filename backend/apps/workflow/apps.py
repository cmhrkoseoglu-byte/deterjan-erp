from django.apps import AppConfig


class WorkflowConfig(AppConfig):
    name = "apps.workflow"
    label = "workflow"
    verbose_name = "İş akışı"

    def ready(self) -> None:
        from typing import Any

        from apps.core.attachments import register_attachment_target
        from apps.core.models import User
        from apps.core.records import register_record_type

        def is_author(user: User, comment: Any) -> bool:
            return bool(comment.author_id == user.pk)

        # Yoruma dosya / fotoğraf eki yalnızca yorumu yazan ekler (Adım 2.4).
        register_attachment_target("workflow.comment", can_add=is_author)
        # Yorumun ekini, yorumun bağlı olduğu kaydı görebilen görür. Yoruma yorum yazılmaz.
        register_record_type(
            "workflow.comment", parent=lambda comment: comment.related_object, commentable=False
        )
        _register_rules()


def _register_rules() -> None:
    """Her kuralın rolünü ve gerektirdiği yetkiyi core'un kayıt defterine yazar (plan §5.1):
    "kimse kalmıyor" uyarısı, canlıya geçiş hazırlık listesi ve sistem durumu buradan okur."""
    from apps.core.access import register_rule
    from apps.workflow import rules

    for rule in rules.RULES:
        if isinstance(rule, rules.TaskRule):
            register_rule(rule.code, "task", (rule.role,), rule.requires)
        elif isinstance(rule, rules.NotifyRule):
            register_rule(rule.code, "notify", rule.roles, rule.requires)
        else:
            register_rule(rule.code, "cancel", rule.notify_roles, rule.requires)
