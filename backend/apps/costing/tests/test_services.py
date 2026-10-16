from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, Currency
from apps.core.roles import DEPO, PLANLAMA, SATIN_ALMA, URETIM, YONETIM
from apps.costing import services
from apps.costing.models import CostRate, CostStage, LotCost, LotCostLine
from apps.costing.tests.factories import build_chain, receive_raw
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceipt, Lot
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.tests.factories import MaterialFactory, SupplierFactory, unit
from apps.production import services as production
from apps.production.tests.factories import build_plant, ready_order

D = Decimal
C = LotCostLine.Category

pytestmark = pytest.mark.usefixtures("invariants")


def current(lot: Lot) -> LotCost:
    return LotCost.objects.get(lot=lot, is_current=True)


def amounts(cost: LotCost) -> list[tuple[str, str, Decimal]]:
    return [(line.category, line.description, line.amount) for line in cost.lines.all()]


def by_category(cost: LotCost) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for line in cost.lines.all():
        totals[line.category] = totals.get(line.category, D(0)) + line.amount
    return totals


def test_allocate_sums_to_amount_and_puts_rounding_on_largest():
    assert services.allocate(D("2600"), [D("90000"), D("40000"), D("100")]) == [
        D("1798.61"),
        D("799.39"),
        D("2.00"),
    ]
    assert services.allocate(D("100"), [D(1), D(1), D(1)]) == [D("33.34"), D("33.33"), D("33.33")]
    assert services.allocate(D("10"), [D(0), D(0)]) == [D("5.00"), D("5.00")]


def test_hand_calculated_purchase_bulk_and_finished_lot_cost(staff, commit):
    """Kabul kriteri: bulk ve mamul lot maliyeti kalem kalem elle hesaplanan örnekle aynı
    (hesap: `tests/factories.py` başındaki açıklama)."""
    chain = build_chain(staff, commit)

    las = current(chain.raw["LAS"])
    assert las.method == LotCost.Method.PURCHASE
    assert [a for _, _, a in amounts(las)] == [D("90000.00"), D("325.00"), D("1798.61")]
    assert las.total_cost == D("92123.61")
    assert las.unit_cost == D("46.0618")
    assert not las.is_estimated
    sles = current(chain.raw["SLES"])
    assert [a for _, _, a in amounts(sles)] == [D("40000.00"), D("162.50"), D("799.39")]
    assert sles.unit_cost == D("40.9619")
    water = current(chain.raw["SU"])
    assert water.total_cost == D("914.50")
    assert water.unit_cost == D("0.1829")
    lot = chain.raw["LAS"]
    lot.refresh_from_db()
    assert lot.unit_cost == D("46.0618")
    assert lot.cost_is_estimated is False

    # Bulk: 600 × 46,0618 + 300 × 40,9619 + 100 × 0,1829 + 980 kg × (0,50 + 1,20 + 0,30).
    assert chain.batch is not None
    bulk = current(chain.batch.output_lot)
    assert bulk.method == LotCost.Method.PRODUCTION
    assert bulk.quantity == D("980")
    assert [(c, a) for c, _, a in amounts(bulk)] == [
        (C.MATERIAL, D("27637.08")),
        (C.MATERIAL, D("12288.57")),
        (C.MATERIAL, D("18.29")),
        (C.ENERGY, D("490.00")),
        (C.LABOR, D("1176.00")),
        (C.DEPRECIATION, D("294.00")),
    ]
    assert bulk.total_cost == D("41903.94")
    assert bulk.unit_cost == D("42.7591")
    assert not bulk.is_estimated and not bulk.has_missing

    # Mamul: 780 kg bulk + ambalaj (1.010 adet; koli 85) + oranlar 780 kg × (0,10 + 0,40)
    # + fire (5 şişe, 5 kg bulk) ÷ 1.000 sağlam adet.
    assert chain.run is not None
    finished = current(chain.run.output_lot)
    assert finished.method == LotCost.Method.FILLING
    assert finished.quantity == D("1000")
    totals = by_category(finished)
    assert totals == {
        C.BULK: D("33352.10"),
        C.PACKAGING: D("3236.00"),
        C.ENERGY: D("78.00"),
        C.LABOR: D("312.00"),
        C.SCRAP: D("223.80"),
    }
    assert [line.amount for line in finished.lines.filter(category=C.PACKAGING)] == [
        D("2020.00"),
        D("505.00"),
        D("303.00"),
        D("408.00"),
    ]
    assert [line.amount for line in finished.lines.filter(category=C.SCRAP)] == [
        D("10.00"),
        D("213.80"),
    ]
    assert finished.total_cost == D("37201.90")
    assert finished.unit_cost == D("37.2019")
    # 10 adet mamul firesinin payı: 36.978,10 × 10 / 1.010.
    assert finished.finished_scrap_cost == D("366.12")
    output = chain.run.output_lot
    output.refresh_from_db()
    assert output.unit_cost == D("37.2019")


