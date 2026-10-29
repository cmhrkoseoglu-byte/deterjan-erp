"""Personel kartları: kimlik ve görev bilgileri (2026-10-25), özlük bilgileri ve belgeleri,
puantaj (2026-10-29, docs/DECISIONS.md).

Sistemi kullanmayan çalışanlar da kaydedilir; sistem hesabı olanın kartı kullanıcısına bağlanır.
Kart silinmez: işten ayrılan pasife alınır ve çıkış tarihi yazılır. Kişisel veridir; yalnızca admin
ve yönetim görür (docs/KVKK.md).
"""

import os
import uuid
from decimal import Decimal
from typing import Any, ClassVar

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import BaseModel, DocumentModel, MasterDataModel, User


class Employee(MasterDataModel):
    """Personel kartı. Ayrılış `personnel.services.terminate_employee` ile kaydedilir."""

    class EducationLevel(models.TextChoices):
        PRIMARY = "PRIMARY", "İlkokul"
        MIDDLE = "MIDDLE", "Ortaokul"
        HIGH_SCHOOL = "HIGH_SCHOOL", "Lise"
        ASSOCIATE = "ASSOCIATE", "Ön lisans"
        BACHELOR = "BACHELOR", "Lisans"
        MASTER = "MASTER", "Yüksek lisans"
        DOCTORATE = "DOCTORATE", "Doktora"

    # Kartta açık görünür; denetim günlüğüne maskeli yazılır (`*******0146`).
    AUDIT_MASKED_FIELDS: ClassVar[tuple[str, ...]] = ("national_id",)

    employee_no = models.CharField("sicil no", max_length=32, blank=True)
    full_name = models.CharField("ad soyad", max_length=150)
    department = models.CharField("birim", max_length=64, db_index=True)
    title = models.CharField("görev", max_length=100, blank=True)
    hire_date = models.DateField("işe giriş tarihi", null=True, blank=True)
    termination_date = models.DateField("işten çıkış tarihi", null=True, blank=True)
    national_id = models.CharField("TC kimlik no", max_length=11, blank=True)
    birth_date = models.DateField("doğum tarihi", null=True, blank=True)
    birth_place = models.CharField("doğum yeri", max_length=100, blank=True)
    phone = models.CharField("telefon", max_length=32, blank=True)
    emergency_contact_name = models.CharField(
        "acil durumda aranacak kişi", max_length=150, blank=True
    )
    emergency_contact_phone = models.CharField("acil durum telefonu", max_length=32, blank=True)
    # En son mezuniyet; diploma `EmployeeDocument` olarak eklenir.
    education_level = models.CharField(
        "öğrenim durumu", max_length=16, choices=EducationLevel.choices, blank=True
    )
    school = models.CharField("okul", max_length=200, blank=True)
    field_of_study = models.CharField("bölüm", max_length=200, blank=True)
    graduation_year = models.PositiveSmallIntegerField("mezuniyet yılı", null=True, blank=True)
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
            models.UniqueConstraint(
                fields=["national_id"],
                condition=~Q(national_id=""),
                name="personnel_national_id_uniq",
                violation_error_message="Bu TC kimlik no başka bir personelde kayıtlı.",
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


def document_upload_to(instance: "EmployeeDocument", filename: str) -> str:
    """Dosya adı tahmin edilemez olsun diye rastgele; özgün ad `original_name`'de tutulur."""
    extension = os.path.splitext(filename)[1].lower()[:10]
    return f"personnel/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class EmployeeDocument(BaseModel):
    """Personel kartına bağlı özlük belgesi: kimlik fotokopisi, bordro, sözleşme, diploma.

    Yalnızca personel uç noktalarından admin ve yönetime verilir; genel ek uç noktaları personel
    kartını kabul etmez. Silinmez: kaldırılınca `is_active=False` olur, kaldıran ve nedeni yazılır.
    """

    class Kind(models.TextChoices):
        ID_COPY = "ID_COPY", "Kimlik fotokopisi"
        PAYROLL = "PAYROLL", "Bordro"
        CONTRACT = "CONTRACT", "Sözleşme"
        DIPLOMA = "DIPLOMA", "Diploma"

    employee = models.ForeignKey(
        Employee, verbose_name="personel", on_delete=models.PROTECT, related_name="documents"
    )
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    file = models.FileField("dosya", upload_to=document_upload_to, max_length=255)
    original_name = models.CharField("dosya adı", max_length=255)
    size = models.PositiveBigIntegerField("boyut (bayt)")
    mime_type = models.CharField("içerik türü", max_length=100)
    # Bordroda dönem (ayın ilk günü); sözleşmede başlangıç ve bitiş (belirsiz sürelide boş).
    period = models.DateField("dönem", null=True, blank=True)
    valid_from = models.DateField("başlangıç tarihi", null=True, blank=True)
    valid_until = models.DateField("bitiş tarihi", null=True, blank=True)
    note = models.CharField("not", max_length=500, blank=True)
    is_active = models.BooleanField("aktif", default=True, db_index=True)
    removed_at = models.DateTimeField("kaldırılma zamanı", null=True, blank=True)
    removed_by = models.ForeignKey(
        User,
        verbose_name="kaldıran",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    removal_reason = models.CharField("kaldırma nedeni", max_length=500, blank=True)

    class Meta:
        verbose_name = "personel belgesi"
        verbose_name_plural = "personel belgeleri"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="PAYROLL", period__isnull=False)
                | (~Q(kind="PAYROLL") & Q(period__isnull=True)),
                name="personnel_document_period_payroll_only",
                violation_error_message="Dönem yalnızca bordroda ve bordroda her zaman girilir.",
            ),
            models.CheckConstraint(
                condition=Q(kind="CONTRACT", valid_from__isnull=False)
                | (~Q(kind="CONTRACT") & Q(valid_from__isnull=True, valid_until__isnull=True)),
                name="personnel_document_dates_contract_only",
                violation_error_message=(
                    "Başlangıç ve bitiş tarihi yalnızca sözleşmede girilir; başlangıç zorunludur."
                ),
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=F("valid_from")),
                name="personnel_document_contract_range",
                violation_error_message="Sözleşme bitiş tarihi başlangıç tarihinden önce olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.original_name}"

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Personel belgeleri silinemez; kaldırılır.")


