from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.roles import LABORATUVAR
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceipt, Lot
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.tests.factories import SupplierFactory, unit
from apps.production.tests.factories import approved_order as approved_production_order
from apps.production.tests.factories import build_plant
from apps.purchasing import selectors, services
from apps.purchasing.models import PurchaseOrder, PurchaseRequest
from apps.purchasing.pdf import purchase_order_pdf
from apps.purchasing.state import purchase_order_states, purchase_request_states
from apps.purchasing.tests.factories import (
    ORDER_DATE,
    approved_order,
    draft_order,
    line,
    raw_material,
    receipt_locations,
)
from apps.workflow.models import Notification, Task

pytestmark = pytest.mark.django_db
Status = PurchaseOrder.Status


def set_limit(manager: User, value: str | None) -> None:
    services.update_settings(
        manager, {"approval_limit_try": Decimal(value) if value is not None else None}
    )


# --- ayarlar ve onay limiti (Karar D-13) -----------------------------------------------------


def test_settings_only_management_changes_limit(buyer: User, manager: User) -> None:
    assert services.get_settings().approval_limit_try is None
    with pytest.raises(PermissionDenied):
        services.update_settings(buyer, {"approval_limit_try": Decimal("50000")})
    set_limit(manager, "50000")
    settings = services.get_settings()
    assert settings.approval_limit_try == Decimal("50000")
    assert AuditLog.objects.filter(object_id=str(settings.pk), action="update").exists()
    with pytest.raises(BusinessRuleError) as exc:
        services.update_settings(manager, {"approval_limit_try": Decimal("-1")})
    assert exc.value.code == "invalid_limit"


def test_without_limit_every_order_goes_to_management(buyer: User, manager: User) -> None:
    order = draft_order(buyer, [line(raw_material(), "10", "1")])
    with pytest.raises(BusinessRuleError) as exc:
        services.approve_order(buyer, order)
    assert exc.value.code == "approval_limit_exceeded"
    assert "yönetim" in exc.value.message
    approved = services.approve_order(manager, order)
    assert approved.status == Status.APPROVED
    assert approved.approved_by == manager
    assert approved.approval_limit_try is None


def test_buyer_approves_within_limit_and_not_above(buyer: User, manager: User) -> None:
    set_limit(manager, "10000")
    material = raw_material()
    within = draft_order(buyer, [line(material, "1000", "10")])  # 10.000 TL (dahil)
    above = draft_order(buyer, [line(material, "1000", "10.01")])  # 10.010 TL
    assert services.approve_order(buyer, within).status == Status.APPROVED
    with pytest.raises(BusinessRuleError) as exc:
        services.approve_order(buyer, above)
    assert exc.value.code == "approval_limit_exceeded"
    assert "10.010,00 TL" in exc.value.message
    log = AuditLog.objects.filter(object_id=str(within.pk), action="status_change").last()
    assert log is not None
    assert "tutar 10.000,00 TL" in log.note and "limit 10.000,00 TL" in log.note


def test_foreign_currency_is_compared_in_try_at_order_rate(buyer: User, manager: User) -> None:
    set_limit(manager, "30000")
    material = raw_material()
    # 1000 × 1 EUR = 1000 EUR; kur 35 → 35.000 TL > 30.000
    eur = draft_order(
        buyer, [line(material, "1000", "1")], currency="EUR", exchange_rate=Decimal("35")
    )
    assert selectors.order_totals(eur).total_try == Decimal("35000.00")
    assert not services.can_approve(buyer, eur)
    with pytest.raises(BusinessRuleError):
        services.approve_order(buyer, eur)
    # Kur 25 → 25.000 TL, limit içinde
    services.update_order(buyer, eur, {"exchange_rate": Decimal("25")})
    assert services.approve_order(buyer, eur).status == Status.APPROVED


def test_foreign_currency_requires_rate_and_try_rate_is_one(buyer: User) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        draft_order(buyer, [], currency="USD", exchange_rate=Decimal("0"))
    assert exc.value.code == "exchange_rate_required"
    order = draft_order(buyer, [], currency="TRY", exchange_rate=Decimal("7"))
    assert order.exchange_rate == Decimal(1)


