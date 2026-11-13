"""Canlıda istek başına veritabanı işlemi yoktur (`ATOMIC_REQUESTS` kapalı): satır kilitleyen her
servis kendi işlemini açmalıdır. Testler normalde bir işlemin içinde koştuğu için eksik işlem fark
edilmez (bkz. `production/tests/test_live_transactions.py`). Buradaki test, canlı gibi dış işlem
olmadan puantaj akışını uç noktalardan yürütür: günlük çalışma saati ayarı, saatli gün, aralık ve
ay onayı."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User
from apps.personnel import selectors
from apps.personnel.models import AttendanceEntry, AttendanceMonth, AttendanceStatus
from apps.personnel.tests.factories import employee

BASE = "/api/v1/personnel/attendance"
D = Decimal
S = AttendanceStatus


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.content[:500]
    return response.json()


@pytest.mark.django_db(transaction=True)
def test_attendance_flow_runs_without_a_surrounding_transaction(
    make_user: Callable[..., User],
) -> None:
    manager = make_user("yonetim", username="yonetim")
    client = APIClient()
    client.force_authenticate(manager)
    card = employee(manager)
    last = timezone.localdate().replace(day=1) - timedelta(days=1)  # bitmiş ay
    year, month = last.year, last.month
    first = last.replace(day=1)
    short, leave = [day for day in selectors.days_between(first, last) if day.weekday() != 6][:2]

    def post(path: str, body: dict[str, Any]) -> Any:
        return ok(client.post(f"{BASE}/{path}/", body, format="json"))

    def day(on: date, **values: Any) -> dict[str, Any]:
        return {"employee": card.pk, "date": on.isoformat(), "status": "WORKED", **values}

    def span(on: date, status: str, note: str = "") -> dict[str, Any]:
        on_day = on.isoformat()
        return {"employee": card.pk, "start": on_day, "end": on_day, "status": status, "note": note}

    # Ayar: günlük çalışma saati (ayar satırı kilitlenir).
    body = {"rest_weekdays": [6], "daily_hours": "9"}
    assert ok(client.patch(f"{BASE}/settings/", body, format="json"))["daily_hours"] == "9.00"
    # Gün: çalışılan saat ve yarım gün işareti (kart, ay ve gün kilitlenir; ay açılır).
    saved = post("days", day(short, worked_hours="4.5", short_day=True))
    assert (saved["code"], saved["worked_hours"], saved["short_day"]) == ("YG", "4.50", True)
    post("days", day(leave, worked_hours="8.5"))
    # Aralık: "Çalıştı" kalan günün saati korunur, izne çevrilen günün saati silinir.
    assert post("ranges", span(short, "WORKED", "Vardiya")) == {"updated": 1}
    assert post("ranges", span(leave, "ANNUAL_LEAVE")) == {"updated": 1}
    # Onay: değiştirilmemiş günler yazılır, ay o anki günlük çalışma saatini alır.
    record = ok(client.post(f"{BASE}/{year}/{month}/approve/"))
    assert record["status"] == AttendanceMonth.Status.APPROVED

    stored = AttendanceMonth.objects.get(year=year, month=month)
    assert (stored.status, stored.daily_hours) == (AttendanceMonth.Status.APPROVED, D("9"))
    entries = {entry.date: entry for entry in AttendanceEntry.objects.filter(employee=card)}
    assert len(entries) == (last - first).days + 1
    kept = entries[short]
    assert (kept.status, kept.worked_hours, kept.short_day, kept.note) == (
        S.WORKED,
        D("4.5"),
        True,
        "Vardiya",
    )
    assert (entries[leave].status, entries[leave].worked_hours) == (S.ANNUAL_LEAVE, None)
    grid = ok(client.get(f"{BASE}/{year}/{month}/"))
    assert (grid["status"], grid["daily_hours"]) == ("APPROVED", "9.00")
    totals = grid["rows"][0]["totals"]
    assert (totals["short_days"], totals["days"]["ANNUAL_LEAVE"]) == (1, 1)
    assert totals["full_days"] == totals["days"]["WORKED"] - 1
