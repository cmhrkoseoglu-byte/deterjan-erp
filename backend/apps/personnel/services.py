"""Personel kartı yazma işlemleri (yalnızca admin ve yönetim).

Kart silinmez (CLAUDE.md kural 6): işten ayrılış `terminate_employee` ile kaydedilir (kart pasife
alınır, çıkış tarihi yazılır), yeniden işe başlayan `reinstate_employee` ile açılır. Her değişiklik
eski → yeni değerleriyle denetim günlüğüne yazılır (kural 7). Özlük belgelerinin eklenmesi,
açılması ve kaldırılması kartın geçmişine de yazılır.
"""

import os
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from apps.core import attachments
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import YONETIM
from apps.core.services import save_with_audit
from apps.masterdata import services as masterdata
from apps.personnel import selectors
from apps.personnel.models import Employee, EmployeeDocument

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