def test_submit_for_approval_opens_management_task_and_return_to_draft(
    buyer: User, manager: User, commit: Callable, published: list
) -> None:
    order = draft_order(buyer, [line(raw_material(), "100", "50")])
    with commit():
        services.submit_for_approval(buyer, order)
    order.refresh_from_db()
    assert order.status == Status.PENDING_APPROVAL
    assert order.approval_total_try == Decimal("5000.00")
    task = Task.objects.get(rule_code="purchase_order_approval")
    assert task.assigned_role is not None and task.assigned_role.name == "yonetim"
    # Tutar binlik ayırıcıyla yazılır (5000.00 değil).
    assert "tutar 5.000,00 TRY (5.000,00 TL)" in task.description
    with pytest.raises(PermissionDenied):
        services.return_to_draft(buyer, order, "neden")
    with pytest.raises(BusinessRuleError):
        services.return_to_draft(manager, order, "  ")
    with commit():
        services.return_to_draft(manager, order, "Fiyat yüksek, tekrar teklif alın")
    order.refresh_from_db()
    assert order.status == Status.DRAFT
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    assert Notification.objects.filter(rule_code="purchase_order_returned").exists()
    with commit():
        services.submit_for_approval(buyer, order)
        services.approve_order(manager, order)
    assert ev.PURCHASE_ORDER_APPROVED in [e.name for e in published]


def test_approved_order_notifies_depo(manager: User, depo: User, commit: Callable) -> None:
    with commit():
        order = approved_order(manager, [line(raw_material(code="LAS"), "500", "10")])
    note = Notification.objects.get(rule_code="expected_delivery", recipient=depo)
    assert order.number in note.title
    assert "LAS" in note.body


def test_empty_order_cannot_be_approved(manager: User) -> None:
    order = draft_order(manager, [])
    with pytest.raises(BusinessRuleError) as exc:
        services.approve_order(manager, order)
    assert exc.value.code == "document_empty"


def test_only_draft_order_can_be_edited(buyer: User, manager: User) -> None:
    order = approved_order(manager, [line(raw_material())])
    with pytest.raises(BusinessRuleError) as exc:
        services.update_order(buyer, order, {"notes": "x"})
    assert exc.value.code == "document_locked"


def test_order_roles(make_user: Callable[..., User]) -> None:
    lab = make_user(LABORATUVAR)
    with pytest.raises(PermissionDenied):
        draft_order(lab, [line(raw_material())])


def test_order_rejects_non_purchasable_material_and_bad_dates(buyer: User) -> None:
    from apps.masterdata.tests.factories import BulkMaterialFactory

    with pytest.raises(BusinessRuleError) as exc:
        draft_order(buyer, [line(BulkMaterialFactory.create())])
    assert exc.value.code == "purchase_material_type"
    with pytest.raises(BusinessRuleError) as exc:
        draft_order(buyer, [line(raw_material(), expected_date=date(2026, 1, 1))])
    assert exc.value.code == "invalid_expected_date"


# --- durum makinesi --------------------------------------------------------------------------


def test_order_state_machine_allowed_and_forbidden_transitions() -> None:
    allowed = {
        ("DRAFT", "PENDING_APPROVAL"),
        ("DRAFT", "APPROVED"),
        ("DRAFT", "CANCELLED"),
        ("PENDING_APPROVAL", "APPROVED"),
        ("PENDING_APPROVAL", "DRAFT"),
        ("PENDING_APPROVAL", "CANCELLED"),
        ("APPROVED", "SENT"),
        ("APPROVED", "PARTIALLY_RECEIVED"),
        ("APPROVED", "RECEIVED"),
        ("APPROVED", "CANCELLED"),
        ("SENT", "PARTIALLY_RECEIVED"),
        ("SENT", "RECEIVED"),
        ("SENT", "CANCELLED"),
        ("PARTIALLY_RECEIVED", "RECEIVED"),
    }
    for source in purchase_order_states.states:
        for target in purchase_order_states.states:
            assert purchase_order_states.can_transition(source, target) == (
                (source, target) in allowed
            ), (source, target)
    with pytest.raises(BusinessRuleError):
        purchase_order_states.assert_can_transition("RECEIVED", "CANCELLED")
    assert purchase_request_states.can_transition("ORDERED", "OPEN")
    assert not purchase_request_states.can_transition("CANCELLED", "OPEN")


