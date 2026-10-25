from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.personnel.models import Employee

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


@override_settings(DEBUG=False, TRAINING_MODE=False)
def test_seed_personnel_demo_refuses_live(roles: None) -> None:
    with pytest.raises(CommandError):
        call_command("seed_personnel_demo", stdout=StringIO())
