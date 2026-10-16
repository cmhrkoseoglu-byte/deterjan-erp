"""Rapor işleri: durum makinesi, hata yolu, dosya saklama süresi."""

import os
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.roles import DEPO, YONETIM
from apps.inventory.tests.factories import stocked_lot
from apps.reporting import services, state
from apps.reporting.models import ReportJob
from apps.reporting.reports import REPORTS
from apps.workflow.models import Notification

pytestmark = pytest.mark.django_db
S = ReportJob.Status


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (S.QUEUED, S.RUNNING),
        (S.QUEUED, S.FAILED),
        (S.RUNNING, S.DONE),
        (S.RUNNING, S.FAILED),
        (S.DONE, S.EXPIRED),
    ],
)
def test_allowed_transitions(current, new):
    assert state.can_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"), [(S.QUEUED, S.DONE), (S.EXPIRED, S.DONE), (S.FAILED, S.RUNNING)]
)
def test_forbidden_transitions(current, new):
    assert not state.can_transition(current, new)


def test_forbidden_transition_raises(make_user):
    job = services.create_job(make_user(DEPO), REPORTS["stock-status"], {}, "xlsx")
    with pytest.raises(BusinessRuleError, match="invalid_transition"):
        services._transition(job, S.DONE)


def test_export_rejects_role_without_access(make_user):
    with pytest.raises(BusinessRuleError, match="report_forbidden"):
        services.export_report(make_user(DEPO), REPORTS["quality"], {}, "xlsx")


def test_run_job_and_expire(make_user, django_capture_on_commit_callbacks):
    stocked_lot("10")
    user = make_user(DEPO)
    with django_capture_on_commit_callbacks(execute=True):
        job = services.create_job(user, REPORTS["stock-status"], {}, "pdf")
    job.refresh_from_db()
    assert job.status == S.DONE and job.file and job.file_name.endswith(".pdf")
    assert job.expires_at > timezone.now() + timedelta(days=6)
    # Tekrar çalıştırmak bir şey değiştirmez.
    assert services.run_job(job.pk).status == S.DONE

    # Sabah kontrolü: süresi dolan dosya silinir, kayıt kalır.
    path = job.file.path
    ReportJob.objects.filter(pk=job.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    with django_capture_on_commit_callbacks(execute=True):
        events.publish(ev.DAILY_CHECK, {"date": timezone.localdate().isoformat()})
    job.refresh_from_db()
    assert job.status == S.EXPIRED and not job.file
    assert not os.path.exists(path)


def test_failed_job_notifies_requester(make_user, django_capture_on_commit_callbacks):
    user = make_user(DEPO)
    with django_capture_on_commit_callbacks(execute=True):
        job = services.create_job(user, REPORTS["stock-status"], {}, "xlsx")
        ReportJob.objects.filter(pk=job.pk).update(report_code="missing")
    job.refresh_from_db()
    assert job.status == S.FAILED and job.error == "Böyle bir rapor yok."
    note = Notification.objects.get(recipient=user, rule_code="report_failed")
    assert note.level == "WARNING"


def test_job_fails_when_requester_lost_access(make_user, django_capture_on_commit_callbacks):
    user = make_user(YONETIM)
    with django_capture_on_commit_callbacks(execute=True):
        job = services.create_job(user, REPORTS["task-durations"], {}, "xlsx")
        user.groups.clear()
    job.refresh_from_db()
    assert job.status == S.FAILED
