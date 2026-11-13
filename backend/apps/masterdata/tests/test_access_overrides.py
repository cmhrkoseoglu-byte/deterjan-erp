"""Kişiye özel ayarla ana veriler (docs/plan/kisi-yetkileri.md §10, 2. adım): sade kart, kod
önerisi ve firma bilgileri."""

from collections.abc import Callable
from typing import Any, cast

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import CHANGE, READ
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.masterdata import services
from apps.masterdata.models import Customer, Supplier
from apps.masterdata.tests.factories import CustomerFactory, SupplierFactory

pytestmark = pytest.mark.django_db
CLOSED = ("masterdata.open_records", READ)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _contact(**extra: Any) -> dict[str, Any]:
    return {
        "tax_office": "Kadıköy",
        "tax_number": "1234567890",
        "address": "Moda Cad. 1",
        "phone": "0216 000 00 00",
        "email": "satis@ornek.com.tr",
        "contact_person": "Ayşe Yılmaz",
        **extra,
    }


def _results(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 200, response.json()
    return list(response.json()["results"])


def test_closing_records_gives_a_plain_supplier_card(make_user: Callable[..., User]) -> None:
    supplier = cast(Supplier, SupplierFactory(**_contact()))
    detail = reverse("masterdata:supplier-detail", args=[supplier.pk])
    listing = reverse("masterdata:supplier-list")
    plain = api(override(make_user("uretim"), *CLOSED))

    card = plain.get(detail).json()
    assert card["code"] == supplier.code and card["name"] == supplier.name
    assert all(card[name] == "" for name in _contact())
    # Arama yalnız kod, eski kod ve adda yapılır.
    assert _results(plain.get(listing, {"search": "1234567890"})) == []
    assert _results(plain.get(listing, {"search": "Ayşe"})) == []
    assert [row["id"] for row in _results(plain.get(listing, {"search": str(supplier.code)}))] == [
        supplier.pk
    ]

    full = api(make_user("uretim"))
    assert full.get(detail).json()["tax_number"] == "1234567890"
    assert [row["id"] for row in _results(full.get(listing, {"search": "Ayşe"}))] == [supplier.pk]


def test_sales_orders_view_keeps_the_customer_card_full(make_user: Callable[..., User]) -> None:
    customer = cast(Customer, CustomerFactory(**_contact()))
    supplier = cast(Supplier, SupplierFactory(**_contact()))
    # Depo Satış siparişleri: Görür'ü taşır: müşteri kartı tam kalır, tedarikçi kartı sade olur.
    depo = api(override(make_user("depo"), *CLOSED))

    card = depo.get(reverse("masterdata:customer-detail", args=[customer.pk])).json()
    assert card["tax_number"] == "1234567890" and card["contact_person"] == "Ayşe Yılmaz"
    supplier_card = depo.get(reverse("masterdata:supplier-detail", args=[supplier.pk])).json()
    assert supplier_card["tax_number"] == "" and supplier_card["contact_person"] == ""


def test_code_suggestion_follows_card_change(make_user: Callable[..., User]) -> None:
    suggest = "/api/v1/coding/suggest/masterdata.material/"
    planner = make_user("planlama")
    assert api(planner).get(suggest).status_code == 200

    refused = api(override(planner, "masterdata.cards", CHANGE)).get(suggest)
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": "masterdata.cards", "level": "change"}]


def test_company_profile_change_follows_its_section(make_user: Callable[..., User]) -> None:
    manager = override(make_user("yonetim"), "masterdata.company", CHANGE)
    company = "/api/v1/masterdata/company/"

    assert api(manager).get(company).status_code == 200
    assert api(manager).put(company, {"legal_name": "X"}, format="json").status_code == 403
    with pytest.raises(MissingAccess):
        services.update_company_profile(manager, {"legal_name": "X"})
