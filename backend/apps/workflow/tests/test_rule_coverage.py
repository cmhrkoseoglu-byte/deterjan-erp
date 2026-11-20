"""Kural kapsama testi (docs/plan/kisi-yetkileri.md §5.5 sonu, §5.7, §10 7. adım).

Her görev, bildirim ve iptal kuralının rollerinin paketi kuralın gerektirdiği yetkiyi verir:
kişiye özel ayar yokken alıcılar bugünkü gibi kalır. Admin rolüne giden kurallar admin dışında
kimseye verilemeyen bir Görür ister (admin her yetkiye sahiptir). Rapor isteyene giden iki
bildirim yetki istemez (rapor isteyen süzülmez).

Plan §5.7'nin iki istisnası (tartım sapması, ara kontrol reddi) sahibin 2026-11-17 kararıyla lot
sayfasına bağlandı; ikisi de herkese açık ve kilitli "Lotlar: Görür"ü ister, alıcıları süzülmez.
"""

import pytest

from apps.core import access
from apps.core.access import VIEW
from apps.core.effective_access import compute_access
from apps.core.roles import ADMIN
from apps.workflow import rules

REQUESTER_RULES = {"report_ready", "report_failed"}
LOT_LINKED_RULES = {"production_deviation", "in_process_out_of_spec"}

# İptal kuralı → kaydına bağlı görevleri iptal ettiği görev kuralları (görevin rolü de iptal
# bildirimini alır; kayıt bölümünde Görür'ü olmalı).
CANCELLED_TASKS = {
    "production_order_cancelled": ("material_prep", "start_batch"),
    "filling_order_cancelled": ("packaging_prep", "start_filling"),
    "sales_order_cancelled": ("plan_shipment", "sales_shortage"),
    "shipment_cancelled": ("pick_shipment", "dispatch_shipment"),
    "purchase_order_cancelled": ("purchase_order_approval",),
}


def roles_of(rule: rules.Rule) -> tuple[str, ...]:
    if isinstance(rule, rules.TaskRule):
        return (rule.role,)
    if isinstance(rule, rules.NotifyRule):
        return rule.roles
    return rule.notify_roles


def kind_of(rule: rules.Rule) -> str:
    if isinstance(rule, rules.TaskRule):
        return access.TASK
    if isinstance(rule, rules.NotifyRule):
        return access.NOTIFY
    return access.CANCEL


def package_allows(role: str, requires: tuple[str, str]) -> bool:
    return compute_access([role]).allows(*requires)


def test_every_rule_declares_a_requirement_except_report_requester_rules():
    exempt = {rule.code for rule in rules.RULES if rule.requires is None}
    assert exempt == REQUESTER_RULES
    for code in REQUESTER_RULES:
        rule = rules.rule_by_code(code)
        assert isinstance(rule, rules.NotifyRule)
        assert rule.roles == ()


@pytest.mark.parametrize("rule", rules.RULES, ids=lambda rule: rule.code)
def test_requirement_is_a_known_section_level(rule):
    if rule.requires is None:
        return
    key, level = rule.requires
    assert access.has_section(key), key
    assert level in access.section(key).levels


@pytest.mark.parametrize("rule", rules.RULES, ids=lambda rule: rule.code)
def test_rule_roles_hold_the_requirement_by_package(rule):
    """Kapsama: kuralın her rolünün paketi gereken yetkiyi verir (ayar yokken kimse düşmez)."""
    for role in roles_of(rule):
        if role == ADMIN:
            continue
        assert package_allows(role, rule.requires), (rule.code, role, rule.requires)


def test_admin_rules_require_an_admin_only_view():
    """Admin rolüne giden kurallar: admin her yetkiye sahip; istenen Görür kimseye verilemez,
    böylece kişiye özel ayarla da alıcı admin rolünün dışına çıkmaz."""
    admin_rules = [rule for rule in rules.RULES if ADMIN in roles_of(rule)]
    assert {rule.code for rule in admin_rules} == {
        "user_locked",
        "ops_alert",
        "ops_recovered",
        "portal_email_failed",
        "problem_reported",
    }
    for rule in admin_rules:
        assert roles_of(rule) == (ADMIN,)
        assert rule.requires == rules.ADMIN_ONLY
    key, level = rules.ADMIN_ONLY
    assert level in access.section(key).admin_only


@pytest.mark.parametrize(("code", "task_codes"), CANCELLED_TASKS.items())
def test_cancelled_task_roles_hold_the_cancel_requirement(code, task_codes):
    """İptal bildirimi iptal edilen görevlerin rollerine de gider; o roller kaydı görür."""
    cancel = rules.rule_by_code(code)
    assert isinstance(cancel, rules.CancelTasksRule)
    for task_code in task_codes:
        task_rule = rules.rule_by_code(task_code)
        assert isinstance(task_rule, rules.TaskRule)
        assert package_allows(task_rule.role, cancel.requires), (code, task_rule.role)


def test_cancel_rules_require_view_of_the_cancelled_record():
    for rule in rules.RULES:
        if isinstance(rule, rules.CancelTasksRule):
            assert rule.requires is not None
            assert rule.requires[1] == VIEW
    assert set(CANCELLED_TASKS) == {
        rule.code for rule in rules.RULES if isinstance(rule, rules.CancelTasksRule)
    }


def test_notify_rules_require_view():
    for rule in rules.RULES:
        if isinstance(rule, rules.NotifyRule) and rule.requires is not None:
            assert rule.requires[1] == VIEW, rule.code


def test_lot_linked_notifications_are_not_filtered():
    """§12 kararı: iki bildirim lot sayfasına bağlanır; "Lotlar: Görür" herkese açık ve kilitli
    olduğundan kişiye özel ayarla da alıcı düşmez."""
    lots = access.section("inventory.lots")
    for code in LOT_LINKED_RULES:
        rule = rules.rule_by_code(code)
        assert isinstance(rule, rules.NotifyRule)
        assert rule.requires == (lots.key, VIEW)
    assert VIEW in lots.locked
    assert compute_access([]).allows(lots, VIEW)
    assert compute_access([], revokes=[(lots.key, VIEW)]).allows(lots, VIEW)


def test_registry_matches_the_rule_table():
    """workflow `ready()`'de her kuralı core'un kayıt defterine yazar (§5.1)."""
    registered = {item.code: item for item in access.rules()}
    assert set(registered) == {rule.code for rule in rules.RULES}
    for rule in rules.RULES:
        item = registered[rule.code]
        assert item.kind == kind_of(rule)
        assert item.roles == tuple(dict.fromkeys(roles_of(rule)))
        assert item.requires == rule.requires
    assert access.validate() == []


def test_rule_by_code():
    assert rules.rule_by_code("material_prep") is not None
    assert rules.rule_by_code("material_prep").code == "material_prep"
    assert rules.rule_by_code("") is None
    assert rules.rule_by_code("no_such_rule") is None
