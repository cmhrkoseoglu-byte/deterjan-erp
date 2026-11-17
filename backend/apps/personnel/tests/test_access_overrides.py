"""Kişiye özel ayarla personel (docs/plan/kisi-yetkileri.md §3.14, §10, 5. adım): kaldırılan
yetki uç noktada ve serviste düşer, okuma açık kalır; bölümler yalnız yönetim rolündekilere
verilebilir (KVKK); Bordro, Ücretler: Görür'ü ön koşul ister. Maliyet bordro çıktısı günlüğünü
kendi bölümüyle denetler ve personelin günlük yardımcısını denetimsiz çağırır (plan §5.4)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.audit import log_change
from apps.core.models import AccessOverride, AuditLog, User
from apps.core.permissions import MissingAccess, has_access
from apps.personnel import services
from apps.personnel.access import ATTENDANCE, CARDS, PAYROLL, SETTINGS, WAGES
from apps.personnel.models import PayrollRun
from apps.personnel.tests.factories import document, employee, parameter_set

pytestmark = pytest.mark.django_db
D = Decimal
BASE = "/api/v1/personnel"
NONE = cast(Any, None)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User | None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim")


def test_removing_payroll_approve_stops_approval_and_keeps_reads(manager: User) -> None:
    """Yönetimden "Bordro: Onaylar" kaldırılınca onay, yeniden açma ve ödeme tarihi düzeltme 403
    olur; bordro okuması ve kalem girişi açık kalır."""
    client = api(override(manager, PAYROLL.key, APPROVE))

    for path in ("approve", "reopen", "payment-date"):
        refused = client.post(f"{BASE}/payroll/2026/10/{path}/", {}, format="json")
        assert refused.status_code == 403, path
        assert refused.json()["required"] == [{"key": PAYROLL.key, "level": APPROVE}]
    assert client.get(f"{BASE}/payroll/2026/10/").status_code != 403
    assert client.get(f"{BASE}/payroll/items/", {"year": 2026, "month": 10}).status_code == 200
    assert client.get(f"{BASE}/payroll/openings/").status_code == 200
    with pytest.raises(MissingAccess):
        services.approve_payroll_month(manager, 2026, 10, payment_date=None, fingerprint="")


def test_removing_card_change_keeps_cards_and_documents_readable(manager: User) -> None:
    """Yönetimden "Personel kartları: Değiştirir" kaldırılınca kart açma, düzenleme, ayrılış,
    belge ekleme ve kaldırma ile karta kullanıcı seçimi 403 olur; kartlar, geçmiş ve belgeler
    okunur, belge açılışı (Görür) kartın geçmişine yazılır."""
    card = employee(manager)
    diploma = document(manager, card)
    client = api(override(manager, CARDS.key, CHANGE))

    assert client.get(f"{BASE}/employees/").status_code == 200
    assert client.get(f"{BASE}/employees/{card.pk}/history/").status_code == 200
    assert client.get(f"{BASE}/departments/").status_code == 200
    assert client.get(f"{BASE}/documents/", {"employee": card.pk}).status_code == 200
    opened = client.get(f"{BASE}/documents/{diploma.pk}/download/")
    assert opened.status_code == 200
    assert AuditLog.objects.filter(note__startswith="Belge açıldı").exists()

    refused = client.post(f"{BASE}/employees/", {"full_name": "Ali Kaya"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": CARDS.key, "level": CHANGE}]
    assert client.patch(f"{BASE}/employees/{card.pk}/", {"title": "X"}).status_code == 403
    assert client.post(f"{BASE}/employees/{card.pk}/reinstate/").status_code == 403
    assert client.post(f"{BASE}/documents/{diploma.pk}/remove/", {"reason": "x"}).status_code == (
        403
    )
    assert client.get(f"{BASE}/linkable-users/").status_code == 403
    # Görünümün karşılamadığı metot yazma yetkisiyle denetlenir.
    assert client.put(f"{BASE}/employees/{card.pk}/", {}).status_code == 403
    with pytest.raises(MissingAccess):
        services.update_employee(manager, card, {"title": "X"})


def test_personnel_sections_cannot_be_given_outside_management(
    make_user: Callable[..., User],
) -> None:
    """KVKK: Personel bölümleri yalnız yönetim rolündekilere verilebilir; başka role kişiye
    eklenen yetki geçerli olmaz."""
    planner = make_user("planlama")
    for section in (CARDS, ATTENDANCE, WAGES, PAYROLL, SETTINGS):
        override(planner, section.key, VIEW, effect="grant")
    assert not has_access(planner, CARDS, VIEW)
    client = api(planner)
    assert client.get(f"{BASE}/employees/").status_code == 403
    assert client.get(f"{BASE}/attendance/2026/10/").status_code == 403
    assert client.get(f"{BASE}/payroll/2026/10/").status_code == 403


def test_payroll_needs_wage_view(manager: User) -> None:
    """Bordro, Ücretler: Görür'ü ön koşul ister (bordro brüt ücreti gösterir): Ücretler'i
    kaldırılan kişi bordroyu da göremez; puantaj açık kalır."""
    client = api(override(manager, WAGES.key, VIEW))

    assert not has_access(manager, PAYROLL, VIEW)
    assert client.get(f"{BASE}/wages/").status_code == 403
    refused = client.get(f"{BASE}/payroll/2026/10/xlsx/")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": PAYROLL.key, "level": VIEW}]
    assert client.get(f"{BASE}/attendance/2026/10/").status_code == 200
    with pytest.raises(MissingAccess):
        services.record_payroll_access(manager, 2026, 10, "Excel")


def test_removing_settings_change_keeps_week_rest_days_and_parameters_readable(
    manager: User,
) -> None:
    client = api(override(manager, SETTINGS.key, CHANGE))

    assert client.get(f"{BASE}/attendance/settings/").status_code == 200
    assert client.get(f"{BASE}/payroll/parameters/").status_code == 200
    assert client.get(f"{BASE}/payroll/parameters/defaults/", {"year": 2026}).status_code == 200
    refused = client.patch(f"{BASE}/attendance/settings/", {"rest_weekdays": [6]}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": SETTINGS.key, "level": CHANGE}]
    assert client.post(f"{BASE}/payroll/parameters/", {}, format="json").status_code == 403
    # Tatiller puantaj bölümündedir.
    assert client.post(
        f"{BASE}/attendance/holidays/fixed/", {"year": 2026}, format="json"
    ).status_code == (201)


def test_removing_attendance_approve_keeps_entry(manager: User) -> None:
    card = employee(manager, hire_date=date(2026, 1, 5))
    client = api(override(manager, ATTENDANCE.key, APPROVE))

    assert client.get(f"{BASE}/attendance/2026/10/").status_code == 200
    refused = client.post(f"{BASE}/attendance/2026/10/approve/")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": ATTENDANCE.key, "level": APPROVE}]
    entered = client.post(
        f"{BASE}/attendance/days/",
        {"employee": card.pk, "date": "2026-10-05", "status": "ANNUAL_LEAVE"},
        format="json",
    )
    assert entered.status_code == 200, entered.json()


def test_cost_module_logs_payroll_output_with_its_own_check(make_user: Callable[..., User]) -> None:
    """Plan §5.4: maliyet kendi bölümüyle (Personel maliyeti: Görür) denetler ve bordro çıktısı
    günlüğünü personelin denetimsiz yardımcısıyla yazar; günlük yazımı Bordro: Görür'e bakmaz."""
    manager = make_user("yonetim")
    run = PayrollRun.objects.create(year=2026, month=10, number="BR-2026-00001")
    override(manager, WAGES.key, VIEW)
    assert not has_access(manager, PAYROLL, VIEW)

    services.log_payroll_access(manager, 2026, 10, "Personel maliyeti (Excel)")

    entry = AuditLog.objects.get(object_id=str(run.pk), note__startswith="Bordro çıktısı açıldı")
    assert (
        entry.note == "Bordro çıktısı açıldı: Personel maliyeti (Excel) · Ekim 2026 · BR-2026-00001"
    )
    with pytest.raises(MissingAccess):
        services.record_payroll_access(manager, 2026, 10, "Personel maliyeti (Excel)")


