"""Kişiye özel ayarla sistem durumu (docs/plan/kisi-yetkileri.md §4, §10 6. adım): sistem durumu
yalnız admindir, hiçbir bölüm açmaz; arayüz hata kaydı giriş yapan herkese, dış izleme ucu
kimlik doğrulamasız açıktır."""

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.core import access
from apps.core.access import READ
from apps.core.models import AccessOverride, User
from apps.core.permissions import DEFAULT_MESSAGE
from apps.core.roles import ADMIN, PLANLAMA

pytestmark = pytest.mark.django_db


def grant_everything(user: User) -> User:
    for section in access.sections():
        for level in section.levels:
            if level == READ:  # okuma kapsamı yalnız kaldırılır
                continue
            AccessOverride.objects.create(
                user=user, key=section.key, level=level, effect="grant", note="deneme"
            )
    user.refresh_access()
    return user


def api(user: User | None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def test_every_section_granted_does_not_open_system_status(
    make_user: Callable[..., User],
) -> None:
    everything = api(grant_everything(make_user(PLANLAMA)))

    refused = everything.get("/api/v1/ops/status/")
    assert refused.status_code == 403
    assert refused.json()["detail"] == DEFAULT_MESSAGE
    assert "required" not in refused.json()
    assert everything.post("/api/v1/ops/status/", {}, format="json").status_code == 403
    admin = api(make_user(ADMIN))
    assert admin.get("/api/v1/ops/status/").status_code == 200
    assert admin.post("/api/v1/ops/status/", {}, format="json").status_code == 405


def test_client_errors_and_health_stay_open(make_user: Callable[..., User]) -> None:
    """Bölümü olmayan kişi de hata kaydı gönderir; izleme ucu oturumsuz yanıt verir."""
    body = {"message": "deneme", "url": "/", "stack": ""}
    assert api(make_user()).post("/api/v1/ops/client-errors/", body, format="json").status_code == (
        204
    )
    assert api(None).post("/api/v1/ops/client-errors/", body, format="json").status_code == 401
    assert api(None).get("/api/v1/ops/health/").status_code in (200, 503)
