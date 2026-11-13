"""Kişiye özel yetki dönemleri ve paket sürümü: silinmez, bitmiş satır değişmez."""

from collections.abc import Callable

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import AccessCatalogSnapshot, AccessOverride, User
from apps.core.roles import DEPO

pytestmark = pytest.mark.django_db


def _override(user: User, **kwargs: object) -> AccessOverride:
    values: dict[str, object] = {
        "key": "production.prep",
        "level": "change",
        "effect": "revoke",
        "note": "İzin süresince",
    }
    values.update(kwargs)
    return AccessOverride.objects.create(user=user, **values)


def test_override_can_be_ended_once(make_user: Callable[..., User]) -> None:
    user = make_user(DEPO)
    admin = make_user("admin")
    row = _override(user, created_by=admin)

    row.ended_at = timezone.now()
    row.ended_by = admin
    row.end_reason = AccessOverride.EndReason.RESET
    row.save(update_fields=["ended_at", "ended_by", "end_reason"])

    row.end_note = "ikinci kez"
    with pytest.raises(ValueError, match="Bitmiş"):
        row.save(update_fields=["end_note"])


def test_override_fields_cannot_change(make_user: Callable[..., User]) -> None:
    row = _override(make_user(DEPO))

    row.note = "değişti"
    with pytest.raises(ValueError, match="değiştirilemez"):
        row.save()
    with pytest.raises(ValueError, match="değiştirilemez"):
        row.save(update_fields=["note"])


def test_override_cannot_be_deleted(make_user: Callable[..., User]) -> None:
    row = _override(make_user(DEPO))

    with pytest.raises(ValueError, match="silinemez"):
        row.delete()


def test_one_active_row_per_user_key_level(make_user: Callable[..., User]) -> None:
    user = make_user(DEPO)
    first = _override(user)

    with transaction.atomic(), pytest.raises(IntegrityError):
        _override(user, effect="grant")

    first.ended_at = timezone.now()
    first.end_reason = AccessOverride.EndReason.REPLACED
    first.save(update_fields=["ended_at", "end_reason"])
    _override(user, effect="grant")  # bitmiş satırdan sonra yeni dönem açılabilir


def test_read_level_only_revokes(make_user: Callable[..., User]) -> None:
    user = make_user(DEPO)
    _override(user, key="production.open_records", level="read")

    with transaction.atomic(), pytest.raises(IntegrityError):
        _override(user, key="quality.open_records", level="read", effect="grant")


def test_end_fields_must_be_consistent(make_user: Callable[..., User]) -> None:
    with transaction.atomic(), pytest.raises(IntegrityError):
        _override(make_user(DEPO), ended_at=timezone.now())


def test_catalog_snapshot_is_immutable() -> None:
    snapshot = AccessCatalogSnapshot.objects.create(catalog_hash="abc", catalog={"modules": []})

    snapshot.catalog_hash = "def"
    with pytest.raises(ValueError, match="değiştirilemez"):
        snapshot.save()
    with pytest.raises(ValueError, match="değiştirilemez"):
        snapshot.delete()