def test_each_service_names_its_section_and_level(make_user: Callable[..., User]) -> None:
    """Her servis denetimi planın §3.14 tablosundaki bölüme ve düzeye bağlıdır: rolü olmayan kişi
    her birinde, işin kurallarından ve kayıtlara dokunmadan önce, o yetkiyi söyleyen 403 alır."""
    nobody = make_user()
    day = date(2026, 10, 5)
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        ("create_employee", lambda: services.create_employee(nobody, {}), (CARDS.key, CHANGE)),
        (
            "update_employee",
            lambda: services.update_employee(nobody, NONE, {}),
            (CARDS.key, CHANGE),
        ),
        (
            "terminate_employee",
            lambda: services.terminate_employee(nobody, NONE, day),
            (CARDS.key, CHANGE),
        ),
        (
            "reinstate_employee",
            lambda: services.reinstate_employee(nobody, NONE),
            (CARDS.key, CHANGE),
        ),
        (
            "add_document",
            lambda: services.add_document(nobody, NONE, kind="DIPLOMA", file=NONE),
            (CARDS.key, CHANGE),
        ),
        (
            "remove_document",
            lambda: services.remove_document(nobody, NONE, "x"),
            (CARDS.key, CHANGE),
        ),
        (
            "record_document_access",
            lambda: services.record_document_access(nobody, NONE),
            (CARDS.key, VIEW),
        ),
        (
            "update_attendance_settings",
            lambda: services.update_attendance_settings(nobody, [6]),
            (SETTINGS.key, CHANGE),
        ),
        ("add_holiday", lambda: services.add_holiday(nobody, {}), (ATTENDANCE.key, CHANGE)),
        (
            "update_holiday",
            lambda: services.update_holiday(nobody, NONE, {}),
            (ATTENDANCE.key, CHANGE),
        ),
        (
            "remove_holiday",
            lambda: services.remove_holiday(nobody, NONE),
            (ATTENDANCE.key, CHANGE),
        ),
        (
            "add_fixed_holidays",
            lambda: services.add_fixed_holidays(nobody, 2026),
            (ATTENDANCE.key, CHANGE),
        ),
        (
            "set_attendance_day",
            lambda: services.set_attendance_day(nobody, NONE, day, status="ANNUAL_LEAVE"),
            (ATTENDANCE.key, CHANGE),
        ),
        (
            "set_attendance_range",
            lambda: services.set_attendance_range(
                nobody, start=day, end=day, status="ANNUAL_LEAVE"
            ),
            (ATTENDANCE.key, CHANGE),
        ),
        (
            "approve_attendance_month",
            lambda: services.approve_attendance_month(nobody, 2026, 10),
            (ATTENDANCE.key, APPROVE),
        ),
        (
            "reopen_attendance_month",
            lambda: services.reopen_attendance_month(nobody, NONE, "x"),
            (ATTENDANCE.key, APPROVE),
        ),
        ("add_wage", lambda: services.add_wage(nobody, {}), (WAGES.key, CHANGE)),
        ("remove_wage", lambda: services.remove_wage(nobody, NONE, "x"), (WAGES.key, CHANGE)),
        (
            "create_parameter_set",
            lambda: services.create_parameter_set(nobody, {}),
            (SETTINGS.key, CHANGE),
        ),
        (
            "update_parameter_set",
            lambda: services.update_parameter_set(nobody, NONE, {}),
            (SETTINGS.key, CHANGE),
        ),
        (
            "remove_parameter_set",
            lambda: services.remove_parameter_set(nobody, NONE, "x"),
            (SETTINGS.key, CHANGE),
        ),
        (
            "set_external_payroll",
            lambda: services.set_external_payroll(
                nobody, NONE, 2026, 10, gross_total=D("1"), employer_cost=D("1")
            ),
            (PAYROLL.key, CHANGE),
        ),
        (
            "remove_external_payroll",
            lambda: services.remove_external_payroll(nobody, NONE, "x"),
            (PAYROLL.key, CHANGE),
        ),
        (
            "record_payroll_access",
            lambda: services.record_payroll_access(nobody, 2026, 10, "Excel"),
            (PAYROLL.key, VIEW),
        ),
        (
            "set_opening_balance",
            lambda: services.set_opening_balance(
                nobody, NONE, 2026, 10, tax_base=None, exemption_months=None
            ),
            (PAYROLL.key, CHANGE),
        ),
        (
            "set_opening_balances",
            lambda: services.set_opening_balances(nobody, 2026, 10, []),
            (PAYROLL.key, CHANGE),
        ),
        (
            "remove_opening_balance",
            lambda: services.remove_opening_balance(nobody, NONE, "x"),
            (PAYROLL.key, CHANGE),
        ),
        (
            "add_payroll_item",
            lambda: services.add_payroll_item(nobody, {}),
            (PAYROLL.key, CHANGE),
        ),
        (
            "add_payroll_items",
            lambda: services.add_payroll_items(nobody, 2026, 10, []),
            (PAYROLL.key, CHANGE),
        ),
        (
            "update_payroll_item",
            lambda: services.update_payroll_item(nobody, NONE, {}),
            (PAYROLL.key, CHANGE),
        ),
        (
            "remove_payroll_item",
            lambda: services.remove_payroll_item(nobody, NONE, "x"),
            (PAYROLL.key, CHANGE),
        ),
        (
            "set_payroll_follow_card",
            lambda: services.set_payroll_follow_card(nobody, NONE, NONE, follow=True),
            (PAYROLL.key, CHANGE),
        ),
        (
            "approve_payroll_month",
            lambda: services.approve_payroll_month(
                nobody, 2026, 10, payment_date=None, fingerprint=""
            ),
            (PAYROLL.key, APPROVE),
        ),
        (
            "reopen_payroll_month",
            lambda: services.reopen_payroll_month(nobody, NONE, "x"),
            (PAYROLL.key, APPROVE),
        ),
        (
            "set_payroll_payment_date",
            lambda: services.set_payroll_payment_date(nobody, NONE, None, "x"),
            (PAYROLL.key, APPROVE),
        ),
    ]

    wrong: list[str] = []
    for name, call, required in calls:
        try:
            call()
        except MissingAccess as error:
            if error.required != (required,):
                wrong.append(f"{name}: {error.required} != {(required,)}")
        except Exception as error:  # noqa: BLE001 - denetimden önce kayda dokunan servis
            wrong.append(f"{name}: denetimden önce {type(error).__name__}")
        else:
            wrong.append(f"{name}: reddedilmedi")
    assert not wrong, "\n".join(wrong)
    assert not AuditLog.objects.filter(actor=nobody).exists()