# --- puantaj (2026-10-29, docs/DECISIONS.md "Personel puantajı") ---------------------------------


class AttendanceStatus(models.TextChoices):
    """Puantajda günün durumu; tablo ve Excel kısa kodu kullanır (`ATTENDANCE_CODES`)."""

    WORKED = "WORKED", "Çalıştı"
    WEEKLY_REST = "WEEKLY_REST", "Hafta tatili"
    PUBLIC_HOLIDAY = "PUBLIC_HOLIDAY", "Resmi tatil"
    ANNUAL_LEAVE = "ANNUAL_LEAVE", "Yıllık izin"
    PAID_LEAVE = "PAID_LEAVE", "Mazeret izni (ücretli)"
    UNPAID_LEAVE = "UNPAID_LEAVE", "Ücretsiz izin"
    SICK_LEAVE = "SICK_LEAVE", "Raporlu"
    ABSENT = "ABSENT", "Devamsız"


ATTENDANCE_CODES: dict[str, str] = {
    AttendanceStatus.WORKED: "Ç",
    AttendanceStatus.WEEKLY_REST: "HT",
    AttendanceStatus.PUBLIC_HOLIDAY: "RT",
    AttendanceStatus.ANNUAL_LEAVE: "Yİ",
    AttendanceStatus.PAID_LEAVE: "Mİ",
    AttendanceStatus.UNPAID_LEAVE: "Üİ",
    AttendanceStatus.SICK_LEAVE: "R",
    AttendanceStatus.ABSENT: "D",
}
# Fazla mesai yalnızca bu günlere girilir (tatilde çalışılan saat de fazla mesaidir).
OVERTIME_STATUSES = (
    AttendanceStatus.WORKED,
    AttendanceStatus.WEEKLY_REST,
    AttendanceStatus.PUBLIC_HOLIDAY,
)


