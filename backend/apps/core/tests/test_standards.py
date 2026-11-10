"""Uluslararası standart kod listeleri."""

import pytest

from apps.core import standards


def test_country_and_language_lists():
    assert len(standards.COUNTRY_CODES) == len(set(standards.COUNTRY_CODES)) == 249
    assert len(standards.LANGUAGE_CODES) == len(set(standards.LANGUAGE_CODES)) == 183
    assert all(len(code) == 2 and code.isupper() for code in standards.COUNTRY_CODES)
    assert all(len(code) == 2 and code.islower() for code in standards.LANGUAGE_CODES)
    assert list(standards.COUNTRY_CODES) == sorted(standards.COUNTRY_CODES)
    assert list(standards.LANGUAGE_CODES) == sorted(standards.LANGUAGE_CODES)
    for code in ("TR", "DE", "GB", "US", "AZ", "IQ"):
        assert standards.is_country_code(code)
    for code in ("UK", "EU", "XK", "tr", ""):
        assert not standards.is_country_code(code)
    for code in ("tr", "en", "de", "ar", "ru", "az"):
        assert standards.is_language_code(code)
    for code in ("TR", "tur", "xx", ""):
        assert not standards.is_language_code(code)
    assert standards.normalize_country(" tr ") == "TR"
    assert standards.normalize_language(" EN ") == "en"


@pytest.mark.parametrize(
    ("code", "valid"),
    [("KGM", True), ("C62", True), ("XCT", True), ("kg", False), ("KGMX", False), ("K", False)],
)
def test_unece_code(code, valid):
    assert standards.is_unece_code(code) is valid


@pytest.mark.django_db
def test_standards_api(client_for, api_client):
    assert api_client.get("/api/v1/standards/").status_code == 401
    response = client_for("depo").get("/api/v1/standards/")
    assert response.status_code == 200
    assert response.data["default_country"] == "TR"
    assert response.data["default_language"] == "tr"
    assert "TR" in response.data["countries"] and "tr" in response.data["languages"]
