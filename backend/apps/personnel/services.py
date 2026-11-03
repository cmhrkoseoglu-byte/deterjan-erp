"""Personel yazma işlemleri (yalnızca admin ve yönetim): kartlar, özlük belgeleri, puantaj,
ücretler ve ön bordro (parametreler, mali müşavir rakamları, devir, ek ödeme ve kesintiler).

Kart silinmez (CLAUDE.md kural 6): işten ayrılış `terminate_employee` ile kaydedilir (kart pasife
alınır, çıkış tarihi yazılır), yeniden işe başlayan `reinstate_employee` ile açılır. Her değişiklik
eski → yeni değerleriyle denetim günlüğüne yazılır (kural 7). Özlük belgelerinin eklenmesi,
açılması ve kaldırılması kartın geçmişine de yazılır. Puantaj ayı onayla kilitlenir; ayrılışta
çıkış tarihinden sonraki puantaj günleri kaldırılır (docs/DECISIONS.md "Puantajda çıkıştan sonraki
günler").

Kilit sırası (kilitlenme olmasın diye her yazımda aynı): personel kartları (kimlik sırasıyla),
puantaj ayları (yıl, ay sırasıyla), puantaj günleri, bordro kayıtları (devir, kalem, mali müşavir
rakamı). Gün ve aralık girişi ile ay onayı önce kartları kilitler; böylece aynı anda kaydedilen bir
ayrılış çıkıştan sonraya gün bırakamaz. Bordro kayıtları da önce kişinin kartını kilitler.
"""

import os
import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import attachments
from apps.core.audit import log_change, snapshot
from apps.core.exceptions import BusinessRuleError
from apps.core.formatting import format_money
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import YONETIM
from apps.core.services import create_document, save_with_audit, transition_status
from apps.masterdata import services as masterdata
from apps.personnel import selectors
from apps.personnel.models import (
    DESCRIBED_CATEGORIES,
    EXTRA_CATEGORIES,
    OVERTIME_STATUSES,
    PARAMETER_RATE_FIELDS,
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeWage,
    ExternalPayrollFigure,
    PayrollItem,
    PayrollItemCategory,
    PayrollItemKind,
    PayrollOpeningBalance,
    PayrollParameterSet,
    PublicHoliday,
)
from apps.personnel.state import attendance_month_states

# Kartları gören ve düzenleyen roller (admin her yere erişir). Kişisel veri: docs/KVKK.md.
PERSONNEL_ROLES = (YONETIM,)

EMPLOYEE_FIELDS = (
    "employee_no",
    "full_name",
    "department",
    "title",
    "hire_date",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
    "national_id",
    "birth_date",
    "birth_place",
    "education_level",
    "school",
    "field_of_study",
    "graduation_year",
    "payroll_external",
    "bes_enrolled",
    "user",
)
_TEXT_FIELDS = (
    "employee_no",
    "full_name",
    "department",
    "title",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
    "birth_place",
    "school",
    "field_of_study",
)
EARLIEST_BIRTH_DATE = date(1900, 1, 1)
EARLIEST_GRADUATION_YEAR = 1940
# Özlük belgeleri taranmış ya da fotoğrafı çekilmiş belgedir; içerik türü uzantıdan belirlenir.
DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def _require_role(actor: User | None) -> None:
    if not user_has_role(actor, PERSONNEL_ROLES):
        raise PermissionDenied("Personel kayıtlarını yalnızca yönetim ve sistem yöneticisi görür.")


