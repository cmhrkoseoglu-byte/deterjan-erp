"""Personel kartları: kimlik ve görev bilgileri (2026-10-25, docs/DECISIONS.md).

Sistemi kullanmayan çalışanlar da kaydedilir; sistem hesabı olanın kartı kullanıcısına bağlanır.
Kart silinmez: işten ayrılan pasife alınır ve çıkış tarihi yazılır. Kişisel veridir; yalnızca admin
ve yönetim görür (docs/KVKK.md).
"""

from django.db import models
from django.db.models import F, Q

from apps.core.models import MasterDataModel, User


class Employee(MasterDataModel):
    """Personel kartı. Ayrılış `personnel.services.terminate_employee` ile kaydedilir."""

    employee_no = models.CharField("sicil no", max_length=32, blank=True)
    full_name = models.CharField("ad soyad", max_length=150)
    department = models.CharField("birim", max_length=64, db_index=True)
    title = models.CharField("görev", max_length=100, blank=True)
    hire_date = models.DateField("işe giriş tarihi", null=True, blank=True)
    termination_date = models.DateField("işten çıkış tarihi", null=True, blank=True)
    phone = models.CharField("telefon", max_length=32, blank=True)
    emergency_contact_name = models.CharField(
        "acil durumda aranacak kişi", max_length=150, blank=True
    )
    emergency_contact_phone = models.CharField("acil durum telefonu", max_length=32, blank=True)
    user = models.OneToOneField(
        User,
        verbose_name="sistem kullanıcısı",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee",
        error_messages={"unique": "Bu kullanıcı başka bir personel kartına bağlı."},
    )

    class Meta:
        verbose_name = "personel"
        verbose_name_plural = "personel"
        ordering = ["full_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee_no"],
                condition=~Q(employee_no=""),
                name="personnel_employee_no_uniq",
                violation_error_message="Bu sicil no başka bir personelde kayıtlı.",
            ),
            # Çalışan personelde çıkış tarihi olmaz; ayrılanda olur.
            models.CheckConstraint(
                condition=Q(is_active=True, termination_date__isnull=True)
                | Q(is_active=False, termination_date__isnull=False),
                name="personnel_termination_matches_status",
                violation_error_message=(
                    "Çalışan personelde işten çıkış tarihi olmaz; ayrılan personelde girilir."
                ),
            ),
            models.CheckConstraint(
                condition=Q(termination_date__isnull=True)
                | Q(hire_date__isnull=True)
                | Q(termination_date__gte=F("hire_date")),
                name="personnel_termination_after_hire",
                violation_error_message="İşten çıkış tarihi işe giriş tarihinden önce olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.employee_no})" if self.employee_no else self.full_name
