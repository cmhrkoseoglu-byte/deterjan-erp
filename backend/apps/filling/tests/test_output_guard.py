"""Partisi bitmemiş dolum lotu serbest bırakılamaz, son kontrolü yapılamaz (DECISIONS
2026-11-12)."""

from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.filling import services
from apps.filling.tests.factories import Line, started_run
from apps.inventory import services as inventory
from apps.inventory.models import Lot
from apps.inventory.testing import assert_stock_invariants
from apps.quality import services as quality
from apps.quality.models import SampleStage
from apps.quality.testing import open_sample_for, pass_sample

pytestmark = pytest.mark.django_db

D = Decimal


def test_unfinished_run_lot_is_not_sampled_decided_or_released(
    line: Line,
    planner: User,
    depo: User,
    filler: User,
    lab: User,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("787"))
    lot = run.output_lot
    reason = f"{lot.lot_no} lotunun dolum partisi bitmedi ({run.order.number}, 1. parti)"

    assert inventory.unfinished_output(lot) == reason
    with pytest.raises(BusinessRuleError) as caught:
        quality.create_sample(lab, lot, SampleStage.FINAL)
    assert caught.value.code == "lot_output_unfinished"
    assert caught.value.message == (
        f"{reason}; son kontrol numunesi parti bitince kendiliğinden açılır."
    )
    with pytest.raises(BusinessRuleError) as caught:
        inventory.release_lot(make_user("admin"), lot, "Elle")
    assert caught.value.code == "lot_output_unfinished"

    # Kuraldan önce açılmış son kontrol numunesine de karar verilemez.
    with monkeypatch.context() as patched:
        patched.setattr(inventory, "_OUTPUT_CHECKS", [])
        early = quality.create_sample(lab, lot, SampleStage.FINAL)
    with pytest.raises(BusinessRuleError) as caught:
        pass_sample(lab, early)
    assert caught.value.code == "lot_output_unfinished"
    assert caught.value.message == f"{reason}; parti bitmeden lota karar verilemez."
    lot.refresh_from_db()
    assert lot.status == Lot.Status.QUARANTINE

    # Erken açılan numune iptal edilince parti biter, son kontrol kendiliğinden açılır.
    quality.cancel_sample(lab, early, "Parti bitmeden açılmıştı")
    run = services.finish_run(filler, run, 1000)
    assert inventory.unfinished_output(lot) is None
    pass_sample(lab, open_sample_for(lot, SampleStage.FINAL))
    lot.refresh_from_db()
    assert lot.status == Lot.Status.RELEASED
    assert_stock_invariants()


def test_cancelled_run_lot_cannot_be_released(
    line: Line, planner: User, depo: User, filler: User, lab: User, make_user
) -> None:
    run = services.cancel_run(filler, started_run(line, planner, depo, filler), "Yanlış başlatıldı")
    lot = run.output_lot

    assert inventory.unfinished_output(lot) == (
        f"{lot.lot_no} lotunun dolum partisi iptal edildi ({run.order.number}, 1. parti)"
    )
    with pytest.raises(BusinessRuleError) as caught:
        inventory.release_lot(make_user("admin"), lot, "Elle")
    assert caught.value.code == "lot_output_unfinished"
    with pytest.raises(BusinessRuleError) as caught:
        quality.create_sample(lab, lot, SampleStage.FINAL)
    assert caught.value.code == "lot_output_unfinished"
    assert_stock_invariants()