def _pick(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


def _text(value: Any) -> str:
    """Baştaki/sondaki boşluklar atılır, aradaki boşluklar teke iner."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean(values: Mapping[str, Any], employee: Employee | None = None) -> dict[str, Any]:
    cleaned = dict(values)
    for name in _TEXT_FIELDS:
        if name in cleaned:
            cleaned[name] = _text(cleaned[name])
    if "national_id" in cleaned:
        cleaned["national_id"] = re.sub(r"\s+", "", str(cleaned["national_id"] or ""))
    if "full_name" in cleaned and not cleaned["full_name"]:
        raise BusinessRuleError("full_name_required", "Ad soyad girilmelidir.")
    if "department" in cleaned:
        if not cleaned["department"]:
            raise BusinessRuleError("department_required", "Birim girilmelidir.")
        # Aynı birim farklı yazılmasın ("depo" / "Depo"): var olan yazım kullanılır.
        cleaned["department"] = selectors.canonical_department(cleaned["department"])
    others = Employee.objects.exclude(pk=employee.pk) if employee else Employee.objects.all()
    if cleaned.get("employee_no"):
        number = cleaned["employee_no"]
        owner = others.filter(employee_no=number).first()
        if owner is not None:
            raise BusinessRuleError(
                "employee_no_taken",
                f"{number} sicil no başka bir personelde kayıtlı: {owner.full_name}.",
            )
    if cleaned.get("national_id"):
        # Mesajda numara tekrarlanmaz (kişisel veri).
        if not masterdata.valid_tckn(cleaned["national_id"]):
            raise BusinessRuleError(
                "invalid_national_id",
                "TC kimlik no geçersiz: 11 haneli olmalı ve kontrol haneleri tutmalı.",
            )
        owner = others.filter(national_id=cleaned["national_id"]).first()
        if owner is not None:
            raise BusinessRuleError(
                "national_id_taken",
                f"Bu TC kimlik no başka bir personelde kayıtlı: {owner.full_name}.",
            )
    today = timezone.localdate()
    birth_date = cleaned.get("birth_date")
    if birth_date is not None and not EARLIEST_BIRTH_DATE <= birth_date <= today:
        raise BusinessRuleError(
            "invalid_birth_date", "Doğum tarihi bugünden sonra ya da 1900'den önce olamaz."
        )
    year = cleaned.get("graduation_year")
    if year is not None and not EARLIEST_GRADUATION_YEAR <= year <= today.year:
        raise BusinessRuleError(
            "invalid_graduation_year",
            f"Mezuniyet yılı {EARLIEST_GRADUATION_YEAR} ile {today.year} arasında olmalı.",
        )
    user = cleaned.get("user")
    if user is not None and (employee is None or employee.user_id != user.pk):
        if not user.is_active:
            raise BusinessRuleError("inactive_user", "Pasif kullanıcı personel kartına bağlanamaz.")
        owner = others.filter(user=user).first()
        if owner is not None:
            raise BusinessRuleError(
                "user_already_linked",
                f"{user.username} kullanıcısı başka bir personel kartına bağlı: {owner.full_name}.",
            )
    return cleaned


@transaction.atomic
def create_employee(actor: User, data: Mapping[str, Any]) -> Employee:
    """Personel kartı açar. Zorunlu: ad soyad, birim. Sicil no ve TC kimlik no girilmişse
    benzersizdir; TC kimlik no kontrol haneleriyle denetlenir (boşluklar atılır). Doğum tarihi ve
    mezuniyet yılı ileri bir tarih olamaz. Sistem kullanıcısı (isteğe bağlı) aktif olmalı ve başka
    karta bağlı olmamalıdır."""
    _require_role(actor)
    values = _clean(_pick(data, EMPLOYEE_FIELDS))
    return masterdata.create_record(actor, Employee, values)


@transaction.atomic
def update_employee(actor: User, employee: Employee, data: Mapping[str, Any]) -> Employee:
    """Kartı günceller; değişen alanlar eski → yeni değerleriyle günlüğe yazılır. Ayrılış ve çıkış
    tarihi bu servisle değişmez (`terminate_employee`, `reinstate_employee`).

    İşe giriş tarihi, kişinin işte olmayacağı aylara düşen bordro kaydı (ek ödeme, kesinti, devir)
    ya da istisna ay sayısı yeni tarihe göre fazla kalan devir varken değiştirilemez. Kart önce
    kilitlenir (bordro kayıtlarının kilit sırası): aynı anda girilen kalem ya da devir bu denetimi
    atlatamaz."""
    _require_role(actor)
    employee = Employee.objects.select_for_update().get(pk=employee.pk)
    values = _clean(_pick(data, EMPLOYEE_FIELDS), employee)
    hire = values.get("hire_date")
    if hire and hire != employee.hire_date:
        _require_no_payroll_records(
            employee,
            Q(year__lt=hire.year) | Q(year=hire.year, month__lt=hire.month),
            Q(year__lt=hire.year) | Q(year=hire.year, month__lte=hire.month),
            f"işe giriş tarihinden ({hire:%d.%m.%Y}) önceki aylarda",
            "payroll_items_before_hire",
        )
        _require_opening_months_within(employee, hire)
    return masterdata.update_record(actor, employee, values)


def _require_opening_months_within(employee: Employee, hire: date) -> None:
    """İşe giriş yılındaki devirlerin asgari ücret istisnası ay sayısı yeni işe giriş tarihine göre
    fazla kalıyorsa reddeder (istisna ay sayısı işe girişten bu yana ay sayısını aşamaz; giriş ayı
    tam sayılır)."""
    excess = [
        opening
        for opening in PayrollOpeningBalance.objects.filter(
            employee=employee, is_active=True, year=hire.year, month__gt=hire.month
        ).order_by("month")
        if opening.exemption_months > opening.month - hire.month
    ]
    if not excess:
        return
    listed = ", ".join(
        f"{selectors.month_label(opening.year, opening.month)} devri ({opening.exemption_months} "
        f"ay; en çok {opening.month - hire.month})"
        for opening in excess
    )
    raise BusinessRuleError(
        "opening_months_exceed_hire",
        f"{employee.full_name} için yeni işe giriş tarihine ({hire:%d.%m.%Y}) göre asgari ücret "
        f"istisnası ay sayısı fazla kalan devir var: {listed}. Önce devri Personel > Bordro'dan "
        "düzeltin ya da gerekçeyle kaldırın.",
    )


REMOVE_FIRST = (
    "Önce bunları Personel > Bordro'dan gerekçeyle kaldırın; ek ödeme ya da kesinti kişinin "
    "çalıştığı bir aya aitse o aya yeniden girin."
)


def _require_no_payroll_records(
    employee: Employee,
    item_months: Q,
    opening_months: Q,
    where: str,
    code: str,
    advice: str = REMOVE_FIRST,
) -> None:
    """Kişinin işte olmadığı aylara düşen etkin ek ödeme, kesinti ve devir varsa reddeder (kalem
    bordrodan sessizce düşmesin; önce gerekçeyle kaldırılır, kalem başka bir aya aitse o aya yeniden
    girilir)."""
    items = list(
        PayrollItem.objects.filter(employee=employee, is_active=True)
        .filter(item_months)
        .order_by("year", "month", "id")
    )
    openings = list(
        PayrollOpeningBalance.objects.filter(employee=employee, is_active=True)
        .filter(opening_months)
        .order_by("year", "month")
    )
    if not items and not openings:
        return
    listed = [
        f"{selectors.month_label(item.year, item.month)} {item.get_category_display()} "
        f"{format_money(item.amount)} TL"
        for item in items
    ] + [f"{selectors.month_label(opening.year, opening.month)} devri" for opening in openings]
    raise BusinessRuleError(
        code,
        f"{employee.full_name} için {where} bordro kaydı var: {', '.join(listed)}. {advice}",
    )


class ApprovedAttendanceAfterExit(BusinessRuleError):
    """Çıkıştan sonraki günlerden biri onaylı aydadır. Onaylı aylar ("2026-09") API yanıtına
    eklenir; pencere ilk aya bağlantı verir."""

    def __init__(self, message: str, months: list[str]) -> None:
        super().__init__("approved_attendance_after_exit", message)
        self.months = months


def _lock_attendance_after(employee: Employee, day: date) -> list[AttendanceEntry]:
    """Kişinin `day`den sonraki kayıtlı puantaj günleri; önce ayları, sonra günleri kilitlenir
    (kilit sırası). Kart kilitliyken başka bir yazım bu kişiye gün ekleyemez."""
    later = AttendanceEntry.objects.filter(employee=employee, date__gt=day)
    months = {
        record.pk: record
        for record in AttendanceMonth.objects.select_for_update()
        .filter(pk__in=later.values("month_id"))
        .order_by("year", "month")
    }
    entries = list(later.select_for_update().order_by("date", "id"))
    for entry in entries:
        entry.month = months.get(entry.month_id) or entry.month
    return entries


def _approved_after_exit(employee: Employee, day: date, entries: Sequence[AttendanceEntry]) -> str:
    """Onaylı aylarda çıkıştan sonra kayıtlı günler için Türkçe hata metni (aylar ve günleri)."""
    spans: dict[tuple[int, int], tuple[date, date]] = {}
    for entry in entries:
        key = (entry.date.year, entry.date.month)
        first, last = spans.get(key, (entry.date, entry.date))
        spans[key] = (min(first, entry.date), max(last, entry.date))
    months = ", ".join(
        f"{selectors.month_label(year, month)} ({selectors.day_span(first, last)})"
        for (year, month), (first, last) in sorted(spans.items())
    )
    which, again = ("bu ayları", "ayları") if len(spans) > 1 else ("bu ayı", "ayı")
    return (
        f"{employee.full_name}, çıkış tarihinden ({day:%d.%m.%Y}) sonra da onaylı puantajda "
        f"görünüyor: {months}. Bordroya giden rakam değişeceği için önce {which} Puantaj'da "
        f"gerekçeyle yeniden açın, sonra ayrılışı kaydedin; ardından {again} yeniden onaylayıp "
        "yeni Excel'i bordroya verin."
    )


def _remove_attendance(actor: User, employee: Employee, entries: Sequence[AttendanceEntry]) -> None:
    """Çıkıştan sonraki günleri kaldırır. Her gün silinmeden önce bütün alanlarıyla ayın denetim
    kaydına yazılır (taslak reçete satırı gibi; docs/DECISIONS.md)."""
    for entry in entries:
        log_change(
            actor,
            entry.month,
            AuditLog.Action.UPDATE,
            {"entry": [{"id": entry.pk, **snapshot(entry)}, None]},
            f"Çıkış tarihinden sonraki puantaj günü kaldırıldı: {employee.full_name} "
            f"{entry.date:%d.%m.%Y}",
        )
    if entries:
        AttendanceEntry.objects.filter(pk__in=[entry.pk for entry in entries]).delete()


@transaction.atomic
def terminate_employee(
    actor: User,
    employee: Employee,
    termination_date: date,
    *,
    note: str = "",
    remove_attendance: bool = False,
) -> Employee:
    """İşten ayrılışı kaydeder: kart pasife alınır ve çıkış tarihi yazılır (kart silinmez).

    Çıkış tarihi kişinin son iş günüdür; puantajda bu tarihten sonra kayıtlı gün kalmaz:

    - Günlerden biri onaylı bir aydaysa ayrılış kaydedilmez (`approved_attendance_after_exit`):
      bordroya giden rakam değişeceği için ay önce gerekçeyle yeniden açılır.
    - Açık aylardaki günler yalnızca `remove_attendance` ile kaldırılır; verilmemişse hata
      (`attendance_after_exit`) günleri listeler ve pencere onay ister.
    - Kaldırılan her gün eski haliyle ayın denetim kaydına, tarihli özeti ayrılışın notuna (kartın
      geçmişi) yazılır. "Yeniden işe başladı" bu günleri geri getirmez.

    Bağlı sistem hesabı kendiliğinden kapanmaz; Sistem > Kullanıcılar'dan pasife alınır.
    """
    _require_role(actor)
    locked = Employee.objects.select_for_update().get(pk=employee.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_terminated", "Bu personelin ayrılışı zaten kayıtlı.")
    if locked.hire_date and termination_date < locked.hire_date:
        raise BusinessRuleError(
            "termination_before_hire", "İşten çıkış tarihi işe giriş tarihinden önce olamaz."
        )
    _require_no_payroll_records(
        locked,
        Q(year__gt=termination_date.year)
        | Q(year=termination_date.year, month__gt=termination_date.month),
        Q(year__gt=termination_date.year)
        | Q(year=termination_date.year, month__gt=termination_date.month),
        f"çıkış ayından ({selectors.month_label(termination_date.year, termination_date.month)}) "
        "sonraki aylarda",
        "payroll_items_after_exit",
    )
    later = _lock_attendance_after(locked, termination_date)
    approved = [entry for entry in later if entry.month.status == AttendanceMonth.Status.APPROVED]
    if approved:
        raise ApprovedAttendanceAfterExit(
            _approved_after_exit(locked, termination_date, approved),
            sorted({f"{entry.date:%Y-%m}" for entry in approved}),
        )
    summary = selectors.summarize_days(later)
    if later and not remove_attendance:
        raise BusinessRuleError(
            "attendance_after_exit",
            f"Çıkış tarihinden ({termination_date:%d.%m.%Y}) sonra puantajda kayıtlı "
            f"{len(later)} gün var: {summary}. Kaydederseniz bu günler puantajdan kaldırılır; "
            "kişi yeniden işe başlatılsa da geri gelmez.",
        )
    locked.is_active = False
    locked.termination_date = termination_date
    locked.full_clean(exclude=["created_by", "updated_by"])
    text = _text(note) or "İşten ayrıldı"
    if later:
        text = f"{text} · çıkıştan sonraki {len(later)} puantaj günü kaldırıldı: {summary}"
    saved = save_with_audit(locked, actor, note=text)
    _remove_attendance(actor, saved, later)
    return saved


@transaction.atomic
def reinstate_employee(actor: User, employee: Employee, *, note: str = "") -> Employee:
    """Ayrılan personeli yeniden çalışır yapar (ör. yeniden işe alım); çıkış tarihi boşalır, eski
    tarih denetim günlüğünde kalır. Ayrılışta kaldırılan puantaj günleri geri gelmez."""
    _require_role(actor)
    locked = Employee.objects.select_for_update().get(pk=employee.pk)
    if locked.is_active:
        raise BusinessRuleError("already_active", "Bu personel zaten çalışıyor görünüyor.")
    locked.is_active = True
    locked.termination_date = None
    locked.full_clean(exclude=["created_by", "updated_by"])
    return save_with_audit(locked, actor, note=_text(note) or "Yeniden işe başladı")


# --- özlük belgeleri -----------------------------------------------------------------------------


def _document_label(document: EmployeeDocument) -> str:
    """Kartın geçmişinde belgenin adı: "Bordro 09.2026 (eylul.pdf)"."""
    detail = ""
    if document.period:
        detail = f" {document.period:%m.%Y}"
    elif document.valid_from:
        until = f"{document.valid_until:%d.%m.%Y}" if document.valid_until else "belirsiz süreli"
        detail = f" {document.valid_from:%d.%m.%Y} – {until}"
    return f"{document.get_kind_display()}{detail} ({document.original_name})"


@transaction.atomic
def add_document(
    actor: User,
    employee: Employee,
    *,
    kind: str,
    file: UploadedFile,
    period: date | None = None,
    valid_from: date | None = None,
    valid_until: date | None = None,
    note: str = "",
) -> EmployeeDocument:
    """Karta özlük belgesi ekler: kimlik fotokopisi, bordro, sözleşme ya da diploma.

    Dosya PDF, JPG ya da PNG olmalı ve ek boyut sınırını (`ATTACHMENT_MAX_BYTES`) aşmamalı.
    Bordroda dönem zorunludur (ayın ilk gününe çekilir). Sözleşmede başlangıç tarihi zorunludur;
    bitiş tarihi belirsiz süreli sözleşmede boş kalır, başlangıçtan önce olamaz. Belgenin türüne
    uymayan tarihler yok sayılır. Ayrılan personele de belge eklenebilir (ör. son bordro).
    """
    _require_role(actor)
    if kind not in EmployeeDocument.Kind.values:
        raise BusinessRuleError("invalid_kind", "Geçersiz belge türü.")
    name = os.path.basename(file.name or "belge")[:255]
    mime_type = DOCUMENT_TYPES.get(os.path.splitext(name)[1].lower())
    if mime_type is None:
        raise BusinessRuleError("file_type_not_allowed", "Belge PDF, JPG ya da PNG olmalı.")
    size = file.size or 0
    if size == 0:
        raise BusinessRuleError("file_empty", "Dosya boş.")
    max_bytes = int(getattr(settings, "ATTACHMENT_MAX_BYTES", attachments.DEFAULT_MAX_BYTES))
    if size > max_bytes:
        raise BusinessRuleError(
            "file_too_large", f"Dosya en çok {max_bytes // (1024 * 1024)} MB olabilir."
        )
    if kind == EmployeeDocument.Kind.PAYROLL:
        if period is None:
            raise BusinessRuleError("period_required", "Bordronun dönemi (ay ve yıl) girilmelidir.")
        period = period.replace(day=1)
    else:
        period = None
    if kind == EmployeeDocument.Kind.CONTRACT:
        if valid_from is None:
            raise BusinessRuleError(
                "valid_from_required", "Sözleşmenin başlangıç tarihi girilmelidir."
            )
        if valid_until is not None and valid_until < valid_from:
            raise BusinessRuleError(
                "invalid_contract_dates", "Sözleşme bitiş tarihi başlangıç tarihinden önce olamaz."
            )
    else:
        valid_from = valid_until = None
    document = EmployeeDocument(
        employee=employee,
        kind=kind,
        file=file,
        original_name=name,
        size=size,
        mime_type=mime_type,
        period=period,
        valid_from=valid_from,
        valid_until=valid_until,
        note=_text(note)[:500],
    )
    save_with_audit(document, actor)
    log_change(
        actor, employee, AuditLog.Action.CUSTOM, {}, f"Belge eklendi: {_document_label(document)}"
    )
    return document


@transaction.atomic
def remove_document(actor: User, document: EmployeeDocument, reason: str) -> EmployeeDocument:
    """Belgeyi kaldırır: silinmez, pasife alınır ve artık verilmez. Neden zorunludur."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    locked = EmployeeDocument.objects.select_for_update().get(pk=document.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Belge zaten kaldırılmış.")
    locked.is_active = False
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.removal_reason = reason
    save_with_audit(locked, actor, note="Belge kaldırıldı")
    log_change(
        actor,
        locked.employee,
        AuditLog.Action.CUSTOM,
        {},
        f"Belge kaldırıldı: {_document_label(locked)}. Neden: {reason}",
    )
    return locked


