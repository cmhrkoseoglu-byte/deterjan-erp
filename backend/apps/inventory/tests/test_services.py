from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.core import event_names as ev
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.inventory import services
from apps.inventory.models import (
    GoodsReceipt,
    Lot,
    LotLink,
    StockAdjustment,
    StockBalance,
    StockMovement,
)
from apps.inventory.tests.factories import quarantine_location, stocked_lot, storage_location
from apps.masterdata.models import Location, Material
from apps.masterdata.tests.factories import (
    BulkMaterialFactory,
    LocationFactory,
    MaterialFactory,
    SupplierFactory,
    unit,
)

pytestmark = pytest.mark.usefixtures("invariants")
T = StockMovement.Type
D = Decimal


def balance(lot: Lot, location: Location) -> Decimal:
    return services.current_balance(lot, location)


# --- post_movement ---------------------------------------------------------------------------


def test_post_movement_updates_balance_and_records_movement(depo):
    loc = storage_location()
    lot = stocked_lot("100", location=loc, actor=depo)
    movement = services.post_movement(
        depo, lot.material, lot, loc, D("-30.12345"), T.SCRAP, None, "Döküldü"
    )
    assert movement.quantity == D("-30.1235")  # 4 ondalığa yuvarlanır
    assert movement.created_by == depo
    assert balance(lot, loc) == D("69.8765")


def test_post_movement_rejects_negative_stock(depo):
    loc = storage_location()
    lot = stocked_lot("10", location=loc)
    with pytest.raises(BusinessRuleError) as exc:
        services.post_movement(depo, lot.material, lot, loc, D("-10.0001"), T.SCRAP, None)
    assert exc.value.code == "negative_stock"
    assert "10" in exc.value.message
    assert balance(lot, loc) == D("10")
    assert StockMovement.objects.filter(lot=lot).count() == 1


def test_post_movement_from_empty_location_is_negative_stock(depo):
    lot = stocked_lot("10")
    with pytest.raises(BusinessRuleError) as exc:
        services.post_movement(depo, lot.material, lot, storage_location(), D("-1"), T.SCRAP, None)
    assert exc.value.code == "negative_stock"


