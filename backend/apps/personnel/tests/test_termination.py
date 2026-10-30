"""Ayrılış ve puantaj: çıkış tarihinden sonraki kayıtlı günler (docs/DECISIONS.md "Puantajda
çıkıştan sonraki günler")."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import connection, models
from django.db.models import F, QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.personnel import selectors, services
from apps.personnel.models import AttendanceEntry, AttendanceMonth, AttendanceStatus, Employee
from apps.personnel.tests.factories import employee

pytestmark = pytest.mark.django_db
S = AttendanceStatus
OTHER_ROLES = ["planlama", "depo", "uretim", "laboratuvar", "dolum", "sevkiyat", "satin_alma"]
EXIT = date(2026, 9, 18)  # cuma
REMOVED_NOTE = "Çıkış tarihinden sonraki puantaj günü kaldırıldı"


@pytest.fixture
def manager(make_user: Callable[..., User]) -> User:
    return make_user("yonetim", username="yonetim")


@pytest.fixture
def api(manager: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(manager)
    return client


def assert_no_attendance_after_exit() -> None:
    """Değişmez: hiçbir kişinin çıkış tarihinden sonra kayıtlı puantaj günü yoktur."""
    stale = AttendanceEntry.objects.filter(
        employee__termination_date__isnull=False, date__gt=F("employee__termination_date")
    )
    assert not stale.exists(), list(stale.values_list("employee__full_name", "date"))


def _error(call: Callable[[], Any]) -> BusinessRuleError:
    with pytest.raises(BusinessRuleError) as exc:
        call()
    return exc.value


def _dates(card: Employee) -> list[date]:
    return sorted(AttendanceEntry.objects.filter(employee=card).values_list("date", flat=True))


def _logs(model: type[models.Model], **filters: Any) -> QuerySet[AuditLog]:
    """Bir modelin denetim kayıtları (kimlikler modeller arasında çakışabilir)."""
    content_type = ContentType.objects.get_for_model(model)
    return AuditLog.objects.filter(content_type=content_type, **filters)


def _previous_month() -> tuple[int, int]:
    """Bitmiş bir ay (onay ancak ay bitince verilir)."""
    last = timezone.localdate().replace(day=1) - timedelta(days=1)
    return last.year, last.month


# --- açık aylar ----------------------------------------------------------------------------------


def test_exit_removes_later_days_after_confirmation(manager: User) -> None:
    card = employee(manager, hire_date=date(2020, 1, 1))
    services.set_attendance_day(manager, card, date(2026, 9, 17), status=S.SICK_LEAVE)
    services.set_attendance_day(
        manager, card, EXIT, status=S.WORKED, overtime_hours=Decimal(2), note="Son gün"
    )
    services.set_attendance_range(
        manager,
        employee=card,
        start=date(2026, 9, 21),
        end=date(2026, 9, 23),
        status=S.UNPAID_LEAVE,
    )
    services.set_attendance_day(
        manager,
        card,
        date(2026, 9, 24),
        status=S.WORKED,
        overtime_hours=Decimal("2.5"),
        note="Sayım",
    )
    services.set_attendance_range(
        manager,
        employee=card,
        start=date(2026, 10, 5),
        end=date(2026, 10, 6),
        status=S.ANNUAL_LEAVE,
    )
    days = "Eylül 2026: 21–23.09 Üİ, 24.09 Ç (2,5 sa FM, notlu); Ekim 2026: 05–06.10 Yİ"
    removed_id = AttendanceEntry.objects.get(employee=card, date=date(2026, 9, 21)).pk

    # Onay olmadan ayrılış kaydedilmez: günler listelenir, hiçbir şey değişmez.
    error = _error(lambda: services.terminate_employee(manager, card, EXIT))
    assert error.code == "attendance_after_exit"
    assert error.message == (
        f"Çıkış tarihinden (18.09.2026) sonra puantajda kayıtlı 6 gün var: {days}. "
        "Kaydederseniz bu günler puantajdan kaldırılır; kişi yeniden işe başlatılsa da geri gelmez."
    )
    card.refresh_from_db()
    assert card.is_active and len(_dates(card)) == 8

    left = services.terminate_employee(manager, card, EXIT, remove_attendance=True)
    assert not left.is_active and left.termination_date == EXIT
    assert _dates(card) == [date(2026, 9, 17), EXIT]  # çıkış günü son iş günüdür, kalır
    assert_no_attendance_after_exit()

    # Kartın geçmişi: ayrılış notunda tarihli özet (tek satır).
    log = _logs(Employee, object_id=card.pk).latest("timestamp", "id")
    assert log.note == f"İşten ayrıldı · çıkıştan sonraki 6 puantaj günü kaldırıldı: {days}"
    assert log.changes["termination_date"] == [None, "2026-09-18"]

    # Ayın denetim kaydı: kaldırılan her gün bütün alanlarıyla; kimlik günün kendi geçmişine bağlar.
    removed = list(_logs(AttendanceMonth, note__startswith=REMOVED_NOTE).order_by("id"))
    assert len(removed) == 6
    assert removed[0].note == f"{REMOVED_NOTE}: Ayşe Demir 21.09.2026"
    before, after = removed[0].changes["entry"]
    assert after is None
    assert _logs(AttendanceEntry, object_id=removed_id, action=AuditLog.Action.CREATE).exists()
    assert before == {
        "id": removed_id,
        "month": AttendanceMonth.objects.get(year=2026, month=9).pk,
        "employee": card.pk,
        "date": "2026-09-21",
        "status": "UNPAID_LEAVE",
        "overtime_hours": "0.00",
        "note": "",
    }
    overtime_day = removed[3].changes["entry"][0]
    assert (overtime_day["date"], overtime_day["overtime_hours"], overtime_day["note"]) == (
        "2026-09-24",
        "2.50",
        "Sayım",
    )
    assert removed[-1].object_id == AttendanceMonth.objects.get(year=2026, month=10).pk

    # Tablo ve toplamlar: çıkıştan sonraki günler boş, düzenlenemez ve sayılmaz.
    grid = selectors.attendance_grid(2026, 9)
    row = next(row for row in grid.rows if row.employee.pk == card.pk)
    later = [cell for cell in row.cells if cell.date > EXIT]
    assert all(not cell.status and not cell.explicit and not cell.editable for cell in later)
    assert row.totals.days[S.UNPAID_LEAVE] == 0 and row.totals.days[S.SICK_LEAVE] == 1
    assert row.totals.overtime_total == Decimal(2)
    october = selectors.attendance_grid(2026, 10)
    assert card.pk not in [row.employee.pk for row in october.rows]


def test_exit_without_later_days_needs_no_confirmation(manager: User) -> None:
    card = employee(manager)
    services.set_attendance_day(manager, card, EXIT, status=S.ANNUAL_LEAVE)
    services.terminate_employee(manager, card, EXIT)
    assert _dates(card) == [EXIT]
    assert _logs(Employee, object_id=card.pk).latest("timestamp", "id").note == "İşten ayrıldı"
    assert not _logs(AttendanceMonth, note__startswith=REMOVED_NOTE).exists()


def test_future_exit_removes_leave_entered_ahead(manager: User) -> None:
    """İhbar süresi: ileri tarihli çıkışta da sonraki günler kaydederken kaldırılır."""
    today = timezone.localdate()
    card = employee(manager)
    kept, dropped = today + timedelta(days=5), today + timedelta(days=15)
    services.set_attendance_day(manager, card, kept, status=S.ANNUAL_LEAVE)
    services.set_attendance_day(manager, card, dropped, status=S.ANNUAL_LEAVE)
    services.terminate_employee(manager, card, today + timedelta(days=10), remove_attendance=True)
    assert _dates(card) == [kept]
    assert_no_attendance_after_exit()


def test_corrected_exit_date_and_reinstate(manager: User) -> None:
    """Tarih düzeltme: Yeniden işe başladı + İşten ayrıldı. Kaldırılan günler geri gelmez."""
    card = employee(manager, hire_date=date(2020, 1, 1))
    services.set_attendance_range(
        manager,
        employee=card,
        start=date(2026, 9, 14),
        end=date(2026, 9, 25),
        status=S.UNPAID_LEAVE,
    )
    services.terminate_employee(
        manager, card, date(2026, 9, 22), note=" İstifa ", remove_attendance=True
    )
    log = _logs(Employee, object_id=card.pk).latest("timestamp", "id")
    assert log.note == (
        "İstifa · çıkıştan sonraki 3 puantaj günü kaldırıldı: Eylül 2026: 23–25.09 Üİ"
    )
    month_logs = _logs(AttendanceMonth).count()

    back = services.reinstate_employee(manager, card)
    assert len(_dates(card)) == 9  # 14–22.09 kaldı; 23–25.09 geri gelmez
    assert _logs(AttendanceMonth).count() == month_logs

    services.terminate_employee(manager, back, date(2026, 9, 16), remove_attendance=True)
    assert _dates(card) == [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)]
    assert_no_attendance_after_exit()


# --- onaylı aylar --------------------------------------------------------------------------------


def test_exit_into_approved_month_waits_for_reopen(manager: User) -> None:
    year, month = _previous_month()
    exit_day = date(year, month, 20)
    card = employee(manager, hire_date=date(2020, 1, 1))
    services.approve_attendance_month(manager, year, month)
    stored, audit = len(_dates(card)), AuditLog.objects.count()

    # Onaylı ay değişmez: ayrılış kaydedilmez, hiçbir şey yazılmaz (onay verilse de).
    error = _error(
        lambda: services.terminate_employee(manager, card, exit_day, remove_attendance=True)
    )
    assert error.code == "approved_attendance_after_exit"
    last = selectors.month_bounds(year, month)[1]
    assert f"{selectors.month_label(year, month)} (21–{last:%d.%m})" in error.message
    assert "önce bu ayı Puantaj'da gerekçeyle yeniden açın" in error.message
    card.refresh_from_db()
    assert card.is_active and len(_dates(card)) == stored
    assert AuditLog.objects.count() == audit

    # Ay yeniden açılınca ayrılış (onayla) kaydedilir; yeniden onayda çıkıştan sonrası boştur.
    record = AttendanceMonth.objects.get(year=year, month=month)
    services.reopen_attendance_month(manager, record, "Geç bildirilen ayrılış")
    code = _error(lambda: services.terminate_employee(manager, card, exit_day)).code
    assert code == "attendance_after_exit"
    services.terminate_employee(manager, card, exit_day, remove_attendance=True)
    services.approve_attendance_month(manager, year, month)
    grid = selectors.attendance_grid(year, month)
    cells = next(row.cells for row in grid.rows if row.employee.pk == card.pk)
    assert all(cell.explicit for cell in cells if cell.date <= exit_day)
    assert not any(cell.status or cell.explicit for cell in cells if cell.date > exit_day)
    assert_no_attendance_after_exit()


def test_exit_message_lists_every_approved_month(manager: User) -> None:
    year, month = _previous_month()
    earlier = date(year, month, 1) - timedelta(days=1)
    card = employee(manager, hire_date=date(2020, 1, 1))
    services.approve_attendance_month(manager, earlier.year, earlier.month)
    services.approve_attendance_month(manager, year, month)
    error = _error(
        lambda: services.terminate_employee(
            manager, card, earlier.replace(day=20), remove_attendance=True
        )
    )
    assert selectors.month_label(earlier.year, earlier.month) in error.message
    assert selectors.month_label(year, month) in error.message
    assert "önce bu ayları" in error.message and "ayları yeniden onaylayıp" in error.message
    assert isinstance(error, services.ApprovedAttendanceAfterExit)
    assert error.months == [f"{earlier:%Y-%m}", f"{year}-{month:02d}"]


def test_exit_moved_later_needs_reopen_to_fill_approved_month(manager: User) -> None:
    """Çıkış onaylı ay içinde ileri alınırsa iki tarih arası o ayda boş kalır; ay yeniden açılıp
    onaylanınca yazılır (kılavuzdaki düzeltme adımı)."""
    year, month = _previous_month()
    card = employee(manager, hire_date=date(2020, 1, 1))
    services.terminate_employee(manager, card, date(year, month, 16))
    services.approve_attendance_month(manager, year, month)
    back = services.reinstate_employee(manager, card)
    services.terminate_employee(manager, back, date(year, month, 22))  # sonrası kayıtsız: sorulmaz

    def stored(day: int) -> bool:
        return AttendanceEntry.objects.filter(employee=card, date=date(year, month, day)).exists()

    assert stored(16) and not stored(17) and not stored(22)
    record = AttendanceMonth.objects.get(year=year, month=month)
    services.reopen_attendance_month(manager, record, "Çıkış tarihi düzeltildi")
    services.approve_attendance_month(manager, year, month)
    assert stored(17) and stored(22) and not stored(23)
    assert_no_attendance_after_exit()


# --- gün özeti -----------------------------------------------------------------------------------


def test_day_summary_splits_runs_on_status_overtime_note_and_gaps() -> None:
    def day(
        on: date, status: str, hours: str = "0", note: str = ""
    ) -> AttendanceEntry:  # kaydedilmemiş gün yeter
        return AttendanceEntry(date=on, status=status, overtime_hours=Decimal(hours), note=note)

    entries = [  # ters sırada: özet tarihe göre sıralar
        day(date(2026, 10, 1), S.ANNUAL_LEAVE),
        day(date(2026, 9, 30), S.WORKED, "2", "Sayım"),
        day(date(2026, 9, 29), S.WORKED, "2"),
        day(date(2026, 9, 28), S.WORKED, "2"),
        day(date(2026, 9, 27), S.WORKED),  # 24 ile boşluk, 28 ile yalnız fazla mesai farkı
        day(date(2026, 9, 24), S.WORKED),
        day(date(2026, 9, 23), S.WEEKLY_REST),
        day(date(2026, 9, 22), S.WORKED),
        day(date(2026, 9, 21), S.WORKED),
    ]
    assert selectors.summarize_days(entries) == (
        "Eylül 2026: 21–22.09 Ç, 23.09 HT, 24.09 Ç, 27.09 Ç, 28–29.09 Ç (günde 2 sa FM), "
        "30.09 Ç (2 sa FM, notlu); Ekim 2026: 01.10 Yİ"
    )
    assert selectors.summarize_days([]) == ""
    assert selectors.format_hours(Decimal("2.50")) == "2,5"
    assert selectors.format_hours(Decimal("10.00")) == "10"


# --- eşzamanlılık ve kilit sırası -----------------------------------------------------------------


def test_stale_card_cannot_write_after_exit(manager: User) -> None:
    """Ayrılıştan önce okunmuş kart nesnesiyle de çıkıştan sonraya gün yazılamaz."""
    card = employee(manager, hire_date=date(2020, 1, 1))
    stale = Employee.objects.get(pk=card.pk)
    services.terminate_employee(manager, card, EXIT)
    error = _error(
        lambda: services.set_attendance_day(
            manager, stale, date(2026, 9, 21), status=S.ANNUAL_LEAVE
        )
    )
    assert error.code == "not_employed"
    changed = services.set_attendance_range(
        manager,
        employee=stale,
        start=date(2026, 9, 21),
        end=date(2026, 9, 25),
        status=S.UNPAID_LEAVE,
    )
    assert changed == 0 and _dates(card) == []


def _first_lock(call: Callable[[], Any]) -> str:
    with CaptureQueriesContext(connection) as queries:
        call()
    return next(query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"])


def test_writers_lock_cards_before_months(manager: User) -> None:
    """Kilit sırası: kartlar aylardan önce (ayrılış da önce kartı kilitler)."""
    year, month = _previous_month()
    card = employee(manager)
    day = date(year, month, 5)
    calls = [
        lambda: services.set_attendance_day(manager, card, day, status=S.ANNUAL_LEAVE),
        lambda: services.set_attendance_range(manager, start=day, end=day, status=S.UNPAID_LEAVE),
        lambda: services.approve_attendance_month(manager, year, month),
    ]
    for call in calls:
        assert 'FROM "personnel_employee"' in _first_lock(call)
    leaver = employee(manager, full_name="Can Kaya")  # onaydan sonra açıldı: kayıtlı günü yok
    assert 'FROM "personnel_employee"' in _first_lock(
        lambda: services.terminate_employee(manager, leaver, EXIT)
    )


def test_approval_refuses_card_that_joined_after_the_lock(
    manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kilitten sonra tabloya giren kart (ör. o sırada yeniden işe başlatılan) için varsayılan
    gün yazılmaz: onay geri alınır, yeniden onaylanınca kart da kilitlenir."""
    year, month = _previous_month()
    first = date(year, month, 1)
    employee(manager)
    returning = employee(manager, full_name="Can Kaya", hire_date=date(2020, 1, 1))
    services.terminate_employee(manager, returning, first - timedelta(days=1))
    real_grid = selectors.attendance_grid

    def grid_after_concurrent_reinstate(*args: Any, **kwargs: Any) -> selectors.AttendanceGrid:
        Employee.objects.filter(pk=returning.pk).update(is_active=True, termination_date=None)
        return real_grid(*args, **kwargs)

    monkeypatch.setattr(selectors, "attendance_grid", grid_after_concurrent_reinstate)
    code = _error(lambda: services.approve_attendance_month(manager, year, month)).code
    assert code == "attendance_cards_changed"
    assert not Employee.objects.get(pk=returning.pk).is_active  # benzetilen değişiklik geri alındı
    # Öteki işlemin yeniden başlatması gerçekte kaydedilmiştir: yeniden onayda kart kilitlenir
    # ve bütün ayın varsayılan günleri yazılır.
    monkeypatch.setattr(selectors, "attendance_grid", real_grid)
    services.reinstate_employee(manager, returning)
    record = services.approve_attendance_month(manager, year, month)
    assert record.status == AttendanceMonth.Status.APPROVED
    last = selectors.month_bounds(year, month)[1]
    assert _dates(returning) == selectors.days_between(first, last)