def test_full_order_lifecycle_through_services(
    buyer: User, manager: User, depo: User, invariants: None
) -> None:
    set_limit(manager, "100000")
    material = raw_material()
    order = draft_order(buyer, [line(material, "100", "10")])
    order = services.approve_order(buyer, order)
    order = services.mark_sent(buyer, order)
    assert order.status == Status.SENT and order.sent_to == ""
    receipt = services.create_receipt_from_order(
        depo,
        order,
        {"receipt_date": date(2026, 10, 18), **receipt_locations()},
        [{"order_line": order.lines.get().pk, "quantity": Decimal("40")}],
    )
    inventory.post_goods_receipt(depo, receipt)
    order.refresh_from_db()
    assert order.status == Status.PARTIALLY_RECEIVED
    with pytest.raises(BusinessRuleError):
        services.close_order(buyer, order, "")
    order = services.close_order(buyer, order, "Tedarikçi kalanı gönderemiyor")
    assert order.status == Status.RECEIVED
    assert order.closed_note == "Tedarikçi kalanı gönderemiyor"


# --- gönderim: PDF ve e-posta ----------------------------------------------------------------


def test_send_by_email_attaches_pdf(buyer: User, manager: User) -> None:
    supplier = SupplierFactory.create(email="satis@tedarikci.com")
    order = approved_order(manager, [line(raw_material())], supplier=supplier)
    with pytest.raises(BusinessRuleError) as exc:
        services.mark_sent(buyer, order, email="gecersiz")
    assert exc.value.code == "invalid_email"
    order = services.mark_sent(buyer, order, email="satis@tedarikci.com")
    assert order.status == Status.SENT
    assert order.sent_to == "satis@tedarikci.com"
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["satis@tedarikci.com"]
    assert order.number in message.subject
    name, content, mimetype = message.attachments[0]
    assert name == f"{order.number}.pdf" and mimetype == "application/pdf"
    assert content[:4] == b"%PDF"


