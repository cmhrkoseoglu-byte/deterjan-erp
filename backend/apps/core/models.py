"""Çekirdek modeller: kullanıcı, ortak soyut modeller, denetim günlüğü, belge numara sayaçları.

Bu dosyada iş mantığı yoktur; yazma işlemleri `services.py` ve `audit.py` üzerinden yapılır.
"""

import os
import uuid
from collections.abc import Collection
from functools import cached_property
from typing import Any, ClassVar, Self

from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from apps.core.roles import ADMIN


class User(AbstractUser):
    """Sistem kullanıcısı. Roller Django `Group` ilişkisiyle tutulur (grup adı = rol kodu)."""

    full_name = models.CharField("ad soyad", max_length=150, blank=True)
    phone = models.CharField("telefon", max_length=32, blank=True)

    class Meta:
        verbose_name = "kullanıcı"
        verbose_name_plural = "kullanıcılar"
        ordering = ["username"]

    def __str__(self) -> str:
        return self.full_name or self.username

    @cached_property
    def role_names(self) -> frozenset[str]:
        """Kullanıcının rol kodları (önbellekli; rol değişince `refresh_roles()` çağrılır)."""
        return frozenset(self.groups.values_list("name", flat=True))

    @property
    def roles(self) -> list[str]:
        """Rol kodları, alfabetik sıralı."""
        return sorted(self.role_names)

    def has_role(self, *roles: str) -> bool:
        """Kullanıcı verilen rollerden en az birine sahipse True.

        Yalnızca gerçekten atanmış rollere bakar; admin/superuser ayrıcalığı
        `is_admin` ile ayrıca kontrol edilir (bkz. `core.permissions.HasRole`).
        """
        return bool(self.role_names.intersection(roles))

    @property
    def is_admin(self) -> bool:
        """Superuser ya da `admin` rolündeki kullanıcı: rol korumalı her uç noktaya erişir."""
        return self.is_superuser or self.has_role(ADMIN)

    def refresh_roles(self) -> None:
        """Rol önbelleğini temizler."""
        self.__dict__.pop("role_names", None)


