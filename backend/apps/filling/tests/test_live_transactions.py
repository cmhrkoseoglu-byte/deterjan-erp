"""Canlıda istek başına veritabanı işlemi yoktur (`ATOMIC_REQUESTS` kapalı): satır kilitleyen her
servis kendi işlemini açmalıdır. Testler normalde bir işlemin içinde koştuğu için eksik işlem fark
edilmez. Buradaki test, canlı gibi dış işlem olmadan dolum akışını servislerle baştan sona yürütür
(ambalaj hazırlama, parti, bulk tüketimi, parti bitişi ve numune, dolumu bitirme, lot kararı)."""

from collections.abc import Callable
from decimal import Decimal

import pytest

from apps.core.models import User
from apps.filling import services
from apps.filling.models import FillingOrder, FillingRun
from apps.filling.tests.factories import build_line, started_run
from apps.inventory import services as inventory
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.tests.factories import ensure_standard_units
from apps.quality.models import Sample, SampleStage

D = Decimal


@pytest.mark.django_db(transaction=True)
def test_filling_flow_runs_without_a_surrounding_transaction(
    make_user: Callable[..., User],
) -> None:
    ensure_standard_units()
    planner = make_user("planlama", username="planlama")
    depo = make_user("depo", username="depo")
    filler = make_user("dolum", username="dolum")
    lab = make_user("laboratuvar", username="laboratuvar")
    line = build_line(planner)

    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("780"))
    services.finish_run(filler, run, 1000)
    order = services.finish_filling(filler, run.order)

    run.refresh_from_db()
    assert run.status == FillingRun.Status.COMPLETED
    assert order.status == FillingOrder.Status.QC_PENDING
    assert Sample.objects.filter(lot=run.output_lot, stage=SampleStage.FINAL).exists()

    inventory.release_lot(lab, run.output_lot, "Analiz uygun", quality_decision=True)
    order.refresh_from_db()
    assert order.status == FillingOrder.Status.COMPLETED
    assert_stock_invariants()


@pytest.mark.django_db(transaction=True)
def test_revert_runs_without_a_surrounding_transaction(make_user: Callable[..., User]) -> None:
    """Dolum emrini geri alma canlı gibi dış işlem olmadan çalışır (DECISIONS 2026-11-14)."""
    ensure_standard_units()
    planner = make_user("planlama", username="planlama")
    depo = make_user("depo", username="depo")
    filler = make_user("dolum", username="dolum")
    manager = make_user("yonetim", username="yonetim")
    line = build_line(planner)

    run = started_run(line, planner, depo, filler)
    services.consume_bulk(filler, run, line.lots["bulk"], D("780"))
    services.finish_run(filler, run, 1000)
    order = services.revert_order(manager, run.order, "Dolum yapılmadı")

    run.refresh_from_db()
    assert order.status == FillingOrder.Status.CANCELLED
    assert run.status == FillingRun.Status.CANCELLED
    assert inventory.current_balance(run.output_lot, line.finished_store) == D("0")
    assert not Sample.objects.filter(
        lot=run.output_lot, stage=SampleStage.FINAL, status=Sample.Status.PENDING
    ).exists()
    assert_stock_invariants()