def test_post_movement_validations(depo):
    loc = storage_location()
    lot = stocked_lot("10", location=loc)
    with pytest.raises(BusinessRuleError) as exc:
        services.post_movement(depo, lot.material, lot, loc, D("0.00001"), T.RECEIPT, None)
    assert exc.value.code == "zero_quantity"
    with pytest.raises(ValueError):
        services.post_movement(depo, lot.material, lot, loc, D("-1"), T.RECEIPT, None)
    with pytest.raises(ValueError):
        services.post_movement(depo, lot.material, lot, loc, D("1"), T.SHIPMENT, None)
    with pytest.raises(ValueError):
        services.post_movement(depo, MaterialFactory(), lot, loc, D("1"), T.RECEIPT, None)
    with pytest.raises(TypeError):
        services.post_movement(depo, lot.material, lot, loc, 1.0, T.RECEIPT, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        services.post_movement(depo, lot.material, lot, loc, D("1"), T.REVERSAL, None)
    inactive = storage_location(is_active=False)
    with pytest.raises(BusinessRuleError) as exc:
        services.post_movement(depo, lot.material, lot, inactive, D("1"), T.RECEIPT, None)
    assert exc.value.code == "inactive_reference"


@pytest.mark.parametrize("status", [Lot.Status.QUARANTINE, Lot.Status.BLOCKED])
def test_issue_to_production_requires_released_lot(depo, lab, status):
    loc = storage_location()
    lot = stocked_lot("10", location=loc, status=Lot.Status.QUARANTINE)
    if status == Lot.Status.BLOCKED:
        services.block_lot(lab, lot, "Şikâyet")
    with pytest.raises(BusinessRuleError) as exc:
        services.post_movement(depo, lot.material, lot, loc, D("-1"), T.ISSUE_PRODUCTION, None)
    assert exc.value.code == "lot_not_released"
    # Transfer ve fire karantinadaki lota da yapılabilir.
    services.transfer(depo, lot, loc, storage_location(), D("2"))
    services.post_movement(depo, lot.material, lot, loc, D("-1"), T.SCRAP, None)


def test_expired_lot_cannot_be_issued_or_shipped(depo):
    loc = storage_location()
    yesterday = timezone.localdate() - timedelta(days=1)
    lot = stocked_lot("10", location=loc, expiry_date=yesterday)
    for movement_type in (T.ISSUE_PRODUCTION, T.SHIPMENT):
        with pytest.raises(BusinessRuleError) as exc:
            services.post_movement(depo, lot.material, lot, loc, D("-1"), movement_type, None)
        assert exc.value.code == "lot_expired"
    today_lot = stocked_lot("10", location=loc, expiry_date=timezone.localdate())
    services.post_movement(
        depo, today_lot.material, today_lot, loc, D("-1"), T.ISSUE_PRODUCTION, None
    )


def test_movement_records_source_document(depo):
    supplier = SupplierFactory()
    receipt = services.create_goods_receipt(
        depo,
        {
            "supplier": supplier,
            "receipt_date": timezone.localdate(),
            "storage_location": storage_location(),
        },
        [
            {
                "material": MaterialFactory(requires_incoming_qc=False),
                "quantity": D("5"),
                "unit": unit("KG"),
            }
        ],
    )
    services.post_goods_receipt(depo, receipt)
    movement = StockMovement.objects.get(movement_type=T.RECEIPT)
    assert movement.source == receipt
    assert movement.document_number == receipt.number


# --- değiştirilemezlik -----------------------------------------------------------------------


def test_movements_and_links_are_immutable(depo):
    lot = stocked_lot("10")
    movement = StockMovement.objects.get(lot=lot)
    movement.note = "değişti"
    with pytest.raises(TypeError):
        movement.save()
    with pytest.raises(TypeError):
        movement.delete()
    with pytest.raises(TypeError):
        StockMovement.objects.filter(pk=movement.pk).update(note="x")
    with pytest.raises(TypeError):
        StockMovement.objects.filter(pk=movement.pk).delete()
    link = services.link_lots(depo, lot, stocked_lot("1"), D("1"))
    with pytest.raises(TypeError):
        link.delete()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE inventory_stockmovement SET note = 'x'",
        "DELETE FROM inventory_stockmovement",
        "UPDATE inventory_lotlink SET quantity = 1",
        "DELETE FROM inventory_lotlink",
    ],
)
def test_database_trigger_blocks_raw_changes(sql, depo):
    parent = stocked_lot("10")
    services.link_lots(depo, parent, stocked_lot("1"), D("1"))
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql)


# --- transfer ve ters kayıt ------------------------------------------------------------------


def test_transfer_moves_stock_with_shared_group(depo):
    a, b = storage_location(), storage_location()
    lot = stocked_lot("50", location=a)
    out, into = services.transfer(depo, lot, a, b, D("20"), note="Raf değişimi")
    assert out.movement_type == T.TRANSFER_OUT and out.quantity == D("-20")
    assert into.movement_type == T.TRANSFER_IN and into.quantity == D("20")
    assert out.transfer_group == into.transfer_group is not None
    assert balance(lot, a) == D("30") and balance(lot, b) == D("20")


def test_transfer_rules(depo):
    a = storage_location()
    lot = stocked_lot("5", location=a)
    with pytest.raises(BusinessRuleError) as exc:
        services.transfer(depo, lot, a, a, D("1"))
    assert exc.value.code == "same_location"
    with pytest.raises(BusinessRuleError) as exc:
        services.transfer(depo, lot, a, storage_location(), D("6"))
    assert exc.value.code == "negative_stock"
    assert not StockMovement.objects.filter(movement_type=T.TRANSFER_IN).exists()
    with pytest.raises(BusinessRuleError) as exc:
        services.transfer(depo, lot, a, storage_location(), D("0"))
    assert exc.value.code == "invalid_quantity"


def test_reverse_movement(depo):
    loc = storage_location()
    lot = stocked_lot("10", location=loc)
    scrap = services.post_movement(depo, lot.material, lot, loc, D("-4"), T.SCRAP, None)
    [reversal] = services.reverse_movement(depo, scrap, "Yanlış giriş")
    assert reversal.movement_type == T.REVERSAL
    assert reversal.quantity == D("4") and reversal.reversal_of == scrap
    assert balance(lot, loc) == D("10")
    with pytest.raises(BusinessRuleError) as exc:
        services.reverse_movement(depo, scrap, "Tekrar")
    assert exc.value.code == "already_reversed"
    with pytest.raises(BusinessRuleError) as exc:
        services.reverse_movement(depo, reversal, "Geri al")
    assert exc.value.code == "cannot_reverse_reversal"
    with pytest.raises(BusinessRuleError) as exc:
        services.reverse_movement(depo, StockMovement.objects.get(movement_type=T.RECEIPT), " ")
    assert exc.value.code == "reversal_reason_required"