def test_failed_email_keeps_order_approved(
    buyer: User, manager: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = approved_order(manager, [line(raw_material())])

    def boom(*args: object, **kwargs: object) -> int:
        raise OSError("smtp down")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", boom)
    with pytest.raises(BusinessRuleError) as exc:
        services.mark_sent(buyer, order, email="a@b.com")
    assert exc.value.code == "email_failed"
    order.refresh_from_db()
    assert order.status == Status.APPROVED


def test_pdf_renders(manager: User) -> None:
    order = approved_order(
        manager,
        [line(raw_material(name="Soda külü"), "1250.5", "12.3456")],
        currency="EUR",
        exchange_rate=Decimal("36.5"),
        notes="Paletli teslim",
    )
    assert purchase_order_pdf(order)[:4] == b"%PDF"


# --- talep -----------------------------------------------------------------------------------


def test_manual_request_opens_purchasing_task_and_links_to_order(
    depo: User, buyer: User, manager: User, commit: Callable
) -> None:
    material = raw_material()
    with commit():
        request = services.create_request(
            depo,
            {
                "material": material,
                "quantity": Decimal("250"),
                "need_date": date(2026, 10, 25),
                "reason": "Sayımda eksik çıktı",
            },
        )
    assert request.number.startswith("ST-")
    assert request.status == PurchaseRequest.Status.OPEN
    task = Task.objects.get(rule_code="purchase_request")
    assert task.assigned_role is not None and task.assigned_role.name == "satin_alma"
    with commit():
        order = draft_order(buyer, [line(material, "250", requests=[request])])
    request.refresh_from_db()
    assert request.status == PurchaseRequest.Status.ORDERED
    assert request.order_line == order.lines.get()
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    # Sipariş iptal edilince talep yeniden açılır.
    services.cancel_order(manager, order, "Tedarikçi değişti")
    request.refresh_from_db()
    assert request.status == PurchaseRequest.Status.OPEN
    assert request.order_line is None


def test_removing_line_reopens_request(buyer: User) -> None:
    material = raw_material()
    request = services.create_request(
        buyer, {"material": material, "quantity": Decimal("5"), "need_date": ORDER_DATE}
    )
    order = draft_order(buyer, [line(material, "5", requests=[request])])
    services.update_order(buyer, order, {}, [])
    request.refresh_from_db()
    assert request.status == PurchaseRequest.Status.OPEN


def test_request_rules(depo: User, make_user: Callable[..., User], buyer: User) -> None:
    lab = make_user(LABORATUVAR)
    data = {"material": raw_material(), "quantity": Decimal("1"), "need_date": ORDER_DATE}
    with pytest.raises(PermissionDenied):
        services.create_request(lab, data)
    with pytest.raises(BusinessRuleError):
        services.create_request(depo, {**data, "quantity": Decimal("0")})
    request = services.create_request(depo, data)
    other = make_user("depo")
    with pytest.raises(PermissionDenied):
        services.update_request(other, request, {"quantity": Decimal("2")})
    services.update_request(depo, request, {"quantity": Decimal("2")})
    material = request.material
    with pytest.raises(BusinessRuleError) as exc:
        draft_order(buyer, [line(raw_material(), requests=[request])])
    assert exc.value.code == "request_material_mismatch"
    services.cancel_request(buyer, request, "Gerek kalmadı")
    request.refresh_from_db()
    assert request.status == PurchaseRequest.Status.CANCELLED
    with pytest.raises(BusinessRuleError) as exc:
        draft_order(buyer, [line(material, requests=[request])])
    assert exc.value.code == "request_not_open"


# --- talep önerisi (kabul kriteri) -----------------------------------------------------------


def test_suggestions_from_min_stock_and_open_production_orders(
    planner: User, buyer: User, manager: User, invariants: None
) -> None:
    """Kabul kriteri: minimum stok ve açık emir ihtiyaçlarından talep öneriliyor.

    Reçete 1000 kg: LAS 600, SLES 300, su 100 (su sayılmaz). İki emir (1000 + 1000 kg)
    → LAS ihtiyacı 1200, SLES 600."""
    plant = build_plant(planner, stock=False)
    plant.las.min_stock = Decimal("500")
    plant.las.save()
    stocked_lot("700", material=plant.las, location=plant.storage)  # serbest
    stocked_lot("100", material=plant.las, location=plant.quarantine, status=Lot.Status.QUARANTINE)
    bad = stocked_lot(
        "999", material=plant.las, location=plant.quarantine, status=Lot.Status.QUARANTINE
    )
    inventory.reject_lot(planner, bad, "Spesifikasyon dışı", quality_decision=True)
    stocked_lot("50", material=plant.sles, location=plant.storage)
    approved_production_order(plant, planner)
    approved_production_order(plant, planner)
    # LAS için 150 kg yolda (onaylı sipariş), 50 kg açık talep.
    approved_order(manager, [line(plant.las, "150")])
    services.create_request(
        buyer, {"material": plant.las, "quantity": Decimal("50"), "need_date": ORDER_DATE}
    )
    suggestions = {s.material.code: s for s in selectors.purchase_suggestions(today=ORDER_DATE)}
    las = suggestions["LAS"]
    assert las.demand == Decimal("1200")
    assert las.min_stock == Decimal("500")
    assert las.free_stock == Decimal("800")  # serbest + karantina; red sayılmaz
    assert las.open_orders == Decimal("150")
    assert las.open_requests == Decimal("50")
    assert las.suggested == Decimal("700")  # 1200 + 500 − 800 − 150 − 50
    assert las.need_date == date(2026, 10, 20)
    assert [s["order_number"] for s in las.sources] == [
        s["order_number"] for s in sorted(las.sources, key=lambda r: r["order_number"])
    ]
    sles = suggestions["SLES"]
    assert sles.suggested == Decimal("550")  # 600 − 50, minimum stok yok
    assert "SU" not in suggestions  # şebeke suyu (D-1) satın alınmaz


def test_consumed_requirements_are_not_suggested(planner: User) -> None:
    plant = build_plant(planner, stock=False)
    plant.sles.min_stock = Decimal("10")
    plant.sles.save()
    stocked_lot("10", material=plant.sles, location=plant.storage)
    assert "SLES" not in {s.material.code for s in selectors.purchase_suggestions()}


def test_daily_check_opens_auto_requests_once(planner: User, commit: Callable) -> None:
    plant = build_plant(planner, stock=False)
    approved_production_order(plant, planner)
    from apps.core import events

    with commit():
        events.publish(ev.DAILY_CHECK, {"date": ORDER_DATE.isoformat()})
    auto = PurchaseRequest.objects.filter(source=PurchaseRequest.Source.AUTO)
    assert {r.material.code: r.quantity for r in auto} == {
        "LAS": Decimal("600"),
        "SLES": Decimal("300"),
    }
    assert "Otomatik öneri" in auto.first().reason  # type: ignore[union-attr]
    assert Task.objects.filter(rule_code="purchase_request").count() == 2
    with commit():
        events.publish(ev.DAILY_CHECK, {"date": ORDER_DATE.isoformat()})
    assert auto.count() == 2


# --- siparişten mal kabul (kabul kriteri) ----------------------------------------------------


def test_receipt_from_order_decreases_pending_quantity(
    buyer: User, manager: User, depo: User, commit: Callable, invariants: None
) -> None:
    """Kabul kriteri: siparişe bağlı mal kabul bekleyen miktarı doğru düşüyor."""
    las = raw_material(code="LAS")
    order = approved_order(
        manager,
        [line(las, "1000", "2.5"), line(raw_material(code="SLES"), "200", "4")],
        currency="EUR",
        exchange_rate=Decimal("36"),
    )
    las_line, sles_line = order.lines.order_by("line_no")
    receipt = services.create_receipt_from_order(
        depo,
        order,
        {"receipt_date": date(2026, 10, 18), "delivery_note_no": "IRS-1", **receipt_locations()},
        [
            {"order_line": las_line.pk, "quantity": Decimal("600"), "supplier_lot_no": "A1"},
            {"order_line": sles_line.pk, "quantity": Decimal("200")},
        ],
    )
    assert receipt.supplier == order.supplier
    first = receipt.lines.get(line_no=1)
    assert first.unit_price == Decimal("2.5")
    assert first.currency == "EUR" and first.exchange_rate == Decimal("36")
    assert first.unit == las_line.unit
    # Taslak mal kabul bekleyen miktarı düşmez.
    pending = {line.pk: line for line in selectors.open_order_lines()}
    assert pending[las_line.pk].pending_quantity == Decimal("1000")  # type: ignore[attr-defined]
    with commit():
        inventory.post_goods_receipt(depo, receipt)
    order.refresh_from_db()
    assert order.status == Status.PARTIALLY_RECEIVED
    pending = {line.pk: line for line in selectors.open_order_lines()}
    assert pending[las_line.pk].pending_quantity == Decimal("400")  # type: ignore[attr-defined]
    assert sles_line.pk not in pending
    second = services.create_receipt_from_order(
        depo,
        order,
        {"receipt_date": date(2026, 10, 19), **receipt_locations()},
        [{"order_line": las_line.pk, "quantity": Decimal("400")}],
    )
    with commit():
        inventory.post_goods_receipt(depo, second)
    order.refresh_from_db()
    assert order.status == Status.RECEIVED
    assert selectors.open_order_lines() == []
    assert Notification.objects.filter(rule_code="purchase_order_received").exists()


def test_over_receipt_tolerance(buyer: User, manager: User, depo: User, invariants: None) -> None:
    order = approved_order(manager, [line(raw_material(), "100")])
    order_line = order.lines.get()
    header = {"receipt_date": date(2026, 10, 18), **receipt_locations()}
    with pytest.raises(BusinessRuleError) as exc:
        services.create_receipt_from_order(
            depo, order, header, [{"order_line": order_line.pk, "quantity": Decimal("110.01")}]
        )
    assert exc.value.code == "over_receipt"
    receipt = services.create_receipt_from_order(
        depo, order, header, [{"order_line": order_line.pk, "quantity": Decimal("110")}]
    )
    # Taslaktaki miktar da sayılır: ikinci taslak toleransı aşamaz.
    with pytest.raises(BusinessRuleError):
        services.create_receipt_from_order(
            depo, order, header, [{"order_line": order_line.pk, "quantity": Decimal("1")}]
        )
    # Depo ekranında taslak büyütülürse kayıtta reddedilir.
    receipt_line = receipt.lines.get()
    inventory.update_goods_receipt(
        depo, receipt, {}, [{"id": receipt_line.pk, "quantity": Decimal("150")}]
    )
    with pytest.raises(BusinessRuleError) as exc:
        inventory.post_goods_receipt(depo, receipt)
    assert exc.value.code == "over_receipt"
    receipt.refresh_from_db()
    assert receipt.status == GoodsReceipt.Status.DRAFT
    inventory.update_goods_receipt(
        depo, receipt, {}, [{"id": receipt_line.pk, "quantity": Decimal("110")}]
    )
    inventory.post_goods_receipt(depo, receipt)
    order.refresh_from_db()
    assert order.status == Status.RECEIVED


def test_receipt_rules(buyer: User, manager: User, depo: User) -> None:
    draft = draft_order(buyer, [line(raw_material())])
    header = {"receipt_date": date(2026, 10, 18), **receipt_locations()}
    with pytest.raises(BusinessRuleError) as exc:
        services.create_receipt_from_order(
            depo, draft, header, [{"order_line": draft.lines.get().pk, "quantity": Decimal("1")}]
        )
    assert exc.value.code == "order_not_receivable"
    order = approved_order(manager, [line(raw_material())])
    with pytest.raises(BusinessRuleError) as exc:
        services.create_receipt_from_order(
            depo, order, header, [{"order_line": draft.lines.get().pk, "quantity": Decimal("1")}]
        )
    assert exc.value.code == "line_not_found"
    receipt = services.create_receipt_from_order(
        depo, order, header, [{"order_line": order.lines.get().pk, "quantity": Decimal("1")}]
    )
    # Bağlı mal kabul varken sipariş iptal edilemez; mal kabul iptal edilince edilebilir.
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_order(manager, order, "vazgeçtik")
    assert exc.value.code == "order_has_receipts"
    inventory.cancel_goods_receipt(depo, receipt, "yanlış")
    assert services.cancel_order(manager, order, "vazgeçtik").status == Status.CANCELLED
    # İptal edilmiş siparişe bağlı mal kabul kaydedilemez.
    order2 = approved_order(manager, [line(raw_material())])
    receipt2 = services.create_receipt_from_order(
        depo, order2, header, [{"order_line": order2.lines.get().pk, "quantity": Decimal("1")}]
    )
    PurchaseOrder.objects.filter(pk=order2.pk).update(status=Status.CANCELLED)
    with pytest.raises(BusinessRuleError) as exc:
        inventory.post_goods_receipt(depo, receipt2)
    assert exc.value.code == "order_not_receivable"


def test_receipt_without_order_is_unaffected(depo: User, invariants: None) -> None:
    material = raw_material()
    receipt = inventory.create_goods_receipt(
        depo,
        {
            "supplier": SupplierFactory.create(),
            "receipt_date": date(2026, 10, 18),
            **receipt_locations(),
        },
        [{"material": material, "quantity": Decimal("5"), "unit": unit("KG")}],
    )
    assert inventory.post_goods_receipt(depo, receipt).status == GoodsReceipt.Status.POSTED


# --- tedarikçi performansı -------------------------------------------------------------------


def test_supplier_performance(
    manager: User, depo: User, make_user: Callable[..., User], invariants: None
) -> None:
    supplier = SupplierFactory.create(name="Kimya A.Ş.")
    header = receipt_locations()
    order = approved_order(
        manager,
        [
            line(raw_material(), "100", expected_date=date(2026, 10, 20)),
            line(raw_material(), "100", expected_date=date(2026, 10, 20)),
            line(raw_material(), "100", expected_date=date(2026, 12, 30)),  # vadesi gelmemiş
        ],
        supplier=supplier,
    )
    first, second, _future = order.lines.order_by("line_no")
    on_time = services.create_receipt_from_order(
        depo,
        order,
        {"receipt_date": date(2026, 10, 19), **header},
        [{"order_line": first.pk, "quantity": Decimal("100")}],
    )
    late = services.create_receipt_from_order(
        depo,
        order,
        {"receipt_date": date(2026, 10, 25), **header},
        [{"order_line": second.pk, "quantity": Decimal("100")}],
    )
    inventory.post_goods_receipt(depo, on_time)
    inventory.post_goods_receipt(depo, late)
    rejected = late.lines.get().created_lot
    assert rejected is not None
    inventory.reject_lot(make_user("admin"), rejected, "Spesifikasyon dışı", quality_decision=True)
    rows = selectors.supplier_performance(
        date(2026, 10, 1), date(2026, 12, 31), today=date(2026, 11, 1)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.supplier == supplier
    assert (row.due_lines, row.on_time_lines) == (2, 1)
    assert row.on_time_rate == Decimal("50.0")
    assert (row.received_lots, row.rejected_lots) == (2, 1)
    assert row.reject_rate == Decimal("50.0")


def test_lot_rejected_notification_names_supplier(
    depo: User, make_user: Callable[..., User], buyer: User, commit: Callable
) -> None:
    supplier = SupplierFactory.create(name="Kimya A.Ş.")
    receipt = inventory.create_goods_receipt(
        depo,
        {"supplier": supplier, "receipt_date": date(2026, 10, 18), **receipt_locations()},
        [{"material": raw_material(), "quantity": Decimal("5"), "unit": unit("KG")}],
    )
    inventory.post_goods_receipt(depo, receipt)
    lot = receipt.lines.get().created_lot
    assert lot is not None
    with commit():
        inventory.reject_lot(make_user("admin"), lot, "Renk farklı", quality_decision=True)
    note = Notification.objects.get(rule_code="lot_rejected", recipient=buyer)
    assert "Tedarikçi: Kimya A.Ş." in note.body
