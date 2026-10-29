"""Personel yazma işlemleri (yalnızca admin ve yönetim): kartlar, özlük belgeleri, puantaj.

Kart silinmez (CLAUDE.md kural 6): işten ayrılış `terminate_employee` ile kaydedilir (kart pasife
alınır, çıkış tarihi yazılır), yeniden işe başlayan `reinstate_employee` ile açılır. Her değişiklik
eski → yeni değerleriyle denetim günlüğüne yazılır (kural 7). Özlük belgelerinin eklenmesi,
açılması ve kaldırılması kartın geçmişine de yazılır. Puantaj ayı onayla kilitlenir.
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
from django.utils import timezone

from apps.core import attachments
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import YONETIM
from apps.core.services import create_document, save_with_audit, transition_status
from apps.masterdata import services as masterdata
from apps.personnel import selectors
from apps.personnel.models import (
    OVERTIME_STATUSES,
    AttendanceEntry,
    AttendanceMonth,
    AttendanceSettings,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
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
    tarihi bu servisle değişmez (`terminate_employee`, `reinstate_employee`)."""
    _require_role(actor)
    values = _clean(_pick(data, EMPLOYEE_FIELDS), employee)
    return masterdata.update_record(actor, employee, values)


@transaction.atomic
def terminate_employee(
    actor: User, employee: Employee, termination_date: date, *, note: str = ""
) -> Employee:
    """İşten ayrılışı kaydeder: kart pasife alınır ve çıkış tarihi yazılır (kart silinmez).

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
    locked.is_active = False
    locked.termination_date = termination_date
    locked.full_clean(exclude=["created_by", "updated_by"])
    return save_with_audit(locked, actor, note=_text(note) or "İşten ayrıldı")


@transaction.atomic
def reinstate_employee(actor: User, employee: Employee, *, note: str = "") -> Employee:
    """Ayrılan personeli yeniden çalışır yapar (ör. yeniden işe alım); çıkış tarihi boşalır, eski
    tarih denetim günlüğünde kalır."""
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


def _check_day(employee: Employee, day: date, status: str, hours: Decimal, *, today: date) -> None:
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
) -> AttendanceEntry:
    if entry is None:
        entry = AttendanceEntry(month=record, employee=employee, date=day)
    entry.status = status
    entry.overtime_hours = hours
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
) -> AttendanceEntry:
    """Kişinin bir gününü yazar: durum, fazla mesai (saat) ve not.

    Gün kişinin işe giriş ile çıkış tarihi arasında, ay açık olmalı. Fazla mesai 0–24 saattir ve
    yalnızca çalışılan, hafta tatili ve resmi tatil günlerine girilir; devamsızlık ve fazla mesai
    ileri bir güne girilemez (izin ve rapor girilebilir).
    """
    _require_role(actor)
    hours = Decimal(overtime_hours or 0)
    _check_day(employee, day, status, hours, today=timezone.localdate())
    record = _open_month(actor, day.year, day.month)
    entry = AttendanceEntry.objects.select_for_update().filter(employee=employee, date=day).first()
    return _write_day(
        actor, record, employee, day, entry, status=status, hours=hours, note=_text(note)[:200]
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
    alamayan duruma geçen günün fazla mesaisi sıfırlanır.
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
    if employee is not None:
        people = [employee]
    else:
        people = list(selectors.employees_between(start, end, _text(department)))
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
            text = note or (entry.note if entry else "")
            if entry is None and status == current and not note:
                continue  # zaten varsayılan; kayda gerek yok
            if entry is not None and (entry.status, entry.overtime_hours, entry.note) == (
                status,
                hours,
                text,
            ):
                continue
            record = records[(day.year, day.month)]
            _write_day(actor, record, person, day, entry, status=status, hours=hours, note=text)
            changed += 1
    return changed


@transaction.atomic
def approve_attendance_month(actor: User, year: int, month: int) -> AttendanceMonth:
    """Ayın puantajını onaylar: değiştirilmemiş günler varsayılan durumlarıyla yazılır ve ay
    kilitlenir (bordroya giden rakam sabitlenir). Ay bitmeden onaylanamaz."""
    _require_role(actor)
    first, last = selectors.month_bounds(year, month)
    if last >= timezone.localdate():
        raise BusinessRuleError(
            "month_not_finished",
            f"{selectors.month_label(year, month)} bitmeden puantaj onaylanamaz.",
        )
    record = _open_month(actor, year, month)
    attendance_month_states.assert_can_transition(record.status, AttendanceMonth.Status.APPROVED)
    grid = selectors.attendance_grid(year, month)
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
