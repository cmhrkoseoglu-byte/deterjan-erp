"""Sistem izleme (Faz 5, Adım 5.5): yedek durum dosyası, kontroller, uyarılar, KVKK temizliği."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.core import services as core_services
from apps.core.models import AuditLog, LoginLockout
from apps.core.roles import ADMIN, YONETIM
from apps.ops import selectors, services
from apps.ops.models import BackupRun, CheckState, Heartbeat
from apps.workflow.models import Notification

pytestmark = pytest.mark.django_db


def status_record(kind="backup", run_id="20261017T020000", status="ok", hours_ago=1, **extra):
    finished = timezone.now() - timedelta(hours=hours_ago)
    return {
        "kind": kind,
        "run_id": run_id,
        "source_run_id": run_id,
        "started_at": (finished - timedelta(minutes=2)).isoformat(),
        "finished_at": finished.isoformat(),
        "status": status,
        "message": "" if status == "ok" else "pg_dump başarısız",
        "database_bytes": 1000,
        "media_bytes": 200,
        "media_files": 3,
        "tables": 120,
        "rows": 5000,
        "offsite": "ok",
        "offsite_message": "",
        "mismatches": [],
        **extra,
    }


@pytest.fixture
def backups_enabled(settings, tmp_path):
    settings.OPS_BACKUP_CHECK_ENABLED = True
    settings.BACKUP_STATUS_DIR = str(tmp_path)
    settings.OPS_DISK_PATHS = [str(tmp_path)]
    return tmp_path


@pytest.fixture
def quiet_system(monkeypatch):
    """Disk, yük ve kuyruk kontrolleri test makinesinden bağımsız olsun."""
    monkeypatch.setattr(
        selectors, "check_disk", lambda: selectors.CheckResult("disk", "ok", "Disk")
    )
    monkeypatch.setattr(selectors, "check_cpu", lambda: selectors.CheckResult("cpu", "ok", "Yük"))
    monkeypatch.setattr(
        selectors, "check_queue", lambda: selectors.CheckResult("queue", "ok", "Kuyruk")
    )


def by_check(results):
    return {r.check: r for r in results}


def test_ingest_status_files_is_idempotent(backups_enabled):
    (backups_enabled / "latest-backup.json").write_text(json.dumps(status_record()))
    (backups_enabled / "latest-restore-test.json").write_text(
        json.dumps(
            status_record("restore_test", "20261018T040000", source_run_id="20261017T020000")
        )
    )

    services.ingest_backup_status()
    services.ingest_backup_status()

    assert BackupRun.objects.count() == 2
    test = BackupRun.objects.get(kind="restore_test")
    assert test.source_run_id == "20261017T020000"
    assert test.rows == 5000


def test_invalid_status_record_is_skipped(backups_enabled):
    (backups_enabled / "latest-backup.json").write_text('{"kind": "backup"}')
    (backups_enabled / "latest-restore-test.json").write_text("bozuk")
    assert services.ingest_backup_status() == []


def test_missing_status_dir_does_nothing(settings):
    settings.BACKUP_STATUS_DIR = "/olmayan/klasor"
    assert services.ingest_backup_status() == []


def test_backup_checks_ok(backups_enabled):
    services.import_status_record(status_record())
    services.import_status_record(status_record("restore_test", "r1", hours_ago=2))
    results = by_check(selectors.evaluate_checks())
    assert results["backup"].status == "ok"
    assert results["restore_test"].status == "ok"


@pytest.mark.parametrize(
    ("record", "title"),
    [
        (status_record(status="failed"), "Gece yedeği alınamadı"),
        (status_record(hours_ago=30), "Yedek gecikti"),
        (
            status_record(offsite="failed", offsite_message="NAS bağlı değil"),
            "Yedek ayrı konuma kopyalanamadı",
        ),
    ],
)
def test_backup_check_errors(backups_enabled, record, title):
    services.import_status_record(record)
    result = selectors.check_backup(timezone.now())
    assert result.status == "error"
    assert result.title == title


def test_no_backup_is_error_when_enabled(backups_enabled):
    assert selectors.check_backup(timezone.now()).status == "error"


def test_backup_check_disabled_in_dev(settings):
    settings.OPS_BACKUP_CHECK_ENABLED = False
    assert selectors.check_backup(timezone.now()).status == "unknown"


def test_restore_test_mismatch_is_error(backups_enabled):
    services.import_status_record(status_record())
    services.import_status_record(
        status_record(
            "restore_test",
            "r1",
            status="failed",
            mismatches=[{"table": "inventory_lot", "expected": 10, "actual": 9}],
        )
    )
    result = selectors.check_restore_test(timezone.now())
    assert result.status == "error"
    assert "inventory_lot" in result.detail


def test_restore_test_waits_for_first_week(backups_enabled):
    services.import_status_record(status_record(hours_ago=24))
    assert selectors.check_restore_test(timezone.now()).status == "unknown"
    services.import_status_record(status_record(run_id="old", hours_ago=24 * 9))
    assert selectors.check_restore_test(timezone.now()).status == "error"


def test_disk_alert_threshold(settings, tmp_path, monkeypatch):
    settings.OPS_DISK_PATHS = [str(tmp_path)]
    settings.OPS_DISK_ALERT_PCT = 85
    monkeypatch.setattr(
        selectors.shutil, "disk_usage", lambda path: SimpleNamespace(total=100, used=90, free=10)
    )
    result = selectors.check_disk()
    assert result.status == "error"
    assert "%90" in result.title


def test_cpu_and_queue_checks(settings, monkeypatch):
    monkeypatch.setattr(selectors.os, "getloadavg", lambda: (9.0, 9.0, 9.0))
    monkeypatch.setattr(selectors.os, "cpu_count", lambda: 4)
    assert selectors.check_cpu().status == "error"
    monkeypatch.setattr(selectors, "queue_length", lambda: 150)
    assert selectors.check_queue().status == "error"
    monkeypatch.setattr(selectors, "queue_length", lambda: 3)
    assert selectors.check_queue().status == "ok"


def test_alert_once_repeat_after_interval_and_recover(
    backups_enabled, quiet_system, make_user, settings, django_capture_on_commit_callbacks
):
    admin = make_user(ADMIN)
    services.import_status_record(status_record(status="failed"))
    now = timezone.now()

    with django_capture_on_commit_callbacks(execute=True):
        services.run_checks(now)
        services.run_checks(now + timedelta(minutes=5))
    assert Notification.objects.filter(rule_code="ops_alert", recipient=admin).count() == 1
    note = Notification.objects.get(rule_code="ops_alert")
    assert note.title == "Sistem uyarısı: Gece yedeği alınamadı"

    with django_capture_on_commit_callbacks(execute=True):
        services.run_checks(now + timedelta(minutes=61))
    assert Notification.objects.filter(rule_code="ops_alert").count() == 2

    services.import_status_record(status_record(run_id="20261018T020000", hours_ago=0))
    with django_capture_on_commit_callbacks(execute=True):
        services.run_checks(now + timedelta(minutes=65))
    assert Notification.objects.filter(rule_code="ops_recovered", recipient=admin).count() == 1
    assert CheckState.objects.get(code="backup").failing is False


def test_unknown_checks_do_not_alert(settings, quiet_system, django_capture_on_commit_callbacks):
    settings.OPS_BACKUP_CHECK_ENABLED = False
    with django_capture_on_commit_callbacks(execute=True):
        services.run_checks()
    assert not Notification.objects.exists()
    assert not CheckState.objects.filter(code="backup").exists()


def test_heartbeat_and_celery_check():
    now = timezone.now()
    assert selectors.check_celery(now).status == "unknown"
    services.record_heartbeat()
    assert selectors.check_celery(now).status == "ok"
    Heartbeat.objects.update(beat_at=now - timedelta(minutes=5))
    assert selectors.check_celery(now).status == "error"


def test_status_endpoint_admin_only(client_for, backups_enabled):
    services.import_status_record(status_record())
    response = client_for(ADMIN).get("/api/v1/ops/status/")
    assert response.status_code == 200
    body = response.json()
    assert {c["check"] for c in body["checks"]} == {
        "backup",
        "restore_test",
        "disk",
        "cpu",
        "queue",
        "celery",
    }
    assert body["runs"][0]["run_id"] == "20261017T020000"
    assert client_for(YONETIM).get("/api/v1/ops/status/").status_code == 403


def test_ops_health_endpoint(api_client, backups_enabled):
    services.record_heartbeat()
    response = api_client.get("/api/v1/ops/health/")
    assert response.status_code == 503  # yedek yok
    assert response.json()["backup"] == "error"

    services.import_status_record(status_record())
    response = api_client.get("/api/v1/ops/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_client_error_is_logged(client_for, caplog):
    response = client_for(ADMIN).post(
        "/api/v1/ops/client-errors/",
        {"message": "TypeError: x is undefined", "url": "/depo"},
        format="json",
    )
    assert response.status_code == 204
    assert "TypeError" in caplog.text


def test_client_error_requires_login(api_client):
    assert api_client.post("/api/v1/ops/client-errors/", {"message": "x"}).status_code == 401


# --- KVKK saklama süreleri ----------------------------------------------------------------------


def test_purge_expired_personal_data(make_user, settings):
    settings.AUDIT_IP_RETENTION_DAYS = 365
    user = make_user()
    old = AuditLog.objects.create(action=AuditLog.Action.LOGIN, ip_address="10.0.0.1", actor=user)
    recent = AuditLog.objects.create(
        action=AuditLog.Action.LOGIN, ip_address="10.0.0.2", actor=user
    )
    other = AuditLog.objects.create(action=AuditLog.Action.UPDATE, ip_address="10.0.0.3")
    AuditLog.objects.filter(pk__in=[old.pk, other.pk]).update(
        timestamp=timezone.now() - timedelta(days=400)
    )
    LoginLockout.objects.create(username="eski", failed_count=2)
    LoginLockout.objects.filter(username="eski").update(
        updated_at=timezone.now() - timedelta(days=2)
    )

    result = core_services.purge_expired_personal_data()

    assert result["audit_ips"] == 1
    assert result["lockouts"] == 1
    old.refresh_from_db()
    recent.refresh_from_db()
    other.refresh_from_db()
    assert old.ip_address is None
    assert recent.ip_address == "10.0.0.2"
    assert other.ip_address == "10.0.0.3"  # yalnızca giriş/çıkış kayıtları