def record_document_access(actor: User, document: EmployeeDocument) -> None:
    """Belgenin açıldığını kartın geçmişine yazar (kişisel veriye erişim izi, docs/KVKK.md)."""
    _require_role(actor)
    log_change(
        actor,
        document.employee,
        AuditLog.Action.CUSTOM,
        {},
        f"Belge açıldı: {_document_label(document)}",
    )


# --- puantaj (docs/DECISIONS.md "Personel puantajı") ---------------------------------------------

# Sabit resmi tatiller (2429 sayılı Kanun): (ay, gün, ad, yarım gün). Ramazan ve Kurban Bayramı
# günleri her yıl değiştiği için elle girilir.
FIXED_HOLIDAYS = (
    (1, 1, "Yılbaşı", False),
    (4, 23, "Ulusal Egemenlik ve Çocuk Bayramı", False),
    (5, 1, "Emek ve Dayanışma Günü", False),
    (5, 19, "Atatürk'ü Anma, Gençlik ve Spor Bayramı", False),
    (7, 15, "Demokrasi ve Millî Birlik Günü", False),
    (8, 30, "Zafer Bayramı", False),
    (10, 28, "Cumhuriyet Bayramı arifesi", True),
    (10, 29, "Cumhuriyet Bayramı", False),
)
HOLIDAY_FIELDS = ("date", "name", "half_day")
# Aralıkla girişte hafta tatili ve resmi tatil günlerine yazılmayan durumlar: izne rastlayan
# tatil günleri izinden sayılmaz (İş Kanunu m.56); devamsızlık da yalnızca iş günlerine yazılır.
# Rapor ve ücretsiz izin her takvim gününe yazılır.
WORKDAY_ONLY_STATUSES = (
    AttendanceStatus.ANNUAL_LEAVE,
    AttendanceStatus.PAID_LEAVE,
    AttendanceStatus.ABSENT,
)
REST_STATUSES = (AttendanceStatus.WEEKLY_REST, AttendanceStatus.PUBLIC_HOLIDAY)
MAX_OVERTIME_HOURS = Decimal(24)
MAX_RANGE_DAYS = 366
MIN_YEAR, MAX_YEAR = 2000, 2100


def get_attendance_settings() -> AttendanceSettings:
    """Puantaj ayarları (tek kayıt; yoksa varsayılanla oluşturulur: hafta tatili pazar)."""
    instance = AttendanceSettings.objects.order_by("pk").first()
    if instance is None:
        instance, _ = AttendanceSettings.objects.get_or_create(pk=1)
    return instance


@transaction.atomic
def update_attendance_settings(actor: User, rest_weekdays: Sequence[int]) -> AttendanceSettings:
    """Varsayılan hafta tatili günlerini değiştirir (pazartesi 0 … pazar 6). En az bir gün seçilir,
    en az bir iş günü kalır. Açık aylarda değiştirilmemiş günler yeni ayara göre hesaplanır;
    onaylı aylar değişmez."""
    _require_role(actor)
    days = sorted({int(day) for day in rest_weekdays})
    if not days or len(days) > 6 or any(day < 0 or day > 6 for day in days):
        raise BusinessRuleError(
            "invalid_rest_weekdays", "Hafta tatili için en az bir, en çok altı gün seçilmelidir."
        )
    instance = AttendanceSettings.objects.select_for_update().get(pk=get_attendance_settings().pk)
    instance.rest_weekdays = days
    return save_with_audit(instance, actor)


def _month_locked(year: int, month: int) -> bool:
    return AttendanceMonth.objects.filter(
        year=year, month=month, status=AttendanceMonth.Status.APPROVED
    ).exists()


def _require_month_open(day: date) -> None:
    if _month_locked(day.year, day.month):
        raise BusinessRuleError(
            "month_locked",
            f"{selectors.month_label(day.year, day.month)} puantajı onaylı; "
            "değiştirmek için önce ay yeniden açılmalı.",
        )


def _clean_holiday(values: dict[str, Any], holiday: PublicHoliday | None = None) -> dict[str, Any]:
    if "name" in values:
        values["name"] = _text(values["name"])
        if not values["name"]:
            raise BusinessRuleError("name_required", "Tatilin adı girilmelidir.")
    day = values.get("date", holiday.date if holiday else None)
    if day is None:
        raise BusinessRuleError("date_required", "Tatilin tarihi girilmelidir.")
    others = PublicHoliday.objects.filter(is_active=True, date=day)
    if holiday is not None:
        others = others.exclude(pk=holiday.pk)
    owner = others.first()
    if owner is not None:
        raise BusinessRuleError(
            "holiday_exists", f"{day:%d.%m.%Y} tarihinde zaten tatil kayıtlı: {owner.name}."
        )
    _require_month_open(day)
    return values


