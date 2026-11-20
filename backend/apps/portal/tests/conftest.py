from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import pytest

from apps.core.models import User
from apps.core.roles import ADMIN, DEPO, SEVKIYAT
from apps.masterdata.models import Customer, Supplier
from apps.masterdata.tests.factories import CustomerFactory, SupplierFactory
from apps.portal import services
from apps.portal.models import PortalAccount


@pytest.fixture
def sysadmin(make_user: Callable[..., User]) -> User:
    return make_user(ADMIN, username="sistem")


@pytest.fixture
def customer() -> Customer:
    return CustomerFactory.create(code="M-PORTAL", name="Portal Müşteri A.Ş.")


@pytest.fixture
def supplier() -> Supplier:
    return SupplierFactory.create(code="T-PORTAL", name="Portal Tedarik Ltd.")


@pytest.fixture
def customer_account(sysadmin: User, customer: Customer) -> PortalAccount:
    account, _ = services.create_account(
        sysadmin,
        username="musteri.yetkili",
        full_name="Müşteri Yetkili",
        customer=customer,
    )
    return account


@pytest.fixture
def supplier_account(sysadmin: User, supplier: Supplier) -> PortalAccount:
    account, _ = services.create_account(
        sysadmin,
        username="tedarik.yetkili",
        full_name="Tedarik Yetkili",
        supplier=supplier,
    )
    return account


Commit = Callable[[], AbstractContextManager[Any]]


@pytest.fixture
def commit(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> Commit:
    """Blok bitince commit sonrası işleri (olaylar, e-posta) çalıştırır."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def seller(make_user: Callable[..., User]) -> User:
    return make_user(SEVKIYAT, username="sevkiyat")


@pytest.fixture
def picker(make_user: Callable[..., User]) -> User:
    return make_user(DEPO, username="depo")
