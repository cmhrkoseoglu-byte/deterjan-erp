"""İş akışı modelleri: görev, bildirim, kayda bağlı yorum.

Bu dosyada iş mantığı yoktur; yazma işlemleri `services.py` üzerinden yapılır.
"""

from typing import Any

from django.contrib.auth.models import Group
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import BaseModel, User


class Task(BaseModel):
    """Bir role ya da kişiye atanmış iş. Çoğunlukla bir olaydan kural tablosuyla doğar
    (`workflow.rules`) ve ilgili adımı tamamlayan olay gelince kendiliğinden kapanır."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Açık"
        IN_PROGRESS = "IN_PROGRESS", "Devam ediyor"
        DONE = "DONE", "Tamamlandı"
        CANCELLED = "CANCELLED", "İptal"

    class Priority(models.IntegerChoices):
        LOW = 1, "Düşük"
        NORMAL = 2, "Normal"
        HIGH = 3, "Yüksek"
        URGENT = 4, "Acil"

    OPEN_STATUSES = (Status.OPEN, Status.IN_PROGRESS)

    title = models.CharField("başlık", max_length=255)
    description = models.TextField("açıklama", blank=True)
    assigned_role = models.ForeignKey(
        Group,
        verbose_name="atanan rol",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_tasks",
    )
    assigned_user = models.ForeignKey(
        User,
        verbose_name="atanan kişi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    # Durum yalnızca workflow.services ile değişir.
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
        editable=False,
    )
    priority = models.PositiveSmallIntegerField(
        "öncelik", choices=Priority.choices, default=Priority.NORMAL
    )
    due_at = models.DateTimeField("son tarih", null=True, blank=True)

    related_content_type = models.ForeignKey(
        ContentType,
        verbose_name="ilgili kayıt türü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    related_object_id = models.BigIntegerField("ilgili kayıt no", null=True, blank=True)
    related_object = GenericForeignKey("related_content_type", "related_object_id")
    related_repr = models.CharField("ilgili kayıt", max_length=255, blank=True)

    event_name = models.CharField("kaynak olay", max_length=100, blank=True, db_index=True)
    rule_code = models.CharField("kural", max_length=64, blank=True, db_index=True)

    claimed_by = models.ForeignKey(
        User,
        verbose_name="üstlenen",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="claimed_tasks",
        editable=False,
    )
    claimed_at = models.DateTimeField("üstlenme zamanı", null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(
        User,
        verbose_name="tamamlayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    completed_at = models.DateTimeField("kapanma zamanı", null=True, blank=True, editable=False)
    completion_note = models.TextField("kapanış notu", blank=True, editable=False)

    class Meta:
        verbose_name = "görev"
        verbose_name_plural = "görevler"
        ordering = ["-priority", "created_at", "id"]
        indexes = [
            models.Index(fields=["related_content_type", "related_object_id"]),
            models.Index(fields=["status", "assigned_role"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(assigned_role__isnull=False)
                | models.Q(assigned_user__isnull=False),
                name="workflow_task_has_assignee",
            )
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES


class Notification(models.Model):
    """Bir kullanıcıya giden bildirim. Role giden bildirim, roldeki her aktif kullanıcıya ayrı
    kayıt olarak yazılır. Bildirimler denetim günlüğüne yazılmaz (yalnızca okundu bilgisi
    değişir)."""

    class Level(models.TextChoices):
        INFO = "INFO", "Bilgi"
        WARNING = "WARNING", "Uyarı"
        CRITICAL = "CRITICAL", "Kritik"

    recipient = models.ForeignKey(
        User, verbose_name="alıcı", on_delete=models.PROTECT, related_name="notifications"
    )
    title = models.CharField("başlık", max_length=255)
    body = models.TextField("metin", blank=True)
    level = models.CharField("düzey", max_length=16, choices=Level.choices, default=Level.INFO)

    related_content_type = models.ForeignKey(
        ContentType,
        verbose_name="ilgili kayıt türü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    related_object_id = models.BigIntegerField("ilgili kayıt no", null=True, blank=True)
    related_object = GenericForeignKey("related_content_type", "related_object_id")
    related_repr = models.CharField("ilgili kayıt", max_length=255, blank=True)

    task = models.ForeignKey(
        Task,
        verbose_name="görev",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notifications",
    )
    event_name = models.CharField("kaynak olay", max_length=100, blank=True)
    rule_code = models.CharField("kural", max_length=64, blank=True)
    read_at = models.DateTimeField("okunma zamanı", null=True, blank=True, db_index=True)
    created_at = models.DateTimeField("oluşturulma zamanı", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "bildirim"
        verbose_name_plural = "bildirimler"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at"])]

    def __str__(self) -> str:
        return self.title


class Comment(BaseModel):
    """Bir kayda (lot, üretim emri vb.) bağlı yorum. Silinmez; düzenlenirse eski metin denetim
    günlüğüne yazılır. Metindeki `@kullanıcıadı` bahsedilen kullanıcıya bildirim gönderir."""

    content_type = models.ForeignKey(
        ContentType, verbose_name="kayıt türü", on_delete=models.PROTECT, related_name="+"
    )
    object_id = models.BigIntegerField("kayıt no")
    related_object = GenericForeignKey("content_type", "object_id")
    author = models.ForeignKey(
        User, verbose_name="yazan", on_delete=models.PROTECT, related_name="comments"
    )
    body = models.TextField("yorum")
    mentions = models.ManyToManyField(
        User, verbose_name="bahsedilenler", blank=True, related_name="mentioned_in_comments"
    )
    edited_at = models.DateTimeField("düzenlenme zamanı", null=True, blank=True)

    class Meta:
        verbose_name = "yorum"
        verbose_name_plural = "yorumlar"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.author}: {self.body[:50]}"

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Yorumlar silinemez.")