# --- yetki ve API --------------------------------------------------------------------------------


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_only_management_and_admin_record_exits(
    make_user: Callable[..., User], manager: User, role: str
) -> None:
    card = employee(manager)
    other = make_user(role)
    with pytest.raises(PermissionDenied):
        services.terminate_employee(other, card, EXIT)
    left = services.terminate_employee(manager, card, EXIT)
    with pytest.raises(PermissionDenied):
        services.reinstate_employee(other, left)
    assert services.reinstate_employee(make_user("admin"), left).is_active


def test_api_asks_before_removing_days(api: APIClient, manager: User) -> None:
    card = employee(manager, hire_date=date(2020, 1, 1))
    services.set_attendance_day(manager, card, date(2026, 9, 21), status=S.ANNUAL_LEAVE)
    url = f"/api/v1/personnel/employees/{card.pk}/terminate/"
    response = api.post(url, {"termination_date": "2026-09-18"}, format="json")
    assert response.status_code == 400
    assert response.json()["code"] == "attendance_after_exit"
    assert "Eylül 2026: 21.09 Yİ" in response.json()["detail"]
    assert Employee.objects.get(pk=card.pk).is_active

    body = {"termination_date": "2026-09-18", "remove_attendance": True}
    response = api.post(url, body, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["termination_date"] == "2026-09-18"
    assert _dates(card) == []


def test_api_refuses_exit_into_approved_month(api: APIClient, manager: User) -> None:
    """Yanıt yalnızca onaylı ayları verir ("2026-09"); açık aydaki günler listeye girmez."""
    year, month = _previous_month()
    card = employee(manager, hire_date=date(2020, 1, 1))
    services.approve_attendance_month(manager, year, month)
    this_month = timezone.localdate().replace(day=1)
    services.set_attendance_day(manager, card, this_month, status=S.ANNUAL_LEAVE)  # açık ay
    body = {"termination_date": str(date(year, month, 20)), "remove_attendance": True}
    response = api.post(f"/api/v1/personnel/employees/{card.pk}/terminate/", body, format="json")
    assert response.status_code == 400
    assert response.json()["code"] == "approved_attendance_after_exit"
    assert response.json()["months"] == [f"{year}-{month:02d}"]
    assert selectors.month_label(year, month) in response.json()["detail"]
    assert Employee.objects.get(pk=card.pk).is_active
