"""Personel yazma işlemleri (yalnızca admin ve yönetim): kartlar, özlük belgeleri, puantaj,
ücretler ve ön bordro (parametreler, mali müşavir rakamları, devir, ek ödeme ve kesintiler).

Kart silinmez (CLAUDE.md kural 6): işten ayrılış `terminate_employee` ile kaydedilir (kart pasife
alınır, çıkış tarihi yazılır), yeniden işe başlayan `reinstate_employee` ile açılır. Her değişiklik
eski → yeni değerleriyle denetim günlüğüne yazılır (kural 7). Özlük belgelerinin eklenmesi,
açılması ve kaldırılması kartın geçmişine de yazılır. Puantaj ayı onayla kilitlenir; ayrılışta
çıkış tarihinden sonraki puantaj günleri kaldırılır (docs/DECISIONS.md "Puantajda çıkıştan sonraki
günler").

Kilit sırası (kilitlenme olmasın diye her yazımda aynı): personel kartları (kimlik sırasıyla),
puantaj ayları (yıl, ay sırasıyla), puantaj günleri, bordro yılı (danışma kilidi), bordro ayları
(önceki ay, sonra bu ay), bordro kayıtları (devir, kalem, mali müşavir rakamı, ücret, parametre
seti). Gün ve aralık girişi ile ay onayı önce kartları kilitler; böylece aynı anda kaydedilen bir
ayrılış çıkıştan sonraya gün bırakamaz. Bordro kayıtları ve ücretler de önce kişinin kartını
kilitler; bordro onayı ayın kartlarını kilitlediği için onay ile o aya yazım arasında kayıt kaçmaz.

Bordro onaylanınca (4. adım) aya etki eden yazımlar reddedilir (`payroll_approved`): kalem, devir,
mali müşavir rakamı, onaylı ayın günlerine düşen ücret, onaylı ayın parametreleri, puantajın
yeniden açılması ve onaylı ayı değiştiren işe giriş tarihi. Düzeltme için bordro gerekçeyle yeniden
açılır (yalnızca en son onaylı ay).
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
from django.db import IntegrityError, connection, transaction
from django.db.models import Max, Q
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
from apps.personnel import payroll, selectors
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
    PayrollApproval,
    PayrollItem,
    PayrollItemCategory,
    PayrollItemKind,
    PayrollOpeningBalance,
    PayrollParameterSet,
    PayrollRun,
    PayrollSlip,
    PublicHoliday,
)
from apps.personnel.state import attendance_month_states, payroll_run_states

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
    if "hire_date" in values and values["hire_date"] != employee.hire_date:
        _require_hire_outside_approved(employee, employee.hire_date, values["hire_date"])
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
    switched_on = bool(values.get("payroll_external")) and not employee.payroll_external
    saved = masterdata.update_record(actor, employee, values)
    if switched_on:
        # Onaylı aylar saklı satırlarıyla korunur; onaylanmamış aylardaki ERP kayıtları kartın
        # geçmişine yazılır (açıklamasız), ekran da uyarır (docs/DECISIONS.md "Onaylılar korunsun").
        records = selectors.unapproved_payroll_records(saved)
        if records:
            _card_note(
                actor, saved, external_switch_note(records, selectors.kept_erp_months(saved))
            )
    return saved


def external_switch_note(records: Sequence[str], kept: Sequence[str]) -> str:
    """Kart "mali müşavirde" işaretlenince kartın geçmişine yazılan not: onaylanmamış aylardaki ERP
    kayıtları; yeniden açılan ayda kişi son onaydaki haliyle ERP'de kalıyorsa o aylar ayrıca."""
    text = (
        'Kartı "Bordrosu mali müşavirde" işaretlendi; onaylanmamış bordro aylarında ERP\'de '
        f"girilmiş kayıtları var: {'; '.join(records)}."
    )
    if kept:
        text += (
            f" Yeniden açılan {', '.join(kept)} son onaydaki haliyle ERP'de hesaplanır; kartın "
            'işaretiyle hesaplamak için Personel > Bordro > Ay hazırlığında "Kartı izle"ye basın.'
        )
    # Kartı izleyen aylardaki kayıtlar (yeniden açık ay notu olmayanlar) mali müşavire bildirilir.
    if any(not record.endswith(f"({selectors.KEPT_ERP_NOTE})") for record in records):
        lead = "Diğer aylardakileri mali müşavire" if kept else "Mali müşavire"
        text += f" {lead} bildirin; gerekmiyorsa Personel > Bordro'dan gerekçeyle kaldırın."
    return text


def _require_hire_outside_approved(employee: Employee, old: date | None, new: date | None) -> None:
    """İşe giriş tarihi değişince işte olunan günleri değişen aylardan biri onaylı bordroda kişinin
    satırı olan aysa reddeder (onaylı satır değişmez; önce bordro yeniden açılır). Değişen günler
    eski ve yeni tarih arasındakilerdir (tarih boşsa öncesinin hepsi). Tarih geri alınınca sonraki
    onaylı satırın kümülatifi de korunur (`_require_later_slips_kept`)."""
    if old is None or new is None:
        low, high = None, old or new
    else:
        low, high = min(old, new), max(old, new)
    assert high is not None
    for year, month, number in selectors.approved_slip_months(employee):
        first, last = selectors.month_bounds(year, month)
        if (low is None or last >= low) and first < high:
            raise BusinessRuleError(
                "payroll_approved",
                f"Yeni işe giriş tarihi {employee.full_name} için onaylı "
                f"{selectors.month_label(year, month)} bordrosunu ({number}) değiştirir. Önce o "
                "ayın bordrosunu Personel > Bordro'dan gerekçeyle yeniden açın.",
            )
    if old is not None and (new is None or new < old):
        _require_later_slips_kept(employee, new, old)


