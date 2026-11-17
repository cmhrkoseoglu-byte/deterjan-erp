"""Denetim günlüğü süzmesi (docs/plan/kisi-yetkileri.md §5.6, §8 madde 7; `core.audit_filter`).

Varsayılan paketlerde yönetim her bölüme sahiptir; süzme yalnız kişiye özel ayarla (ya da yalnız
admine görünen yetki kayıtlarında) fark edilir. Kayıtlar burada elle yazılır: kuralları tek tek
denemek için (gerçek servislerin kayıt izi `access_contract/test_probe_audit.py`'dedir).
"""

import re
from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.core import access, audit_filter
from apps.core.access import AUDIT_LOG, COSTS, PRICES, VIEW
from apps.core.models import AccessOverride, Attachment, AuditLog, User
from apps.core.tests.testapp.models import Widget
from apps.costing.access import OLD_LABOR_RATE_NOTE, PERSONNEL_COST
from apps.costing.api.serializers import OLD_LABOR_RATE_NOTE as SERIALIZER_LABOR_NOTE
from apps.hse.access import INCIDENTS
from apps.inventory import access as inventory_access
from apps.inventory import services as inventory
from apps.personnel.access import CARDS, PAYROLL, PAYROLL_ACCESS_NOTE, WAGES
from apps.purchasing import access as purchasing_access
from apps.purchasing.api.serializers import PRICE_FIELDS
from apps.workflow.models import Comment, Task

pytestmark = pytest.mark.django_db
URL = "/api/v1/audit-log/"
MARK = "IZDENEME"