class BaseModel(models.Model):
    """Tüm iş modellerinin atası: oluşturma/güncelleme zamanı ve kullanıcısı."""

    created_at = models.DateTimeField("oluşturulma zamanı", auto_now_add=True)
    updated_at = models.DateTimeField("güncellenme zamanı", auto_now=True)
    # null=True: sistem işlemleri (komutlar, arka plan işleri) için.
    created_by = models.ForeignKey(
        User,
        verbose_name="oluşturan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    updated_by = models.ForeignKey(
        User,
        verbose_name="güncelleyen",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        abstract = True


class MasterDataModel(BaseModel):
    """Ana veriler için: silinmez, `is_active=False` ile pasife alınır."""

    is_active = models.BooleanField("aktif", default=True, db_index=True)

    class Meta:
        abstract = True


class DocumentModel(BaseModel):
    """Durumlu belgeler için. Durum yalnızca `core.services.transition_status` ile değişir."""

    number = models.CharField("belge no", max_length=32, unique=True, editable=False)
    status = models.CharField("durum", max_length=32, db_index=True, editable=False)
    cancelled_at = models.DateTimeField("iptal zamanı", null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(
        User,
        verbose_name="iptal eden",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    cancel_reason = models.TextField("iptal nedeni", blank=True, editable=False)

    # Yalnızca core.services (create_document, transition_status, cancel_document) yazar.
    STATE_FIELDS: ClassVar[tuple[str, ...]] = (
        "number",
        "status",
        "cancelled_at",
        "cancelled_by",
        "cancel_reason",
    )

    # Durum alanlarının veritabanından yüklendiği/son kaydedildiği andaki değerleri (alan değil).
    _loaded_state: dict[str, Any]

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.number

    @classmethod
    def from_db(
        cls,
        db: str | None,
        field_names: Collection[str],
        values: Collection[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Self:
        instance = super().from_db(db, field_names, values, *args, **kwargs)
        # Doğrudan atamayı yakalamak için (bkz. core.services.save_with_audit).
        instance._loaded_state = instance.state_values()
        return instance

    def state_values(self) -> dict[str, Any]:
        """Durum alanlarının bellekteki değerleri (FK için kimlik). Yüklenmemiş (deferred)
        alanlar dahil edilmez."""
        values = {}
        for name in self.STATE_FIELDS:
            attname = self._meta.get_field(name).attname  # type: ignore[union-attr]
            if attname in self.__dict__:
                values[name] = self.__dict__[attname]
        return values


class AuditLog(models.Model):
    """Denetim günlüğü. Kayıtlar değiştirilemez ve silinemez."""

    class Action(models.TextChoices):
        CREATE = "create", "Oluşturma"
        UPDATE = "update", "Güncelleme"
        STATUS_CHANGE = "status_change", "Durum değişikliği"
        CANCEL = "cancel", "İptal"
        LOGIN = "login", "Giriş"
        LOGOUT = "logout", "Çıkış"
        LOGIN_FAILED = "login_failed", "Başarısız giriş"
        CUSTOM = "custom", "Diğer"

    timestamp = models.DateTimeField("zaman", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        User,
        verbose_name="kullanıcı",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField("işlem", max_length=32, choices=Action.choices, db_index=True)
    content_type = models.ForeignKey(
        ContentType,
        verbose_name="kayıt türü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    object_id = models.BigIntegerField("kayıt no", null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField("kayıt", max_length=255, blank=True)
    # {"alan": [eski, yeni]}
    changes = models.JSONField("değişiklikler", default=dict, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField("IP adresi", null=True, blank=True)
    note = models.TextField("not", blank=True)

    class Meta:
        verbose_name = "denetim kaydı"
        verbose_name_plural = "denetim günlüğü"
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.timestamp:%d.%m.%Y %H:%M} {self.get_action_display()} {self.object_repr}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValueError("Denetim kayıtları değiştirilemez.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Denetim kayıtları silinemez.")


class DocumentSequence(models.Model):
    """Belge numarası sayacı: önek + yıl başına son verilen numara."""

    prefix = models.CharField("önek", max_length=10)
    year = models.PositiveSmallIntegerField("yıl")
    last_number = models.PositiveIntegerField("son numara", default=0)

    class Meta:
        verbose_name = "belge numara sayacı"
        verbose_name_plural = "belge numara sayaçları"
        constraints = [
            models.UniqueConstraint(fields=["prefix", "year"], name="core_docseq_prefix_year_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.prefix}-{self.year}: {self.last_number}"


def attachment_upload_to(instance: "Attachment", filename: str) -> str:
    """Dosya adı tahmin edilemez olsun diye rastgele; özgün ad `original_name`'de tutulur."""
    extension = os.path.splitext(filename)[1].lower()[:10]
    return f"attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class Attachment(BaseModel):
    """Bir kayda (lot, numune, mal kabul, yorum) bağlı dosya ya da fotoğraf. Silinmez;
    kaldırılınca `is_active=False` olur ve denetim günlüğüne yazılır."""

    class Kind(models.TextChoices):
        SUPPLIER_COA = "SUPPLIER_COA", "Tedarikçi analiz sertifikası"
        PHOTO = "PHOTO", "Fotoğraf"
        DELIVERY_NOTE = "DELIVERY_NOTE", "İrsaliye"
        DOCUMENT = "DOCUMENT", "Belge"
        OTHER = "OTHER", "Diğer"

    content_type = models.ForeignKey(
        ContentType, verbose_name="kayıt türü", on_delete=models.PROTECT, related_name="+"
    )
    object_id = models.BigIntegerField("kayıt no")
    related_object = GenericForeignKey("content_type", "object_id")
    file = models.FileField("dosya", upload_to=attachment_upload_to, max_length=255)
    kind = models.CharField("tür", max_length=16, choices=Kind.choices, default=Kind.OTHER)
    original_name = models.CharField("dosya adı", max_length=255)
    size = models.PositiveBigIntegerField("boyut (bayt)")
    mime_type = models.CharField("içerik türü", max_length=100, blank=True)
    note = models.CharField("not", max_length=500, blank=True)
    is_active = models.BooleanField("aktif", default=True, db_index=True)
    removed_at = models.DateTimeField("kaldırılma zamanı", null=True, blank=True)
    removed_by = models.ForeignKey(
        User,
        verbose_name="kaldıran",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    removal_reason = models.CharField("kaldırma nedeni", max_length=500, blank=True)

    class Meta:
        verbose_name = "ek"
        verbose_name_plural = "ekler"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return self.original_name

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Ekler silinemez; kaldırılır.")