def test_reverse_transfer_reverses_both_legs(depo):
    a, b = storage_location(), storage_location()
    lot = stocked_lot("10", location=a)
    out, _ = services.transfer(depo, lot, a, b, D("10"))
    reversals = services.reverse_movement(depo, out, "Yanlış lokasyon")
    assert len(reversals) == 2
    assert balance(lot, a) == D("10") and balance(lot, b) == D("0")


def test_reversal_cannot_make_stock_negative(depo):
    loc = storage_location()
    lot = stocked_lot("10", location=loc)
    receipt_movement = StockMovement.objects.get(lot=lot)
    services.post_movement(depo, lot.material, lot, loc, D("-6"), T.SCRAP, None)
    with pytest.raises(BusinessRuleError) as exc:
        services.reverse_movement(depo, receipt_movement, "Hatalı kabul")
    assert exc.value.code == "negative_stock"


# --- lot numarası ve lot -----------------------------------------------------------------------


def test_lot_numbers_follow_decision_d2():
    day = date(2026, 10, 15)
    assert services.next_lot_number("H", day) == "H-261015-001"
    assert services.next_lot_number("H", day) == "H-261015-002"
    assert services.next_lot_number("B", day) == "B-261015-001"
    assert services.next_lot_number("H", date(2026, 10, 16)) == "H-261016-001"
    with pytest.raises(ValueError):
        services.next_lot_number("X", day)


def test_create_lot_defaults(depo):
    material = MaterialFactory(shelf_life_days=365)
    lot = services.create_lot(
        depo, material=material, source=Lot.Source.PRODUCTION, manufactured_at=date(2026, 1, 1)
    )
    assert lot.lot_no.startswith("B-")
    assert lot.status == Lot.Status.QUARANTINE
    assert lot.expiry_date == date(2027, 1, 1)
    assert AuditLog.objects.filter(object_id=lot.pk, action=AuditLog.Action.CREATE).exists()
    released = services.create_lot(
        depo, material=material, source=Lot.Source.PURCHASE, status=Lot.Status.RELEASED
    )
    assert released.released_by == depo and released.released_at is not None


def test_create_lot_rules(depo):
    material = MaterialFactory()
    services.create_lot(depo, material=material, source=Lot.Source.OPENING, lot_no="eski-1")
    with pytest.raises(BusinessRuleError) as exc:
        services.create_lot(depo, material=material, source=Lot.Source.OPENING, lot_no="ESKI-1")
    assert exc.value.code == "lot_exists"
    with pytest.raises(BusinessRuleError) as exc:
        services.create_lot(depo, material=material, source=Lot.Source.OPENING)
    assert exc.value.code == "lot_no_required"
    with pytest.raises(BusinessRuleError) as exc:
        services.create_lot(
            depo,
            material=material,
            source=Lot.Source.PURCHASE,
            manufactured_at=date(2026, 5, 1),
            expiry_date=date(2026, 4, 1),
        )
    assert exc.value.code == "invalid_expiry_date"


def test_link_lots(depo):
    raw = stocked_lot("10")
    bulk = services.create_lot(depo, material=BulkMaterialFactory(), source=Lot.Source.PRODUCTION)
    link = services.link_lots(depo, raw, bulk, D("2.5"))
    assert (link.parent_lot, link.child_lot, link.quantity) == (raw, bulk, D("2.5"))
    with pytest.raises(BusinessRuleError) as exc:
        services.link_lots(depo, raw, raw, D("1"))
    assert exc.value.code == "lot_self_link"
    with pytest.raises(BusinessRuleError) as exc:
        services.link_lots(depo, raw, bulk, D("0"))
    assert exc.value.code == "invalid_quantity"


# --- mal kabul -------------------------------------------------------------------------------


@pytest.fixture
def receipt_setup(depo):
    return {
        "supplier": SupplierFactory(),
        "quarantine": quarantine_location(),
        "storage": storage_location(),
        "qc_material": MaterialFactory(
            code="HM-LAS", requires_incoming_qc=True, shelf_life_days=730
        ),
        "packaging": MaterialFactory(
            code="AMB-SISE",
            material_type=Material.Type.PACKAGING,
            requires_incoming_qc=False,
            base_unit=unit("ADET"),
        ),
    }