def test_unrouted_methods_keep_todays_rule(manager: User, make_user: Callable[..., User]) -> None:
    """Görünümün karşılamadığı metotlar ve yalnız POST'u olan yollar (sözleşme testinin dışındaki
    yollar dahil) bugünkü kararı verir: yönetim olmayana 403, yönetime 405; OPTIONS yönetime
    açık; oturumsuza 401."""
    card = employee(manager)
    management, planning = api(manager), api(make_user("planlama"))

    cases: list[tuple[APIClient, str, str, int]] = [
        (management, "put", f"employees/{card.pk}/", 405),
        (planning, "put", f"employees/{card.pk}/", 403),
        (management, "delete", f"employees/{card.pk}/", 405),
        (management, "get", f"employees/{card.pk}/terminate/", 405),
        (planning, "get", f"employees/{card.pk}/terminate/", 403),
        (management, "patch", "employees/", 405),
        (management, "delete", "documents/1/", 405),
        (planning, "delete", "documents/1/", 403),
        (management, "post", "departments/", 405),
        (planning, "post", "departments/", 403),
        (management, "post", "linkable-users/", 405),
        (management, "get", "attendance/days/", 405),
        (planning, "get", "attendance/days/", 403),
        (management, "head", "attendance/ranges/", 405),
        (management, "options", "attendance/2026/10/approve/", 200),
        (planning, "options", "attendance/2026/10/approve/", 403),
        (management, "get", "attendance/2026/10/reopen/", 405),
        (management, "post", "attendance/2026/10/export/", 405),
        (management, "put", "attendance/holidays/1/", 405),
        (planning, "put", "attendance/holidays/1/", 403),
        (management, "post", "attendance/settings/", 405),
        (planning, "head", "attendance/settings/", 403),
        (management, "head", "attendance/settings/", 200),
        (management, "patch", "wages/1/", 405),
        (planning, "patch", "wages/1/", 403),
        (management, "post", "payroll/2026/10/", 405),
        (management, "get", "payroll/2026/10/approve/", 405),
        (planning, "get", "payroll/2026/10/approve/", 403),
        (management, "options", "payroll/2026/10/external/", 200),
        (management, "delete", "payroll/2026/10/xlsx/", 405),
        (management, "get", "payroll/external/1/remove/", 405),
        (management, "put", "payroll/parameters/1/", 405),
        (planning, "put", "payroll/parameters/1/", 403),
        (management, "put", "payroll/items/1/", 405),
        (management, "patch", "payroll/openings/1/", 405),
        (planning, "patch", "payroll/openings/1/", 403),
        (api(None), "get", "employees/", 401),
        (api(None), "put", f"employees/{card.pk}/", 401),
    ]
    wrong: list[str] = []
    for client, method, path, expected in cases:
        status = getattr(client, method)(f"{BASE}/{path}").status_code
        if status != expected:
            user = getattr(client.handler, "_force_user", None)
            wrong.append(f"{method.upper()} {path} [{user}]: {status} != {expected}")
    assert not wrong, "\n".join(wrong)