def _require_later_slips_kept(employee: Employee, new: date | None, old: date) -> None:
    """İşe giriş tarihi geri alınınca kişi, satırı olmayan onaylı bir ayda (ya da başlangıç
    yılında ERP bordrosundan önceki bir ayda) işte sayılmaya başlıyorsa o ayın kümülatifi
    bilinmez. Aynı yıl sonraki ilk onaylı satırı ERP'deyse ve zinciri o aydan sonraki bir devirle
    başlamıyorsa o satırın kümülatifi bu ayı saymadan kurulmuştur: değişiklik onaylı satırı
    değiştirir, reddedilir (önce bordro yeniden açılır; açılan ayda zincir kopar ve devir
    istenir). Sonraki satır mali müşavirdeyse zincir zaten orada koptu."""
    slips = list(
        PayrollSlip.objects.filter(
            employee=employee,
            approval__reopened_at__isnull=True,
            approval__run__status=PayrollRun.Status.APPROVED,
        ).values_list(
            "approval__run__year",
            "approval__run__month",
            "approval__run__number",
            "external",
            "chain",
        )
    )
    present = {(year, month) for year, month, *_ in slips}
    # Başlangıç yılında ERP bordrosundan önceki aylar (mali müşavirde; onaylanmaz, satırı olmaz)
    # satırı olmayan onaylı ay gibidir: kümülatifleri ancak devirle gelir.
    start_year, start_month = selectors.PAYROLL_START
    months = [(start_year, number) for number in range(1, start_month)]
    months += list(
        PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED)
        .order_by("year", "month")
        .values_list("year", "month")
    )
    for year, month in months:
        first, last = selectors.month_bounds(year, month)
        if (year, month) in present or not ((new is None or last >= new) and first < old):
            continue  # satırı olan ay yukarıda denetlendi ya da ayın işte olunan günleri değişmiyor
        later = [slip for slip in slips if slip[0] == year and slip[1] > month]
        if not later:
            continue
        _, slip_month, number, external, chain = min(later, key=lambda slip: slip[1])
        opening = (chain or {}).get("opening") or {}
        if external or int(opening.get("month") or 0) > month:
            continue  # zincir orada koptu ya da sonraki devir bu ayı kapsıyor
        raise BusinessRuleError(
            "payroll_approved",
            f"Yeni işe giriş tarihiyle {employee.full_name} {selectors.month_label(year, month)} "
            "ayında işte sayılır; o ay ERP bordrosunda satırı yok, onaylı "
            f"{selectors.month_label(year, slip_month)} bordrosunun ({number}) kümülatifi onu "
            "saymadan kuruldu. Önce o ayın bordrosunu Personel > Bordro'dan gerekçeyle yeniden "
            "açın.",
        )


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
    # Onaylı aydaki devir kilitlidir: önce o ayın bordrosu yeniden açılır.
    locked = sorted(
        PayrollRun.objects.filter(
            year=hire.year,
            month__in=[opening.month for opening in excess],
            status=PayrollRun.Status.APPROVED,
        ).values_list("month", flat=True)
    )
    if locked:
        months = ", ".join(selectors.month_label(hire.year, number) for number in locked)
        noun = "bordrosu" if len(locked) == 1 else "bordroları"
        advice = (
            f"{months} {noun} onaylı: önce Personel > Bordro'dan gerekçeyle yeniden açın, sonra "
            "devri düzeltin ya da gerekçeyle kaldırın."
        )
    else:
        advice = "Önce devri Personel > Bordro'dan düzeltin ya da gerekçeyle kaldırın."
    raise BusinessRuleError(
        "opening_months_exceed_hire",
        f"{employee.full_name} için yeni işe giriş tarihine ({hire:%d.%m.%Y}) göre asgari ücret "
        f"istisnası ay sayısı fazla kalan devir var: {listed}. {advice}",
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
    """Onaylı aylarda çıkıştan sonra kayıtlı günler için Türkçe hata metni (aylar ve günleri). Ayın
    bordrosu da onaylıysa önce bordronun yeniden açılması söylenir (puantaj ondan sonra açılır)."""
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
    approved = PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED)
    payrolls = sorted(
        (run.year, run.month, run.number) for run in approved if (run.year, run.month) in spans
    )
    reopen = f"önce {which} Puantaj'da"
    if payrolls:
        listed = ", ".join(
            f"{selectors.month_label(year, month)} {number}" for year, month, number in payrolls
        )
        reopen = f"önce bordroyu Personel > Bordro'dan ({listed}), sonra {which} Puantaj'da"
    return (
        f"{employee.full_name}, çıkış tarihinden ({day:%d.%m.%Y}) sonra da onaylı puantajda "
        f"görünüyor: {months}. Bordroya giden rakam değişeceği için {reopen} gerekçeyle yeniden "
        f"açın, sonra ayrılışı kaydedin; ardından {again} yeniden onaylayıp yeni Excel'i bordroya "
        "verin."
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
    # Önce onaylı puantaj: bordrosu da onaylı aydaki kayıtlar bordro açılmadan kaldırılamaz,
    # hata önce bordronun sonra puantajın açılmasını söyler.
    later = _lock_attendance_after(locked, termination_date)
    approved = [entry for entry in later if entry.month.status == AttendanceMonth.Status.APPROVED]
    if approved:
        raise ApprovedAttendanceAfterExit(
            _approved_after_exit(locked, termination_date, approved),
            sorted({f"{entry.date:%Y-%m}" for entry in approved}),
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
                    year=year,  # Aralık puantajı Ocak'ta açılsa da PU-<Aralık'ın yılı>
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
    """Onaylı ayı düzeltme için yeniden açar (gerekçe zorunlu). Günler onaydaki haliyle kalır. Ayın
    bordrosu onaylıysa reddedilir (önce bordro yeniden açılır)."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Yeniden açma gerekçesi girilmelidir.")
    locked = AttendanceMonth.objects.select_for_update().get(pk=record.pk)
    attendance_month_states.assert_can_transition(locked.status, AttendanceMonth.Status.OPEN)
    run = PayrollRun.objects.filter(
        year=locked.year, month=locked.month, status=PayrollRun.Status.APPROVED
    ).first()
    if run is not None:
        raise BusinessRuleError(
            "payroll_approved",
            f"{selectors.month_label(locked.year, locked.month)} bordrosu onaylı ({run.number}); "
            "puantajı açmadan önce bordroyu Personel > Bordro'dan gerekçeyle yeniden açın.",
        )
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


def _next_wage_start(
    employee: Employee, after: date, exclude: EmployeeWage | None = None
) -> date | None:
    """Kişinin `after` tarihinden sonra başlayan ilk geçerli ücretinin başlangıcı (yoksa None)."""
    rows = EmployeeWage.objects.filter(employee=employee, is_active=True, valid_from__gt=after)
    if exclude is not None:
        rows = rows.exclude(pk=exclude.pk)
    return rows.order_by("valid_from").values_list("valid_from", flat=True).first()


def _require_wage_outside_approved(employee: Employee, start: date, end: date | None) -> None:
    """[start, end) günlerinin ücreti değişecek: kişinin ERP'de hesaplanan satırı olan onaylı bir
    bordro ayına düşerse reddeder (onaylı satır değişmez)."""
    for year, month, number in selectors.approved_slip_months(employee, computed_only=True):
        first, last = selectors.month_bounds(year, month)
        if last >= start and (end is None or first < end):
            raise BusinessRuleError(
                "payroll_approved",
                f"Bu ücret {employee.full_name} için onaylı {selectors.month_label(year, month)} "
                f"bordrosunu ({number}) değiştirir. Önce o ayın bordrosunu Personel > Bordro'dan "
                "gerekçeyle yeniden açın.",
            )


@transaction.atomic
def add_wage(actor: User, data: Mapping[str, Any]) -> EmployeeWage:
    """Kişiye brüt aylık ücret girer, `valid_from` tarihinden itibaren geçerli. Zam yeni tarihle
    eklenir; aynı kişide aynı tarihte iki geçerli ücret olamaz. Ücret sıfırdan büyük olmalı.
    Ayrılan kişiye de girilir (geçmiş ayın hesabı için). Ücretin geçerli olacağı günler (bir sonraki
    ücrete kadar) kişinin onaylı bordrodaki bir ayına düşerse reddedilir."""
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
    # Kart önce kilitlenir (bordro onayıyla aynı sıra): onay sürerken ücret araya giremez.
    employee = Employee.objects.select_for_update().get(pk=wage.employee_id)
    duplicate = EmployeeWage.objects.filter(
        employee_id=wage.employee_id, valid_from=wage.valid_from, is_active=True
    )
    if duplicate.exists():
        raise _duplicate_wage(wage.valid_from)
    _require_wage_outside_approved(
        employee, wage.valid_from, _next_wage_start(employee, wage.valid_from)
    )
    wage.note = _text(wage.note)[:200]
    try:
        with transaction.atomic():
            return save_with_audit(wage, actor)
    except IntegrityError:
        # Aynı kişi ve tarihe aynı anda iki ücret girildi (tekil kısıt).
        raise _duplicate_wage(wage.valid_from) from None


@transaction.atomic
def remove_wage(actor: User, wage: EmployeeWage, reason: str) -> EmployeeWage:
    """Yanlış ücret kaydını kaldırır (silinmez, pasife alınır; neden zorunlu). Ücretin geçerli
    olduğu günler kişinin onaylı bordrodaki bir ayına düşüyorsa reddedilir."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    employee = Employee.objects.select_for_update().get(pk=wage.employee_id)
    locked = EmployeeWage.objects.select_for_update().get(pk=wage.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Ücret kaydı zaten kaldırılmış.")
    _require_wage_outside_approved(
        employee, locked.valid_from, _next_wage_start(employee, locked.valid_from, locked)
    )
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


# Bordro yılı kilidi (PostgreSQL danışma kilidi, işlem sonunda bırakılır): bordro onayı ve
# parametre seti yazımı aynı yıl için sırayla çalışır; onayın hesapladığı parametreler onay bitene
# kadar değişmez.
PAYROLL_LOCK_NAMESPACE = 7302


def _lock_payroll_years(years: Sequence[int] | set[int]) -> None:
    with connection.cursor() as cursor:
        for year in sorted(set(years)):
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s::integer, %s::integer)",
                [PAYROLL_LOCK_NAMESPACE, year],
            )


def _approved_parameters(years: set[int]) -> dict[tuple[int, int], tuple[str, payroll.Parameters]]:
    """Yılların onaylı bordro aylarında bugün geçerli parametreler: (yıl, ay) → (kaynak, değerler).
    Önce yılların bordro kilidi alınır."""
    _lock_payroll_years(years)
    found = {}
    for year in sorted(years):
        months = list(
            PayrollRun.objects.filter(year=year, status=PayrollRun.Status.APPROVED).values_list(
                "month", flat=True
            )
        )
        for month, found_settings in selectors.parameter_settings(year, months).items():
            found[(year, month)] = (found_settings.source, found_settings.params)
    return found


def _require_parameters_unchanged(
    before: dict[tuple[int, int], tuple[str, payroll.Parameters]], years: set[int]
) -> None:
    """Yazımdan sonra onaylı ayların geçerli parametreleri yazımdan öncekiyle aynı olmalı."""
    if not before:
        return
    after = _approved_parameters(years)
    changed = sorted(key for key, value in before.items() if after.get(key) != value)
    if not changed:
        return
    numbers = dict(
        ((run.year, run.month), run.number)
        for run in PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED, year__in=years)
    )
    listed = ", ".join(
        f"{selectors.month_label(year, month)} ({numbers.get((year, month), '')})"
        for year, month in changed
    )
    raise BusinessRuleError(
        "payroll_approved",
        f"Bu değişiklik onaylı bordroların parametrelerini değiştirir: {listed}. Önce bu ayların "
        "bordrosunu Personel > Bordro'dan gerekçeyle yeniden açın (sondan başa).",
    )