def _receipt(depo, setup, lines=None, **header):
    data = {
        "supplier": setup["supplier"],
        "receipt_date": date(2026, 10, 15),
        "delivery_note_no": "IRS-1",
        "quarantine_location": setup["quarantine"],
        "storage_location": setup["storage"],
        **header,
    }
    if lines is None:
        lines = [
            {
                "material": setup["qc_material"],
                "quantity": D("1250"),
                "unit": unit("KG"),
                "supplier_lot_no": "S-77",
            },
            {"material": setup["packaging"], "quantity": D("500"), "unit": unit("ADET")},
        ]
    return services.create_goods_receipt(depo, data, lines)


def test_post_goods_receipt_creates_lots_and_movements(depo, receipt_setup, published, commit):
    receipt = _receipt(depo, receipt_setup)
    assert receipt.number.startswith("MK-") and receipt.status == GoodsReceipt.Status.DRAFT
    with commit():
        services.post_goods_receipt(depo, receipt)
    receipt.refresh_from_db()
    assert receipt.status == GoodsReceipt.Status.POSTED
    assert receipt.posted_by == depo
    qc_line, pack_line = receipt.lines.order_by("line_no")
    qc_lot, pack_lot = qc_line.created_lot, pack_line.created_lot
    assert qc_lot.lot_no == "H-261015-001" and pack_lot.lot_no == "H-261015-002"
    assert qc_lot.status == Lot.Status.QUARANTINE and qc_lot.supplier_lot_no == "S-77"
    assert qc_lot.supplier == receipt_setup["supplier"]
    assert qc_lot.expiry_date == date(2026, 10, 15) + timedelta(days=730)
    assert pack_lot.status == Lot.Status.RELEASED
    assert balance(qc_lot, receipt_setup["quarantine"]) == D("1250")
    assert balance(pack_lot, receipt_setup["storage"]) == D("500")

    [event] = [e for e in published if e.name == ev.GOODS_RECEIPT_POSTED]
    assert event.payload["number"] == receipt.number
    assert event.payload["lots"] == [
        {
            "model": "inventory.lot",
            "id": qc_lot.pk,
            "lot_no": qc_lot.lot_no,
            "material_code": "HM-LAS",
            "material_name": qc_lot.material.name,
            "requires_qc": True,
        },
        {
            "model": "inventory.lot",
            "id": pack_lot.pk,
            "lot_no": pack_lot.lot_no,
            "material_code": "AMB-SISE",
            "material_name": pack_lot.material.name,
            "requires_qc": False,
        },
    ]


def test_goods_receipt_opens_incoming_sample_and_qc_task(depo, receipt_setup, commit, make_user):
    """Faz 2: mal kabul kaydedilince giriş numunesi açılır, görev numuneye bağlıdır (karar ve
    görevin kapanışı quality testlerinde)."""
    from apps.quality.models import Sample
    from apps.workflow.models import Task

    make_user("laboratuvar")
    receipt = _receipt(depo, receipt_setup)
    with commit():
        services.post_goods_receipt(depo, receipt)
    lot = receipt.lines.get(line_no=1).created_lot
    sample = Sample.objects.get(lot=lot)
    assert sample.stage == "INCOMING" and sample.origin == "GOODS_RECEIPT"
    task = Task.objects.get(rule_code="incoming_qc")
    assert task.title == f"Giriş kontrolü: {lot.lot_no}"
    assert task.related_object_id == sample.pk
    assert task.status == Task.Status.OPEN


def test_goods_receipt_converts_units_to_base(depo, receipt_setup):
    receipt = _receipt(
        depo,
        receipt_setup,
        lines=[
            {"material": receipt_setup["qc_material"], "quantity": D("2500"), "unit": unit("G")}
        ],
    )
    services.post_goods_receipt(depo, receipt)
    line = receipt.lines.get()
    assert line.base_quantity == D("2.5")
    assert balance(line.created_lot, receipt_setup["quarantine"]) == D("2.5")


