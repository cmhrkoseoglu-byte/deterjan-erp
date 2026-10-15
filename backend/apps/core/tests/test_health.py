import pytest
from django.urls import reverse

from apps.core import health

pytestmark = pytest.mark.django_db


def test_health_ok(client):
    response = client.get(reverse("core:health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


def test_health_reports_redis_failure(client, monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: False)

    response = client.get(reverse("core:health"))

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "ok", "redis": "error"}


def test_health_reports_database_failure(client, monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: False)

    response = client.get(reverse("core:health"))

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "error", "redis": "ok"}


def test_health_does_not_require_login(client):
    response = client.get("/api/v1/health/")

    assert response.status_code == 200
