from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.api.serializers import AuditLogSerializer, ContentTypeField
from apps.core.models import User
from apps.workflow.models import Comment, Notification, Task
from apps.workflow.selectors import user_can_act_on_task


class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "full_name"]
        read_only_fields = fields


class RelatedRecordSerializer(serializers.Serializer):
    """İlgili kayıt: `{"model": "inventory.lot", "id": 5, "repr": "H-261015-001"}`."""

    model = serializers.CharField()
    id = serializers.IntegerField()
    repr = serializers.CharField()


def _related(content_type: Any, object_id: int | None, label: str) -> dict[str, Any] | None:
    if content_type is None or object_id is None:
        return None
    return {
        "model": f"{content_type.app_label}.{content_type.model}",
        "id": object_id,
        "repr": label,
    }


class TaskSerializer(serializers.ModelSerializer):
    assigned_role: serializers.SlugRelatedField = serializers.SlugRelatedField(
        slug_field="name", read_only=True
    )
    assigned_user = UserBriefSerializer(read_only=True)
    claimed_by = UserBriefSerializer(read_only=True)
    completed_by = UserBriefSerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    related = serializers.SerializerMethodField()
    can_act = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "status",
            "status_label",
            "priority",
            "priority_label",
            "due_at",
            "assigned_role",
            "assigned_user",
            "claimed_by",
            "claimed_at",
            "completed_by",
            "completed_at",
            "completion_note",
            "related",
            "event_name",
            "rule_code",
            "created_at",
            "updated_at",
            "can_act",
        ]
        read_only_fields = fields

    @extend_schema_field(RelatedRecordSerializer(allow_null=True))
    def get_related(self, obj: Task) -> dict[str, Any] | None:
        return _related(obj.related_content_type, obj.related_object_id, obj.related_repr)

    def get_can_act(self, obj: Task) -> bool:
        request = self.context.get("request")
        if request is None or not obj.is_open:
            return False
        return user_can_act_on_task(request.user, obj)


class TaskCompleteSerializer(serializers.Serializer):
    note = serializers.CharField(label="Not", required=False, allow_blank=True, max_length=2000)


class NotificationSerializer(serializers.ModelSerializer):
    related = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "body",
            "level",
            "related",
            "task",
            "event_name",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(RelatedRecordSerializer(allow_null=True))
    def get_related(self, obj: Notification) -> dict[str, Any] | None:
        return _related(obj.related_content_type, obj.related_object_id, obj.related_repr)

    def get_is_read(self, obj: Notification) -> bool:
        return obj.read_at is not None


class UnreadCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=500
    )
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("all") and not attrs.get("ids"):
            raise serializers.ValidationError({"ids": ["`ids` ya da `all: true` gönderilmeli."]})
        return attrs


class MarkReadResultSerializer(serializers.Serializer):
    updated = serializers.IntegerField()


class CommentSerializer(serializers.ModelSerializer):
    content_type = ContentTypeField(read_only=True)
    author = UserBriefSerializer(read_only=True)
    mentions = UserBriefSerializer(many=True, read_only=True)
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id",
            "content_type",
            "object_id",
            "author",
            "body",
            "mentions",
            "created_at",
            "edited_at",
            "can_edit",
        ]
        read_only_fields = fields

    def get_can_edit(self, obj: Comment) -> bool:
        request = self.context.get("request")
        return request is not None and obj.author_id == request.user.pk


class CommentCreateSerializer(serializers.Serializer):
    content_type = serializers.CharField(label="Kayıt türü", max_length=100)
    object_id = serializers.IntegerField(label="Kayıt no", min_value=1)
    body = serializers.CharField(label="Yorum", max_length=5000)


class CommentEditSerializer(serializers.Serializer):
    body = serializers.CharField(label="Yorum", max_length=5000)


class RecordQuerySerializer(serializers.Serializer):
    content_type = serializers.CharField(label="Kayıt türü (ör. inventory.lot)")
    object_id = serializers.IntegerField(label="Kayıt no", min_value=1)


class RecordHistorySerializer(AuditLogSerializer):
    pass