def test_goods_receipt_line_sync_and_draft_lock(depo, receipt_setup):
    receipt = _receipt(depo, receipt_setup)
    first, second = receipt.lines.order_by("line_no")
    services.update_goods_receipt(
        depo,
        receipt,
        {"delivery_note_no": "IRS-2"},
        [
            {"id": first.pk, "material": first.material, "quantity": D("1000"), "unit": unit("KG")},
            {"material": receipt_setup["packaging"], "quantity": D("12"), "unit": unit("ADET")},
        ],
    )
    lines = list(receipt.lines.order_by("line_no"))
    assert [(line.line_no, line.quantity) for line in lines] == [(1, D("1000")), (3, D("12"))]
    assert AuditLog.objects.filter(
        object_id=receipt.pk, note="Satır 2 kaldırıldı (taslak)"
    ).exists()
    with pytest.raises(BusinessRuleError) as exc:
        services.update_goods_receipt(depo, receipt, {}, [{"id": 999999}])
    assert exc.value.code == "line_not_found"

    services.post_goods_receipt(depo, receipt)
    with pytest.raises(BusinessRuleError) as exc:
        services.update_goods_receipt(depo, receipt, {"delivery_note_no": "X"})
    assert exc.value.code == "document_locked"
    with pytest.raises(BusinessRuleError) as exc:
        services.post_goods_receipt(depo, receipt)
    assert exc.value.code == "invalid_transition"
    with pytest.raises(BusinessRuleError) as exc:
        services.cancel_goods_receipt(depo, receipt, "Hata")
    assert exc.value.code == "invalid_transition"


def test_goods_receipt_cancel_draft(depo, receipt_setup, published, commit):
    receipt = _receipt(depo, receipt_setup)
    with commit():
        services.cancel_goods_receipt(depo, receipt, "Yanlış tedarikçi")
    receipt.refresh_from_db()
    assert receipt.status == GoodsReceipt.Status.CANCELLED
    assert ev.GOODS_RECEIPT_CANCELLED in [e.name for e in published]
    with pytest.raises(BusinessRuleError) as exc:
        services.post_goods_receipt(depo, receipt)
    assert exc.value.code == "invalid_transition"


@pytest.mark.parametrize(
    ("line_change", "header_change", "code"),
    [
        ({"material": "bulk"}, {}, "receipt_material_type"),
        ({}, {"quarantine_location": None}, "receipt_location_required"),
        ({"expiry_date": date(2026, 10, 14)}, {}, "lot_already_expired"),
        ({"unit": "ADET"}, {}, "no_conversion"),
    ],
)
def test_goods_receipt_rules(depo, receipt_setup, line_change, header_change, code):
    line = {"material": receipt_setup["qc_material"], "quantity": D("10"), "unit": unit("KG")}
    if line_change.get("material") == "bulk":
        line["material"] = BulkMaterialFactory()
    elif "unit" in line_change:
        line["unit"] = unit(line_change["unit"])
    else:
        line.update(line_change)
    with pytest.raises(BusinessRuleError) as exc:
        receipt = _receipt(depo, receipt_setup, lines=[line], **header_change)
        services.post_goods_receipt(depo, receipt)
    assert exc.value.code == code
    assert not Lot.objects.exists()


def test_goods_receipt_header_rules(depo, receipt_setup):
    with pytest.raises(BusinessRuleError) as exc:
        _receipt(depo, receipt_setup, quarantine_location=storage_location())
    assert exc.value.code == "invalid_quarantine_location"
    with pytest.raises(BusinessRuleError) as exc:
        _receipt(depo, receipt_setup, storage_location=quarantine_location())
    assert exc.value.code == "invalid_storage_location"
    with pytest.raises(BusinessRuleError) as exc:
        _receipt(depo, receipt_setup, supplier=SupplierFactory(is_active=False))
    assert exc.value.code == "inactive_reference"
    empty = _receipt(depo, receipt_setup, lines=[])
    with pytest.raises(BusinessRuleError) as exc:
        services.post_goods_receipt(depo, empty)
    assert exc.value.code == "document_empty"


# --- lot kararı ------------------------------------------------------------------------------