def test_cost_is_calculated_once_per_event(staff, commit):
    chain = build_chain(staff, commit, fill=False)
    lot = chain.raw["LAS"]
    services.ensure_lot_cost(staff[YONETIM], lot)
    assert LotCost.objects.filter(lot=lot).count() == 1
    assert AuditLog.objects.filter(
        content_type__model="lotcost", object_id=current(lot).pk, action=AuditLog.Action.CREATE
    ).exists()


def test_missing_price_uses_last_known_cost_then_standard_and_marks_estimated(staff, commit):
    plant = build_plant(staff[PLANLAMA], stock=False)
    receive_raw(staff, plant, commit)
    # Fiyatsız LAS kabulü → son bilinen alış maliyeti, tahmini.
    receipt = inventory.create_goods_receipt(
        staff[DEPO],
        {
            "supplier": SupplierFactory.create(),
            "receipt_date": date.today(),
            "quarantine_location": plant.quarantine,
        },
        [{"material": plant.las, "quantity": D("100"), "unit": unit("KG")}],
    )
    with commit():
        inventory.post_goods_receipt(staff[DEPO], receipt)
    cost = current(receipt.lines.get().created_lot)
    assert cost.is_estimated and not cost.has_missing
    assert cost.unit_cost == D("46.0618")
    assert cost.lines.get().category == C.ESTIMATE

    # Açılış stoku, hiç alışı olmayan malzeme → standart maliyet.
    perfume = MaterialFactory.create(code="PARFUM")
    services.create_standard_cost(staff[YONETIM], {"material": perfume, "unit_cost": D("250")})
    opening = inventory.post_opening_balance(
        staff[DEPO], material=perfume, lot_no="ESKI-1", location=plant.storage, quantity=D("4")
    ).lot
    cost = services.ensure_lot_cost(staff[YONETIM], opening)
    assert cost is not None
    assert cost.method == LotCost.Method.ESTIMATE
    assert (cost.quantity, cost.total_cost, cost.unit_cost) == (D("4"), D("1000.00"), D("250"))
    assert cost.is_estimated


def test_unknown_input_cost_is_flagged_missing_downstream(staff, commit):
    chain = build_chain(staff, commit, fill=False)
    assert chain.batch is not None
    # Fiyatsız ve tahmin kaynağı olmayan lot, girdisi olduğu şarjı "eksik" yapar.
    orphan = stocked_lot("10", material=MaterialFactory.create(code="RENK"))
    cost = services.ensure_lot_cost(staff[YONETIM], orphan)
    assert cost is not None
    assert cost.unit_cost is None and cost.has_missing and cost.is_estimated
    orphan.refresh_from_db()
    assert orphan.unit_cost is None and orphan.cost_is_estimated


def test_overhead_without_density_is_flagged(staff, commit):
    plant = build_plant(staff[PLANLAMA], stock=False)
    plant.product.base_unit = unit("LT")
    plant.product.density = None
    plant.product.save()
    lines = services._overhead_lines(CostStage.PRODUCTION, timezone.localdate(), None, "kg")
    assert lines == []  # oran yoksa satır da yok
    services.create_rate(
        staff[YONETIM],
        {
            "stage": CostStage.PRODUCTION,
            "kind": CostRate.Kind.ENERGY,
            "rate_per_kg": D("1"),
            "valid_from": timezone.localdate(),
        },
    )
    assert services.to_kg(plant.product, D("10")) is None
    (line,) = services._overhead_lines(CostStage.PRODUCTION, timezone.localdate(), None, "kg")
    assert line.is_missing and line.amount == 0


def test_price_correction_on_posted_receipt_recosts_lot_as_new_version(staff, commit):
    chain = build_chain(staff, commit, fill=False)
    receipt = chain.receipt
    sles_line = receipt.lines.get(material__code="SLES")
    with pytest.raises(BusinessRuleError, match="note_required"):
        inventory.set_receipt_costs(
            staff[SATIN_ALMA], receipt, lines=[{"id": sles_line.pk, "unit_price": D("42")}]
        )
    with commit():
        inventory.set_receipt_costs(
            staff[SATIN_ALMA],
            receipt,
            lines=[{"id": sles_line.pk, "unit_price": D("42")}],
            note="Fatura fiyatı",
        )
    lot = chain.raw["SLES"]
    versions = LotCost.objects.filter(lot=lot).order_by("version")
    assert [v.version for v in versions] == [1, 2]
    assert not versions[0].is_current
    new = versions[1]
    assert new.is_current and "Fatura fiyatı" in new.note
    # 42.000 + 162,50 + gümrük payı (tutar oranı değişti: 2.600 × 42.000 / 132.100 = 826,65).
    assert new.total_cost == D("42989.15")
    # Bağlı bulk lot otomatik değişmez; yeniden hesaplama ayrı işlem.
    assert chain.batch is not None
    assert LotCost.objects.filter(lot=chain.batch.output_lot).count() == 1