@transaction.atomic
def add_holiday(actor: User, data: Mapping[str, Any]) -> PublicHoliday:
    """Takvime resmi tatil ekler (ör. dini bayram günü). Tarih onaylı bir aya düşemez."""
    _require_role(actor)
    values = _clean_holiday(_pick(data, HOLIDAY_FIELDS))
    return masterdata.create_record(actor, PublicHoliday, values)


@transaction.atomic
def update_holiday(actor: User, holiday: PublicHoliday, data: Mapping[str, Any]) -> PublicHoliday:
    """Tatilin adını, tarihini ya da yarım gün bilgisini değiştirir (eski ve yeni tarih açık ayda
    olmalı)."""
    _require_role(actor)
    _require_month_open(holiday.date)
    values = _clean_holiday(_pick(data, HOLIDAY_FIELDS), holiday)
    return masterdata.update_record(actor, holiday, values)


@transaction.atomic
def remove_holiday(actor: User, holiday: PublicHoliday) -> PublicHoliday:
    """Tatili takvimden kaldırır (silinmez, pasife alınır). Onaylı aydaki tatil kaldırılamaz."""
    _require_role(actor)
    _require_month_open(holiday.date)
    return masterdata.set_active(actor, holiday, False, note="Tatil takvimden kaldırıldı")


@transaction.atomic
def add_fixed_holidays(actor: User, year: int) -> list[PublicHoliday]:
    """Yılın sabit resmi tatillerini ekler. Takvimde zaten tatil olan ya da onaylı aya düşen
    günler atlanır; tekrar çalıştırmak güvenlidir."""
    _require_role(actor)
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise BusinessRuleError("invalid_year", f"Yıl {MIN_YEAR} ile {MAX_YEAR} arasında olmalı.")
    taken = set(selectors.holidays_of_year(year).values_list("date", flat=True))
    created = []
    for month, day_of_month, name, half_day in FIXED_HOLIDAYS:
        day = date(year, month, day_of_month)
        if day in taken or _month_locked(year, month):
            continue
        values = {"date": day, "name": name, "half_day": half_day}
        created.append(masterdata.create_record(actor, PublicHoliday, values))
    return created


def _open_month(actor: User, year: int, month: int) -> AttendanceMonth:
    """Ayın puantaj kaydı (yoksa açılır); onaylı ayda `month_locked`."""
    record = AttendanceMonth.objects.select_for_update().filter(year=year, month=month).first()
    if record is None:
        try:
            with transaction.atomic():
                record = create_document(
                    AttendanceMonth(year=year, month=month),
                    actor,
                    prefix="PU",
                    machine=attendance_month_states,
                    event_payload={"year": year, "month": month},
                )
        except IntegrityError:  # aynı ay eşzamanlı açıldı
            record = AttendanceMonth.objects.select_for_update().get(year=year, month=month)
    if record.status == AttendanceMonth.Status.APPROVED:
        _require_month_open(date(year, month, 1))
    return record


def _check_day(
    employee: Employee,
    day: date,
    status: str,
    hours: Decimal,
    *,
    today: date,
    half: bool = False,
) -> None:
    if status not in AttendanceStatus.values:
        raise BusinessRuleError("invalid_status", "Geçersiz puantaj durumu.")
    if not selectors.employed_on(employee, day):
        raise BusinessRuleError(
            "not_employed",
            f"{employee.full_name} {day:%d.%m.%Y} tarihinde işte değil (işe giriş ya da çıkış "
            "tarihi).",
        )
    if hours < 0 or hours > MAX_OVERTIME_HOURS:
        raise BusinessRuleError("invalid_overtime", "Fazla mesai 0 ile 24 saat arasında olmalı.")
    if hours and status not in OVERTIME_STATUSES:
        raise BusinessRuleError(
            "overtime_not_allowed",
            "Fazla mesai yalnızca çalışılan, hafta tatili ve resmi tatil günlerine girilir.",
        )
    if day > today and (status == AttendanceStatus.ABSENT or hours):
        raise BusinessRuleError(
            "future_day", "Devamsızlık ve fazla mesai ileri bir güne girilemez."
        )
    if half:
        holiday = selectors.holidays_between(day, day).get(day)
        if holiday is None or not holiday.half_day:
            raise BusinessRuleError(
                "not_half_holiday", f"{day:%d.%m.%Y} yarım gün tatil değil (Tatil takvimi)."
            )
        if status != AttendanceStatus.WORKED:
            raise BusinessRuleError(
                "half_holiday_not_worked",
                "Yarım gün tatil çalışması yalnızca çalışılan güne (Ç) girilir.",
            )
        if day > today:
            raise BusinessRuleError(
                "future_day", "Yarım gün tatil çalışması ileri bir güne girilemez."
            )


def _write_day(
    actor: User,
    record: AttendanceMonth,
    employee: Employee,
    day: date,
    entry: AttendanceEntry | None,
    *,
    status: str,
    hours: Decimal,
    note: str,
    half: bool = False,
) -> AttendanceEntry:
    if entry is None:
        entry = AttendanceEntry(month=record, employee=employee, date=day)
    entry.status = status
    entry.overtime_hours = hours
    entry.holiday_half_worked = half
    entry.note = note
    return save_with_audit(entry, actor)


@transaction.atomic
def set_attendance_day(
    actor: User,
    employee: Employee,
    day: date,
    *,
    status: str,
    overtime_hours: Decimal | None = None,
    note: str = "",
    holiday_half_worked: bool = False,
) -> AttendanceEntry:
    """Kişinin bir gününü yazar: durum, fazla mesai (saat), yarım gün tatil çalışması ve not.

    Gün kişinin işe giriş ile çıkış tarihi arasında, ay açık olmalı. Fazla mesai 0–24 saattir ve
    yalnızca çalışılan, hafta tatili ve resmi tatil günlerine girilir; devamsızlık ve fazla mesai
    ileri bir güne girilemez (izin ve rapor girilebilir). Yarım gün tatilde (28 Ekim, arife) öğleden
    sonra da çalışıldıysa `holiday_half_worked` işaretlenir: yalnızca takvimde yarım gün tatil olan,
    geçmiş ya da bugünkü çalışılan güne girilir (bordroda yarım günlük ilave ücret).
    """
    _require_role(actor)
    # Kart kilitlenip yeniden okunur: aynı anda kaydedilen ayrılışın çıkış tarihi görülür.
    employee = Employee.objects.select_for_update().get(pk=employee.pk)
    hours = Decimal(overtime_hours or 0)
    half = bool(holiday_half_worked)
    _check_day(employee, day, status, hours, today=timezone.localdate(), half=half)
    record = _open_month(actor, day.year, day.month)
    entry = AttendanceEntry.objects.select_for_update().filter(employee=employee, date=day).first()
    return _write_day(
        actor,
        record,
        employee,
        day,
        entry,
        status=status,
        hours=hours,
        note=_text(note)[:200],
        half=half,
    )


@transaction.atomic
def set_attendance_range(
    actor: User,
    *,
    start: date,
    end: date,
    status: str,
    employee: Employee | None = None,
    department: str = "",
    note: str = "",
) -> int:
    """Bir aralığa aynı durumu yazar: tek kişi, bir birim ya da (ikisi de boşsa) o aralıkta işte
    olan herkes. Değişen gün sayısını döner.

    Yıllık izin, mazeret izni ve devamsızlık hafta tatili ve resmi tatil günlerine yazılmaz; rapor
    ve ücretsiz izin her takvim gününe yazılır. Kişinin işte olmadığı günler atlanır. Fazla mesai
    alamayan duruma geçen günün fazla mesaisi, çalışılmayan duruma geçen günün yarım gün tatil
    çalışması işareti sıfırlanır.
    """
    _require_role(actor)
    if status not in AttendanceStatus.values:
        raise BusinessRuleError("invalid_status", "Geçersiz puantaj durumu.")
    if end < start:
        raise BusinessRuleError("invalid_range", "Bitiş tarihi başlangıçtan önce olamaz.")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise BusinessRuleError("range_too_long", "Aralık en çok bir yıl olabilir.")
    today = timezone.localdate()
    if status == AttendanceStatus.ABSENT and end > today:
        raise BusinessRuleError("future_day", "Devamsızlık ileri bir güne girilemez.")
    # Kartlar kimlik sırasıyla kilitlenip yeniden okunur (kilit sırası; güncel çıkış tarihleri).
    if employee is not None:
        people = [Employee.objects.select_for_update().get(pk=employee.pk)]
    else:
        people = list(
            selectors.employees_between(start, end, _text(department))
            .select_for_update()
            .order_by("pk")
        )
    if not people:
        raise BusinessRuleError("no_employees", "Bu aralıkta işte olan personel yok.")
    days = selectors.days_between(start, end)
    records = {
        key: _open_month(actor, *key) for key in sorted({(day.year, day.month) for day in days})
    }
    holidays = selectors.holidays_between(start, end)
    rest = selectors.rest_weekdays()
    saved = {
        (entry.employee_id, entry.date): entry
        for entry in AttendanceEntry.objects.select_for_update().filter(
            employee__in=people, date__range=(start, end)
        )
    }
    note = _text(note)[:200]
    changed = 0
    for person in people:
        for day in days:
            if not selectors.employed_on(person, day):
                continue
            entry = saved.get((person.pk, day))
            current = (
                entry.status if entry else selectors.default_status(day, holidays.get(day), rest)
            )
            if status in WORKDAY_ONLY_STATUSES and current in REST_STATUSES:
                continue
            hours = entry.overtime_hours if entry and status in OVERTIME_STATUSES else Decimal(0)
            half = bool(entry and entry.holiday_half_worked and status == AttendanceStatus.WORKED)
            text = note or (entry.note if entry else "")
            if entry is None and status == current and not note:
                continue  # zaten varsayılan; kayda gerek yok
            if entry is not None and (
                entry.status,
                entry.overtime_hours,
                entry.holiday_half_worked,
                entry.note,
            ) == (status, hours, half, text):
                continue
            record = records[(day.year, day.month)]
            _write_day(
                actor,
                record,
                person,
                day,
                entry,
                status=status,
                hours=hours,
                note=text,
                half=half,
            )
            changed += 1
    return changed


