"""Kodlama sistematiğinden önceki kod değişikliklerini eski kod geçmişine yükleme
(`backfill_code_history`)."""

import io

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from apps.core.coding import registry, selectors, services
from apps.core.exceptions import BusinessRuleError
from apps.core.management.commands.backfill_code_history import NOTE
from apps.core.models import AuditLog, CodeHistory
from apps.core.roles import ADMIN
from apps.core.services import save_with_audit
from apps.core.tests.testapp.models import Widget

pytestmark = pytest.mark.django_db

WIDGET = "core_testapp.widget"


@pytest.fixture
def admin(make_user):
    return make_user(ADMIN)


def item() -> registry.CodeType:
    return registry.get_code_type(WIDGET)


def rename(actor, widget, code):
    """Sistematikten önceki kod değişikliği: yalnızca denetim günlüğüne yazılırdı."""
    widget.code = code
    return save_with_audit(widget, actor)


def code_changes(widget) -> list[AuditLog]:
    return list(
        AuditLog.objects.filter(
            content_type=ContentType.objects.get_for_model(Widget),
            object_id=widget.pk,
            action=AuditLog.Action.UPDATE,
        ).order_by("timestamp", "id")
    )


def backfill(*args: str) -> str:
    out = io.StringIO()
    call_command("backfill_code_history", *args, stdout=out)
    return out.getvalue()


def summaries() -> int:
    return AuditLog.objects.filter(
        action=AuditLog.Action.CUSTOM, note__contains="backfill_code_history"
    ).count()


def test_backfill_writes_former_codes_from_audit_log(admin):
    widget = save_with_audit(Widget(name="a", code="ESKI-1"), admin)
    rename(admin, widget, "ESKI-2")
    rename(admin, widget, "WDG-0001")
    untouched = save_with_audit(Widget(name="b", code="WDG-0002"), admin)
    assert not selectors.code_reserved(item(), "ESKI-1")
    assert selectors.find_by_code(Widget, "ESKI-1") == (None, False)

    output = backfill("--dry-run")
    assert "Deneme parçası: 1 kayıt, 2 eski kod yazılacak" in output
    assert "Deneme çalıştırması: hiçbir şey yazılmadı." in output
    assert not CodeHistory.objects.exists() and summaries() == 0

    output = backfill()
    assert "Deneme parçası: 1 kayıt, 2 eski kod yazıldı" in output
    assert "Toplam: 1 kayıt, 2 eski kod yazıldı." in output
    first, second = code_changes(widget)
    rows = CodeHistory.objects.filter(object_id=widget.pk).order_by("valid_to", "id")
    assert [
        (row.code, row.valid_from, row.valid_to, row.reason, row.note, row.created_by)
        for row in rows
    ] == [
        ("ESKI-1", widget.created_at, first.timestamp, "change", NOTE, admin),
        ("ESKI-2", first.timestamp, second.timestamp, "change", NOTE, admin),
    ]
    assert not CodeHistory.objects.filter(object_id=untouched.pk).exists()
    assert summaries() == 1
    # Eski kodlar artık kullanılmış sayılır ve eski koduyla bulunur.
    with pytest.raises(BusinessRuleError) as exc:
        services.check_master_code(item(), Widget(name="c", code="ESKI-1"), previous_code=None)
    assert exc.value.code == "code_reserved"
    assert selectors.find_by_code(Widget, "ESKI-1") == (widget, True)
    assert selectors.former_codes(widget) == ["ESKI-2", "ESKI-1"]
    assert selectors.code_as_of(widget, widget.created_at) == "ESKI-1"
    assert selectors.code_as_of(widget, first.timestamp) == "ESKI-2"

    # Tekrar çalıştırmak bir şey yazmaz.
    assert "Toplam: 0 kayıt, 0 eski kod yazıldı." in backfill()
    assert CodeHistory.objects.count() == 2 and summaries() == 1