class PublicHoliday(MasterDataModel):
    """Resmi tatil günü. Sabit tatiller düğmeyle eklenir, dini bayramlar her yıl elle girilir.
    Yarım gün tatil (arife, 28 Ekim) puantajda "Çalıştı" açılır, tabloda işaretli görünür."""

    date = models.DateField("tarih")
    name = models.CharField("ad", max_length=100)
    half_day = models.BooleanField("yarım gün", default=False)

    class Meta:
        verbose_name = "resmi tatil"
        verbose_name_plural = "resmi tatiller"
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["date"],
                condition=Q(is_active=True),
                name="personnel_holiday_date_uniq",
                violation_error_message="Bu tarihte zaten bir tatil kayıtlı.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date:%d.%m.%Y} {self.name}"


def default_rest_weekdays() -> list[int]:
    """Varsayılan hafta tatili: pazar (pazartesi 0 … pazar 6)."""
    return [6]


class AttendanceSettings(BaseModel):
    """Puantaj ayarları (tek kayıt): ay önceden dolu açılırken hafta tatili sayılan günler."""

    rest_weekdays = models.JSONField("hafta tatili günleri", default=default_rest_weekdays)

    class Meta:
        verbose_name = "puantaj ayarları"
        verbose_name_plural = "puantaj ayarları"

    def __str__(self) -> str:
        return "Puantaj ayarları"


class AttendanceMonth(DocumentModel):
    """Aylık puantaj (`PU-`). Açıkken yalnızca değiştirilen günler saklanır; onaylanınca ayın bütün
    günleri yazılır ve ay kilitlenir. Düzeltme için gerekçeyle yeniden açılır."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Açık"
        APPROVED = "APPROVED", "Onaylandı"

    year = models.PositiveSmallIntegerField("yıl")
    month = models.PositiveSmallIntegerField("ay")
    approved_at = models.DateTimeField("onay zamanı", null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        verbose_name="onaylayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "puantaj"
        verbose_name_plural = "puantajlar"
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "month"], name="personnel_attendance_month_uniq"
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1, month__lte=12), name="personnel_attendance_month_range"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} ({self.month:02d}.{self.year})"


class AttendanceEntry(BaseModel):
    """Bir kişinin bir günlük puantajı. Açık ayda yalnızca değiştirilen günler vardır; onayda
    kalan günler varsayılan durumlarıyla yazılır."""

    month = models.ForeignKey(
        AttendanceMonth, verbose_name="puantaj", on_delete=models.PROTECT, related_name="entries"
    )
    employee = models.ForeignKey(
        Employee, verbose_name="personel", on_delete=models.PROTECT, related_name="attendance"
    )
    date = models.DateField("tarih")
    status = models.CharField("durum", max_length=16, choices=AttendanceStatus.choices)
    # Saat (ör. 2,5); Decimal, CLAUDE.md kural 8.
    overtime_hours = models.DecimalField(
        "fazla mesai (saat)", max_digits=5, decimal_places=2, default=Decimal(0)
    )
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        verbose_name = "puantaj günü"
        verbose_name_plural = "puantaj günleri"
        ordering = ["date", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date"], name="personnel_attendance_entry_uniq"
            ),
            models.CheckConstraint(
                condition=Q(overtime_hours__gte=0, overtime_hours__lte=24),
                name="personnel_attendance_overtime_range",
                violation_error_message="Fazla mesai 0 ile 24 saat arasında olmalı.",
            ),
            models.CheckConstraint(
                condition=Q(overtime_hours=0) | Q(status__in=[s.value for s in OVERTIME_STATUSES]),
                name="personnel_attendance_overtime_status",
                violation_error_message=(
                    "Fazla mesai yalnızca çalışılan, hafta tatili ve resmi tatil günlerine girilir."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.date:%d.%m.%Y} {ATTENDANCE_CODES.get(self.status, '')}"