@transaction.atomic
def approve_attendance_month(actor: User, year: int, month: int) -> AttendanceMonth:
    """Ayın puantajını onaylar: değiştirilmemiş günler varsayılan durumlarıyla yazılır ve ay
    kilitlenir (bordroya giden rakam sabitlenir). Ay bitmeden onaylanamaz.

    Ayın kişileri (o ay işte olanlar ve kayıtlı günü olanlar) aydan önce kilitlenir: varsayılan
    günler güncel giriş ve çıkış tarihleriyle yazılır, aynı anda kaydedilen ayrılışla çakışmaz.
    Kilitten sonra tabloya yeni bir kart girerse (ör. o sırada yeniden işe başlatılan ya da açılan
    kart) onay geri alınır (`attendance_cards_changed`); yeniden onaylanınca kart da kilitlenir."""
    _require_role(actor)
    first, last = selectors.month_bounds(year, month)
    if last >= timezone.localdate():
        raise BusinessRuleError(
            "month_not_finished",
            f"{selectors.month_label(year, month)} bitmeden puantaj onaylanamaz.",
        )
    holders = AttendanceEntry.objects.filter(date__range=(first, last)).values("employee_id")
    in_month = selectors.employees_between(first, last).values("pk")
    locked = {
        card.pk
        for card in Employee.objects.select_for_update()
        .filter(Q(pk__in=in_month) | Q(pk__in=holders))
        .order_by("pk")
        .only("pk")
    }
    record = _open_month(actor, year, month)
    attendance_month_states.assert_can_transition(record.status, AttendanceMonth.Status.APPROVED)
    grid = selectors.attendance_grid(year, month)
    if any(row.employee.pk not in locked for row in grid.rows):
        raise BusinessRuleError(
            "attendance_cards_changed",
            "Onay sırasında personel kartları değişti; ayı yeniden onaylayın.",
        )
    defaults = [
        AttendanceEntry(
            month=record,
            employee=row.employee,
            date=cell.date,
            status=cell.status,
            created_by=actor,
            updated_by=actor,
        )
        for row in grid.rows
        for cell in row.cells
        if cell.status and not cell.explicit
    ]
    AttendanceEntry.objects.bulk_create(defaults)
    record.approved_at = timezone.now()
    record.approved_by = actor
    save_with_audit(record, actor)
    return transition_status(
        record,
        AttendanceMonth.Status.APPROVED,
        actor,
        machine=attendance_month_states,
        note=f"{len(grid.rows)} personel; {len(defaults)} gün varsayılan durumuyla yazıldı",
        event_payload={"year": year, "month": month},
    )


@transaction.atomic
def reopen_attendance_month(actor: User, record: AttendanceMonth, reason: str) -> AttendanceMonth:
    """Onaylı ayı düzeltme için yeniden açar (gerekçe zorunlu). Günler onaydaki haliyle kalır."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Yeniden açma gerekçesi girilmelidir.")
    locked = AttendanceMonth.objects.select_for_update().get(pk=record.pk)
    attendance_month_states.assert_can_transition(locked.status, AttendanceMonth.Status.OPEN)
    locked.approved_at = None
    locked.approved_by = None
    save_with_audit(locked, actor)
    return transition_status(
        locked,
        AttendanceMonth.Status.OPEN,
        actor,
        machine=attendance_month_states,
        note=reason,
        event_payload={"year": locked.year, "month": locked.month, "reason": reason},
    )


# --- ücretler (docs/DECISIONS.md "Personel maliyeti", "Personel bordrosu") -----------------------

WAGE_FIELDS = ("employee", "gross_monthly", "valid_from", "note")
# Akla yatkınlık sınırları: hatalı yazılan tarih (ör. 0026 yılı) ya da tutar hesabı bozmasın.
WAGE_DATE_MIN, WAGE_DATE_MAX = date(2000, 1, 1), date(2100, 12, 31)
MAX_MONTHLY_WAGE = Decimal("100000000")


def _duplicate_wage(day: date) -> BusinessRuleError:
    return BusinessRuleError(
        "duplicate_wage",
        f"Bu kişinin {day:%d.%m.%Y} tarihinden geçerli bir ücreti zaten var; yanlışsa önce o "
        "kaydı kaldırın.",
    )


@transaction.atomic
def add_wage(actor: User, data: Mapping[str, Any]) -> EmployeeWage:
    """Kişiye brüt aylık ücret girer, `valid_from` tarihinden itibaren geçerli. Zam yeni tarihle
    eklenir; aynı kişide aynı tarihte iki geçerli ücret olamaz. Ücret sıfırdan büyük olmalı.
    Ayrılan kişiye de girilir (geçmiş ayın hesabı için)."""
    _require_role(actor)
    wage = EmployeeWage(**_pick(data, WAGE_FIELDS))
    if wage.employee_id is None:
        raise BusinessRuleError("employee_required", "Personel seçilmelidir.")
    if wage.valid_from is None:
        raise BusinessRuleError("valid_from_required", "Geçerlilik başlangıcı girilmelidir.")
    if not WAGE_DATE_MIN <= wage.valid_from <= WAGE_DATE_MAX:
        raise BusinessRuleError(
            "invalid_valid_from", "Geçerlilik başlangıcı 2000 ile 2100 yılları arasında olmalı."
        )
    if wage.gross_monthly is None or not Decimal(0) < wage.gross_monthly <= MAX_MONTHLY_WAGE:
        raise BusinessRuleError(
            "invalid_wage",
            f"Brüt ücret sıfırdan büyük ve en çok {format_money(MAX_MONTHLY_WAGE)} TL olmalı.",
        )
    duplicate = EmployeeWage.objects.filter(
        employee_id=wage.employee_id, valid_from=wage.valid_from, is_active=True
    )
    if duplicate.exists():
        raise _duplicate_wage(wage.valid_from)
    wage.note = _text(wage.note)[:200]
    try:
        with transaction.atomic():
            return save_with_audit(wage, actor)
    except IntegrityError:
        # Aynı kişi ve tarihe aynı anda iki ücret girildi (tekil kısıt).
        raise _duplicate_wage(wage.valid_from) from None


@transaction.atomic
def remove_wage(actor: User, wage: EmployeeWage, reason: str) -> EmployeeWage:
    """Yanlış ücret kaydını kaldırır (silinmez, pasife alınır; neden zorunlu)."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    locked = EmployeeWage.objects.select_for_update().get(pk=wage.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Ücret kaydı zaten kaldırılmış.")
    locked.is_active = False
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.removal_reason = reason
    return save_with_audit(locked, actor, note="Ücret kaydı kaldırıldı")


# --- ön bordro (docs/DECISIONS.md "Personel bordrosu") -------------------------------------------

PARAMETER_FIELDS = (
    "valid_from",
    "minimum_wage",
    "ceiling_multiplier",
    "employee_sgk_rate",
    "employee_unemployment_rate",
    "employer_sgk_rate",
    "employer_unemployment_rate",
    "incentive_points",
    "stamp_tax_per_mille",
    "tax_bracket_1",
    "tax_bracket_2",
    "tax_bracket_3",
    "tax_bracket_4",
    "tax_rate_1",
    "tax_rate_2",
    "tax_rate_3",
    "tax_rate_4",
    "tax_rate_5",
    "bes_rate",
    "meal_exemption_daily",
    "source",
    "note",
)
_OPTIONAL_PARAMETER_FIELDS = ("source", "note")
MAX_CEILING_MULTIPLIER = Decimal(20)
MAX_PAYROLL_AMOUNT = Decimal("100000000000")


def _duplicate_parameters(day: date) -> BusinessRuleError:
    return BusinessRuleError(
        "duplicate_parameters",
        f"{day:%m.%Y} ayından geçerli bir parametre seti zaten var; onu düzenleyin.",
    )


