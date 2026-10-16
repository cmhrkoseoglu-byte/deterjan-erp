"""Denetim günlüğü yardımcıları: değişiklik farkı çıkarma ve kayıt yazma."""

import contextlib
import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.fields.files import FieldFile

from apps.core.context import get_client_ip
from apps.core.models import AuditLog, User

# Farka hiç girmeyen alanlar: gizli bilgiler ve her kayıtta değişen otomatik alanlar.
EXCLUDED_FIELDS = frozenset(
    {"password", "last_login", "created_at", "created_by", "updated_at", "updated_by"}
)


def _serialize(value: Any) -> Any:
    """Alan değerini JSON'a yazılabilir, karşılaştırılabilir biçime çevirir."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name or None
    return value


def mask_identifier(value: str | None, visible: int = 4) -> str:
    """Kimlik numarası gibi kişisel veriyi maskeler (KVKK): `12345678901` → `*******8901`."""
    if not value:
        return ""
    keep = value[-visible:] if len(value) > visible else ""
    return "*" * (len(value) - len(keep)) + keep


def _masked_fields(instance: models.Model) -> tuple[str, ...]:
    """Modelin `AUDIT_MASKED_FIELDS` alanları: günlüğe maskeli yazılır."""
    return tuple(getattr(type(instance), "AUDIT_MASKED_FIELDS", ()))


def _tracked_fields(
    instance: models.Model, exclude: frozenset[str] = EXCLUDED_FIELDS
) -> list[models.Field]:
    return [
        field
        for field in instance._meta.concrete_fields
        if not field.primary_key and field.name not in exclude
    ]


def _value(field: models.Field, instance: models.Model) -> Any:
    """Alanın veritabanına yazılacağı biçimdeki değeri.

    Atanmış "1.5" metni Decimal'e çevrilir; ondalık değerler, PostgreSQL'in `numeric` alanında
    yaptığı gibi alanın basamak sayısına yuvarlanır (1.23456 → 1.2346). Böylece günlükte
    veritabanında olmayan bir değer görünmez.
    """
    value = field.value_from_object(instance)
    try:
        value = field.to_python(value)
    except ValidationError:
        return value
    if isinstance(field, models.DecimalField) and isinstance(value, Decimal):
        with contextlib.suppress(InvalidOperation):  # max_digits aşımı: olduğu gibi bırak
            value = value.quantize(Decimal(1).scaleb(-field.decimal_places), ROUND_HALF_UP)
    return value


def snapshot(instance: models.Model) -> dict[str, Any]:
    """İzlenen alanların anlık değerleri, JSON'a yazılabilir biçimde (FK'lar kimlik olarak)."""
    masked = _masked_fields(instance)
    values = {}
    for field in _tracked_fields(instance):
        value = _value(field, instance)
        values[field.name] = mask_identifier(value) if field.name in masked else _serialize(value)
    return values


def diff(
    instance_before: models.Model | None,
    instance_after: models.Model,
    *,
    exclude: frozenset[str] = EXCLUDED_FIELDS,
) -> dict[str, list[Any]]:
    """Değişen alanları `{"alan": [eski, yeni]}` olarak döner.

    `instance_before` None ise (yeni kayıt) dolu tüm alanlar `[None, yeni]` olarak döner.
    Şifre ve otomatik alanlar (`EXCLUDED_FIELDS`) farka girmez; şifre değişikliği ayrıca,
    maskelenerek yazılır (bkz. `core.signals`).
    """
    changes: dict[str, list[Any]] = {}
    masked = _masked_fields(instance_after)

    def out(field: models.Field, value: Any) -> Any:
        if field.name in masked:
            return mask_identifier(value) if value else value
        return _serialize(value)

    for field in _tracked_fields(instance_after, exclude):
        new = _value(field, instance_after)
        if instance_before is None:
            if new not in (None, ""):
                changes[field.name] = [None, out(field, new)]
            continue
        old = _value(field, instance_before)
        if old != new:
            changes[field.name] = [out(field, old), out(field, new)]
    return changes


def log_change(
    actor: User | None,
    instance: models.Model | None,
    action: str,
    changes: dict[str, Any] | None = None,
    note: str = "",
    *,
    ip_address: str | None = None,
) -> AuditLog:
    """Denetim günlüğüne bir kayıt yazar.

    `instance` None olabilir (ör. bilinmeyen kullanıcı adıyla başarısız giriş).
    `ip_address` verilmezse geçerli isteğin IP adresi kullanılır.
    """
    if action not in AuditLog.Action.values:
        raise ValueError(f"Bilinmeyen denetim işlemi: {action}")
    if actor is not None and not actor.is_authenticated:
        actor = None
    entry = AuditLog(
        actor=actor,
        action=action,
        changes=changes or {},
        note=note,
        ip_address=ip_address or get_client_ip(),
    )
    if instance is not None:
        entry.content_type = ContentType.objects.get_for_model(instance)
        entry.object_id = instance.pk
        entry.object_repr = str(instance)[:255]
    entry.save()
    return entry
