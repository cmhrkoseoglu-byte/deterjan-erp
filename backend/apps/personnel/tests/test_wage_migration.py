"""Ücretlerin maliyetten personele taşınması (costing/0003, personnel/0004; docs/DECISIONS.md
"Personel bordrosu"): tablo, kayıtlar ve kimlikleri yerinde kalır, denetim geçmişi içerik türüyle
birlikte personel uygulamasına geçer; geçiş geri alınabilir."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("costing", "0002_personel_maliyeti"), ("personnel", "0003_puantaj")]
AFTER = [("costing", "0003_ucretler_personele"), ("personnel", "0004_ucretler")]


def _migrate(targets: list[tuple[str, str]]) -> Any:
    """Hedef geçişlere gider ve o durumun (tarihsel) modellerini döner."""
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _wage_type(apps: Any) -> tuple[str, ...]:
    content_types = apps.get_model("contenttypes", "ContentType").objects
    return tuple(content_types.filter(model="employeewage").values_list("app_label", flat=True))


@pytest.mark.django_db(transaction=True)
def test_wage_move_keeps_rows_ids_and_history() -> None:
    try:
        _check_move()
    finally:
        # Test başarısız olsa da şema en son geçişte kalır (sonraki testler etkilenmez).
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def _check_move() -> None:
    old = _migrate(BEFORE)
    # Eski durumda içerik türü maliyettedir (geri dönüş içerik türünü de geri taşır).
    assert _wage_type(old) == ("costing",)
    ContentType = old.get_model("contenttypes", "ContentType")
    content_type = ContentType.objects.get(app_label="costing", model="employeewage")
    person = old.get_model("personnel", "Employee").objects.create(
        full_name="Ayşe Demir", department="Dolum"
    )
    wage = old.get_model("costing", "EmployeeWage").objects.create(
        employee=person, gross_monthly=Decimal("30000.00"), valid_from=date(2026, 1, 1)
    )
    log = old.get_model("core", "AuditLog").objects.create(
        action="CREATE", content_type=content_type, object_id=wage.pk, object_repr=str(wage.pk)
    )

    new = _migrate(AFTER)
    moved = new.get_model("personnel", "EmployeeWage").objects.get(pk=wage.pk)
    assert moved.gross_monthly == Decimal("30000.00") and moved.employee_id == person.pk
    assert _wage_type(new) == ("personnel",)
    # Aynı içerik türü kaydı taşındı: denetim kaydı yeni modeli gösterir.
    audit = new.get_model("core", "AuditLog").objects.get(pk=log.pk)
    assert audit.content_type_id == content_type.pk
    assert audit.content_type.app_label == "personnel"
    with pytest.raises(LookupError):
        new.get_model("costing", "EmployeeWage")

    # Geri alınır: kayıt ve içerik türü maliyete döner.
    old = _migrate(BEFORE)
    assert old.get_model("costing", "EmployeeWage").objects.get(pk=wage.pk).valid_from == date(
        2026, 1, 1
    )
    assert _wage_type(old) == ("costing",)
    # Tekrar ileri: hedefte boş kalmış içerik türü (ör. sonradan açılmış) birleştirilir.
    old.get_model("contenttypes", "ContentType").objects.create(
        app_label="personnel", model="employeewage"
    )
    new = _migrate(AFTER)
    assert _wage_type(new) == ("personnel",)
    assert new.get_model("core", "AuditLog").objects.get(pk=log.pk).content_type_id == (
        content_type.pk
    )