def test_release_lot_moves_quarantine_stock(lab, published, commit):
    quarantine, target = quarantine_location(), storage_location()
    lot = stocked_lot("80", location=quarantine, status=Lot.Status.QUARANTINE)
    with commit():
        services.release_lot(lab, lot, "Analiz uygun", to_location=target, quality_decision=True)
    lot.refresh_from_db()
    assert lot.status == Lot.Status.RELEASED
    assert lot.released_by == lab and lot.status_note == "Analiz uygun"
    assert balance(lot, quarantine) == 0 and balance(lot, target) == D("80")
    [event] = [e for e in published if e.name == ev.LOT_RELEASED]
    assert event.payload["lot_no"] == lot.lot_no
    assert event.payload["material_type"] == "RAW"
    assert event.payload["model"] == "inventory.lot"
    assert AuditLog.objects.filter(
        object_id=lot.pk,
        action=AuditLog.Action.STATUS_CHANGE,
        changes__status=["QUARANTINE", "RELEASED"],
    ).exists()


def test_release_lot_requires_target_for_quarantine_stock(lab):
    lot = stocked_lot("5", location=quarantine_location(), status=Lot.Status.QUARANTINE)
    with pytest.raises(BusinessRuleError) as exc:
        services.release_lot(lab, lot, quality_decision=True)
    assert exc.value.code == "release_location_required"
    with pytest.raises(BusinessRuleError) as exc:
        services.release_lot(lab, lot, to_location=quarantine_location(), quality_decision=True)
    assert exc.value.code == "invalid_release_location"
    lot.refresh_from_db()
    assert lot.status == Lot.Status.QUARANTINE


def test_release_bulk_lot_in_tank_needs_no_transfer(lab):
    tank = LocationFactory(location_type=Location.Type.TANK)
    lot = stocked_lot(
        "900",
        material=BulkMaterialFactory(),
        location=tank,
        status=Lot.Status.QUARANTINE,
        source=Lot.Source.PRODUCTION,
    )
    services.release_lot(lab, lot, quality_decision=True)
    assert balance(lot, tank) == D("900")


def test_release_and_reject_only_through_quality_decision(lab, depo):
    """Faz 2: laboratuvar dahil kimse lotu kalite kararı dışında serbest bırakamaz ya da
    reddedemez; bloke laboratuvarın işidir."""
    lot = stocked_lot("5", status=Lot.Status.QUARANTINE)
    for user in (lab, depo):
        with pytest.raises(PermissionDenied):
            services.release_lot(user, lot, "acil")
        with pytest.raises(PermissionDenied):
            services.reject_lot(user, lot, "x")
    with pytest.raises(PermissionDenied):
        services.block_lot(depo, lot, "x")
    lot.refresh_from_db()
    assert lot.status == Lot.Status.QUARANTINE


def test_admin_manual_release_requires_reason_and_is_audited(make_user, commit, published):
    """Karar D-5: admin gerekçe yazarak lotu elle serbest bırakabilir."""
    admin = make_user("admin")
    quarantine, target = quarantine_location(), storage_location()
    lot = stocked_lot("10", location=quarantine, status=Lot.Status.QUARANTINE)
    with pytest.raises(BusinessRuleError) as exc:
        services.release_lot(admin, lot, "  ", to_location=target)
    assert exc.value.code == "note_required"
    with commit():
        services.release_lot(admin, lot, "Laboratuvar kapalı, müşteri acil", to_location=target)
    lot.refresh_from_db()
    assert lot.status == Lot.Status.RELEASED
    assert lot.status_note == "Elle serbest bırakma (D-5): Laboratuvar kapalı, müşteri acil"
    assert AuditLog.objects.filter(
        object_id=lot.pk,
        actor=admin,
        changes__status=["QUARANTINE", "RELEASED"],
        note__startswith="Elle serbest bırakma (D-5)",
    ).exists()
    assert balance(lot, target) == D("10")


def test_reject_and_block(lab, published, commit):
    lot = stocked_lot("5", status=Lot.Status.QUARANTINE)
    with pytest.raises(BusinessRuleError) as exc:
        services.reject_lot(lab, lot, " ", quality_decision=True)
    assert exc.value.code == "note_required"
    with commit():
        services.reject_lot(lab, lot, "Aktif madde düşük", quality_decision=True)
    lot.refresh_from_db()
    assert lot.status == Lot.Status.REJECTED
    assert [e.payload["note"] for e in published if e.name == ev.LOT_REJECTED] == [
        "Aktif madde düşük"
    ]
    with pytest.raises(BusinessRuleError) as exc:
        services.release_lot(lab, lot, quality_decision=True)
    assert exc.value.code == "invalid_transition"

    other = stocked_lot("5")
    with commit():
        services.block_lot(lab, other, "Müşteri şikâyeti")
    other.refresh_from_db()
    assert other.status == Lot.Status.BLOCKED
    assert ev.LOT_BLOCKED in [e.name for e in published]
    services.release_lot(lab, other, "Şikâyet asılsız", quality_decision=True)
    other.refresh_from_db()
    assert other.status == Lot.Status.RELEASED


