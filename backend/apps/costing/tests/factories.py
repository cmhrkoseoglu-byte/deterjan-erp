"""Maliyet testleri için uçtan uca kurulum: fiyatlı mal kabul → şarj → dolum (servislerle).

Elle hesaplanan örnek (`test_services.test_hand_calculated_bulk_and_finished_lot_cost`):

- Mal kabul MK-1: LAS 2.000 kg × 1,50 USD × 30 = 90.000 TL; SLES 1.000 kg × 40 TL = 40.000 TL;
  su 5.000 kg × 0,02 TL = 100 TL. Ek masraf: nakliye 1.300 TL miktar oranında (325 / 162,50 /
  812,50), gümrük 2.600 TL tutar oranında (1.798,61 / 799,39 / 2,00; yuvarlama farkı en büyüğe).
- Ambalaj mal kabulü MK-2 (TL): şişe 2,00, kapak 0,50, etiket 0,30, koli 4,80.
- Şarj: 1.000 kg emir; 600 LAS + 300 SLES + 100 su tüketilir, çıktı 980 kg. Üretim oranları:
  enerji 0,50, işçilik 1,20, amortisman 0,30 TL/kg.
- Dolum: 780 kg bulk, 1.000 sağlam + 10 mamul firesi adet, 5 şişe ve 5 kg bulk firesi. Dolum
  oranları: enerji 0,10, işçilik 0,40 TL/kg.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.core.models import Currency, User
from apps.core.roles import DEPO, DOLUM, LABORATUVAR, PLANLAMA, URETIM, YONETIM
from apps.costing import services
from apps.costing.models import CostRate, CostStage
from apps.filling import services as filling
from apps.filling.models import FillingRun, ScrapRecord
from apps.filling.tests.factories import Line, build_line
from apps.filling.tests.factories import order_data as filling_order_data
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceipt, GoodsReceiptExtraCost, Lot
from apps.masterdata.tests.factories import SupplierFactory, unit
from apps.production import services as production
from apps.production.models import ProductionBatch
from apps.production.tests.factories import Plant, build_plant
from apps.production.tests.factories import order_data as production_order_data
from apps.quality.testing import open_sample_for, pass_sample

D = Decimal


@dataclass
class Chain:
    plant: Plant
    line: Line
    receipt: GoodsReceipt
    raw: dict[str, Lot]
    packaging: dict[str, Lot]
    batch: ProductionBatch | None = None
    run: FillingRun | None = None


def add_rates(actor: User, stage: str, **rates: str) -> None:
    start = timezone.localdate() - timedelta(days=30)
    for kind, value in rates.items():
        services.create_rate(
            actor,
            {"stage": stage, "kind": kind.upper(), "rate_per_kg": D(value), "valid_from": start},
        )


def receive_raw(staff: dict[str, User], plant: Plant, commit: Any) -> tuple[GoodsReceipt, dict]:
    kg = unit("KG")
    receipt = inventory.create_goods_receipt(
        staff[DEPO],
        {
            "supplier": SupplierFactory.create(name="Kimya Tedarik A.Ş."),
            "receipt_date": date.today(),
            "quarantine_location": plant.quarantine,
            "storage_location": plant.storage,
        },
        [
            {
                "material": plant.las,
                "quantity": D("2000"),
                "unit": kg,
                "unit_price": D("1.50"),
                "currency": Currency.USD,
                "exchange_rate": D("30"),
            },
            {"material": plant.sles, "quantity": D("1000"), "unit": kg, "unit_price": D("40")},
            {"material": plant.water, "quantity": D("5000"), "unit": kg, "unit_price": D("0.02")},
        ],
    )
    inventory.set_receipt_costs(
        staff[DEPO],
        receipt,
        extra_costs=[
            {
                "kind": GoodsReceiptExtraCost.Kind.FREIGHT,
                "amount": D("1300"),
                "allocation": GoodsReceiptExtraCost.Allocation.QUANTITY,
            },
            {
                "kind": GoodsReceiptExtraCost.Kind.CUSTOMS,
                "amount": D("2600"),
                "allocation": GoodsReceiptExtraCost.Allocation.VALUE,
            },
        ],
    )
    with commit():
        inventory.post_goods_receipt(staff[DEPO], receipt)
    lots = {
        line.material.code: line.created_lot for line in receipt.lines.all() if line.created_lot
    }
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(lots["LAS"], "INCOMING"))
        pass_sample(staff[LABORATUVAR], open_sample_for(lots["SLES"], "INCOMING"))
    return receipt, lots


def receive_packaging(staff: dict[str, User], line: Line, commit: Any) -> dict[str, Lot]:
    prices = {"bottle": "2", "cap": "0.50", "label": "0.30", "case": "4.80"}
    materials = dict(zip(("bottle", "cap", "label", "case"), line.packaging, strict=True))
    receipt = inventory.create_goods_receipt(
        staff[DEPO],
        {
            "supplier": SupplierFactory.create(name="Ambalaj A.Ş."),
            "receipt_date": date.today(),
            "storage_location": line.storage,
        },
        [
            {
                "material": materials[key],
                "quantity": D("2000"),
                "unit": unit("ADET"),
                "unit_price": D(price),
            }
            for key, price in prices.items()
        ],
    )
    with commit():
        inventory.post_goods_receipt(staff[DEPO], receipt)
    by_material = {
        line.material_id: line.created_lot for line in receipt.lines.all() if line.created_lot
    }
    return {key: by_material[material.pk] for key, material in materials.items()}


def build_chain(staff: dict[str, User], commit: Any, *, fill: bool = True) -> Chain:
    plant = build_plant(staff[PLANLAMA], stock=False)
    receipt, raw = receive_raw(staff, plant, commit)
    add_rates(
        staff[YONETIM], CostStage.PRODUCTION, energy="0.50", labor="1.20", depreciation="0.30"
    )
    add_rates(staff[YONETIM], CostStage.FILLING, energy="0.10", labor="0.40")
    # Gelecekte başlayan oran bugünkü hesaba girmez.
    services.create_rate(
        staff[YONETIM],
        {
            "stage": CostStage.PRODUCTION,
            "kind": CostRate.Kind.ENERGY,
            "rate_per_kg": D("9.99"),
            "valid_from": timezone.localdate() + timedelta(days=1),
        },
    )
    with commit():
        order = production.create_order(staff[PLANLAMA], production_order_data(plant, "1000"))
        production.approve_order(staff[PLANLAMA], order)
        for material in (plant.las, plant.sles):
            row = plant.requirement(order, material)
            production.pick_material(
                staff[DEPO], order, row, raw[material.code], row.required_quantity
            )
        production.mark_material_ready(staff[DEPO], order)
        batch = production.start_batch(staff[URETIM], order)
    for row in order.requirements.order_by("sequence"):
        lot = raw["SU" if row.is_water else row.material.code]
        production.record_consumption(
            staff[URETIM], batch, row, lot, production.batch_line_quantity(row, batch)
        )
    with commit():
        production.finish_batch(staff[URETIM], batch, D("980"), note="test")
    line = build_line(staff[PLANLAMA], stock=False, bulk=plant.product, warehouse=plant.warehouse)
    packaging = receive_packaging(staff, line, commit)
    chain = Chain(plant, line, receipt, raw, packaging, batch)
    if not fill:
        return chain
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(batch.output_lot, "FINAL"))
    bulk = batch.output_lot
    with commit():
        fill_order = filling.create_order(staff[PLANLAMA], filling_order_data(line, 1000))
        filling.approve_order(staff[PLANLAMA], fill_order)
        for need in fill_order.requirements.select_related("material"):
            key = {"SISE-750": "bottle", "KAPAK-28": "cap", "ETIKET-750": "label"}.get(
                need.material.code, "case"
            )
            filling.pick_packaging(
                staff[DEPO], fill_order, need, packaging[key], need.required_quantity
            )
        filling.mark_material_ready(staff[DEPO], fill_order)
        run = filling.start_run(staff[DOLUM], fill_order)
        filling.consume_bulk(staff[DOLUM], run, bulk, D("780"))
        filling.record_scrap(
            staff[DOLUM],
            run,
            kind=ScrapRecord.Kind.PACKAGING,
            quantity=D("5"),
            reason_code=ScrapRecord.Reason.DAMAGED_PACKAGING,
            lot=packaging["bottle"],
        )
        filling.record_scrap(
            staff[DOLUM],
            run,
            kind=ScrapRecord.Kind.BULK,
            quantity=D("5"),
            reason_code=ScrapRecord.Reason.LEAK,
            lot=bulk,
        )
        filling.record_scrap(
            staff[DOLUM],
            run,
            kind=ScrapRecord.Kind.FINISHED,
            quantity=D("10"),
            reason_code=ScrapRecord.Reason.UNDERFILL,
        )
    with commit():
        filling.finish_run(staff[DOLUM], run, 1000)
    chain.run = run
    return chain
