"""Portal hesabı servisleri (docs/plan/musteri-siparis-takibi.md §4.2).

Hesabı yalnız sistem yöneticisi açar, şifresini sıfırlar, kilidini açar ve pasife alır
(CUMHUR, 2026-11-19). Kullanıcının kendisi `core.services` ile açılır; burada firmaya bağlanır.
"""

from django.db import transaction

from apps.core import security
from apps.core import services as core
from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.permissions import require_admin
from apps.core.services import save_with_audit
from apps.masterdata.models import Customer, Supplier
from apps.portal.models import PortalAccount

ADMIN_MESSAGE = "Portal hesaplarını yalnız sistem yöneticisi yönetir."


def _check_firm(customer: Customer | None, supplier: Supplier | None) -> Customer | Supplier:
    if (customer is None) == (supplier is None):
        raise BusinessRuleError(
            "portal_firm_required",
            "Hesap tek bir müşteriye ya da tek bir tedarikçiye bağlanır.",
        )
    firm: Customer | Supplier = customer if customer is not None else supplier  # type: ignore[assignment]
    if not firm.is_active:
        raise BusinessRuleError(
            "portal_firm_inactive",
            "Pasif müşteri ya da tedarikçiye portal hesabı açılamaz.",
        )
    return firm


def create_account(
    actor: User,
    *,
    username: str,
    full_name: str,
    customer: Customer | None = None,
    supplier: Supplier | None = None,
    email: str = "",
    phone: str = "",
) -> tuple[PortalAccount, str]:
    """Müşteri ya da tedarikçi yetkilisine portal hesabı açar; sistemin ürettiği geçici şifreyi
    döner (yalnız bu dönüş değerinde görünür, ilk girişte değiştirilir).

    Hata kodları: `portal_firm_required` (ikisi birden ya da hiçbiri), `portal_firm_inactive`;
    kullanıcı adı ve ad soyad kuralları `core.services.create_user`'daki gibidir.
    """
    require_admin(actor, ADMIN_MESSAGE)
    _check_firm(customer, supplier)
    kinds = User.AccountType
    account_type = kinds.CUSTOMER_PORTAL if customer is not None else kinds.SUPPLIER_PORTAL
    with transaction.atomic():
        user, password = core.create_user(
            actor,
            username=username,
            full_name=full_name,
            email=email,
            phone=phone,
            account_type=account_type,
        )
        account = PortalAccount(user=user, customer=customer, supplier=supplier)
        save_with_audit(account, actor, note="Portal hesabı açıldı")
    return account, password


def reset_password(actor: User, account: PortalAccount) -> str:
    """Yeni geçici şifre üretir (pasif hesapta `user_inactive`)."""
    require_admin(actor, ADMIN_MESSAGE)
    return core.reset_user_password(actor, account.user)


def unlock(actor: User, account: PortalAccount) -> None:
    """Hatalı denemelerden kilitlenen hesabın kilidini açar (`not_locked`)."""
    require_admin(actor, ADMIN_MESSAGE)
    security.unlock_user(actor, account.user)


def set_active(actor: User, account: PortalAccount, active: bool) -> PortalAccount:
    """Hesabı kapatır ya da yeniden açar. Bağlı firma pasifse yeniden açılamaz
    (`portal_firm_inactive`)."""
    require_admin(actor, ADMIN_MESSAGE)
    if active:
        _check_firm(account.customer, account.supplier)
    core.set_user_active(actor, account.user, active)
    account.user.refresh_from_db(fields=["is_active"])
    return account
