"""Yetki kataloğu komutları: paket sürümü kopyası ve dışa aktarım."""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.core import access, services
from apps.core.access import VIEW, grant, register_module, register_section, temporary_catalog
from apps.core.access_export import perm_name, to_markdown, to_typescript
from apps.core.models import AccessCatalogSnapshot, AuditLog
from apps.core.roles import DEPO


@pytest.mark.django_db
def test_sync_access_catalog_writes_once_per_version() -> None:
    first, created = services.sync_access_catalog()
    again, created_again = services.sync_access_catalog()

    assert created and not created_again
    assert again.pk == first.pk
    assert first.catalog_hash == access.catalog_hash()
    assert first.catalog == access.catalog()
    entry = AuditLog.objects.get(object_id=first.pk, note="Yetki paketleri değişti.")
    assert entry.action == AuditLog.Action.CUSTOM
    assert entry.changes == {"catalog_hash": [None, first.catalog_hash]}

    with temporary_catalog():
        register_module("demo", "Deneme", order=999)
        grant(DEPO, register_section("demo.orders", "Emirler", levels=(VIEW,)), VIEW)
        changed, created_changed = services.sync_access_catalog()

    assert created_changed
    assert AccessCatalogSnapshot.objects.count() == 2
    assert AuditLog.objects.get(object_id=changed.pk).changes == {
        "catalog_hash": [first.catalog_hash, changed.catalog_hash]
    }


@pytest.mark.django_db
def test_sync_access_catalog_command_output() -> None:
    out = StringIO()
    call_command("sync_access_catalog", stdout=out)
    call_command("sync_access_catalog", stdout=out)

    lines = out.getvalue().splitlines()
    assert lines[0].startswith("Yetki paketlerinin yeni sürümü kaydedildi")
    assert lines[1] == "Yetki paketleri değişmedi."


def test_typescript_export_contains_catalog() -> None:
    text = to_typescript()

    assert text.startswith("// Bu dosya üretilir; elle değiştirmeyin.")
    assert f'export const ACCESS_CATALOG_HASH = "{access.catalog_hash()}";' in text
    assert '"PRODUCTION_ORDERS": "production.orders"' in text
    assert "export type PermKey" in text
    assert '"production.prep": "vc"' in text
    assert perm_name("inventory.open_records") == "INVENTORY_OPEN_RECORDS"
    assert "export const FIELD_OPENERS" in text
    assert "docker compose exec -T backend python manage.py export_access --format=ts" in text


def test_markdown_export_has_one_row_per_section() -> None:
    text = to_markdown()
    rows = [line for line in text.splitlines() if line.startswith("| ") and "---" not in line]

    assert rows[0].startswith("| Modül | Bölüm | Herkes | Rolü olan herkes | Yönetim |")
    assert len(rows) == 1 + len(access.sections())
    assert any("| Malzeme hazırlama |" in row and "| vc |" in row for row in rows)


def test_export_command_writes_and_checks(tmp_path: Path) -> None:
    target = tmp_path / "access.gen.ts"
    out = StringIO()

    call_command("export_access", "--format=ts", f"--output={target}", stdout=out)
    call_command("export_access", "--format=ts", f"--check={target}", stdout=out)

    assert target.read_text(encoding="utf-8") == to_typescript()
    assert "güncel." in out.getvalue()

    target.write_text("// eski\n", encoding="utf-8")
    with pytest.raises(CommandError, match="güncel değil"):
        call_command("export_access", "--format=ts", f"--check={target}", stdout=out)


def test_export_command_check_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="bulunamadı. Yeniden üretin"):
        call_command("export_access", "--format=ts", f"--check={tmp_path / 'yok.ts'}")


def test_export_command_prints_markdown() -> None:
    out = StringIO()

    call_command("export_access", "--format=markdown", stdout=out)

    assert out.getvalue() == to_markdown()
