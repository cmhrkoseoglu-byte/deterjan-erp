import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.urls import reverse

BACKEND_DIR = Path(__file__).resolve().parents[3]


def test_site_info_public_and_reports_training_mode(client, settings):
    settings.TRAINING_MODE = False
    assert client.get(reverse("core:site-info")).json() == {"training_mode": False}

    settings.TRAINING_MODE = True
    response = client.get(reverse("core:site-info"))

    assert response.status_code == 200
    assert response.json() == {"training_mode": True}


def _import_prod_settings(**extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DJANGO_SECRET_KEY": "x" * 30 + "abcdefghijklmnopqrstuvwxyz",
        "DJANGO_ALLOWED_HOSTS": "egitim.example.com",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://egitim.example.com",
        **extra,
    }
    return subprocess.run(
        [sys.executable, "-c", "import config.settings.prod"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("password", ["", "Demo.12345", "kisa"])
def test_prod_training_mode_refuses_weak_demo_password(password):
    result = _import_prod_settings(TRAINING_MODE="true", DEMO_USER_PASSWORD=password)

    assert result.returncode != 0
    assert "DEMO_USER_PASSWORD" in result.stderr


def test_prod_training_mode_starts_with_strong_demo_password():
    result = _import_prod_settings(TRAINING_MODE="true", DEMO_USER_PASSWORD="Egitim.Sifre.2026")

    assert result.returncode == 0, result.stderr