def test_receipt_price_rules(staff, commit):
    chain = build_chain(staff, commit, fill=False)
    line = chain.receipt.lines.get(material__code="SLES")
    with pytest.raises(BusinessRuleError, match="exchange_rate_required"):
        inventory.set_receipt_costs(
            staff[SATIN_ALMA],
            chain.receipt,
            lines=[{"id": line.pk, "currency": Currency.EUR}],
            note="x",
        )
    with pytest.raises(BusinessRuleError, match="invalid_amount"):
        inventory.set_receipt_costs(
            staff[SATIN_ALMA],
            chain.receipt,
            extra_costs=[{"kind": "FREIGHT", "amount": D("0"), "allocation": "QUANTITY"}],
            note="x",
        )
    draft = inventory.create_goods_receipt(
        staff[DEPO],
        {"supplier": SupplierFactory.create(), "receipt_date": date.today()},
        [{"material": chain.plant.las, "quantity": D("1"), "unit": unit("KG")}],
    )
    inventory.cancel_goods_receipt(staff[DEPO], draft, "yanlış")
    with pytest.raises(BusinessRuleError, match="document_locked"):
        inventory.set_receipt_costs(staff[SATIN_ALMA], draft, extra_costs=[])
    # TL satırda kur tutulmaz.
    inventory.set_receipt_costs(
        staff[SATIN_ALMA],
        chain.receipt,
        lines=[{"id": line.pk, "currency": Currency.TRY, "exchange_rate": D("5")}],
        note="kur",
    )
    line.refresh_from_db()
    assert line.exchange_rate is None
    chain.receipt.refresh_from_db()
    assert chain.receipt.status == GoodsReceipt.Status.POSTED


def test_recalculate_requires_note_and_cascades_downstream(staff, commit):
    chain = build_chain(staff, commit)
    assert chain.batch is not None and chain.run is not None
    las = chain.raw["LAS"]
    with pytest.raises(BusinessRuleError, match="note_required"):
        services.recalculate_lot_cost(staff[YONETIM], las, " ")
    services.create_standard_cost(staff[YONETIM], {"material": las.material, "unit_cost": D("1")})
    results = services.recalculate_lot_cost(staff[YONETIM], las, "Yeni fiyat", cascade=True)
    assert [r.lot for r in results] == [las, chain.batch.output_lot, chain.run.output_lot]
    assert all(r.version == 2 and r.is_current for r in results)
    assert "girdi lot" in results[1].note
    # Fiyat değişmediği için sonuç aynı.
    assert results[2].unit_cost == D("37.2019")


def test_unfinished_batch_cannot_be_costed(staff, commit):
    plant = build_plant(staff[PLANLAMA])
    order = ready_order(plant, staff[PLANLAMA], staff[DEPO])
    batch = production.start_batch(staff[URETIM], order)
    assert services.ensure_lot_cost(staff[YONETIM], batch.output_lot) is None
    with pytest.raises(BusinessRuleError, match="cost_not_ready"):
        services.recalculate_lot_cost(staff[YONETIM], batch.output_lot, "deneme")


def test_rate_rules_and_effective_date(staff):
    today = timezone.localdate()
    data = {
        "stage": CostStage.FILLING,
        "kind": CostRate.Kind.LABOR,
        "rate_per_kg": D("0.40"),
        "valid_from": today - timedelta(days=10),
    }
    old = services.create_rate(staff[YONETIM], data)
    with pytest.raises(BusinessRuleError, match="duplicate_rate"):
        services.create_rate(staff[YONETIM], data)
    with pytest.raises(BusinessRuleError, match="invalid_rate"):
        services.create_rate(staff[YONETIM], {**data, "rate_per_kg": D("-1"), "valid_from": today})
    new = services.create_rate(
        staff[YONETIM], {**data, "rate_per_kg": D("0.50"), "valid_from": today}
    )
    assert services.rates_on(CostStage.FILLING, today) == [new]
    assert services.rates_on(CostStage.FILLING, today - timedelta(days=1)) == [old]
    assert services.rates_on(CostStage.FILLING, today - timedelta(days=11)) == []
    services.update_rate(staff[YONETIM], new, {"rate_per_kg": D("0")})
    # Sıfır oran satır üretmez.
    assert services.rates_on(CostStage.FILLING, today) == []


def test_standard_cost_rules(staff):
    material = MaterialFactory.create()
    cost = services.create_standard_cost(
        staff[YONETIM], {"material": material, "unit_cost": D("3")}
    )
    with pytest.raises(BusinessRuleError, match="duplicate_standard_cost"):
        services.create_standard_cost(staff[YONETIM], {"material": material, "unit_cost": D("4")})
    with pytest.raises(BusinessRuleError, match="invalid_cost"):
        services.update_standard_cost(staff[YONETIM], cost, {"unit_cost": D("-1")})
    services.update_standard_cost(staff[YONETIM], cost, {"is_active": False})
    assert services.known_unit_cost(material) is None
