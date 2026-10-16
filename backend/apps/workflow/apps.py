from django.apps import AppConfig


class WorkflowConfig(AppConfig):
    name = "apps.workflow"
    label = "workflow"
    verbose_name = "İş akışı"

    def ready(self) -> None:
        from typing import Any

        from apps.core.attachments import register_attachment_target
        from apps.core.models import User

        def is_author(user: User, comment: Any) -> bool:
            return bool(comment.author_id == user.pk)

        # Yoruma dosya / fotoğraf eki yalnızca yorumu yazan ekler (Adım 2.4).
        register_attachment_target("workflow.comment", can_add=is_author)