@transaction.atomic
def create_parameter_set(actor: User, data: Mapping[str, Any]) -> PayrollParameterSet:
    """Bordro parametre seti açar (ör. yeni yılın yasal değerleri; ekranda yasal değerlerle dolu
    gelir, mali müşavirle kontrol edilip kaydedilir). Geçerlilik bir ayın ilk günüdür; aynı aydan
    geçerli ikinci set açılamaz."""
    _require_role(actor)
    values = _clean_parameters(_pick(data, PARAMETER_FIELDS))
    years = {values["valid_from"].year}
    before = _approved_parameters(years)
    try:
        with transaction.atomic():
            saved = save_with_audit(PayrollParameterSet(**values), actor)
    except IntegrityError:  # aynı ay eşzamanlı açıldı
        raise _duplicate_parameters(values["valid_from"]) from None
    _require_parameters_unchanged(before, years)
    return saved


@transaction.atomic
def update_parameter_set(
    actor: User, instance: PayrollParameterSet, data: Mapping[str, Any]
) -> PayrollParameterSet:
    """Parametre setini düzeltir; değişen değerler eski → yeni denetim günlüğüne yazılır. Onaylı
    bir bordro ayının parametrelerini değiştirecekse reddedilir (kaynak ya da not düzeltmesi
    serbesttir)."""
    _require_role(actor)
    locked = PayrollParameterSet.objects.select_for_update().get(pk=instance.pk)
    if not locked.is_active:
        raise BusinessRuleError("parameters_removed", "Kaldırılmış parametre seti düzenlenemez.")
    values = _clean_parameters(_pick(data, PARAMETER_FIELDS), locked)
    years = {locked.valid_from.year, values["valid_from"].year}
    before = _approved_parameters(years)
    for name, value in values.items():
        setattr(locked, name, value)
    try:
        with transaction.atomic():
            saved = save_with_audit(locked, actor)
    except IntegrityError:
        raise _duplicate_parameters(values["valid_from"]) from None
    _require_parameters_unchanged(before, years)
    return saved


