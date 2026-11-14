"""Gerçek yetki kataloğu planın §3'üyle aynı (docs/plan/kisi-yetkileri.md).

Rol varsayılanlarının bugünkü kodla aynı olduğunu her modülün `test_access_package.py` dosyası
(paket denkliği) kanıtlar; burada katalogun yapısı ve planın kilit kuralları sınanır.
"""

from pathlib import Path

import pytest

from apps.core import access
from apps.core.access import ANY_ROLE, APPROVE, CHANGE, EVERYONE, READ, VIEW, Kind
from apps.core.access_export import REGENERATE, to_typescript
from apps.core.roles import YONETIM

FRONTEND_FILE = Path(__file__).resolve().parents[4] / "frontend" / "src" / "auth" / "access.gen.ts"


def test_section_counts_match_the_plan() -> None:
    kinds = [item.kind for item in access.sections()]

    assert kinds.count(Kind.SECTION) + kinds.count(Kind.ACTION) == 76
    assert kinds.count(Kind.OPEN_RECORDS) == 7
    assert kinds.count(Kind.SENSITIVE) == 2


def test_modules_in_menu_order() -> None:
    assert [item.key for item in access.modules()] == [
        "sensitive",
        "masterdata",
        "recipes",
        "inventory",
        "production",
        "quality",
        "filling",
        "sales",
        "returns",
        "traceability",
        "purchasing",
        "costing",
        "maintenance",
        "hse",
        "personnel",
        "reporting",
        "golive",
        "workflow",
        "system",
    ]


def test_kvkk_sections_are_limited_to_management() -> None:
    restricted = {item.key for item in access.sections() if item.restricted_to_role}

    assert restricted == {
        "personnel.cards",
        "personnel.attendance",
        "personnel.wages",
        "personnel.payroll",
        "personnel.settings",
        "costing.personnel_cost",
        "hse.incidents",
        "system.audit_log",
    }
    assert {access.section(key).restricted_to_role for key in restricted} == {YONETIM}


def test_admin_only_and_locked_levels() -> None:
    admin_only = {(item.key, level) for item in access.sections() for level in item.admin_only}
    locked = {(item.key, level) for item in access.sections() for level in item.locked}

    assert admin_only == {
        ("masterdata.reference", CHANGE),
        ("inventory.manual_release", APPROVE),
        ("golive.problems", VIEW),
    }
    assert locked == {
        ("inventory.stock", VIEW),
        ("inventory.lots", VIEW),
        ("inventory.pallets", VIEW),
        ("maintenance.breakdowns", CHANGE),
        ("hse.incident_report", VIEW),
        ("hse.incident_report", CHANGE),
        ("hse.hazards", VIEW),
    }


def test_locked_levels_belong_to_everyone_or_any_role() -> None:
    everyone = access.package(EVERYONE) | access.package(ANY_ROLE)
    for item in access.sections():
        for level in item.locked:
            assert (item.key, level) in everyone, (item.key, level)


def test_open_records_rows() -> None:
    rows = {item.module for item in access.sections() if item.kind is Kind.OPEN_RECORDS}

    assert rows == {
        "masterdata",
        "recipes",
        "inventory",
        "production",
        "quality",
        "filling",
        "returns",
    }
    for module in rows:
        assert (f"{module}.open_records", READ) in access.package(EVERYONE)


def test_prerequisites_of_the_plan() -> None:
    def needs(key: str, level: str) -> set[tuple[str, str]]:
        return set(access.section(key).requirements(level))

    assert needs("sensitive.costs", VIEW) == {("sensitive.prices", VIEW)}
    assert needs("personnel.payroll", VIEW) == {("personnel.wages", VIEW)}
    assert needs("costing.personnel_cost", VIEW) == {
        ("sensitive.costs", VIEW),
        ("personnel.wages", VIEW),
        ("personnel.payroll", VIEW),
    }
    assert needs("purchasing.orders", VIEW) == set()
    assert needs("purchasing.orders", CHANGE) == {("sensitive.prices", VIEW)}
    assert needs("purchasing.over_limit", APPROVE) == {
        ("purchasing.orders", VIEW),
        ("sensitive.prices", VIEW),
    }
    assert needs("maintenance.any_unit", CHANGE) == {("maintenance.work_orders", CHANGE)}
    assert needs("inventory.receipt_prices", CHANGE) == {
        ("inventory.receipts", VIEW),
        ("sensitive.prices", VIEW),
    }


def test_actions_never_open_a_menu_module() -> None:
    actions = {item.key for item in access.sections() if item.kind is Kind.ACTION}

    assert actions == {
        "inventory.receipt_prices",
        "inventory.lot_block",
        "inventory.manual_release",
        "returns.receiving",
        "purchasing.over_limit",
        "maintenance.any_unit",
        "maintenance.breakdowns",
        "filling.revert",
    }
    for key in actions:
        assert VIEW not in access.section(key).levels


@pytest.mark.skipif(not FRONTEND_FILE.exists(), reason="ön yüz kaynakları bu kopyada yok")
def test_frontend_file_is_current() -> None:
    current = FRONTEND_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")

    message = f"frontend/src/auth/access.gen.ts güncel değil. {REGENERATE}"
    assert current == to_typescript(), message