def override(user: User, key: str, level: str = VIEW, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def entry(
    label: str | None,
    changes: dict[str, Any] | None = None,
    note: str = "",
    *,
    object_id: int | None = None,
    action: str = AuditLog.Action.UPDATE,
    name: str = "",
) -> AuditLog:
    content_type = None
    if label is not None:
        app_label, _, model = label.partition(".")
        content_type = ContentType.objects.get_by_natural_key(app_label, model)
    return AuditLog.objects.create(
        action=action,
        content_type=content_type,
        object_id=object_id,
        object_repr=f"{MARK} {name or label or '-'}",
        changes=changes or {},
        note=note,
    )


def listed(user: User, **params: str) -> dict[int, dict[str, Any]]:
    response = api(user).get(URL, {"search": MARK, "page_size": "500", **params})
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["count"] == len(data["results"])
    return {row["id"]: row for row in data["results"]}


# --- kayıt defteri ------------------------------------------------------------------------------


def test_registry_is_consistent_with_the_code() -> None:
    assert access.validate() == []
    assert audit_filter.model_errors() == []
    assert set(purchasing_access.ORDER_PRICE_FIELDS) == set(PRICE_FIELDS)
    assert inventory_access.RECEIPT_PRICE_FIELDS == inventory.RECEIPT_PRICE_FIELDS
    assert re.match(inventory_access.PRICE_CORRECTION_NOTE, f"{inventory.PRICE_CORRECTION_NOTE} x")
    assert (
        "^"
        + SERIALIZER_LABOR_NOTE.pattern.replace(
            "(Personel maliyeti [^:]*)", "Personel maliyeti [^:]*"
        )
        == OLD_LABOR_RATE_NOTE
    )
    assert PAYROLL_ACCESS_NOTE == "Bordro çıktısı açıldı:"
    # Satın alma notu kalıbı kayıt geçmişininkiyle (purchasing/apps.py) aynı notları yakalar.
    history = re.compile(r"Tutar [\d.]+,\d{2} TL|Onay: tutar [\d.]+,\d{2} TL \(kur .*")
    for note in (
        "Tutar 12.345,60 TL",
        "Onay: tutar 12.345,60 TL (kur 1,0000), limit 50.000,00 TL",
        "Onaya gönderildi",
        "Tutar 12.345,60 TL ve fazlası",
    ):
        assert bool(re.match(purchasing_access.AMOUNT_NOTE, note)) == bool(history.fullmatch(note))


def test_invalid_registrations_are_rejected() -> None:
    with access.temporary_catalog():
        with pytest.raises(ValueError):
            access.register_audit_model("demo.thing")  # yetki yok
        with pytest.raises(ValueError):
            access.register_audit_model("Demo", requires=[PRICES])
        with pytest.raises(ValueError):
            access.register_audit_model("demo.thing", requires=[PRICES], nested=True)
        with pytest.raises(ValueError):
            access.register_audit_rows("demo.rows", None, requires=[PRICES])
        access.register_audit_model("demo.thing", requires=[("sensitive.none", VIEW)])
        assert any("sensitive.none" in error for error in access.validate())
        assert audit_filter.model_errors() == ["demo.thing: denetim günlüğü kuralının modeli yok."]
    assert access.validate() == []


# --- okuma izni ---------------------------------------------------------------------------------


def test_reading_follows_the_audit_log_section(make_user: Callable[..., User]) -> None:
    depo, manager = make_user("depo"), make_user("yonetim")
    refused = api(depo).get(URL)
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": AUDIT_LOG.key, "level": VIEW}]
    # Karşılanmayan metot: okuyamayana 403, okuyana 405 (bugünkü gibi).
    assert api(depo).post(URL, {}, format="json").status_code == 403
    assert api(manager).post(URL, {}, format="json").status_code == 405
    assert api(manager).get(URL).status_code == 200

    override(manager, AUDIT_LOG.key)
    revoked = api(manager).get(URL)
    assert revoked.status_code == 403
    assert revoked.json()["required"] == [{"key": AUDIT_LOG.key, "level": VIEW}]
    assert api(manager).post(URL, {}, format="json").status_code == 403

    # KVKK: yalnız yönetim rolünde geçerli; depoya eklenen yetki açmaz.
    override(depo, AUDIT_LOG.key, effect="grant")
    assert api(depo).get(URL).status_code == 403


# --- yetki kayıtları ----------------------------------------------------------------------------


def test_access_records_are_admin_only(make_user: Callable[..., User]) -> None:
    manager, admin = make_user("yonetim"), make_user("admin")
    hidden = [entry("core.accessoverride"), entry("core.accesscatalogsnapshot")]
    roles = entry("core.user", {"roles": [["depo"], ["depo", "yonetim"]]}, "Görev değişti")
    both = entry(
        "core.user",
        {"roles": [["depo"], ["yonetim"]], "access": [[], ["sensitive.prices:view"]]},
        "Gerekçe: satın almaya destek",
    )
    only_access = entry("core.user", {"access": [[], ["sensitive.prices:view"]]}, "Gerekçe")
    login = entry("core.user", {}, "Giriş", action=AuditLog.Action.LOGIN)

    shown = listed(manager)
    assert not set(shown) & {row.pk for row in hidden}
    assert only_access.pk not in shown
    assert shown[roles.pk]["changes"] == roles.changes and shown[roles.pk]["note"] == roles.note
    assert shown[both.pk]["changes"] == {"roles": [["depo"], ["yonetim"]]}
    assert shown[both.pk]["note"] == ""
    assert shown[login.pk]["note"] == "Giriş"
    assert listed(manager, content_type="core.accessoverride") == {}
    assert api(manager).get(f"{URL}{hidden[0].pk}/").status_code == 404
    assert api(manager).get(URL, {"search": "satın almaya destek"}).json()["count"] == 0

    full = listed(admin)
    assert {row.pk for row in [*hidden, only_access]} <= set(full)
    assert full[both.pk]["changes"] == both.changes and full[both.pk]["note"] == both.note
    assert api(admin).get(f"{URL}{hidden[0].pk}/").status_code == 200


# --- personel (KVKK) ----------------------------------------------------------------------------


def test_personnel_rows_follow_their_sections(make_user: Callable[..., User]) -> None:
    wage = entry("personnel.employeewage", {"gross_monthly": [None, "45678.90"]})
    card = entry("personnel.employee", {"department": ["A", "B"]})
    card_payroll = entry(
        "personnel.employee", {}, "Ek ödeme eklendi: Prim 1.500,00 TL", action="custom"
    )
    payroll_access = entry(
        None, {"year": [None, 2026]}, f"{PAYROLL_ACCESS_NOTE} PDF · Eylül 2026", action="custom"
    )
    failed_login = entry(None, {}, "bilinmeyen kullanıcı", action=AuditLog.Action.LOGIN_FAILED)
    manager = make_user("yonetim")
    assert {wage.pk, card.pk, card_payroll.pk, payroll_access.pk} <= set(listed(manager))

    override(manager, WAGES.key)  # Bordro'nun ön koşulu: Bordro da düşer
    shown = listed(manager)
    assert wage.pk not in shown and card_payroll.pk not in shown
    assert payroll_access.pk not in shown
    assert card.pk in shown and failed_login.pk in shown
    assert api(manager).get(URL, {"search": "45678.90"}).json()["count"] == 0
    assert api(manager).get(f"{URL}{wage.pk}/").status_code == 404

    only_payroll = override(make_user("yonetim"), PAYROLL.key)
    shown = listed(only_payroll)
    assert wage.pk in shown and card.pk in shown and card_payroll.pk not in shown

    no_cards = override(make_user("yonetim"), CARDS.key)
    shown = listed(no_cards)
    assert card.pk not in shown and card_payroll.pk not in shown and wage.pk in shown


# --- fiyat ve maliyet ---------------------------------------------------------------------------


def test_prices_hide_amount_fields_notes_and_rows(make_user: Callable[..., User]) -> None:
    order = entry(
        "purchasing.purchaseorder",
        {
            "status": ["DRAFT", "PENDING"],
            "total": ["0", "12345.60"],
            "line": [{"line_no": 1, "unit_price": "10.00", "quantity": "5"}, None],
        },
        "Tutar 12.345,60 TL",
        action=AuditLog.Action.STATUS_CHANGE,
    )
    order_prices = entry("purchasing.purchaseorder", {"total": ["0", "1"]})
    correction = entry(
        "inventory.goodsreceipt", {}, "Fiyat düzeltmesi: 7.777,77 TL", action="custom"
    )
    receipt_line = entry(
        "inventory.goodsreceiptline",
        {"unit_price": ["1", "2"], "quantity": ["1", "2"]},
        "Tedarikçi faturası 7.777,77",
    )
    extra = entry("inventory.goodsreceiptextracost", {"kind": ["", "NAKLIYE"]})
    lot = entry("inventory.lot", {"unit_cost": ["1", "2"]}, "Maliyet sürüm 2: düzeltme")
    lot_status = entry("inventory.lot", {"status": ["QUARANTINE", "RELEASED"]})
    lot_cost = entry("costing.lotcost", {"total_cost": [None, "10"]})
    order_line = entry(
        "purchasing.purchaseorderline", {"unit_price": ["1", "2"], "note": ["", "x"]}
    )
    manager = make_user("yonetim")
    assert listed(manager)[order.pk]["changes"] == order.changes

    override(manager, PRICES.key)  # Maliyetleri görür'ün ön koşulu: ikisi de düşer
    shown = listed(manager)
    assert shown[order.pk]["changes"] == {
        "status": ["DRAFT", "PENDING"],
        "line": [{"line_no": 1, "quantity": "5"}, None],
    }
    assert shown[order.pk]["note"] == ""
    for gone in (order_prices, correction, extra, lot, lot_cost):
        assert gone.pk not in shown, gone.object_repr
    assert shown[receipt_line.pk]["changes"] == {"quantity": ["1", "2"]}
    assert shown[receipt_line.pk]["note"] == ""
    assert shown[lot_status.pk]["changes"] == lot_status.changes
    assert shown[order_line.pk]["changes"] == {"note": ["", "x"]}
    for term in ("12.345,60", "7.777,77"):
        assert api(manager).get(URL, {"search": term}).json()["count"] == 0
    detail = api(manager).get(f"{URL}{order.pk}/").json()
    assert "total" not in detail["changes"] and detail["note"] == ""


def test_costs_alone_hide_cost_rows(make_user: Callable[..., User]) -> None:
    lot = entry("inventory.lot", {"unit_cost": ["1", "2"], "status": ["A", "B"]}, "Maliyet sürüm 2")
    rate = entry("costing.costrate", {"rate_per_kg": [None, "1.5"]})
    receipt = entry("inventory.goodsreceipt", {"unit_price": ["1", "2"], "note": ["", "x"]})
    manager = override(make_user("yonetim"), COSTS.key)
    shown = listed(manager)
    assert rate.pk not in shown
    assert shown[lot.pk]["changes"] == {"status": ["A", "B"]} and shown[lot.pk]["note"] == ""
    assert shown[receipt.pk]["changes"] == receipt.changes


def test_purchase_approval_task_description(make_user: Callable[..., User]) -> None:
    assignee = make_user("yonetim")
    approval = Task.objects.create(
        title="Onay", rule_code="purchase_order_approval", assigned_user=assignee
    )
    other = Task.objects.create(title="Hazırla", rule_code="material_prep", assigned_user=assignee)
    approval_row = entry(
        "workflow.task",
        {"description": ["", "ABC, tutar 12.345,60 TRY"], "status": ["OPEN", "DONE"]},
        object_id=approval.pk,
    )
    created = entry(
        "workflow.task",
        {"description": [None, "tutar 1,00"], "rule_code": [None, "purchase_order_approval"]},
        object_id=None,
        action=AuditLog.Action.CREATE,
    )
    other_row = entry("workflow.task", {"description": ["", "x"]}, object_id=other.pk)
    manager = override(make_user("yonetim"), PRICES.key)
    shown = listed(manager)
    assert shown[approval_row.pk]["changes"] == {"status": ["OPEN", "DONE"]}
    assert shown[created.pk]["changes"] == {"rule_code": [None, "purchase_order_approval"]}
    assert shown[other_row.pk]["changes"] == other_row.changes
    assert listed(make_user("yonetim"))[approval_row.pk]["changes"] == approval_row.changes


def test_old_labor_rate_note_needs_personnel_cost(make_user: Callable[..., User]) -> None:
    labor = "Personel maliyeti Eylül 2026 (BR-2026-00001): 53.437,50 TL / 980,00 kg"
    old = entry("costing.costrate", {"note": [None, labor], "rate_per_kg": [None, "54.53"]})
    noted = entry("costing.costrate", {"valid_from": ["a", "b"]}, labor)
    plain = entry("costing.costrate", {"note": [None, "Elle girildi"]})
    manager = override(make_user("yonetim"), PERSONNEL_COST.key)
    shown = listed(manager)
    assert shown[old.pk]["changes"] == {"rate_per_kg": [None, "54.53"]}
    assert shown[noted.pk]["note"] == "" and shown[noted.pk]["changes"] == noted.changes
    assert shown[plain.pk]["changes"] == plain.changes
    assert api(manager).get(URL, {"search": "53.437,50"}).json()["count"] == 0
    full = listed(make_user("yonetim"))
    assert full[old.pk]["changes"] == old.changes and full[noted.pk]["note"] == labor


# --- yorum ve ek bağlı kaydı izler --------------------------------------------------------------


def _attachment(target: Any, user: User) -> Attachment:
    return Attachment.objects.create(
        content_type=ContentType.objects.get_for_model(target),
        object_id=target.pk,
        file="ek/deneme.txt",
        original_name="deneme.txt",
        size=1,
        created_by=user,
    )


def test_comments_and_attachments_follow_their_record(make_user: Callable[..., User]) -> None:
    from apps.hse.tests.factories import report

    reporter = make_user("depo")
    incident = report(reporter)
    widget = Widget.objects.create(name="A")
    on_incident = Comment.objects.create(
        content_type=ContentType.objects.get_for_model(incident),
        object_id=incident.pk,
        author=reporter,
        body="Olay yorumu",
    )
    on_widget = Comment.objects.create(
        content_type=ContentType.objects.get_for_model(widget),
        object_id=widget.pk,
        author=reporter,
        body="Parça yorumu",
    )
    photo = _attachment(incident, reporter)
    comment_photo = _attachment(on_incident, reporter)
    widget_photo = _attachment(on_widget, reporter)
    rows = {
        "incident": entry("hse.incident", {"status": ["A", "B"]}, object_id=incident.pk),
        "comment": entry("workflow.comment", {"body": ["", "x"]}, object_id=on_incident.pk),
        "photo": entry("core.attachment", {"kind": ["", "PHOTO"]}, object_id=photo.pk),
        "comment photo": entry("core.attachment", {"size": [0, 1]}, object_id=comment_photo.pk),
    }
    kept = {
        "widget comment": entry("workflow.comment", {"body": ["", "y"]}, object_id=on_widget.pk),
        "widget photo": entry("core.attachment", {"size": [0, 1]}, object_id=widget_photo.pk),
        "orphan photo": entry("core.attachment", {"size": [0, 1]}, object_id=None),
    }
    manager = make_user("yonetim")
    assert {row.pk for row in [*rows.values(), *kept.values()]} <= set(listed(manager))

    override(manager, INCIDENTS.key)
    shown = listed(manager)
    for name, row in rows.items():
        assert row.pk not in shown, name
    for name, row in kept.items():
        assert shown[row.pk]["changes"] == row.changes, name
    assert api(manager).get(f"{URL}{rows['comment photo'].pk}/").status_code == 404


def test_pagination_counts_only_visible_rows(make_user: Callable[..., User]) -> None:
    for _ in range(3):
        entry("personnel.employeewage", {"gross_monthly": [None, "1"]})
    visible = [entry("masterdata.material", {"name": ["a", str(n)]}) for n in range(3)]
    manager = override(make_user("yonetim"), WAGES.key)
    page = api(manager).get(URL, {"search": MARK, "page_size": "2"}).json()
    assert page["count"] == 3
    second = api(manager).get(URL, {"search": MARK, "page_size": "2", "page": "2"}).json()
    ids = [row["id"] for row in page["results"] + second["results"]]
    assert sorted(ids) == sorted(row.pk for row in visible)