@transaction.atomic
def remove_parameter_set(
    actor: User, instance: PayrollParameterSet, reason: str
) -> PayrollParameterSet:
    """Yanlış açılmış parametre setini kaldırır (silinmez, pasife alınır; neden zorunlu). O ay ve
    sonrası bir önceki setle, yoksa yasal değerlerle hesaplanır. Onaylı bir bordro ayının
    parametrelerini değiştirecekse reddedilir."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Kaldırma nedeni girilmelidir.")
    locked = PayrollParameterSet.objects.select_for_update().get(pk=instance.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Parametre seti zaten kaldırılmış.")
    years = {locked.valid_from.year}
    before = _approved_parameters(years)
    locked.is_active = False
    saved = save_with_audit(locked, actor, note=f"Parametre seti kaldırıldı. Neden: {reason}")
    _require_parameters_unchanged(before, years)
    return saved


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
    personel maliyeti bu rakamları kullanır. Kişinin o aya ERP'de girilmiş kalemleri varsa rakam
    yine girilir; kalemler hesaplanmaz, bordro listesinde mali müşavir bölümünde yazar."""
    _require_role(actor)
    _check_period(year, month)
    employee = Employee.objects.select_for_update().get(pk=employee.pk)
    figure = (
        ExternalPayrollFigure.objects.select_for_update()
        .filter(employee=employee, year=year, month=month, is_active=True)
        .first()
    )
    _require_payroll_open(year, month)
    # Kartın işareti sonradan kaldırılsa da o ayın girilmiş rakamı düzeltilebilir; yeniden açılan
    # ayda onaydaki işaret geçerlidir.
    if not selectors.month_flags(employee, year, month)[0] and figure is None:
        # Kart "mali müşavirde" iken ERP'de hesaplanıyorsa yeniden açılan ayda onaydaki işarettir.
        reason = (
            "yeniden açılan ayda onaydaki haliyle ERP'de; kartın bugünkü işaretiyle hesaplamak "
            'için Ay hazırlığında "Kartı izle"ye basın'
            if employee.payroll_external
            else 'kartında "Bordrosu mali müşavirde" işaretli değil'
        )
        raise BusinessRuleError(
            "not_external",
            f"{employee.full_name} için {selectors.month_label(year, month)} bordrosu ERP'de "
            f"hesaplanıyor ({reason}).",
        )
    first, last = selectors.month_bounds(year, month)
    if not selectors.employees_between(first, last).filter(pk=employee.pk).exists():
        raise BusinessRuleError(
            "not_employed",
            f"{employee.full_name} {selectors.month_label(year, month)} ayında işte değil.",
        )
    # Rakam ancak kişinin o ayı zaten mali müşavirdeyken girilir: ERP'de girilmiş kalemleri varsa
    # da hesaplanmaz; bordro listesinin mali müşavir bölümünde yazar (2026-11-03 "Onaylansın,
    # listede yazsın").
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


