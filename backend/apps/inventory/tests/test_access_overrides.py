"""Kişiye özel ayarla depo ve stok (docs/plan/kisi-yetkileri.md §10, 2. adım): kaldırılan yetki
uç noktada ve serviste düşer; okuma ve açık kalması gerekenler açık kalır."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, PRICES, READ, VIEW
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.inventory import services
from apps.inventory.models import GoodsReceipt, Lot
from apps.inventory.tests.factories import quarantine_location, stocked_lot, storage_location
from apps.masterdata.tests.factories import MaterialFactory, SupplierFactory, unit

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
HISTORY = "/api/v1/workflow/record-history/"


def url(name: str, *args: Any) -> str:
    return reverse(f"inventory:{name}", args=args)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _receipt(actor: User) -> GoodsReceipt:
    data = {
        "supplier": SupplierFactory(),
        "receipt_date": date(2026, 10, 15),
        "quarantine_location": quarantine_location(),
        "storage_location": storage_location(),
    }
    lines = [
        {
            "material": MaterialFactory(requires_incoming_qc=False),
            "quantity": D("10"),
            "unit": unit("KG"),
        }
    ]
    receipt = services.create_goods_receipt(actor, data, lines)
    line = receipt.lines.get()
    services.set_receipt_costs(
        actor, receipt, lines=[{"id": line.pk, "unit_price": D("2.5"), "currency": "TRY"}]
    )
    return receipt


def _history_notes(user: User, receipt: GoodsReceipt) -> list[str]:
    response = api(user).get(
        HISTORY, {"content_type": "inventory.goodsreceipt", "object_id": str(receipt.pk)}
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    entries = body["results"] if isinstance(body, dict) else body
    return [entry["note"] for entry in entries]


def test_removing_receipt_change_stops_writes_and_keeps_reads(
    make_user: Callable[..., User],
) -> None:
    depo = make_user("depo")
    receipt = _receipt(depo)
    client = api(override(depo, "inventory.receipts", CHANGE))

    assert client.get(url("goods-receipt-list")).status_code == 200
    assert client.get(url("goods-receipt-detail", receipt.pk)).status_code == 200
    assert client.post(url("goods-receipt-post", receipt.pk)).status_code == 403
    refused = client.post(url("goods-receipt-cancel", receipt.pk), {"reason": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": "inventory.receipts", "level": "change"}]


def test_closing_inventory_records_keeps_lot_labels(make_user: Callable[..., User]) -> None:
    depo = make_user("depo")
    receipt = _receipt(depo)
    services.post_goods_receipt(depo, receipt)
    # Üretim mal kabulü açık okumayla okur; Açık kayıtlar kapatılınca belge kapanır, lot etiketleri
    # Lotlar okumasıyla açık kalır (plan §3.3).
    client = api(override(make_user("uretim"), "inventory.open_records", READ))

    assert client.get(url("goods-receipt-list")).status_code == 403
    assert client.get(url("goods-receipt-detail", receipt.pk)).status_code == 403
    labels = client.get(url("goods-receipt-labels", receipt.pk))
    assert labels.status_code == 200 and labels.content.startswith(b"%PDF")
    assert client.get(url("lot-list")).status_code == 200


def test_prices_follow_prices_right_and_entry_needs_its_prerequisite(
    make_user: Callable[..., User],
) -> None:
    receipt = _receipt(make_user("depo"))
    buyer = make_user("satin_alma")
    assert api(buyer).get(url("goods-receipt-detail", receipt.pk)).json()["lines"][0][
        "unit_price"
    ] == ("2.5000")

    override(buyer, PRICES.key, VIEW)
    detail = api(buyer).get(url("goods-receipt-detail", receipt.pk)).json()
    assert "unit_price" not in detail["lines"][0]
    assert detail["extra_costs"] is None
    # Fiyat girişi Fiyatları görür'ü ön koşul ister: o kaldırılınca giriş de kapanır.
    costs = api(buyer).post(url("goods-receipt-costs", receipt.pk), {"lines": []}, format="json")
    assert costs.status_code == 403


def test_receipt_history_hides_price_correction_without_prices(
    make_user: Callable[..., User],
) -> None:
    depo = make_user("depo")
    receipt = _receipt(depo)
    services.post_goods_receipt(depo, receipt)
    line = receipt.lines.get()
    services.set_receipt_costs(
        depo,
        receipt,
        lines=[{"id": line.pk, "unit_price": D("3"), "currency": "TRY"}],
        note="2,5 TL yerine 3 TL",
    )
    manager = make_user("yonetim")

    assert any(
        note.startswith(services.PRICE_CORRECTION_NOTE) for note in _history_notes(manager, receipt)
    )
    override(manager, PRICES.key, VIEW)
    assert not any(
        note.startswith(services.PRICE_CORRECTION_NOTE) for note in _history_notes(manager, receipt)
    )


def test_lot_block_follows_its_section(make_user: Callable[..., User]) -> None:
    lot = stocked_lot("10", location=quarantine_location(), status=Lot.Status.QUARANTINE)
    lab = override(make_user("laboratuvar"), "inventory.lot_block", APPROVE)

    assert api(lab).post(url("lot-block", lot.pk), {"note": "x"}, format="json").status_code == 403
    with pytest.raises(MissingAccess):
        services.block_lot(lab, lot, "x")

    planner = override(make_user("planlama"), "inventory.lot_block", APPROVE, effect="grant")
    blocked = api(planner).post(url("lot-block", lot.pk), {"note": "Şikâyet"}, format="json")
    assert blocked.status_code == 200, blocked.json()
    assert blocked.json()["status"] == "BLOCKED"


def test_posting_an_adjustment_needs_approve_while_drafting_needs_change(
    make_user: Callable[..., User],
) -> None:
    depo = make_user("depo")
    lot = stocked_lot("10", location=storage_location())
    client = api(override(depo, "inventory.adjustments", APPROVE))
    payload = {
        "adjustment_date": "2026-10-20",
        "note": "Sayım",
        "lines": [
            {
                "lot": lot.pk,
                "location": lot.balances.get().location_id,
                "counted_quantity": "8",
                "reason": "Fire",
            }
        ],
    }

    created = client.post(url("adjustment-list"), payload, format="json")
    assert created.status_code == 201, created.json()
    adjustment = created.json()["id"]
    assert (
        client.patch(
            url("adjustment-detail", adjustment), {"note": "Sayım 2"}, format="json"
        ).status_code
        == 200
    )
    posted = client.post(url("adjustment-post", adjustment))
    assert posted.status_code == 403
    assert posted.json()["required"] == [{"key": "inventory.adjustments", "level": "approve"}]


def test_seeing_prices_without_entering_them_keeps_submitted_prices_out(
    make_user: Callable[..., User],
) -> None:
    # Depoya Fiyatları görür eklenir; Mal kabul fiyat ve masrafları: Değiştirir yoktur.
    depo = override(make_user("depo"), PRICES.key, VIEW, effect="grant")
    receipt = _receipt(make_user("depo"))
    line = receipt.lines.get()
    client = api(depo)

    detail = client.get(url("goods-receipt-detail", receipt.pk)).json()
    assert detail["lines"][0]["unit_price"] == "2.5000"
    patched = client.patch(
        url("goods-receipt-detail", receipt.pk),
        {"lines": [{**detail["lines"][0], "unit_price": "99"}]},
        format="json",
    )
    assert patched.status_code == 200, patched.json()
    line.refresh_from_db()
    assert line.unit_price == D("2.5")
    assert (
        client.post(
            url("goods-receipt-costs", receipt.pk), {"lines": []}, format="json"
        ).status_code
        == 403
    )
