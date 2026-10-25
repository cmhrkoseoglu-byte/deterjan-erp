"""Personel kartı yazma işlemleri (yalnızca admin ve yönetim).

Kart silinmez (CLAUDE.md kural 6): işten ayrılış `terminate_employee` ile kaydedilir (kart pasife
alınır, çıkış tarihi yazılır), yeniden işe başlayan `reinstate_employee` ile açılır. Her değişiklik
eski → yeni değerleriyle denetim günlüğüne yazılır (kural 7).
"""

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.permissions import user_has_role
from apps.core.roles import YONETIM
from apps.core.services import save_with_audit
from apps.masterdata import services as masterdata
from apps.personnel import selectors
from apps.personnel.models import Employee

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
)


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
    """Personel kartı açar. Zorunlu: ad soyad, birim. Sicil no girilmişse benzersizdir; sistem
    kullanıcısı (isteğe bağlı) aktif olmalı ve başka karta bağlı olmamalıdır."""
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
