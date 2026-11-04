from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from apps.personnel import selectors
from apps.personnel.models import (
    AttendanceEntry,
    AttendanceMonth,
    Employee,
    EmployeeWage,
    PayrollItem,
    PayrollOpeningBalance,
    PayrollParameterSet,
    PayrollRun,
    PublicHoliday,
)

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_personnel_demo(roles: None) -> None:
    call_command("create_demo_users", stdout=StringIO())
    call_command("seed_personnel_demo", stdout=StringIO())
    call_command("seed_personnel_demo", stdout=StringIO())  # tekrar çalıştırmak güvenli
    assert Employee.objects.count() == 14
    assert Employee.objects.filter(user__isnull=False).count() == 8
    assert Employee.objects.get(user__username="depo").department == "Depo"
    former = Employee.objects.get(employee_no="S-0010")
    assert not former.is_active and former.termination_date is not None
    # Özlük bilgisi ve belgesi dolu örnek kart; TC kimlik no demo verisine girilmez.
    profile = Employee.objects.get(employee_no="S-0012")
    assert profile.school and profile.graduation_year and profile.national_id == ""
    kinds = sorted(profile.documents.values_list("kind", flat=True))
    assert kinds == ["CONTRACT", "DIPLOMA", "ID_COPY", "PAYROLL", "PAYROLL"]
    assert not Employee.objects.exclude(national_id="").exists()
    # Sabit tatiller ve geçen ayın örnek puantajı (ay açık kalır).
    today = timezone.localdate()
    assert PublicHoliday.objects.filter(is_active=True, date__year=today.year).count() == 8
    last = today.replace(day=1) - timedelta(days=1)
    entries = AttendanceEntry.objects.filter(date__year=last.year, date__month=last.month)
    assert set(entries.values_list("status", flat=True)) == {
        "ANNUAL_LEAVE",
        "SICK_LEAVE",
        "WORKED",
        "ABSENT",
    }
    assert entries.filter(overtime_hours__gt=0).count() == 3
    assert not AttendanceMonth.objects.filter(status="APPROVED").exists()
    # Örnek ücretler: her karta bir ücret, bir kişiye geçen aydan zam; tekrar çalıştırmak eklemez.
    assert EmployeeWage.objects.values("employee").distinct().count() == 14
    assert EmployeeWage.objects.filter(employee__employee_no="S-0012").count() in (1, 2)
    assert EmployeeWage.objects.count() == 14 + (
        EmployeeWage.objects.filter(employee__employee_no="S-0012").count() - 1
    )
    # Ön bordro örneği (geçen ay başlangıç ayı ya da sonrasıysa); bordro onaylanmaz.
    assert not PayrollRun.objects.exists()
    if not selectors.net_available(last.year, last.month):
        assert not PayrollItem.objects.exists() and not PayrollOpeningBalance.objects.exists()
        return
    if last.year == 2026:
        sets = PayrollParameterSet.objects.filter(is_active=True, valid_from__year=2026)
        assert sets.count() == 1
    items = PayrollItem.objects.filter(year=last.year, month=last.month, is_active=True)
    assert sorted(items.values_list("category", flat=True)) == ["ADVANCE", "MEAL", "PREMIUM"]
    start = selectors.chain_start(last.year)
    if start and start > 1:
        first, end = selectors.month_bounds(last.year, start)
        expected = [
            person
            for person in selectors.employees_between(first, end)
            if selectors.months_employed_before(person, last.year, start)
        ]
        openings = PayrollOpeningBalance.objects.filter(year=last.year, month=start)
        assert openings.count() == len(expected) > 0
        rows = selectors.payroll_month(last.year, last.month).rows
        assert not any(selectors.OPENING_MISSING in row.warnings for row in rows)


@override_settings(DEBUG=False, TRAINING_MODE=False)
def test_seed_personnel_demo_refuses_live(roles: None) -> None:
    with pytest.raises(CommandError):
        call_command("seed_personnel_demo", stdout=StringIO())