def test_card_history_and_external_switch_hide_payroll_without_payroll_view(
    manager: User, make_user: Callable[..., User]
) -> None:
    """Bordro özetleri (ek ödeme, kesinti, devir, pusula, mali müşavir işareti, ayın kartı
    izlemesi) Bordro bölümünün verisidir (plan §3.14, §5.6): "Bordro: Görür"ü kaldırılan kişi
    kartın geçmişinde onları görmez, kartı "mali müşavirde" işaretlerken yanıtta ERP kayıtları
    listelenmez. Kartın kendi kayıtları (belge, düzenleme) görünür; bordrosu olan hepsini görür."""
    parameter_set(manager)
    card = employee(manager)
    services.add_wage(
        manager, {"employee": card, "gross_monthly": D("45000"), "valid_from": date(2020, 1, 1)}
    )
    services.add_payroll_item(
        manager,
        {"employee": card, "year": 2026, "month": 11, "category": "BONUS", "amount": D("5000")},
    )
    services.set_opening_balance(
        manager, card, 2026, 11, tax_base=D("344250"), exemption_months=9, confirm_override=True
    )
    log_change(manager, card, AuditLog.Action.CUSTOM, {}, "Kasım 2026 bordrosu: kartı izler")
    document(manager, card)

    full = api(manager).get(f"{BASE}/employees/{card.pk}/history/").json()
    full_notes = [row["note"] for row in full]
    assert any(note.startswith("Ek ödeme eklendi:") for note in full_notes)
    assert any(note.startswith("Devir girildi:") for note in full_notes)
    assert "Kasım 2026 bordrosu: kartı izler" in full_notes

    viewer = override(make_user("yonetim"), PAYROLL.key, VIEW)
    client = api(viewer)
    assert client.get(f"{BASE}/payroll/items/", {"employee": card.pk}).status_code == 403
    shown = client.get(f"{BASE}/employees/{card.pk}/history/")
    assert shown.status_code == 200
    notes = [row["note"] for row in shown.json()]
    assert not any(" TL" in note or "bordrosu:" in note for note in notes), notes
    assert any(note.startswith("Belge eklendi:") for note in notes)
    assert len(notes) == len(full_notes) - 3

    switched = client.patch(
        f"{BASE}/employees/{card.pk}/", {"payroll_external": True}, format="json"
    )
    assert switched.status_code == 200
    assert "payroll_external_records" not in switched.json()
    assert "payroll_external_kept" not in switched.json()
    later = [row["note"] for row in client.get(f"{BASE}/employees/{card.pk}/history/").json()]
    assert not any("mali müşavirde" in note for note in later)
    assert any(
        "mali müşavirde" in row["note"]
        for row in api(manager).get(f"{BASE}/employees/{card.pk}/history/").json()
    )
