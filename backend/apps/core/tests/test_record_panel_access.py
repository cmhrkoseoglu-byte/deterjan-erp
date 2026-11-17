"""Kayıt paneli kişiye özel ayarla (docs/plan/kisi-yetkileri.md §5.1 tablosu, §5.8): yorum, geçmiş,
ek ve @bahsetme kayıt türünün okuma bölümlerini izler; açık okumalı türde modülün "Açık kayıtlar"
satırı kapatılınca panel de kapanır."""

from collections.abc import Callable

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import records
from apps.core.access import READ, VIEW
from apps.core.models import AccessOverride, User
from apps.inventory.access import OPEN_RECORDS, RECEIPTS
from apps.inventory.models import GoodsReceipt
from apps.masterdata.tests.factories import SupplierFactory

pytestmark = pytest.mark.django_db


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _receipt() -> GoodsReceipt:
    return GoodsReceipt.objects.create(
        number="MK-2026-99001",
        status="DRAFT",
        supplier=SupplierFactory.create(),
        receipt_date=timezone.localdate(),
    )


def _panel(user: User, receipt: GoodsReceipt) -> dict[str, int]:
    query = {"content_type": "inventory.goodsreceipt", "object_id": str(receipt.pk)}
    client = api(user)
    return {
        "history": client.get("/api/v1/workflow/record-history/", query).status_code,
        "comments": client.get("/api/v1/workflow/comments/", query).status_code,
        "attachments": client.get("/api/v1/attachments/", query).status_code,
    }


def test_open_records_revoked_closes_the_panel(make_user: Callable[..., User]) -> None:
    receipt = _receipt()
    worker = make_user("uretim")
    assert records.can_view(worker, receipt)
    assert set(_panel(worker, receipt).values()) == {200}

    override(worker, OPEN_RECORDS.key, READ)
    assert not records.can_view(worker, receipt)
    assert set(_panel(worker, receipt).values()) == {400}
    refused = api(worker).get(
        "/api/v1/workflow/record-history/",
        {"content_type": "inventory.goodsreceipt", "object_id": str(receipt.pk)},
    )
    assert refused.json()["code"] == "record_not_found"

    # Okuma bölümünde Görür (kişiye eklenen) paneli yeniden açar.
    override(worker, RECEIPTS.key, VIEW, effect="grant")
    assert records.can_view(worker, receipt)
    assert set(_panel(worker, receipt).values()) == {200}