@pytest.mark.parametrize(
    ("start", "action", "end"),
    [
        (Lot.Status.QUARANTINE, "release", Lot.Status.RELEASED),
        (Lot.Status.QUARANTINE, "reject", Lot.Status.REJECTED),
        (Lot.Status.QUARANTINE, "block", Lot.Status.BLOCKED),
        (Lot.Status.RELEASED, "block", Lot.Status.BLOCKED),
        (Lot.Status.BLOCKED, "release", Lot.Status.RELEASED),
        (Lot.Status.BLOCKED, "reject", Lot.Status.REJECTED),
    ],
)
def test_lot_state_machine_allowed_transitions(lab, start, action, end):
    lot = services.create_lot(
        lab,
        material=MaterialFactory(),
        source=Lot.Source.PURCHASE,
        status=Lot.Status.RELEASED if start == Lot.Status.RELEASED else Lot.Status.QUARANTINE,
    )
    if start == Lot.Status.BLOCKED:
        services.block_lot(lab, lot, "ön koşul")
    getattr(services, f"{action}_lot")(lab, lot, "not", quality_decision=True)
    lot.refresh_from_db()
    assert lot.status == end


@pytest.mark.parametrize("action", ["release", "block", "reject"])
def test_lot_state_machine_forbidden_transitions(lab, action):
    lot = services.create_lot(lab, material=MaterialFactory(), source=Lot.Source.PURCHASE)
    services.reject_lot(lab, lot, "ret", quality_decision=True)
    with pytest.raises(BusinessRuleError) as exc:
        getattr(services, f"{action}_lot")(lab, lot, "not", quality_decision=True)
    assert exc.value.code == "invalid_transition"
    released = services.create_lot(
        lab, material=MaterialFactory(), source=Lot.Source.PURCHASE, status=Lot.Status.RELEASED
    )
    with pytest.raises(BusinessRuleError):
        services.release_lot(lab, released, quality_decision=True)
    with pytest.raises(BusinessRuleError):
        services.reject_lot(lab, released, "doğrudan ret yok", quality_decision=True)


# --- sayım düzeltme --------------------------------------------------------------------------


def test_stock_adjustment_posts_differences(depo, published, commit):
    loc = storage_location()
    short = stocked_lot("100", location=loc)
    exact = stocked_lot("40", location=loc)
    found = stocked_lot("10")  # sayılan lokasyonda hiç kaydı yok
    adjustment = services.create_stock_adjustment(
        depo,
        {"adjustment_date": date(2026, 10, 15), "note": "Ekim sayımı"},
        [
            {"lot": short, "location": loc, "counted_quantity": D("97.5"), "reason": "Fire"},
            {"lot": exact, "location": loc, "counted_quantity": D("40"), "reason": "Sayım"},
            {"lot": found, "location": loc, "counted_quantity": D("3"), "reason": "Bulundu"},
        ],
    )
    assert adjustment.number.startswith("SD-")
    first = adjustment.lines.get(line_no=1)
    assert (first.system_quantity, first.difference) == (D("100"), D("-2.5"))
    # Taslak ile kayıt arasında stok değişirse kayıt anındaki bakiye esas alınır.
    services.post_movement(depo, short.material, short, loc, D("-10"), T.SCRAP, None)
    with commit():
        services.post_stock_adjustment(depo, adjustment)
    adjustment.refresh_from_db()
    assert adjustment.status == StockAdjustment.Status.POSTED
    assert adjustment.posted_by == depo
    first.refresh_from_db()
    assert (first.system_quantity, first.difference) == (D("90"), D("7.5"))
    assert first.movement.movement_type == T.ADJUSTMENT and first.movement.note == "Fire"
    assert adjustment.lines.get(line_no=2).movement is None
    assert balance(short, loc) == D("97.5")
    assert balance(found, loc) == D("3")
    assert ev.STOCK_ADJUSTMENT_POSTED in [e.name for e in published]


