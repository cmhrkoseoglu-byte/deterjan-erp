"""Personel kartları: kimlik ve görev bilgileri (2026-10-25), özlük bilgileri ve belgeleri,
puantaj (2026-10-29), ücretler (2026-11-01, maliyet modülünden taşındı) ve ön bordro (2026-11-01;
docs/DECISIONS.md).

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
    # Bordro (docs/DECISIONS.md "Personel bordrosu"). Emekli (SGDP), engelli, kısmi süreli, net
    # ücretle anlaşılmış ya da başka işyerinde de çalışan kişinin bordrosu mali müşavirdedir ve
    # ERP'de hesaplanmaz; nedeni yazılmaz (engellilik sağlık verisidir, KVKK m.6).
    payroll_external = models.BooleanField("bordrosu mali müşavirde", default=False)
    # BES otomatik katılım: kesinti her ay SGK matrahının yüzdesi (bordro parametresi).
    bes_enrolled = models.BooleanField("BES'e dahil", default=False)
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
    # Yarım gün tatilde (28 Ekim, arife) öğleden sonra da çalıştı: bordroda yarım günlük ilave
    # ücret (docs/DECISIONS.md "Personel bordrosu"). Yalnızca çalışılan güne girilir.
    holiday_half_worked = models.BooleanField("yarım gün tatilde çalıştı", default=False)
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
            models.CheckConstraint(
                condition=Q(holiday_half_worked=False) | Q(status=AttendanceStatus.WORKED),
                name="personnel_attendance_half_holiday_worked",
                violation_error_message=(
                    "Yarım gün tatil çalışması yalnızca çalışılan güne girilir."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.date:%d.%m.%Y} {ATTENDANCE_CODES.get(self.status, '')}"


# --- ücretler (docs/DECISIONS.md "Personel maliyeti", "Personel bordrosu") -----------------------


class EmployeeWage(BaseModel):
    """Kişinin brüt aylık ücreti, bir tarihten itibaren geçerli. Zam yeni tarihle eklenir; yanlış
    kayıt silinmez, gerekçeyle kaldırılır. Kişisel veri: yalnızca yönetim ve admin görür
    (docs/KVKK.md).

    2026-10-29'da maliyet modülünde açıldı, 2026-11-01'de buraya taşındı: tablo ve kısıt adları
    (`costing_employeewage`, `costing_wage_*`) taşınırken değiştirilmedi, kayıtlar yerinde kaldı."""

    employee = models.ForeignKey(
        Employee, verbose_name="personel", on_delete=models.PROTECT, related_name="wages"
    )
    gross_monthly = models.DecimalField("brüt aylık ücret (TL)", max_digits=18, decimal_places=2)
    valid_from = models.DateField("geçerlilik başlangıcı")
    note = models.CharField("not", max_length=200, blank=True)
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
        db_table = "costing_employeewage"
        verbose_name = "ücret"
        verbose_name_plural = "ücretler"
        ordering = ["employee", "-valid_from", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "valid_from"],
                condition=Q(is_active=True),
                name="costing_wage_employee_date_uniq",
                violation_error_message="Bu kişinin bu tarihte başlayan bir ücreti zaten var.",
            ),
            models.CheckConstraint(
                condition=Q(gross_monthly__gt=0),
                name="costing_wage_positive",
                violation_error_message="Brüt ücret sıfırdan büyük olmalı.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.gross_monthly} ({self.valid_from})"


# --- ön bordro (docs/DECISIONS.md "Personel bordrosu") ------------------------------------------

PARAMETER_RATE_FIELDS = (
    "employee_sgk_rate",
    "employee_unemployment_rate",
    "employer_sgk_rate",
    "employer_unemployment_rate",
    "incentive_points",
    "tax_rate_1",
    "tax_rate_2",
    "tax_rate_3",
    "tax_rate_4",
    "tax_rate_5",
    "bes_rate",
)


def _percent(label: str) -> models.DecimalField:
    return models.DecimalField(label, max_digits=5, decimal_places=2)


def _amount(label: str) -> models.DecimalField:
    return models.DecimalField(label, max_digits=18, decimal_places=2)


def _rates_in_range() -> Q:
    condition = Q()
    for name in PARAMETER_RATE_FIELDS:
        condition &= Q(**{f"{name}__gte": 0, f"{name}__lte": 100})
    return condition


class PayrollParameterSet(MasterDataModel):
    """Bordro parametreleri: bir yılın yasal değerleri, ayın ilk gününden geçerli. Yıl içinde
    değişirse (ör. Temmuz'da asgari ücret) o aydan geçerli yeni set açılır; set yalnızca kendi
    yılına uygulanır. Oranlar yüzde, damga vergisi binde; gelir vergisi tarifesi dört dilim üst
    sınırı ve beş oran. Silinmez; yanlış set pasife alınır."""

    valid_from = models.DateField("geçerlilik başlangıcı")
    minimum_wage = _amount("asgari ücret (aylık brüt, TL)")
    ceiling_multiplier = models.DecimalField(
        "SGK üst sınır çarpanı", max_digits=5, decimal_places=2
    )
    employee_sgk_rate = _percent("SGK işçi payı (%)")
    employee_unemployment_rate = _percent("işsizlik işçi payı (%)")
    employer_sgk_rate = _percent("SGK işveren payı (%)")
    employer_unemployment_rate = _percent("işsizlik işveren payı (%)")
    # 5510 s. Kanun m.81/ı: imalatta 5 puan, diğer sektörlerde 2 puan, şartlar sağlanmazsa 0.
    incentive_points = _percent("SGK işveren teşviki (puan)")
    stamp_tax_per_mille = models.DecimalField(
        "damga vergisi (binde)", max_digits=6, decimal_places=3
    )
    tax_bracket_1 = _amount("gelir vergisi 1. dilim üst sınırı (TL)")
    tax_bracket_2 = _amount("gelir vergisi 2. dilim üst sınırı (TL)")
    tax_bracket_3 = _amount("gelir vergisi 3. dilim üst sınırı (TL)")
    tax_bracket_4 = _amount("gelir vergisi 4. dilim üst sınırı (TL)")
    tax_rate_1 = _percent("gelir vergisi 1. dilim oranı (%)")
    tax_rate_2 = _percent("gelir vergisi 2. dilim oranı (%)")
    tax_rate_3 = _percent("gelir vergisi 3. dilim oranı (%)")
    tax_rate_4 = _percent("gelir vergisi 4. dilim oranı (%)")
    tax_rate_5 = _percent("gelir vergisi 5. dilim oranı (%)")
    bes_rate = _percent("BES katkı payı (%)")
    # Nakit yemek ödemesinin SGK istisnası, fiilen çalışılan gün başına (0: istisna yok;
    # 5510 s. Kanun m.80, tutar mali müşavirden alınır).
    meal_exemption_daily = models.DecimalField(
        "nakit yemek SGK istisnası (günlük TL)",
        max_digits=18,
        decimal_places=2,
        default=Decimal(0),
    )
    source = models.CharField("kaynak", max_length=500, blank=True)
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        verbose_name = "bordro parametreleri"
        verbose_name_plural = "bordro parametreleri"
        ordering = ["-valid_from", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["valid_from"],
                condition=Q(is_active=True),
                name="personnel_payroll_parameters_date_uniq",
                violation_error_message="Bu tarihten geçerli bir parametre seti zaten var.",
            ),
            models.CheckConstraint(
                condition=Q(valid_from__day=1),
                name="personnel_payroll_parameters_first_day",
                violation_error_message="Geçerlilik başlangıcı ayın ilk günü olmalı.",
            ),
            models.CheckConstraint(
                condition=Q(minimum_wage__gt=0, ceiling_multiplier__gte=1)
                & Q(stamp_tax_per_mille__gte=0, stamp_tax_per_mille__lte=100)
                & Q(incentive_points__lte=F("employer_sgk_rate"))
                & _rates_in_range(),
                name="personnel_payroll_parameters_values",
                violation_error_message="Parametre değerleri geçersiz.",
            ),
            models.CheckConstraint(
                condition=Q(tax_bracket_1__gt=0)
                & Q(tax_bracket_2__gt=F("tax_bracket_1"))
                & Q(tax_bracket_3__gt=F("tax_bracket_2"))
                & Q(tax_bracket_4__gt=F("tax_bracket_3")),
                name="personnel_payroll_parameters_brackets",
                violation_error_message="Gelir vergisi dilim sınırları artan olmalı.",
            ),
            models.CheckConstraint(
                condition=Q(meal_exemption_daily__gte=0),
                name="personnel_payroll_parameters_meal",
                violation_error_message="Nakit yemek istisnası negatif olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"Bordro parametreleri {self.valid_from:%m.%Y}"


class ExternalPayrollFigure(BaseModel):
    """Bordrosu mali müşavirde olan kişinin (`Employee.payroll_external`) ay rakamları: mali
    müşavirin bordrosundaki brüt toplam ve işverene maliyet. İşveren maliyeti tablosu ve personel
    maliyeti eksik kalmasın diye elle girilir; değişiklik denetim günlüğüne yazılır. Rakamı olan ay
    kişinin bordrosunun mali müşavirde olduğu aydır (kart işareti sonradan değişse de); ERP'deki
    kümülatif zinciri keser. Silinmez; yanlış girilen rakam gerekçeyle kaldırılır."""

    employee = models.ForeignKey(
        Employee,
        verbose_name="personel",
        on_delete=models.PROTECT,
        related_name="external_payroll",
    )
    year = models.PositiveSmallIntegerField("yıl")
    month = models.PositiveSmallIntegerField("ay")
    gross_total = _amount("brüt toplam (TL)")
    employer_cost = _amount("işverene maliyet (TL)")
    note = models.CharField("not", max_length=200, blank=True)
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
        verbose_name = "mali müşavir bordrosu"
        verbose_name_plural = "mali müşavir bordroları"
        ordering = ["-year", "-month", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "month"],
                condition=Q(is_active=True),
                name="personnel_external_payroll_month_uniq",
                violation_error_message="Bu kişinin bu ay için rakamları zaten girilmiş.",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1, month__lte=12)
                & Q(gross_total__gte=0)
                & Q(employer_cost__gte=F("gross_total")),
                name="personnel_external_payroll_values",
                violation_error_message=(
                    "Brüt toplam negatif olamaz; işverene maliyet brüt toplamdan az olamaz."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.month:02d}.{self.year}"


class PayrollOpeningBalance(BaseModel):
    """Devir: kişinin bu işverende, `month` ayından ÖNCEKİ yıl içi kümülatif gelir vergisi
    matrahı ve asgari ücret istisnası matrahı (mali müşavirin bir önceki ay bordrosundan). ERP
    bordrosunun başladığı ayda (Ekim 2026), mali müşavirden ERP'ye geçişte ya da ERP ile mali
    müşavirin kümülatifi ayrıştığında girilir; hesap kişinin o yıl, o ay ya da öncesindeki en son
    devrinden başlar. `exemption_base` kayıtta, devir ayından önceki `exemption_months` ayın kendi
    parametrelerindeki asgari ücret matrahlarının toplamı olarak yazılır. Silinmez; yanlış devir
    gerekçeyle kaldırılır."""

    employee = models.ForeignKey(
        Employee,
        verbose_name="personel",
        on_delete=models.PROTECT,
        related_name="payroll_openings",
    )
    year = models.PositiveSmallIntegerField("yıl")
    month = models.PositiveSmallIntegerField("ay")
    tax_base = _amount("kümülatif gelir vergisi matrahı (TL)")
    exemption_months = models.PositiveSmallIntegerField("asgari ücret istisnası uygulanan ay")
    exemption_base = _amount("kümülatif asgari ücret istisna matrahı (TL)")
    note = models.CharField("not", max_length=200, blank=True)
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
        verbose_name = "bordro devri"
        verbose_name_plural = "bordro devirleri"
        ordering = ["-year", "-month", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "month"],
                condition=Q(is_active=True),
                name="personnel_payroll_opening_month_uniq",
                violation_error_message="Bu kişinin bu ay için devri zaten girilmiş.",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=2, month__lte=12)
                & Q(tax_base__gte=0, exemption_base__gte=0)
                & Q(exemption_months__lte=F("month") - 1),
                name="personnel_payroll_opening_values",
                violation_error_message=(
                    "Devir Şubat–Aralık ayına girilir; matrahlar negatif olamaz, istisna ay sayısı "
                    "devir ayından önceki ay sayısını aşamaz."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"Devir {self.employee_id} {self.month:02d}.{self.year}"


class PayrollItemKind(models.TextChoices):
    EXTRA = "EXTRA", "Ek ödeme"
    DEDUCTION = "DEDUCTION", "Kesinti"


class PayrollItemCategory(models.TextChoices):
    PREMIUM = "PREMIUM", "Prim"
    BONUS = "BONUS", "İkramiye"
    TRAVEL = "TRAVEL", "Yol (nakit)"
    MEAL = "MEAL", "Yemek (nakit)"
    OTHER_EXTRA = "OTHER_EXTRA", "Diğer ek ödeme"
    ADVANCE = "ADVANCE", "Avans"
    GARNISHMENT = "GARNISHMENT", "İcra / nafaka"
    OTHER_DEDUCTION = "OTHER_DEDUCTION", "Diğer kesinti"


EXTRA_CATEGORIES = (
    PayrollItemCategory.PREMIUM,
    PayrollItemCategory.BONUS,
    PayrollItemCategory.TRAVEL,
    PayrollItemCategory.MEAL,
    PayrollItemCategory.OTHER_EXTRA,
)
DEDUCTION_CATEGORIES = (
    PayrollItemCategory.ADVANCE,
    PayrollItemCategory.GARNISHMENT,
    PayrollItemCategory.OTHER_DEDUCTION,
)
# Açıklaması zorunlu kategoriler (pusulada ne olduğu yazsın; İş Kanunu m.37).
DESCRIBED_CATEGORIES = (PayrollItemCategory.OTHER_EXTRA, PayrollItemCategory.OTHER_DEDUCTION)


class PayrollItem(BaseModel):
    """Kişinin bir aydaki elle girilen kalemi: ek ödeme (brüt; SGK'ya ve vergiye tabi, nakit yemekte
    günlük sınıra kadar SGK istisnası) ya da netten kesinti. Kalem, birlikte ödendiği ücretin
    bordro ayına girilir. Silinmez; yanlış kalem gerekçeyle kaldırılır. Açıklama ekranda, dökümde
    ve kişinin pusulasında görünür, bordro listesine, Excel'e ve kartın geçmişine yazılmaz; denetim
    günlüğünde eski → yeni değeriyle kalır. Kişisel veri olabilir (icra dosyası gibi)."""

    Kind = PayrollItemKind
    Category = PayrollItemCategory

    employee = models.ForeignKey(
        Employee,
        verbose_name="personel",
        on_delete=models.PROTECT,
        related_name="payroll_items",
    )
    year = models.PositiveSmallIntegerField("yıl")
    month = models.PositiveSmallIntegerField("ay")
    kind = models.CharField("tür", max_length=10, choices=PayrollItemKind.choices)
    category = models.CharField("kategori", max_length=20, choices=PayrollItemCategory.choices)
    description = models.CharField("açıklama", max_length=100, blank=True)
    amount = _amount("tutar (TL)")
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
        verbose_name = "bordro kalemi"
        verbose_name_plural = "bordro kalemleri"
        ordering = ["year", "month", "employee_id", "id"]
        indexes = [models.Index(fields=["year", "month"], name="personnel_payroll_item_month")]
        constraints = [
            models.CheckConstraint(
                condition=Q(month__gte=1, month__lte=12) & Q(amount__gt=0),
                name="personnel_payroll_item_values",
                violation_error_message="Tutar sıfırdan büyük olmalı.",
            ),
            models.CheckConstraint(
                condition=Q(kind=PayrollItemKind.EXTRA, category__in=EXTRA_CATEGORIES)
                | Q(kind=PayrollItemKind.DEDUCTION, category__in=DEDUCTION_CATEGORIES),
                name="personnel_payroll_item_category",
                violation_error_message="Kategori kalemin türüne uymuyor.",
            ),
        ]

    def __str__(self) -> str:
        # Açıklama yazılmaz (icra ya da nafaka bilgisi denetim günlüğünün başlığına düşmesin).
        return f"{self.get_category_display()} {self.employee_id} {self.month:02d}.{self.year}"


class PayrollRun(DocumentModel):
    """Aylık bordro (`BR-`, numara bordronun yılından). Açıkken her açılışta hesaplanır
    (taslak); onaylanınca ayın satırları saklanır (`PayrollApproval`, `PayrollSlip`) ve aya etki
    eden yazımlar kilitlenir. Düzeltme için gerekçeyle yeniden açılır; eski onay saklanır. Aylar
    sırayla onaylanır, sondan başa açılır (docs/DECISIONS.md "Personel bordrosu", 4. adım)."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Açık"
        APPROVED = "APPROVED", "Onaylandı"

    year = models.PositiveSmallIntegerField("yıl")
    month = models.PositiveSmallIntegerField("ay")
    current = models.ForeignKey(
        "PayrollApproval",
        verbose_name="geçerli onay",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    # Yeniden açılan ayda onaydaki işaretler yerine kartın bugünkü işaretlerine geçirilen kişiler.
    follow_card = models.JSONField("kartı izleyen kişiler", default=list, blank=True)

    class Meta:
        verbose_name = "bordro"
        verbose_name_plural = "bordrolar"
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "month"], name="personnel_payroll_run_month_uniq"
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1, month__lte=12), name="personnel_payroll_run_month_range"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} {self.month:02d}.{self.year}"


