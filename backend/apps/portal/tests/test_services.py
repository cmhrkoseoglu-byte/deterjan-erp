"""Portal hesabı servisleri: açma, firma kuralları, şifre, açma/kapama, rol reddi, çalışan
listeleri (docs/plan/musteri-siparis-takibi.md §4.2)."""

from collections.abc import Callable

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.core import services as core
from apps.core.access_report import people
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.masterdata.models import Customer, Supplier
from apps.portal import services
from apps.portal.models import PortalAccount
from apps.workflow.selectors import mentionable_users
from apps.workflow.services import parse_mentions

pytestmark = pytest.mark.django_db


def test_create_customer_account(sysadmin: User, customer: Customer) -> None:
    account, password = services.create_account(
        sysadmin,
        username="ali.musteri",
        full_name="Ali Müşteri",
        email="ali@example.com",
        customer=customer,
    )

    user = account.user
    assert user.account_type == User.AccountType.CUSTOMER_PORTAL
    assert user.is_portal and user.must_change_password and user.check_password(password)
    assert user.roles == [] and not user.is_staff and not user.is_superuser
    assert account.kind == "customer" and account.firm == customer
    assert AuditLog.objects.filter(object_id=str(account.pk), note="Portal hesabı açıldı").exists()


def test_create_supplier_account(sysadmin: User, supplier: Supplier) -> None:
    account, _ = services.create_account(
        sysadmin, username="veli.tedarik", full_name="Veli Tedarik", supplier=supplier
    )
    assert account.user.account_type == User.AccountType.SUPPLIER_PORTAL
    assert account.kind == "supplier" and account.firm == supplier


def test_account_needs_exactly_one_active_firm(
    sysadmin: User, customer: Customer, supplier: Supplier
) -> None:
    with pytest.raises(BusinessRuleError) as both:
        services.create_account(
            sysadmin,
            username="iki",
            full_name="İki",
            customer=customer,
            supplier=supplier,
        )
    assert both.value.code == "portal_firm_required"
    with pytest.raises(BusinessRuleError) as none:
        services.create_account(sysadmin, username="hic", full_name="Hiç")
    assert none.value.code == "portal_firm_required"
    Customer.objects.filter(pk=customer.pk).update(is_active=False)
    customer.refresh_from_db()
    with pytest.raises(BusinessRuleError) as inactive:
        services.create_account(sysadmin, username="pasif", full_name="Pasif", customer=customer)
    assert inactive.value.code == "portal_firm_inactive"
    assert not User.objects.filter(username__in=["iki", "hic", "pasif"]).exists()


def test_only_admin_manages_accounts(
    make_user: Callable[..., User], customer: Customer, customer_account: PortalAccount
) -> None:
    boss = make_user("yonetim", username="yonetici")
    with pytest.raises(PermissionDenied):
        services.create_account(boss, username="x.y", full_name="X Y", customer=customer)
    with pytest.raises(PermissionDenied):
        services.reset_password(boss, customer_account)
    with pytest.raises(PermissionDenied):
        services.set_active(boss, customer_account, False)


def test_username_must_be_unique(
    sysadmin: User, customer: Customer, customer_account: PortalAccount
) -> None:
    with pytest.raises(BusinessRuleError) as taken:
        services.create_account(
            sysadmin, username="musteri.yetkili", full_name="Kopya", customer=customer
        )
    assert taken.value.code == "username_taken"


def test_database_allows_one_firm_only(customer_account: PortalAccount, supplier: Supplier) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        PortalAccount.objects.filter(pk=customer_account.pk).update(supplier=supplier)


def test_portal_user_gets_no_roles_or_access(
    sysadmin: User, customer_account: PortalAccount
) -> None:
    user = customer_account.user
    with pytest.raises(BusinessRuleError) as roles:
        core.set_user_roles(user, ["sevkiyat"], sysadmin)
    assert roles.value.code == "portal_user_roles"
    with pytest.raises(BusinessRuleError) as access:
        core.set_user_access(sysadmin, user, version="x", overrides=[], roles=[], note="deneme")
    assert access.value.code == "portal_user_roles"
    core.set_user_roles(user, [], sysadmin)  # boş liste zararsız
    assert user.roles == []


def test_reset_password_and_toggle(
    sysadmin: User, customer: Customer, customer_account: PortalAccount
) -> None:
    user = customer_account.user
    User.objects.filter(pk=user.pk).update(must_change_password=False)

    password = services.reset_password(sysadmin, customer_account)
    user.refresh_from_db()
    assert user.must_change_password and user.check_password(password)

    services.set_active(sysadmin, customer_account, False)
    assert customer_account.user.is_active is False
    Customer.objects.filter(pk=customer.pk).update(is_active=False)
    customer_account.refresh_from_db()
    with pytest.raises(BusinessRuleError) as inactive:
        services.set_active(sysadmin, customer_account, True)
    assert inactive.value.code == "portal_firm_inactive"
    Customer.objects.filter(pk=customer.pk).update(is_active=True)
    customer_account.refresh_from_db()
    services.set_active(sysadmin, customer_account, True)
    assert customer_account.user.is_active is True


def test_unlock_requires_lock(sysadmin: User, customer_account: PortalAccount) -> None:
    with pytest.raises(BusinessRuleError) as not_locked:
        services.unlock(sysadmin, customer_account)
    assert not_locked.value.code == "not_locked"


def test_portal_users_are_not_in_staff_lists(
    make_user: Callable[..., User], customer_account: PortalAccount
) -> None:
    make_user("sevkiyat", username="musteri.sevk")
    portal = customer_account.user

    assert portal not in mentionable_users("musteri")
    assert [u.username for u in mentionable_users("musteri")] == ["musteri.sevk"]
    assert portal not in people()
    assert parse_mentions("@musteri.yetkili ve @musteri.sevk") == [
        User.objects.get(username="musteri.sevk")
    ]