def test_stock_adjustment_rules(depo):
    loc = storage_location()
    lot = stocked_lot("10", location=loc)
    base = {"adjustment_date": date(2026, 10, 15)}
    with pytest.raises(BusinessRuleError) as exc:
        services.create_stock_adjustment(
            depo, base, [{"lot": lot, "location": loc, "counted_quantity": D("1"), "reason": " "}]
        )
    assert exc.value.code == "reason_required"
    with pytest.raises(BusinessRuleError) as exc:
        services.create_stock_adjustment(
            depo, base, [{"lot": lot, "location": loc, "counted_quantity": D("-1"), "reason": "x"}]
        )
    assert exc.value.code == "invalid_quantity"
    line = {"lot": lot, "location": loc, "counted_quantity": D("1"), "reason": "x"}
    with pytest.raises(BusinessRuleError) as exc:
        services.create_stock_adjustment(depo, base, [line, line])
    assert exc.value.code == "duplicate_count_line"
    empty = services.create_stock_adjustment(depo, base)
    with pytest.raises(BusinessRuleError) as exc:
        services.post_stock_adjustment(depo, empty)
    assert exc.value.code == "document_empty"
    services.cancel_stock_adjustment(depo, empty, "Gerek kalmadı")
    empty.refresh_from_db()
    assert empty.status == StockAdjustment.Status.CANCELLED


# --- açılış stoku ----------------------------------------------------------------------------


def test_opening_balance(depo):
    material = MaterialFactory()
    a, b = storage_location(), storage_location()
    services.post_opening_balance(
        depo,
        material=material,
        lot_no="eski-7",
        location=a,
        quantity=D("10"),
        expiry_date=date(2027, 1, 1),
    )
    services.post_opening_balance(
        depo, material=material, lot_no="ESKI-7", location=b, quantity=D("500"), unit=unit("G")
    )
    lot = Lot.objects.get(material=material)
    assert (lot.lot_no, lot.source, lot.status) == (
        "ESKI-7",
        Lot.Source.OPENING,
        Lot.Status.RELEASED,
    )
    assert balance(lot, a) == D("10") and balance(lot, b) == D("0.5")
    with pytest.raises(BusinessRuleError) as exc:
        services.post_opening_balance(
            depo,
            material=material,
            lot_no="ESKI-7",
            location=a,
            quantity=D("1"),
            expiry_date=date(2028, 1, 1),
        )
    assert exc.value.code == "lot_expiry_mismatch"
    quarantined = services.post_opening_balance(
        depo,
        material=material,
        lot_no="K-1",
        location=a,
        quantity=D("1"),
        status=Lot.Status.QUARANTINE,
    )
    assert quarantined.lot.status == Lot.Status.QUARANTINE


def test_opening_balance_rules(depo):
    lot = stocked_lot("1")
    with pytest.raises(BusinessRuleError) as exc:
        services.post_opening_balance(
            depo,
            material=lot.material,
            lot_no=lot.lot_no,
            location=storage_location(),
            quantity=D("1"),
        )
    assert exc.value.code == "lot_exists"
    with pytest.raises(BusinessRuleError) as exc:
        services.post_opening_balance(
            depo,
            material=lot.material,
            lot_no="Y",
            location=storage_location(),
            quantity=D("1"),
            status=Lot.Status.REJECTED,
        )
    assert exc.value.code == "invalid_opening_status"
    with pytest.raises(BusinessRuleError) as exc:
        services.post_opening_balance(
            depo, material=lot.material, lot_no="Y", location=storage_location(), quantity=D("0")
        )
    assert exc.value.code == "invalid_quantity"
    assert StockBalance.objects.filter(lot__lot_no="Y").count() == 0
    assert not LotLink.objects.exists()


def test_opening_closes_on_go_live_date(depo):
    material = MaterialFactory()
    today = timezone.localdate()
    services.set_go_live_date(depo, today + timedelta(days=1))
    assert services.opening_is_open()
    services.post_opening_balance(
        depo, material=material, lot_no="A-1", location=storage_location(), quantity=D("5")
    )

    services.set_go_live_date(depo, today)
    assert not services.opening_is_open()
    with pytest.raises(BusinessRuleError) as exc:
        services.post_opening_balance(
            depo, material=material, lot_no="A-2", location=storage_location(), quantity=D("5")
        )
    assert exc.value.code == "opening_closed"
    assert AuditLog.objects.filter(note="Canlı başlangıç tarihi").count() == 2

    services.set_go_live_date(depo, None)
    assert services.opening_is_open()