def record_payroll_access(
    actor: User,
    year: int,
    month: int,
    output: str,
    *,
    approval: PayrollApproval | None = None,
    employee: Employee | None = None,
) -> None:
    """Bordro çıktısının (PDF, Excel) açıldığını denetim günlüğüne yazar (ücret ve kimlik bilgisi
    içeren kişisel veriye erişim izi, docs/KVKK.md): ayın bordro kaydına (yoksa kayıtsız); tek
    kişinin ücret pusulası kişinin kartının geçmişine de."""
    _require_role(actor)
    label = selectors.month_label(year, month)
    run = PayrollRun.objects.filter(year=year, month=month).first()
    parts = [f"Bordro çıktısı açıldı: {output}", label]
    if run is not None:
        parts.append(run.number)
    if approval is not None:
        state = " (geçersiz)" if approval.reopened_at else ""
        parts.append(f"{approval.sequence}. onay{state}")
    changes: dict[str, Any] = {"year": year, "month": month}
    if employee is not None:
        changes["employee"] = employee.pk
    log_change(actor, run, AuditLog.Action.CUSTOM, changes, " · ".join(parts))
    if employee is not None:
        _card_note(actor, employee, f"Ücret hesap pusulası açıldı: {label}")


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
    """Ayın bordrosu onaylıysa o aya etki eden yazım reddedilir (`payroll_approved`). Bordroya etki
    eden her yazım (kalem, devir, mali müşavir rakamı) kişinin kartını kilitledikten sonra bunu
    çağırır. Önce bordro yılının kilidi paylaşımlı alınır: onay aynı kilidi özel alır ve onay
    bitene kadar tutar; böylece onayın kilitlemediği bir karta (o ay günü olmayan) yazılan kayıt
    da onayla sıraya girer, arada kayıt kaçmaz."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock_shared(%s::integer, %s::integer)",
            [PAYROLL_LOCK_NAMESPACE, year],
        )
    run = PayrollRun.objects.filter(
        year=year, month=month, status=PayrollRun.Status.APPROVED
    ).first()
    if run is not None:
        raise BusinessRuleError(
            "payroll_approved",
            f"{selectors.month_label(year, month)} bordrosu onaylı ({run.number}); değiştirmek "
            "için önce bordroyu Personel > Bordro'dan gerekçeyle yeniden açın.",
        )


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
    if selectors.external_in_month(employee, year, month):
        raise BusinessRuleError(
            "not_computed",
            f"{employee.full_name} için {label} bordrosu mali müşavirde; ERP'de hesaplanmaz.",
        )


def _erp_month(employee: Employee, year: int, month: int) -> bool:
    """Kişinin o ay bordrosu ERP'de mi hesaplandı (başlangıçtan sonra, işte, mali müşavirde
    değil; onaylı ayda saklı satırına göre)? Devir bu aydan sonraki bir aya girilirse ERP
    hesabının yerine geçer."""
    if month < 1 or not selectors.net_available(year, month):
        return False
    run = PayrollRun.objects.filter(
        year=year, month=month, status=PayrollRun.Status.APPROVED
    ).first()
    if run is not None:
        return PayrollSlip.objects.filter(
            approval_id=run.current_id, employee=employee, external=False
        ).exists()
    if not selectors.in_payroll(employee, year, month):
        return False  # o ay bordroda değil (zincir "Bordroda satırı yok" der): eşitleme yok
    return not selectors.external_in_month(employee, year, month)


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
    _require_payroll_open(year, month)
    _require_computed(employee, year, month)
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
    _require_payroll_open(year, month)
    _require_computed(employee, year, month)
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


# --- bordro onayı (docs/DECISIONS.md "Personel bordrosu", 4. adım) -------------------------------

# Onay denetimlerinin Türkçe adları (hata metni; ekran kendi metinlerini kullanır).
GATE_TEXTS = {
    selectors.GATE_BEFORE_START: "brütten nete bordro başlangıç ayından önce onaylanmaz",
    selectors.GATE_ATTENDANCE_OPEN: "puantaj onaylanmadı",
    selectors.GATE_PREVIOUS_OPEN: "bir önceki ayın bordrosu onaylanmadı (aylar sırayla onaylanır)",
    selectors.GATE_PARAMETERS: "bu yılın bordro parametreleri kaydedilmedi",
    selectors.GATE_NO_EMPLOYEES: "bu ay bordroda kişi yok",
    selectors.GATE_ORPHAN_ITEMS: "o ay işte olmayan kişiye girilmiş kalem var",
    selectors.OPENING_MISSING: "devir girilmedi",
    selectors.CARRY_INCOMPLETE: "kümülatif eksik",
    selectors.MISSING_WAGE: "ücret eksik",
    selectors.EXTERNAL_MISSING: "mali müşavir rakamı girilmedi",
    selectors.NEGATIVE_PAYABLE: "kesintiler netten fazla",
    selectors.BELOW_MINIMUM_WAGE: "asgari ücretin altında",
    selectors.PAY_WITHOUT_SGK_DAYS: "SGK günü olmadan ödeme",
    selectors.EXIT_IN_MONTH: "ay içinde çıkış",
    selectors.CEILING_WITH_BONUS: "tavanı aşan prim",
    selectors.EXTERNAL_ITEMS: "mali müşavirdeki kişiye ERP'de girilmiş kalem",
}
NAMES_SHOWN = 5
# Ödeme tarihi en geç bordro ayından üç ay sonrasının son günü.
PAYMENT_MONTHS_AFTER = 3


def gate_text(gate: selectors.Gate) -> str:
    """ "ücret eksik: Ali Kaya, Ayşe Demir ve 3 kişi daha"."""
    text = GATE_TEXTS.get(gate.code, gate.code)
    if not gate.people:
        return text
    names = [person.full_name for person in gate.people[:NAMES_SHOWN]]
    rest = len(gate.people) - len(names)
    listed = ", ".join(names) + (f" ve {rest} kişi daha" if rest > 0 else "")
    return f"{text}: {listed}"


class PayrollGateError(BusinessRuleError):
    """Onayı reddettiren denetimler: engelleyenler (`payroll_not_ready`) ya da okunmamış "okudum"
    denetimleri (`acknowledgement_required`); `gates` API yanıtına eklenir."""

    def __init__(self, code: str, message: str, gates: list[selectors.Gate]) -> None:
        super().__init__(code, message)
        self.gates = gates


def _check_payment_date(year: int, month: int, payment_date: date | None) -> date:
    """Ödeme tarihi bordro ayının ilk gününden üç ay sonrasının son gününe kadar."""
    if payment_date is None:
        raise BusinessRuleError("payment_date_required", "Ödeme tarihi girilmelidir.")
    first, _ = selectors.month_bounds(year, month)
    limit_year, limit_month = year, month + PAYMENT_MONTHS_AFTER
    if limit_month > 12:
        limit_year, limit_month = limit_year + 1, limit_month - 12
    _, latest = selectors.month_bounds(limit_year, limit_month)
    if not first <= payment_date <= latest:
        raise BusinessRuleError(
            "invalid_payment_date",
            f"Ödeme tarihi {first:%d.%m.%Y} ile {latest:%d.%m.%Y} arasında olmalı (bordro ayının "
            "başından üç ay sonrasının sonuna kadar).",
        )
    return payment_date


def _company_snapshot() -> dict[str, str]:
    """Onayda saklanan firma bilgileri (pusula ve listeler onaydaki unvanla basılır)."""
    company = masterdata.get_company_profile()
    return {
        "legal_name": company.legal_name,
        "address": company.address,
        "tax_office": company.tax_office,
        "tax_number": company.tax_number,
        "registry": masterdata.company_registry_line(company),
    }


def _lock_run(actor: User, year: int, month: int) -> PayrollRun:
    """Ayın bordro kaydı, kilitli (yoksa açılır; numara bordronun yılından: Aralık bordrosu Ocak'ta
    onaylansa da BR-<Aralık'ın yılı>)."""
    run = PayrollRun.objects.select_for_update().filter(year=year, month=month).first()
    if run is not None:
        return run
    try:
        with transaction.atomic():
            return create_document(
                PayrollRun(year=year, month=month),
                actor,
                prefix="BR",
                machine=payroll_run_states,
                event_payload={"year": year, "month": month},
                year=year,
            )
    except IntegrityError:  # aynı ay eşzamanlı açıldı
        return PayrollRun.objects.select_for_update().get(year=year, month=month)


def _slip(approval: PayrollApproval, row: selectors.PayrollRow, actor: User) -> PayrollSlip:
    """Onaylanan ayın bir kişisi: hesap satırı, kişi bilgisi ve ay sonu kümülatifi."""
    line = row.line
    computed = not row.external
    carry = payroll.carry_after(line)
    return PayrollSlip(
        approval=approval,
        employee=row.employee,
        external=row.external,
        bes_enrolled=row.bes,
        person=selectors.person_snapshot(row.person),
        sgk_days=line.sgk_days,
        gross_total=row.gross_total,
        employer_cost=row.employer_cost,
        figure=selectors.figure_snapshot(row.figure),
        net_pay=line.net_pay if computed else None,
        payable=line.payable if computed else None,
        income_tax=line.income_tax if computed else None,
        stamp_tax=line.stamp_tax if computed else None,
        tax_base_after=carry.tax_base if computed else None,
        exemption_base_after=carry.exemption_base if computed else None,
        line=payroll.result_to_dict(line),
        items=[selectors.item_snapshot(item) for item in row.items],
        warnings=list(row.warnings),
        chain=selectors.carry_snapshot(row),
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def approve_payroll_month(
    actor: User,
    year: int,
    month: int,
    *,
    payment_date: date | None,
    fingerprint: str,
    acknowledged: Sequence[str] = (),
) -> PayrollRun:
    """Ayın bordrosunu onaylar: o anki hesap (kişi satırları, kişi bilgisi, kalemler, kümülatif,
    parametreler, firma bilgisi) saklanır ve ay kilitlenir; aya etki eden yazımlar reddedilir.

    Koşullar: ay başlangıç ayı ya da sonrası; puantajı onaylı; bir önceki ayın bordrosu onaylı
    (aylar sırayla); o yılın parametreleri kayıtlı; engelleyen uyarı yok (devir eksik, kümülatif
    eksik, ücret eksik, mali müşavir rakamı girilmedi, kesintiler netten fazla, asgari ücretin
    altında, SGK günü olmadan ödeme, o ay işte olmayan kişiye kalem); "ay içinde çıkış" ve "tavanı
    aşan prim" okundu (`acknowledged`, kodlar). `fingerprint` onay penceresinin gösterdiği hesabın
    özetidir: arada bir şey değiştiyse onay reddedilir (`payroll_changed`). Ödeme tarihi ayın ilk
    gününden üç ay sonrasının son gününe kadar.

    Kilit sırası: ayın kartları, puantaj ayı, bordro yılı, önceki bordro ayı, bu bordro ayı."""
    _require_role(actor)
    _check_payroll_month(year, month)
    label = selectors.month_label(year, month)
    first, last = selectors.month_bounds(year, month)
    holders = (
        Q(pk__in=AttendanceEntry.objects.filter(date__range=(first, last)).values("employee_id"))
        | Q(
            pk__in=PayrollItem.objects.filter(year=year, month=month, is_active=True).values(
                "employee_id"
            )
        )
        | Q(
            pk__in=ExternalPayrollFigure.objects.filter(
                year=year, month=month, is_active=True
            ).values("employee_id")
        )
    )
    list(Employee.objects.select_for_update().filter(holders).order_by("pk").only("pk"))
    AttendanceMonth.objects.select_for_update().filter(year=year, month=month).first()
    _lock_payroll_years({year})
    if (year, month) > selectors.PAYROLL_START:
        before_year, before_month = selectors.previous_period(year, month)
        PayrollRun.objects.select_for_update().filter(year=before_year, month=before_month).first()
    run = _lock_run(actor, year, month)
    if run.status == PayrollRun.Status.APPROVED:
        raise BusinessRuleError(
            "payroll_approved", f"{label} bordrosu zaten onaylı ({run.number})."
        )
    computed = selectors.payroll_month(year, month)
    gates = selectors.payroll_gates(computed)
    blocking = [gate for gate in gates if gate.level == selectors.BLOCK]
    if blocking:
        raise PayrollGateError(
            "payroll_not_ready",
            f"{label} bordrosu onaylanamaz: {'; '.join(gate_text(gate) for gate in blocking)}.",
            blocking,
        )
    read = set(acknowledged)
    unread = [
        gate for gate in gates if gate.level == selectors.ACKNOWLEDGE and gate.code not in read
    ]
    if unread:
        raise PayrollGateError(
            "acknowledgement_required",
            "Onaydan önce şu uyarıları okuduğunuzu işaretleyin: "
            f"{'; '.join(gate_text(gate) for gate in unread)}.",
            unread,
        )
    if fingerprint != selectors.payroll_fingerprint(computed):
        raise BusinessRuleError(
            "payroll_changed",
            f"{label} bordrosu onay penceresi açıldıktan sonra değişti; yenilenen hesabı inceleyip "
            "yeniden onaylayın.",
        )
    payment_date = _check_payment_date(year, month, payment_date)
    sequence = (run.approvals.aggregate(top=Max("sequence"))["top"] or 0) + 1
    approval = PayrollApproval(
        run=run,
        sequence=sequence,
        approved_at=timezone.now(),
        approved_by=actor,
        payment_date=payment_date,
        attendance_number=computed.attendance_number,
        engine_version=payroll.ENGINE_VERSION,
        parameters=selectors.settings_snapshot(computed.settings),
        company=_company_snapshot(),
        acknowledged=[
            {"code": gate.code, "employees": [person.pk for person in gate.people]}
            for gate in gates
            if gate.level in (selectors.ACKNOWLEDGE, selectors.NOTICE)
        ],
        employee_count=len(computed.computed),
        external_count=len(computed.rows) - len(computed.computed),
        gross_total=computed.gross_total,
        employer_cost=computed.employer_cost,
        net_pay=computed.total("net_pay"),
        payable=computed.total("payable"),
        income_tax=computed.total("income_tax"),
        stamp_tax=computed.total("stamp_tax"),
    )
    save_with_audit(approval, actor, note=f"{label} bordrosu onaylandı ({sequence}. onay)")
    PayrollSlip.objects.bulk_create([_slip(approval, row, actor) for row in computed.rows])
    run.current = approval
    run.follow_card = []
    save_with_audit(run, actor)
    note = (
        f"{len(computed.rows)} kişi ({approval.external_count} mali müşavirde) · ödeme "
        f"{payment_date:%d.%m.%Y}"
    )
    return transition_status(
        run,
        PayrollRun.Status.APPROVED,
        actor,
        machine=payroll_run_states,
        note=note,
        event_payload={"year": year, "month": month, "sequence": sequence},
    )


@transaction.atomic
def reopen_payroll_month(actor: User, run: PayrollRun, reason: str) -> PayrollRun:
    """Onaylı bordroyu düzeltme için yeniden açar (gerekçe zorunlu). Yalnızca en son onaylı ay
    açılır (aylar sondan başa). Onay ve satırları saklanır (geçersiz olarak); ay yeniden canlı
    hesaplanır ve onaydaki kişiler onaydaki "Bordrosu mali müşavirde" ve "BES'e dahil"
    işaretleriyle hesaplanır (kartı izlemeye ayrıca geçirilir)."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Yeniden açma gerekçesi girilmelidir.")
    locked = PayrollRun.objects.select_for_update().get(pk=run.pk)
    payroll_run_states.assert_can_transition(locked.status, PayrollRun.Status.OPEN)
    later = (
        PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED)
        .filter(Q(year__gt=locked.year) | Q(year=locked.year, month__gt=locked.month))
        .order_by("year", "month")
        .first()
    )
    if later is not None:
        raise BusinessRuleError(
            "later_payroll_approved",
            f"{selectors.month_label(later.year, later.month)} bordrosu onaylı ({later.number}); "
            "aylar sondan başa açılır, önce o ayı yeniden açın.",
        )
    if locked.current_id is None:  # onaylı bordroda geçerli onay her zaman vardır
        raise BusinessRuleError("payroll_not_approved", "Bordronun geçerli onayı yok.")
    approval = PayrollApproval.objects.select_for_update().get(pk=locked.current_id)
    approval.reopened_at = timezone.now()
    approval.reopened_by = actor
    approval.reopen_reason = reason
    save_with_audit(approval, actor, note=f"Onay geçersiz: bordro yeniden açıldı. Neden: {reason}")
    locked.current = None
    locked.follow_card = []
    save_with_audit(locked, actor)
    return transition_status(
        locked,
        PayrollRun.Status.OPEN,
        actor,
        machine=payroll_run_states,
        note=reason,
        event_payload={"year": locked.year, "month": locked.month, "reason": reason},
    )


@transaction.atomic
def set_payroll_payment_date(
    actor: User, run: PayrollRun, payment_date: date | None, reason: str
) -> PayrollRun:
    """Onaylı bordronun ödeme tarihini gerekçeyle düzeltir (tutarlar değişmez, ay kilitli kalır);
    eski → yeni denetim günlüğüne yazılır."""
    _require_role(actor)
    reason = _text(reason)[:500]
    if not reason:
        raise BusinessRuleError("reason_required", "Düzeltme gerekçesi girilmelidir.")
    locked = PayrollRun.objects.select_for_update().get(pk=run.pk)
    label = selectors.month_label(locked.year, locked.month)
    if locked.status != PayrollRun.Status.APPROVED or locked.current_id is None:
        raise BusinessRuleError(
            "payroll_not_approved", f"{label} bordrosu onaylı değil; ödeme tarihi onayda girilir."
        )
    payment_date = _check_payment_date(locked.year, locked.month, payment_date)
    approval = PayrollApproval.objects.select_for_update().get(pk=locked.current_id)
    old = approval.payment_date
    if old == payment_date:
        return locked
    approval.payment_date = payment_date
    note = f"Ödeme tarihi düzeltildi: {old:%d.%m.%Y} → {payment_date:%d.%m.%Y}. Neden: {reason}"
    save_with_audit(approval, actor, note=note)
    log_change(
        actor,
        locked,
        AuditLog.Action.UPDATE,
        {"payment_date": [old.isoformat(), payment_date.isoformat()]},
        note,
    )
    return locked


@transaction.atomic
def set_payroll_follow_card(
    actor: User, run: PayrollRun, employee: Employee, *, follow: bool
) -> PayrollRun:
    """Yeniden açılan ayda kişiyi kartın bugünkü işaretlerine ("Bordrosu mali müşavirde", "BES'e
    dahil") geçirir (`follow`) ya da son onaydaki işaretlere döndürür. Kayda ve kartın geçmişine
    yazılır."""
    _require_role(actor)
    employee = Employee.objects.select_for_update().get(pk=employee.pk)
    locked = PayrollRun.objects.select_for_update().get(pk=run.pk)
    label = selectors.month_label(locked.year, locked.month)
    if locked.status != PayrollRun.Status.OPEN:
        raise BusinessRuleError(
            "payroll_approved",
            f"{label} bordrosu onaylı ({locked.number}); önce bordroyu gerekçeyle yeniden açın.",
        )
    previous = locked.approvals.order_by("-sequence").first()
    if previous is None or not previous.slips.filter(employee=employee).exists():
        raise BusinessRuleError(
            "not_in_approval",
            f"{employee.full_name} {label} bordrosunun önceki onayında yok; kartın işaretleriyle "
            "hesaplanır.",
        )
    following = set(locked.follow_card or ())
    if (employee.pk in following) == follow:
        return locked
    if follow:
        following.add(employee.pk)
        text = "kartın bugünkü işaretleriyle hesaplanacak"
    else:
        following.discard(employee.pk)
        text = "son onaydaki işaretlerle hesaplanacak"
    locked.follow_card = sorted(following)
    saved = save_with_audit(locked, actor, note=f"{employee.full_name}: {text}")
    _card_note(actor, employee, f"{label} bordrosu: {text}")
    return saved
