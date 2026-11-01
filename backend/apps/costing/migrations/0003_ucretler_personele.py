"""Ücretler (`EmployeeWage`) personel modülüne taşındı (2026-11-01, docs/DECISIONS.md "Personel
bordrosu").

Yalnızca Django'nun model durumu değişir: tablo (`costing_employeewage`), kayıtlar ve kısıtlar
yerinde kalır (personnel/0004 aynı tabloyu durum olarak açar). Denetim kayıtları ve izinler içerik
türüne bağlıdır; içerik türü personel uygulamasına aktarılır, böylece ücretlerin geçmişi korunur.

`run_before`: personel modülünün kodu ve geçişleri maliyeti anmaz (CLAUDE.md §3), bu yüzden
sıralama bu taraftan verilir; yeni kurulumda tablo önce costing/0002 ile açılır, personnel/0004
ondan sonra gelir. Bu geçiş geri alınırken personnel/0004 de geri alınır.
"""

from typing import Any

from django.db import migrations

MODEL = "employeewage"


def _move_content_type(apps: Any, schema_editor: Any, source: str, target: str) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    AuditLog = apps.get_model("core", "AuditLog")
    types = ContentType.objects.using(schema_editor.connection.alias)
    current = types.filter(app_label=source, model=MODEL).first()
    if current is None:
        return  # yeni kurulum: içerik türleri geçişlerden sonra açılır
    existing = types.filter(app_label=target, model=MODEL).first()
    if existing is not None:
        # Hedefte boş bir içerik türü kalmışsa (ör. elle açılmış) kaldırılır; geçmişi olan
        # içerik türü birleştirilmez.
        if AuditLog.objects.using(schema_editor.connection.alias).filter(
            content_type=existing
        ).exists():
            raise RuntimeError(
                f"{target}.{MODEL} içerik türünün denetim kaydı var; ücret geçmişi "
                "birleştirilemez. Geçişten önce veritabanını kontrol edin."
            )
        existing.delete()
    current.app_label = target
    current.save(update_fields=["app_label"])


def forward(apps: Any, schema_editor: Any) -> None:
    _move_content_type(apps, schema_editor, "costing", "personnel")


def backward(apps: Any, schema_editor: Any) -> None:
    _move_content_type(apps, schema_editor, "personnel", "costing")


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0001_initial"),
        ("costing", "0002_personel_maliyeti"),
    ]
    run_before = [("personnel", "0004_ucretler")]

    operations = [
        migrations.RunPython(forward, backward),
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="EmployeeWage")],
            database_operations=[],
        ),
    ]