def _clean_parameters(
    values: dict[str, Any], instance: PayrollParameterSet | None = None
) -> dict[str, Any]:
    """Parametre setinin kuralları: geçerlilik bir ayın ilk günü (gün ayın başına çekilir), bütün
    değerler girilir, oranlar 0–100, teşvik SGK işveren payını aşmaz, dilim sınırları artar."""
    merged = {name: getattr(instance, name) for name in PARAMETER_FIELDS} if instance else {}
    merged.update(values)
    for name in _OPTIONAL_PARAMETER_FIELDS:
        merged[name] = _text(merged.get(name))[: 500 if name == "source" else 200]
    # Nakit yemek SGK istisnası isteğe bağlı: girilmezse 0 (istisna yok).
    if merged.get("meal_exemption_daily") is None:
        merged["meal_exemption_daily"] = Decimal(0)
    if any(merged.get(name) is None for name in PARAMETER_FIELDS):
        raise BusinessRuleError("parameters_incomplete", "Bütün parametreler girilmelidir.")
    day = merged["valid_from"].replace(day=1)
    merged["valid_from"] = day
    if not MIN_YEAR <= day.year <= MAX_YEAR:
        raise BusinessRuleError(
            "invalid_valid_from", f"Geçerlilik yılı {MIN_YEAR} ile {MAX_YEAR} arasında olmalı."
        )
    if not Decimal(0) < merged["minimum_wage"] <= MAX_MONTHLY_WAGE:
        raise BusinessRuleError("invalid_minimum_wage", "Asgari ücret sıfırdan büyük olmalı.")
    if not Decimal(1) <= merged["ceiling_multiplier"] <= MAX_CEILING_MULTIPLIER:
        raise BusinessRuleError(
            "invalid_ceiling", "SGK üst sınır çarpanı 1 ile 20 arasında olmalı (2026'da 9)."
        )
    if any(not Decimal(0) <= merged[name] <= 100 for name in PARAMETER_RATE_FIELDS):
        raise BusinessRuleError("invalid_rate", "Oranlar %0 ile %100 arasında olmalı.")
    if merged["incentive_points"] > merged["employer_sgk_rate"]:
        raise BusinessRuleError(
            "invalid_incentive", "Teşvik puanı SGK işveren payından büyük olamaz."
        )
    if not Decimal(0) <= merged["stamp_tax_per_mille"] <= 100:
        raise BusinessRuleError(
            "invalid_stamp_tax", "Damga vergisi binde 0 ile 100 arasında olmalı."
        )
    if not Decimal(0) <= merged["meal_exemption_daily"] <= MAX_MONTHLY_WAGE:
        raise BusinessRuleError(
            "invalid_meal_exemption",
            "Nakit yemek SGK istisnası günlük 0 ile "
            f"{format_money(MAX_MONTHLY_WAGE)} TL arasında olmalı.",
        )
    brackets = [merged[f"tax_bracket_{index}"] for index in range(1, 5)]
    if (
        brackets[0] <= 0
        or brackets[-1] > MAX_PAYROLL_AMOUNT
        or any(upper <= lower for lower, upper in zip(brackets, brackets[1:], strict=False))
    ):
        raise BusinessRuleError(
            "invalid_brackets", "Gelir vergisi dilim üst sınırları sıfırdan büyük ve artan olmalı."
        )
    others = PayrollParameterSet.objects.filter(is_active=True, valid_from=day)
    if instance is not None:
        others = others.exclude(pk=instance.pk)
    if others.exists():
        raise _duplicate_parameters(day)
    return merged


@transaction.atomic
def create_parameter_set(actor: User, data: Mapping[str, Any]) -> PayrollParameterSet:
    """Bordro parametre seti açar (ör. yeni yılın yasal değerleri; ekranda yasal değerlerle dolu
    gelir, mali müşavirle kontrol edilip kaydedilir). Geçerlilik bir ayın ilk günüdür; aynı aydan
    geçerli ikinci set açılamaz."""
    _require_role(actor)
    values = _clean_parameters(_pick(data, PARAMETER_FIELDS))
    try:
        with transaction.atomic():
            return save_with_audit(PayrollParameterSet(**values), actor)
    except IntegrityError:  # aynı ay eşzamanlı açıldı
        raise _duplicate_parameters(values["valid_from"]) from None


@transaction.atomic
def update_parameter_set(
    actor: User, instance: PayrollParameterSet, data: Mapping[str, Any]
) -> PayrollParameterSet:
    """Parametre setini düzeltir; değişen değerler eski → yeni denetim günlüğüne yazılır."""
    _require_role(actor)
    locked = PayrollParameterSet.objects.select_for_update().get(pk=instance.pk)
    if not locked.is_active:
        raise BusinessRuleError("parameters_removed", "Kaldırılmış parametre seti düzenlenemez.")
    values = _clean_parameters(_pick(data, PARAMETER_FIELDS), locked)
    for name, value in values.items():
        setattr(locked, name, value)
    try:
        with transaction.atomic():
            return save_with_audit(locked, actor)
    except IntegrityError:
        raise _duplicate_parameters(values["valid_from"]) from None


