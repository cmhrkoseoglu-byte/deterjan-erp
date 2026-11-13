"""Kişiye özel ayarla izlenebilirlik (docs/plan/kisi-yetkileri.md §10, 4. adım): raporlar ve
çıktılar "Geri ve ileri izleme, geri çağırma: Görür" ister; karşılanmayan metot da aynı kuralla
denetlenir, sonra DRF 405 döner."""

from collections.abc import Callable

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import VIEW
from apps.core.models import AccessOverride, User
from apps.inventory.tests.factories import stocked_lot
from apps.traceability.access import TRACE

pytestmark = pytest.mark.django_db


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_trace_follows_its_section(make_user: Callable[..., User]) -> None:
    lot = stocked_lot("10")
    backward = reverse("traceability:backward", args=[lot.pk])
    recall = reverse("traceability:recall")

    manager = api(override(make_user("yonetim"), TRACE.key, VIEW))
    refused = manager.get(backward)
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": TRACE.key, "level": VIEW}]
    assert manager.get(recall, {"lot": str(lot.pk)}).status_code == 403

    planner = api(override(make_user("planlama"), TRACE.key, VIEW, effect="grant"))
    assert planner.get(backward).status_code == 200
    assert planner.get(recall, {"lot": str(lot.pk)}).status_code == 200


def test_unrouted_methods_keep_todays_rule(make_user: Callable[..., User]) -> None:
    lot = stocked_lot("10")
    backward = reverse("traceability:backward", args=[lot.pk])

    assert api(make_user("laboratuvar")).post(backward, {}).status_code == 405
    assert api(make_user("depo")).post(backward, {}).status_code == 403
    assert APIClient().post(backward, {}).status_code == 401