def test_backfill_keeps_changes_recorded_after_the_feature(admin):
    """Sistematikten sonra da kodu değişen kayıtta yalnızca önceki değişiklikler yüklenir; bir
    sonraki kayıt değişikliği geçerlilik aralığını öncekinin sonundan başlatır."""
    widget = save_with_audit(Widget(name="a", code="ESKI-1"), admin)
    rename(admin, widget, "ESKI-2")  # önce: yalnızca günlük
    rename(admin, widget, "WDG-0001")  # sonra: günlük ve eski kod geçmişi (masterdata._save)
    services.record_code_change(admin, item(), widget, "ESKI-2")
    first, _ = code_changes(widget)

    assert "Deneme parçası: 1 kayıt, 1 eski kod yazıldı" in backfill()
    rows = CodeHistory.objects.filter(object_id=widget.pk).order_by("valid_to", "id")
    assert [(row.code, row.note) for row in rows] == [("ESKI-1", NOTE), ("ESKI-2", "")]
    assert selectors.code_as_of(widget, widget.created_at) == "ESKI-1"
    assert selectors.code_as_of(widget, first.timestamp) == "ESKI-2"
    assert "Toplam: 0 kayıt, 0 eski kod yazıldı." in backfill()

    other = save_with_audit(Widget(name="b", code="ESKI-9"), admin)
    rename(admin, other, "WDG-0002")
    backfill()
    rename(admin, other, "WDG-0003")
    latest = services.record_code_change(admin, item(), other, "WDG-0002")
    assert latest.valid_from == code_changes(other)[0].timestamp


def test_backfill_skips_unreadable_changes_and_missing_records(admin):
    widget = Widget.objects.create(name="a", code="")
    rename(admin, widget, "WDG-0001")  # boş koddan: eski kod yok
    AuditLog.objects.create(
        action=AuditLog.Action.UPDATE,
        content_type=ContentType.objects.get_for_model(Widget),
        object_id=widget.pk + 1000,
        changes={"code": ["SILINMIS", "WDG-0099"]},
    )
    output = backfill()
    assert "Deneme parçası: 0 kayıt, 0 eski kod yazıldı (1 kayıt bulunamadı, atlandı)" in output
    assert not CodeHistory.objects.exists() and summaries() == 0


def test_backfill_rerun_writes_nothing_after_a_skipped_change(admin):
    """Okunamayan (boş) eski kodlu değişiklik okunabilir olanın ardından gelse de ikinci çalıştırma
    bir şey yazmaz."""
    widget = save_with_audit(Widget(name="a", code="ESKI-A"), admin)
    rename(admin, widget, "")
    rename(admin, widget, "WDG-0001")
    assert "Toplam: 1 kayıt, 1 eski kod yazıldı." in backfill()
    assert "Toplam: 0 kayıt, 0 eski kod yazıldı." in backfill()
    assert list(CodeHistory.objects.values_list("code", flat=True)) == ["ESKI-A"]


def test_backfill_skips_old_codes_now_used_by_another_record(admin):
    """Sistematikten önce başka kayda verilmiş eski kod yazılmaz ve özette listelenir; birden çok
    kaydın eski kodu bilgi olarak listelenir."""
    first = save_with_audit(Widget(name="a", code="K-1"), admin)
    rename(admin, first, "WDG-0001")
    holder = save_with_audit(Widget(name="b", code="K-1"), admin)
    second = save_with_audit(Widget(name="c", code="K-2"), admin)
    rename(admin, second, "WDG-0002")
    third = save_with_audit(Widget(name="d", code="K-2"), admin)
    rename(admin, third, "WDG-0003")

    output = backfill()
    assert f"K-1: şu an başka bir kaydın kodu (#{holder.pk}); #{first.pk} kaydına" in output
    assert f"K-2: birden çok kaydın eski kodu (#{second.pk}, #{third.pk})." in output
    assert "Toplam: 2 kayıt, 2 eski kod yazıldı." in output
    assert not CodeHistory.objects.filter(code="K-1").exists()
    # K-1'in sahibi kendi kodunda kalır; kodu değişip geri dönebilir.
    assert not selectors.code_reserved(item(), "K-1", exclude_pk=holder.pk)
