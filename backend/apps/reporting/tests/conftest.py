"""Raporlama testleri için ortak veri: mal kabulden sevkiyata kısa bir gerçek akış.

Zincir servisler üzerinden kurulur (diğer modüllerin e2e testleriyle aynı yol): mal kabul, giriş
numuneleri (biri reddedilir), tolerans dışı bir tartımla şarj, fireli dolum partisi, sevkiyat.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from apps.core.models import User
from apps.core.roles import (
    DEPO,
    DOLUM,
    LABORATUVAR,
    PLANLAMA,
    SATIN_ALMA,
    SEVKIYAT,
    URETIM,
    YONETIM,
)
from apps.filling import services as filling
from apps.filling.models import FillingRun, ScrapRecord
from apps.filling.tests.factories import build_line
from apps.filling.tests.factories import order_data as filling_order_data
from apps.inventory import services as inventory
from apps.inventory.models import Lot
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Location, MaterialUnitConversion
from apps.masterdata.tests.factories import CustomerFactory, LocationFactory, SupplierFactory, unit
from apps.production import services as production
from apps.production.models import ProductionBatch
from apps.production.tests.factories import build_plant
from apps.production.tests.factories import order_data as production_order_data
from apps.quality.models import QualityDecision
from apps.quality.testing import open_sample_for, pass_sample
from apps.sales import services as sales
from apps.sales.models import Shipment

D = Decimal
ALL_STAFF = (DEPO, URETIM, LABORATUVAR, PLANLAMA, YONETIM, DOLUM, SEVKIYAT, SATIN_ALMA)


@pytest.fixture
def staff(make_user: Callable[..., User]) -> dict[str, User]:
    return {role: make_user(role, username=role) for role in ALL_STAFF}


@pytest.fixture
def commit(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> Callable[[], AbstractContextManager[Any]]:
    """`with commit(): ...` bloğundaki commit sonrası işleri (olaylar) hemen çalıştırır."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def invariants(db: None) -> Iterator[None]:
    yield
    assert_stock_invariants()


@dataclass
class Chain:
    plant: Any
    line: Any
    batch: ProductionBatch
    run: FillingRun
    shipment: Shipment
    rejected_lot: Lot


@pytest.fixture
def chain(staff: dict[str, User], commit: Callable[[], AbstractContextManager[Any]]) -> Chain:
    plant = build_plant(staff[PLANLAMA], stock=False)
    supplier = SupplierFactory.create(name="Kimya Tedarik A.Ş.")
    kg = unit("KG")
    receipt = inventory.create_goods_receipt(
        staff[DEPO],
        {
            "supplier": supplier,
            "receipt_date": date.today(),
            "delivery_note_no": "IRS-1",
            "quarantine_location": plant.quarantine,
            "storage_location": plant.storage,
        },
        [
            {"material": plant.las, "quantity": D("2000"), "unit": kg},
            {"material": plant.sles, "quantity": D("1000"), "unit": kg},
            {"material": plant.water, "quantity": D("5000"), "unit": kg},
            {"material": plant.sles, "quantity": D("100"), "unit": kg, "supplier_lot_no": "KOT"},
        ],
    )
    with commit():
        inventory.post_goods_receipt(staff[DEPO], receipt)
    lines = list(receipt.lines.order_by("id"))
    lots = {"LAS": lines[0].created_lot, "SLES": lines[1].created_lot, "SU": lines[2].created_lot}
    rejected = lines[3].created_lot
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(lots["LAS"], "INCOMING"))
        pass_sample(staff[LABORATUVAR], open_sample_for(lots["SLES"], "INCOMING"))
        pass_sample(
            staff[LABORATUVAR],
            open_sample_for(rejected, "INCOMING"),
            decision=QualityDecision.Decision.REJECT,
        )

    with commit():
        order = production.create_order(staff[PLANLAMA], production_order_data(plant, "1000"))
        production.approve_order(staff[PLANLAMA], order)
        for material in (plant.las, plant.sles):
            row = plant.requirement(order, material)
            # LAS fazla hazırlanır: tartımda %10 sapma (tolerans dışı, notlu).
            production.pick_material(
                staff[DEPO], order, row, lots[material.code], row.required_quantity * D("1.2")
            )
        production.mark_material_ready(staff[DEPO], order)
        batch = production.start_batch(staff[URETIM], order)
    for row in order.requirements.order_by("sequence"):
        lot = lots["SU" if row.is_water else row.material.code]
        planned = production.batch_line_quantity(row, batch)
        over = row.material == plant.las
        production.record_consumption(
            staff[URETIM],
            batch,
            row,
            lot,
            planned * D("1.1") if over else planned,
            note="Fazla tartıldı" if over else "",
        )
    with commit():
        production.finish_batch(staff[URETIM], batch, D("950"))
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(batch.output_lot, "FINAL"))
    bulk = batch.output_lot

    line = build_line(staff[PLANLAMA], bulk=plant.product, warehouse=plant.warehouse)
    with commit():
        fill = filling.create_order(staff[PLANLAMA], filling_order_data(line, 1000))
        filling.approve_order(staff[PLANLAMA], fill)
        for row in fill.requirements.select_related("material"):
            key = {"SISE-750": "bottle", "KAPAK-28": "cap", "ETIKET-750": "label"}.get(
                row.material.code, "case"
            )
            filling.pick_packaging(staff[DEPO], fill, row, line.lots[key], row.required_quantity)
        filling.mark_material_ready(staff[DEPO], fill)
        run = filling.start_run(staff[DOLUM], fill)
        filling.consume_bulk(staff[DOLUM], run, bulk, D("780"))
        filling.record_scrap(
            staff[DOLUM],
            run,
            kind=ScrapRecord.Kind.FINISHED,
            quantity=D("25"),
            reason_code=ScrapRecord.Reason.LEAK,
        )
    with commit():
        filling.finish_run(staff[DOLUM], run, 975)
        filling.finish_filling(staff[DOLUM], fill)
    finished = run.output_lot
    with commit():
        pass_sample(staff[LABORATUVAR], open_sample_for(finished, "FINAL"))

    product = line.finished
    if not MaterialUnitConversion.objects.filter(material=product, unit=unit("KOLI")).exists():
        MaterialUnitConversion.objects.create(
            material=product, unit=unit("KOLI"), factor_to_base=12
        )
    LocationFactory.create(
        warehouse=plant.warehouse, code="SEVK", location_type=Location.Type.SHIPPING
    )
    customer = CustomerFactory.create(code="ZM-01", name="Zincir Market A.Ş.")
    with commit():
        sale = sales.create_order(
            staff[SEVKIYAT],
            {
                "customer": customer,
                "order_date": date.today(),
                "requested_delivery_date": date.today(),
            },
            [{"product": product, "quantity": D("600"), "unit": unit("ADET")}],
        )
        sales.confirm_order(staff[SEVKIYAT], sale)
        shipment = sales.plan_shipment(
            staff[SEVKIYAT],
            sale,
            {"planned_date": date.today(), "vehicle_plate": "41 ABC 41", "driver_name": "Ali Kaya"},
        )
    with commit():
        sales.pick_lot(staff[DEPO], shipment, finished)
        sales.mark_loaded(staff[DEPO], shipment)
    with commit():
        sales.dispatch_shipment(staff[SEVKIYAT], shipment)
    for obj in (batch, run, shipment):
        obj.refresh_from_db()
    assert_stock_invariants()
    return Chain(plant, line, batch, run, shipment, rejected)
