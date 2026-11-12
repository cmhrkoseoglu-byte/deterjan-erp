"""Şarjı bitmemiş dökme lota yalnız şarj sırası numunesi açılır (DECISIONS 2026-11-12)."""

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.inventory import services as inventory
from apps.inventory.testing import assert_stock_invariants
from apps.production import services
from apps.production.tests.factories import Plant, ready_order
from apps.quality import services as quality
from apps.quality.models import SampleStage

pytestmark = pytest.mark.django_db


def test_unfinished_batch_lot_allows_only_in_process_samples(
    plant: Plant, planner: User, depo: User, operator: User, lab: User
) -> None:
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    lot = batch.output_lot

    assert inventory.unfinished_output(lot) == (
        f"{lot.lot_no} lotunun şarjı bitmedi ({order.number}, 1. şarj)"
    )
    sample = quality.create_sample(lab, lot, SampleStage.IN_PROCESS)
    assert sample.stage == SampleStage.IN_PROCESS
    with pytest.raises(BusinessRuleError) as caught:
        quality.create_sample(lab, lot, SampleStage.FINAL)
    assert caught.value.code == "lot_output_unfinished"
    assert_stock_invariants()
