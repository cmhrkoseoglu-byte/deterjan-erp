"""Var olan rapor işlerine yetki bölümü ve maliyet bilgisi (reporting/0002; plan §5.6, §8 madde
12): göçten sonra hiçbir kişinin indirebildiği dosya değişmez."""

from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("reporting", "0001_initial")]
AFTER = [("reporting", "0002_reportjob_access")]


def _migrate(targets: list[tuple[str, str]]) -> Any:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_jobs_get_section_and_cost_flag() -> None:
    try:
        _check()
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def _check() -> None:
    # Yalnız raporlama geri alınır; kullanıcı ve rol tabloları güncel modellerle yazılır.
    from django.contrib.auth.models import Group

    from apps.core.models import User

    old = _migrate(BEFORE)

    def user(username: str, *roles: str, superuser: bool = False) -> Any:
        person = User.objects.create(username=username, is_superuser=superuser)
        for role in roles:
            person.groups.add(Group.objects.get_or_create(name=role)[0])
        return person

    manager = user("m", "yonetim")
    admin = user("a", "admin")
    root = user("r", superuser=True)
    planner = user("p", "planlama", "satin_alma")
    Job = old.get_model("reporting", "ReportJob")

    def job(code: str, owner: Any) -> int:
        return int(
            Job.objects.create(
                report_code=code,
                title=code,
                file_format="xlsx",
                status="DONE",
                created_by_id=owner.pk,
            ).pk
        )

    ids = {
        "manager": job("stock-status", manager),
        "admin": job("stock-status", admin),
        "root": job("stock-status", root),
        "planner": job("stock-status", planner),
        "movements": job("stock-movements", manager),
        "durations": job("task-durations", manager),
        "unknown": job("eski-rapor", manager),
    }

    new = _migrate(AFTER)
    jobs = new.get_model("reporting", "ReportJob").objects
    rows = {
        name: tuple(jobs.filter(pk=pk).values_list("section", "has_costs", "has_prices").get())
        for name, pk in ids.items()
    }
    assert rows == {
        "manager": ("reporting.stock", True, False),
        "admin": ("reporting.stock", True, False),
        "root": ("reporting.stock", True, False),
        "planner": ("reporting.stock", False, False),
        "movements": ("reporting.stock", False, False),
        "durations": ("reporting.management", False, False),
        "unknown": ("", False, False),
    }


def test_migration_map_matches_the_reports() -> None:
    """Göçteki rapor → bölüm eşlemesi ve maliyetli raporlar koddaki tanımlarla aynı."""
    from importlib import import_module

    from apps.reporting.reports import REPORTS

    migration = import_module("apps.reporting.migrations.0002_reportjob_access")
    assert {code: d.section.key for code, d in REPORTS.items()} == migration.SECTIONS
    costly = {code for code, d in REPORTS.items() if any(c.sensitive == "cost" for c in d.columns)}
    assert set(migration.COST_REPORTS) == costly
