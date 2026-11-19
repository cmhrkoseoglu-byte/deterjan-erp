"""Portal hesabı: bir kullanıcıyı tek bir müşteriye ya da tek bir tedarikçiye bağlar
(docs/plan/musteri-siparis-takibi.md §4.2). İş mantığı `services.py`'dedir."""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, User
from apps.masterdata.models import Customer, Supplier


class PortalAccount(BaseModel):
    """Portal kullanıcısının bağlı olduğu firma. Firma sonradan değişmez (yanlış bağlanan hesap
    kapatılıp yenisi açılır); hesabın açık/kapalı durumu kullanıcının `is_active` alanıdır."""

    user = models.OneToOneField(
        User,
        verbose_name="kullanıcı",
        on_delete=models.PROTECT,
        related_name="portal_account",
        editable=False,
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name="müşteri",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="portal_accounts",
        editable=False,
    )
    supplier = models.ForeignKey(
        Supplier,
        verbose_name="tedarikçi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="portal_accounts",
        editable=False,
    )

    class Meta:
        verbose_name = "portal hesabı"
        verbose_name_plural = "portal hesapları"
        ordering = ["user__username"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(customer__isnull=False, supplier__isnull=True)
                    | Q(customer__isnull=True, supplier__isnull=False)
                ),
                name="portal_account_one_firm",
                violation_error_message=(
                    "Portal hesabı tek bir müşteriye ya da tedarikçiye bağlanır."
                ),
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.username} ({self.firm})"

    @property
    def firm(self) -> Customer | Supplier:
        """Bağlı müşteri ya da tedarikçi."""
        firm = self.customer if self.customer_id else self.supplier
        assert firm is not None
        return firm

    @property
    def kind(self) -> str:
        """`customer` ya da `supplier`."""
        return "customer" if self.customer_id else "supplier"
