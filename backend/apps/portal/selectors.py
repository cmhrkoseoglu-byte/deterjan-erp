"""Portal okumaları. Portal uç noktalarındaki her sorgu buradaki hesap ve firma süzgeciyle başlar
(docs/plan/musteri-siparis-takibi.md §4.7)."""

from django.db.models import QuerySet

from apps.core.models import User
from apps.portal.models import PortalAccount


def accounts() -> QuerySet[PortalAccount]:
    """Admin listesi: kullanıcı ve firmayla."""
    return PortalAccount.objects.select_related("user", "customer", "supplier")


def account_of(user: User) -> PortalAccount | None:
    """Portal kullanıcısının hesabı (firmasıyla); çalışanda ya da hesabı yoksa boş."""
    if not getattr(user, "is_portal", False):
        return None
    return PortalAccount.objects.select_related("customer", "supplier").filter(user=user).first()


def is_usable(account: PortalAccount | None) -> bool:
    """Hesap kullanılabilir mi: hesap var, kullanıcı etkin ve bağlı firma etkin."""
    return account is not None and account.user.is_active and account.firm.is_active
