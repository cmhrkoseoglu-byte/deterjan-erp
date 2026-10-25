"""Firma ticari bilgileri (Ana veriler > Firma bilgileri)."""

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.masterdata import services
from apps.masterdata.models import CompanyProfile

pytestmark = pytest.mark.django_db
URL = "/api/v1/masterdata/company/"


@pytest.fixture(autouse=True)
def empty_company_settings(settings: Any) -> None:
    """Geliştirme ortamının `.env` değerleri testleri etkilemesin: ilk kayıt boş başlar."""
    for name in ("COMPANY_NAME", "COMPANY_ADDRESS", "COMPANY_TAX_OFFICE", "COMPANY_TAX_NO"):
        setattr(settings, name, "")


@override_settings(
    COMPANY_NAME=" Örnek A.Ş. ",
    COMPANY_ADDRESS="OSB",
    COMPANY_TAX_OFFICE="Gebze",
    COMPANY_TAX_NO="1234567890",
)
def test_first_profile_comes_from_settings() -> None:
    profile = services.get_company_profile()
    assert (profile.legal_name, profile.address, profile.tax_office, profile.tax_number) == (
        "Örnek A.Ş.",
        "OSB",
        "Gebze",
        "1234567890",
    )
    assert services.get_company_profile().pk == profile.pk
    assert CompanyProfile.objects.count() == 1


@pytest.mark.parametrize(
    ("value", "ok"),
    [("1234567890", True), ("1234567891", False), ("123456789", False), ("12345678a0", False)],
)
def test_vkn_check_digit(value: str, ok: bool) -> None:
    assert services.valid_vkn(value) is ok


@pytest.mark.parametrize(
    ("value", "ok"),
    [("10000000146", True), ("10000000145", False), ("01000000146", False), ("1000000014", False)],
)
def test_tckn_check_digits(value: str, ok: bool) -> None:
    assert services.valid_tckn(value) is ok


def test_update_normalizes_validates_and_logs(make_user: Callable[..., User]) -> None:
    manager = make_user("yonetim")
    profile = services.update_company_profile(
        manager,
        {
            "legal_name": "  Örnek   Deterjan A.Ş. ",
            "address": " OSB 1. Cadde \n\n  Kocaeli ",
            "tax_office": " Gebze ",
            "tax_number": "123 456 7890",
            "trade_registry_no": " Gebze 12345 ",
            "mersis_no": "0123 4567 8900 0017",
        },
    )
    assert profile.legal_name == "Örnek Deterjan A.Ş."
    assert profile.address == "OSB 1. Cadde\nKocaeli"
    assert profile.tax_number == "1234567890" and profile.mersis_no == "0123456789000017"
    assert services.company_registry_line(profile) == (
        "Ticaret sicil no: Gebze 12345  MERSİS no: 0123456789000017"
    )
    content_type = ContentType.objects.get_for_model(CompanyProfile)
    log = AuditLog.objects.filter(content_type=content_type, object_id=profile.pk).latest(
        "timestamp"
    )
    assert log.actor == manager and log.changes["tax_number"][1] == "1234567890"

    for data, code in (
        ({"legal_name": " "}, "legal_name_required"),
        ({"tax_number": "1234567891"}, "invalid_tax_number"),
        ({"mersis_no": "123"}, "invalid_mersis_no"),
    ):
        with pytest.raises(BusinessRuleError) as exc:
            services.update_company_profile(manager, data)
        assert exc.value.code == code
    # Şahıs firması: vergi no yerine TCKN.
    assert services.update_company_profile(manager, {"tax_number": "10000000146"}).tax_number == (
        "10000000146"
    )


@pytest.mark.parametrize("role", ["planlama", "depo", "satin_alma"])
def test_only_management_and_admin_update(make_user: Callable[..., User], role: str) -> None:
    with pytest.raises(PermissionDenied):
        services.update_company_profile(make_user(role), {"legal_name": "X A.Ş."})
    profile = services.update_company_profile(make_user("admin"), {"legal_name": "X A.Ş."})
    assert profile.legal_name == "X A.Ş."


def test_api(client_for: Callable[..., APIClient]) -> None:
    assert client_for("depo").get(URL).status_code == 200
    assert APIClient().get(URL).status_code in (401, 403)
    response = client_for("planlama").put(URL, {"legal_name": "X A.Ş."}, format="json")
    assert response.status_code == 403
    manager = client_for("yonetim")
    response = manager.put(
        URL, {"legal_name": "Örnek A.Ş.", "tax_number": "1234567891"}, format="json"
    )
    assert response.status_code == 400 and response.json()["code"] == "invalid_tax_number"
    response = manager.put(
        URL, {"legal_name": "Örnek A.Ş.", "tax_number": "123 456 7890"}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert response.json()["tax_number"] == "1234567890"
    assert client_for("planlama").get(URL).json()["legal_name"] == "Örnek A.Ş."