class PayrollApproval(BaseModel):
    """Bordronun bir onayı: onay anındaki parametreler, firma bilgisi, ödeme tarihi, toplamlar ve
    kişi satırları (`PayrollSlip`). Yeniden açılınca `reopened_*` doldurulur ve kayıt saklanır; bir
    sonraki onay yeni kayıttır. Tutarlar değişmez; yalnızca ödeme tarihi gerekçeyle düzeltilir."""

    run = models.ForeignKey(
        PayrollRun, verbose_name="bordro", on_delete=models.PROTECT, related_name="approvals"
    )
    sequence = models.PositiveSmallIntegerField("onay sırası")
    approved_at = models.DateTimeField("onay zamanı")
    approved_by = models.ForeignKey(
        User, verbose_name="onaylayan", on_delete=models.PROTECT, related_name="+"
    )
    payment_date = models.DateField("ödeme tarihi")
    attendance_number = models.CharField("puantaj no", max_length=32, blank=True)
    engine_version = models.CharField("hesap motoru sürümü", max_length=16)
    parameters = models.JSONField("parametreler")
    company = models.JSONField("firma bilgileri")
    acknowledged = models.JSONField("okunan uyarılar", default=list, blank=True)
    employee_count = models.PositiveIntegerField("ERP'de hesaplanan kişi")
    external_count = models.PositiveIntegerField("mali müşavirdeki kişi")
    gross_total = models.DecimalField("brüt toplam", max_digits=18, decimal_places=2)
    employer_cost = models.DecimalField("işverene maliyet", max_digits=18, decimal_places=2)
    net_pay = models.DecimalField("net ücret", max_digits=18, decimal_places=2)
    payable = models.DecimalField("ödenecek", max_digits=18, decimal_places=2)
    income_tax = models.DecimalField("gelir vergisi", max_digits=18, decimal_places=2)
    stamp_tax = models.DecimalField("damga vergisi", max_digits=18, decimal_places=2)
    reopened_at = models.DateTimeField("yeniden açma zamanı", null=True, blank=True)
    reopened_by = models.ForeignKey(
        User,
        verbose_name="yeniden açan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    reopen_reason = models.TextField("yeniden açma gerekçesi", blank=True)

    class Meta:
        verbose_name = "bordro onayı"
        verbose_name_plural = "bordro onayları"
        ordering = ["run", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"], name="personnel_payroll_approval_sequence_uniq"
            ),
            models.UniqueConstraint(
                fields=["run"],
                condition=Q(reopened_at__isnull=True),
                name="personnel_payroll_approval_current_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.run_id} · {self.sequence}. onay"


class PayrollSlip(BaseModel):
    """Onaylı bordronun bir kişisi: kişi bilgisi (TC kimlik no yalnızca maskeli), onaydaki
    işaretler, hesap satırı, kalemler, uyarılar ve kümülatifin kuruluşu onay anındaki haliyle.
    Bordrosu mali müşavirde olan kişide tutarlar mali müşavirin rakamlarıdır, satır yalnızca
    günler içindir.
    Değiştirilmez ve silinmez (yasal kayıt)."""

    approval = models.ForeignKey(
        PayrollApproval, verbose_name="onay", on_delete=models.PROTECT, related_name="slips"
    )
    employee = models.ForeignKey(
        Employee, verbose_name="personel", on_delete=models.PROTECT, related_name="+"
    )
    external = models.BooleanField("bordrosu mali müşavirde")
    bes_enrolled = models.BooleanField("BES'e dahil")
    person = models.JSONField("kişi bilgisi")
    sgk_days = models.PositiveSmallIntegerField("SGK gün")
    gross_total = models.DecimalField("brüt toplam", max_digits=18, decimal_places=2)
    employer_cost = models.DecimalField("işverene maliyet", max_digits=18, decimal_places=2)
    # Mali müşavirdeki kişide onay anındaki rakam kaydı: {"id", "gross_total", "employer_cost",
    # "note"}; girilmemişse ya da ERP'de hesaplanan kişide boş.
    figure = models.JSONField("mali müşavir rakamı", null=True, blank=True)
    net_pay = models.DecimalField("net ücret", max_digits=18, decimal_places=2, null=True)
    payable = models.DecimalField("ödenecek", max_digits=18, decimal_places=2, null=True)
    income_tax = models.DecimalField("gelir vergisi", max_digits=18, decimal_places=2, null=True)
    stamp_tax = models.DecimalField("damga vergisi", max_digits=18, decimal_places=2, null=True)
    tax_base_after = models.DecimalField(
        "kümülatif GV matrahı (ay sonu)", max_digits=18, decimal_places=2, null=True
    )
    exemption_base_after = models.DecimalField(
        "asgari ücret istisna matrahı (ay sonu)", max_digits=18, decimal_places=2, null=True
    )
    line = models.JSONField("hesap satırı")
    items = models.JSONField("ek ödeme ve kesintiler", default=list, blank=True)
    warnings = models.JSONField("uyarılar", default=list, blank=True)
    chain = models.JSONField("kümülatifin kuruluşu", default=dict, blank=True)

    class Meta:
        verbose_name = "bordro satırı"
        verbose_name_plural = "bordro satırları"
        ordering = ["approval", "employee"]
        constraints = [
            models.UniqueConstraint(
                fields=["approval", "employee"], name="personnel_payroll_slip_employee_uniq"
            ),
            models.CheckConstraint(
                condition=Q(external=True)
                | Q(
                    net_pay__isnull=False,
                    payable__isnull=False,
                    tax_base_after__isnull=False,
                    exemption_base_after__isnull=False,
                ),
                name="personnel_payroll_slip_computed_values",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.approval_id} · {self.employee_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValueError("Onaylı bordro satırı değiştirilemez.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("Onaylı bordro satırı silinemez.")