@transaction.atomic
def remove_parameter_set(
    actor: User, instance: PayrollParameterSet, reason: str
) -> PayrollParameterSet:
    """Yanlış açılmış parametre setini kaldırır (silinmez, pasife alınır; neden zorunlu). O ay ve
    sonrası bir önceki setle, yoksa yasal değerlerle hesaplanır."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    locked = PayrollParameterSet.objects.select_for_update().get(pk=instance.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Parametre seti zaten kaldırılmış.")
    locked.is_active = False
    return save_with_audit(locked, actor, note=f"Parametre seti kaldırıldı. Neden: {reason}")


def _check_period(year: int, month: int) -> None:
    if not (1 <= month <= 12 and MIN_YEAR <= year <= MAX_YEAR):
        raise BusinessRuleError("invalid_period", "Geçersiz ay.")


@transaction.atomic
def set_external_payroll(
    actor: User,
    employee: Employee,
    year: int,
    month: int,
    *,
    gross_total: Decimal,
    employer_cost: Decimal,
    note: str = "",
) -> ExternalPayrollFigure:
    """Bordrosu mali müşavirde olan kişinin ay rakamlarını yazar (yoksa açar, varsa düzeltir):
    mali müşavirin bordrosundaki brüt toplam ve işverene maliyet. İşveren maliyeti tablosu ve
    personel maliyeti bu rakamları kullanır."""
    _require_role(actor)
    _check_period(year, month)
    employee = Employee.objects.select_for_update().get(pk=employee.pk)
    figure = (
        ExternalPayrollFigure.objects.select_for_update()
        .filter(employee=employee, year=year, month=month, is_active=True)
        .first()
    )
    # Kartın işareti sonradan kaldırılsa da o ayın girilmiş rakamı düzeltilebilir.
    if not employee.payroll_external and figure is None:
        raise BusinessRuleError(
            "not_external",
            f'{employee.full_name} kartında "Bordrosu mali müşavirde" işaretli değil; bordrosu '
            "ERP'de hesaplanır.",
        )
    _require_payroll_open(year, month)
    first, last = selectors.month_bounds(year, month)
    if not selectors.employees_between(first, last).filter(pk=employee.pk).exists():
        raise BusinessRuleError(
            "not_employed",
            f"{employee.full_name} {selectors.month_label(year, month)} ayında işte değil.",
        )
    if figure is None:
        # Rakam girilen ay mali müşavirde sayılır; o aya ERP'de girilmiş kalem hesaba girmezdi.
        label = selectors.month_label(year, month)
        _require_no_payroll_records(
            employee,
            Q(year=year, month=month),
            Q(pk__in=[]),
            f"{label} ayında",
            "payroll_items_external",
            "Bu ayın bordrosu mali müşavirde hesaplanacaksa ERP'de girilmiş kalemler hesaba "
            "girmez: önce mali müşavire bildirip Personel > Bordro'dan gerekçeyle kaldırın.",
        )
    if gross_total is None or employer_cost is None:
        raise BusinessRuleError(
            "external_incomplete", "Brüt toplam ve işverene maliyet girilmelidir."
        )
    if not Decimal(0) <= gross_total <= MAX_PAYROLL_AMOUNT:
        raise BusinessRuleError("invalid_amount", "Brüt toplam negatif olamaz.")
    if not gross_total <= employer_cost <= MAX_PAYROLL_AMOUNT:
        raise BusinessRuleError(
            "invalid_employer_cost", "İşverene maliyet brüt toplamdan az olamaz."
        )
    if figure is None:
        figure = ExternalPayrollFigure(employee=employee, year=year, month=month)
    figure.gross_total = gross_total
    figure.employer_cost = employer_cost
    figure.note = _text(note)[:200]
    try:
        with transaction.atomic():
            return save_with_audit(figure, actor)
    except IntegrityError:  # aynı kişi ve ay eşzamanlı açıldı: yeniden dene
        figure = ExternalPayrollFigure.objects.select_for_update().get(
            employee=employee, year=year, month=month, is_active=True
        )
        figure.gross_total = gross_total
        figure.employer_cost = employer_cost
        figure.note = _text(note)[:200]
        return save_with_audit(figure, actor)


def record_payroll_access(actor: User, year: int, month: int, output: str) -> None:
    """Bordro çıktısının (PDF, Excel) açıldığını denetim günlüğüne yazar (ücret ve kimlik bilgisi
    içeren kişisel veriye erişim izi, docs/KVKK.md)."""
    _require_role(actor)
    log_change(
        actor,
        None,
        AuditLog.Action.CUSTOM,
        {"year": year, "month": month},
        f"Bordro çıktısı açıldı: {output} · {selectors.month_label(year, month)}",
    )


@transaction.atomic
def remove_external_payroll(
    actor: User, figure: ExternalPayrollFigure, reason: str
) -> ExternalPayrollFigure:
    """Yanlış girilen mali müşavir rakamını kaldırır (silinmez, pasife alınır; neden zorunlu). O ay
    yeniden kartın işaretine göre hesaplanır."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    Employee.objects.select_for_update().get(pk=figure.employee_id)
    locked = ExternalPayrollFigure.objects.select_for_update().get(pk=figure.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Rakamlar zaten kaldırılmış.")
    _require_payroll_open(locked.year, locked.month)
    locked.is_active = False
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.removal_reason = reason
    note = f"Mali müşavir rakamları kaldırıldı. Neden: {reason}"
    return save_with_audit(locked, actor, note=note)


# --- devir, ek ödeme ve kesintiler (docs/DECISIONS.md "Personel bordrosu", 3. adım) -------------


class PayrollBatchError(BusinessRuleError):
    """Toplu kayıtta reddedilen satırlar (hiçbiri kaydedilmez). `errors`: [{"index", "employee",
    "code", "detail"}]; API yanıtına eklenir, pencere satırın altında gösterir."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        count = len(errors)
        super().__init__(
            "batch_rejected",
            f"{count} satır kaydedilemedi; hiçbir satır kaydedilmedi. Satırların altındaki "
            "hataları düzeltip yeniden kaydedin.",
        )
        self.errors = errors


def _require_payroll_open(year: int, month: int) -> None:
    """Ayın bordrosu onaylıysa o aya etki eden yazım reddedilir. Onay 4. adımda gelir; o zamana
    kadar bütün aylar açıktır. Bordroya etki eden her yazım (kalem, devir, mali müşavir rakamı) bunu
    çağırır."""
    return None


def _check_payroll_month(year: int, month: int) -> None:
    """Brütten nete bordro ayı: geçerli ve başlangıç ayından sonra."""
    _check_period(year, month)
    if not selectors.net_available(year, month):
        start_year, start_month = selectors.PAYROLL_START
        raise BusinessRuleError(
            "before_start",
            f"Brütten nete bordro {selectors.month_label(start_year, start_month)} ayından başlar; "
            "önceki aylar mali müşavirdedir.",
        )


def _require_computed(employee: Employee, year: int, month: int) -> None:
    """Kişi o ay işte ve bordrosu ERP'de hesaplanıyor (mali müşavirde değil)."""
    label = selectors.month_label(year, month)
    first, last = selectors.month_bounds(year, month)
    if not selectors.employees_between(first, last).filter(pk=employee.pk).exists():
        raise BusinessRuleError("not_employed", f"{employee.full_name} {label} ayında işte değil.")
    external = employee.payroll_external or (
        ExternalPayrollFigure.objects.filter(
            employee=employee, year=year, month=month, is_active=True
        ).exists()
    )
    if external:
        raise BusinessRuleError(
            "not_computed",
            f"{employee.full_name} için {label} bordrosu mali müşavirde; ERP'de hesaplanmaz.",
        )


def _erp_month(employee: Employee, year: int, month: int) -> bool:
    """Kişinin o ay bordrosu ERP'de mi hesaplandı (başlangıçtan sonra, işte, mali müşavirde
    değil)? Devir bu aydan sonraki bir aya girilirse ERP hesabının yerine geçer."""
    if month < 1 or not selectors.net_available(year, month):
        return False
    first, last = selectors.month_bounds(year, month)
    if not selectors.employees_between(first, last).filter(pk=employee.pk).exists():
        return False
    return not ExternalPayrollFigure.objects.filter(
        employee=employee, year=year, month=month, is_active=True
    ).exists()


def _card_note(actor: User, employee: Employee, note: str) -> None:
    """Bordro kaydının özeti kartın geçmişine (kimin, ne zaman; icra ya da nafaka açıklaması
    yazılmaz)."""
    log_change(actor, employee, AuditLog.Action.CUSTOM, {}, note)


def _employee_ids(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    """Toplu kayıttaki kişilerin kimlikleri, sıralı (kartlar bu sırayla kilitlenir)."""
    return sorted({int(row["employee"].pk) for row in rows if row.get("employee") is not None})


def _batch(rows: Sequence[Mapping[str, Any]], write: Any) -> list[Any]:
    """Toplu kayıt: her satır kendi kayıt noktasında yazılır; biri reddedilirse hepsi geri alınır
    ve satır hataları birlikte döner."""
    saved, errors = [], []
    for index, row in enumerate(rows):
        try:
            with transaction.atomic():
                saved.append(write(row))
        except BusinessRuleError as exc:
            employee = row.get("employee")
            errors.append(
                {
                    "index": index,
                    "employee": getattr(employee, "pk", employee),
                    "code": exc.code,
                    "detail": exc.message,
                }
            )
    if errors:
        raise PayrollBatchError(errors)
    return saved


@transaction.atomic
def set_opening_balance(
    actor: User,
    employee: Employee,
    year: int,
    month: int,
    *,
    tax_base: Decimal | None,
    exemption_months: int | None,
    note: str = "",
    confirm_override: bool = False,
) -> PayrollOpeningBalance:
    """Devir girer ya da düzeltir: kişinin bu işverende `month` ayından önceki yıl içi kümülatif
    gelir vergisi matrahı (mali müşavirin bir önceki ay bordrosundaki kümülatif, o ay dahil) ve
    asgari ücret istisnasının uygulandığı ay sayısı (işe giriş ayı tam sayılır; işe girişten bu
    yana ay sayısını aşamaz). İstisna matrahı devir ayından önceki o ayların kendi
    parametrelerinden hesaplanıp yazılır.

    Ocak'ta kümülatif sıfırdan başlar, devir girilmez; bu yıl o aydan önce bu işyerinde çalışmayan
    kişiye de gerekmez. Kişi bir önceki ay ERP'de hesaplandıysa devir o ayların ERP hesabının
    yerine geçer (mali müşavirle eşitleme): `confirm_override` ile onaylanır."""
    _require_role(actor)
    _check_payroll_month(year, month)
    if month == 1:
        raise BusinessRuleError(
            "opening_not_needed", "Ocak'ta kümülatif sıfırdan başlar; devir girilmez."
        )
    today = timezone.localdate()
    if (year, month) > (today.year, today.month):
        raise BusinessRuleError(
            "future_month",
            "Gelecek aya devir girilemez: bir önceki ayın kümülatifi o ay bitince belli olur.",
        )
    employee = Employee.objects.select_for_update().get(pk=employee.pk)
    label = selectors.month_label(year, month)
    _require_computed(employee, year, month)
    _require_payroll_open(year, month)
    available = selectors.months_employed_before(employee, year, month)
    if available == 0:
        raise BusinessRuleError(
            "opening_not_needed",
            f"{employee.full_name} bu yıl {label} ayından önce bu işyerinde çalışmadı; kümülatif "
            "sıfırdır, devir gerekmez.",
        )
    if tax_base is None or not Decimal(0) <= tax_base <= MAX_PAYROLL_AMOUNT:
        raise BusinessRuleError(
            "invalid_tax_base", "Kümülatif gelir vergisi matrahı sıfır ya da daha büyük olmalı."
        )
    if exemption_months is None or not 0 <= exemption_months <= available:
        raise BusinessRuleError(
            "invalid_exemption_months",
            f"Asgari ücret istisnası uygulanan ay 0 ile {available} arasında olmalı (bu yıl işe "
            "girişten bu yana).",
        )
    if not confirm_override and _erp_month(employee, year, month - 1):
        previous = selectors.month_label(year, month - 1)
        raise BusinessRuleError(
            "opening_overrides_chain",
            f"{employee.full_name} için {previous} bordrosu ERP'de hesaplandı; bu devir önceki "
            "ayların ERP hesabının yerine geçer (mali müşavirle eşitleme). Onaylayarak kaydedin.",
        )
    settings_by_month = selectors.parameter_settings(year, range(1, month))
    exemption_base = selectors.opening_exemption_base(settings_by_month, month, exemption_months)
    opening = (
        PayrollOpeningBalance.objects.select_for_update()
        .filter(employee=employee, year=year, month=month, is_active=True)
        .first()
    )
    created = opening is None
    note = _text(note)[:200]
    if opening is not None and (
        opening.tax_base,
        opening.exemption_months,
        opening.exemption_base,
        opening.note,
    ) == (tax_base, exemption_months, exemption_base, note):
        return opening  # Değişiklik yok: kayıt ve kart notu yazılmaz.
    if opening is None:
        opening = PayrollOpeningBalance(employee=employee, year=year, month=month)
    opening.tax_base = tax_base
    opening.exemption_months = exemption_months
    opening.exemption_base = exemption_base
    opening.note = note
    try:
        with transaction.atomic():
            saved = save_with_audit(opening, actor)
    except IntegrityError:
        raise BusinessRuleError(
            "duplicate_opening",
            f"{employee.full_name} için {label} devri aynı anda girildi; sayfayı yenileyip "
            "yeniden deneyin.",
        ) from None
    _card_note(
        actor,
        employee,
        f"Devir {'girildi' if created else 'düzeltildi'}: {label} · kümülatif GV matrahı "
        f"{format_money(tax_base)} TL · asgari ücret istisnası {exemption_months} ay",
    )
    return saved


OPENING_ROW_FIELDS = ("employee", "tax_base", "exemption_months", "note", "confirm_override")


@transaction.atomic
def set_opening_balances(
    actor: User, year: int, month: int, rows: Sequence[Mapping[str, Any]]
) -> list[PayrollOpeningBalance]:
    """Ayın devirlerini toplu girer (devir penceresinin tek "Kaydet"i): satırlar tek tek
    `set_opening_balance` kurallarıyla yazılır; biri reddedilirse hiçbiri kaydedilmez ve satır
    hataları birlikte döner (`PayrollBatchError`). Kartlar kimlik sırasıyla kilitlenir."""
    _require_role(actor)
    ids = _employee_ids(rows)
    list(Employee.objects.select_for_update().filter(pk__in=ids).order_by("pk"))

    def write(row: Mapping[str, Any]) -> PayrollOpeningBalance:
        values = _pick(row, OPENING_ROW_FIELDS)
        if values.get("employee") is None:
            raise BusinessRuleError("employee_required", "Personel seçilmelidir.")
        return set_opening_balance(
            actor,
            values["employee"],
            year,
            month,
            tax_base=values.get("tax_base"),
            exemption_months=values.get("exemption_months"),
            note=values.get("note") or "",
            confirm_override=bool(values.get("confirm_override")),
        )

    return _batch(rows, write)


@transaction.atomic
def remove_opening_balance(
    actor: User, opening: PayrollOpeningBalance, reason: str
) -> PayrollOpeningBalance:
    """Yanlış devri kaldırır (silinmez, pasife alınır; neden zorunlu). Zincir bir önceki devirden
    ya da yılın ilk ERP ayından yeniden kurulur."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    employee = Employee.objects.select_for_update().get(pk=opening.employee_id)
    locked = PayrollOpeningBalance.objects.select_for_update().get(pk=opening.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Devir zaten kaldırılmış.")
    _require_payroll_open(locked.year, locked.month)
    locked.is_active = False
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.removal_reason = reason
    saved = save_with_audit(locked, actor, note="Devir kaldırıldı")
    _card_note(
        actor,
        employee,
        f"Devir kaldırıldı: {selectors.month_label(locked.year, locked.month)}. Neden: {reason}",
    )
    return saved


ITEM_FIELDS = ("employee", "year", "month", "category", "description", "amount")
ITEM_UPDATE_FIELDS = ("category", "description", "amount")
ITEM_ROW_FIELDS = ("employee", "category", "description", "amount")


def _item_kind(category: Any) -> str:
    if category not in PayrollItemCategory.values:
        raise BusinessRuleError("invalid_category", "Geçersiz kalem kategorisi.")
    return PayrollItemKind.EXTRA if category in EXTRA_CATEGORIES else PayrollItemKind.DEDUCTION


def _clean_item(item: PayrollItem, values: Mapping[str, Any]) -> None:
    """Kalemin kuralları: kategori türe uyar (tür sonradan değişmez), "Diğer"de açıklama zorunlu,
    tutar sıfırdan büyük."""
    category = values.get("category", item.category)
    kind = _item_kind(category)
    if item.pk is not None and kind != item.kind:
        raise BusinessRuleError(
            "invalid_category",
            "Kalemin türü (ek ödeme ya da kesinti) değiştirilemez; kaldırıp yeni kalem girin.",
        )
    description = _text(values.get("description", item.description))[:100]
    if category in DESCRIBED_CATEGORIES and not description:
        raise BusinessRuleError(
            "description_required", "Diğer ek ödeme ve kesintide açıklama yazılmalıdır."
        )
    amount = values.get("amount", item.amount)
    if amount is None or not Decimal(0) < amount <= MAX_MONTHLY_WAGE:
        raise BusinessRuleError(
            "invalid_amount",
            f"Tutar sıfırdan büyük ve en çok {format_money(MAX_MONTHLY_WAGE)} TL olmalı.",
        )
    item.kind = kind
    item.category = category
    item.description = description
    item.amount = amount


def _item_label(item: PayrollItem) -> str:
    """Kartın geçmişindeki özet: "Ekim 2026 · Prim 5.000,00 TL" (açıklama yazılmaz)."""
    return (
        f"{selectors.month_label(item.year, item.month)} · {item.get_category_display()} "
        f"{format_money(item.amount)} TL"
    )


def _kind_word(item: PayrollItem) -> str:
    return "Ek ödeme" if item.kind == PayrollItemKind.EXTRA else "Kesinti"


def _add_item(
    actor: User, employee: Employee, year: int, month: int, values: Mapping[str, Any]
) -> PayrollItem:
    _check_payroll_month(year, month)
    today = timezone.localdate()
    if (year, month) > (today.year, today.month):
        raise BusinessRuleError("future_month", "Gelecek aya kalem girilemez.")
    _require_computed(employee, year, month)
    _require_payroll_open(year, month)
    item = PayrollItem(employee=employee, year=year, month=month)
    _clean_item(item, values)
    saved = save_with_audit(item, actor)
    _card_note(actor, employee, f"{_kind_word(saved)} eklendi: {_item_label(saved)}")
    return saved


@transaction.atomic
def add_payroll_item(actor: User, data: Mapping[str, Any]) -> PayrollItem:
    """Kişiye o ayın ek ödemesini (brüt) ya da kesintisini (netten) girer. Kalem, birlikte ödendiği
    ücretin bordro ayına girilir; başlangıç ayından önceye ve gelecek aya girilmez. Kişi o ay işte
    ve bordrosu ERP'de hesaplanıyor olmalı."""
    _require_role(actor)
    values = _pick(data, ITEM_FIELDS)
    if values.get("employee") is None:
        raise BusinessRuleError("employee_required", "Personel seçilmelidir.")
    employee = Employee.objects.select_for_update().get(pk=values["employee"].pk)
    return _add_item(actor, employee, values.get("year") or 0, values.get("month") or 0, values)


@transaction.atomic
def add_payroll_items(
    actor: User, year: int, month: int, rows: Sequence[Mapping[str, Any]]
) -> list[PayrollItem]:
    """Ayın kalemlerini toplu girer ("Toplu ekle" ve "Geçen aydan kopyala"): satırlar
    `add_payroll_item` kurallarıyla yazılır; biri reddedilirse hiçbiri kaydedilmez ve satır hataları
    birlikte döner (`PayrollBatchError`). Kartlar kimlik sırasıyla kilitlenir."""
    _require_role(actor)
    ids = _employee_ids(rows)
    cards = {
        card.pk: card
        for card in Employee.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    }

    def write(row: Mapping[str, Any]) -> PayrollItem:
        values = _pick(row, ITEM_ROW_FIELDS)
        employee = values.get("employee")
        if employee is None:
            raise BusinessRuleError("employee_required", "Personel seçilmelidir.")
        return _add_item(actor, cards[employee.pk], year, month, values)

    return _batch(rows, write)


@transaction.atomic
def update_payroll_item(actor: User, item: PayrollItem, data: Mapping[str, Any]) -> PayrollItem:
    """Kalemi düzeltir: tutar, kategori (aynı tür içinde) ve açıklama. Değişen değerler eski → yeni
    denetim günlüğüne, özeti kartın geçmişine yazılır."""
    _require_role(actor)
    values = _pick(data, ITEM_UPDATE_FIELDS)
    employee = Employee.objects.select_for_update().get(pk=item.employee_id)
    locked = PayrollItem.objects.select_for_update().get(pk=item.pk)
    if not locked.is_active:
        raise BusinessRuleError("item_removed", "Kaldırılmış kalem düzeltilemez.")
    _require_payroll_open(locked.year, locked.month)
    before = (locked.category, locked.description, locked.amount)
    _clean_item(locked, values)
    if (locked.category, locked.description, locked.amount) == before:
        return locked  # Değişiklik yok: kayıt ve kart notu yazılmaz.
    saved = save_with_audit(locked, actor)
    _card_note(actor, employee, f"{_kind_word(saved)} düzeltildi: {_item_label(saved)}")
    return saved


@transaction.atomic
def remove_payroll_item(actor: User, item: PayrollItem, reason: str) -> PayrollItem:
    """Yanlış kalemi kaldırır (silinmez, pasife alınır; neden zorunlu)."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    employee = Employee.objects.select_for_update().get(pk=item.employee_id)
    locked = PayrollItem.objects.select_for_update().get(pk=item.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Kalem zaten kaldırılmış.")
    _require_payroll_open(locked.year, locked.month)
    locked.is_active = False
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.removal_reason = reason
    saved = save_with_audit(locked, actor, note=f"{_kind_word(locked)} kaldırıldı")
    _card_note(
        actor, employee, f"{_kind_word(saved)} kaldırıldı: {_item_label(saved)}. Neden: {reason}"
    )
    return saved
