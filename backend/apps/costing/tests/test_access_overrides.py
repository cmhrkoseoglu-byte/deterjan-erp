"""Kişiye özel ayarla maliyet (docs/plan/kisi-yetkileri.md §10, 5. adım): bölümler Maliyetleri
görür'ü ister; personel maliyetinden işçilik oranı Gider oranları: Değiştirir'i de ister; eski
işçilik notundaki tutar Personel maliyeti: Görür'ü olmayana gösterilmez (plan §5.6). Maliyet
hesabı denetimsiz bir sistem adımıdır (plan §5.4)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.access import CHANGE, COSTS, PRICES, VIEW
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.core.roles import DEPO, PLANLAMA, SATIN_ALMA, YONETIM
from apps.costing import services
from apps.costing.access import LOT_COSTS, PERSONNEL_COST, RATES
from apps.costing.models import CostStage, LotCost
from apps.inventory import services as inventory
from apps.masterdata.tests.factories import SupplierFactory, unit
from apps.production.tests.factories import build_plant

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
URL = "/api/v1/costing"
OLD_NOTE = "Personel maliyeti Eylül 2026 (BR-2026-00001): 53.437,50 TL / 980,00 kg"


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User | None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def required(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"key": key, "level": level} for key, level in pairs]


def _rate(actor: User, note: str, valid_from: date) -> Any:
    return services.create_rate(
        actor,
        {
            "stage": CostStage.PRODUCTION,
            "kind": "LABOR",
            "rate_per_kg": D("54.5281"),
            "valid_from": valid_from,
            "note": note,
        },
    )


def test_rates_change_is_needed_for_rates_and_the_labor_rate(staff: dict[str, User]) -> None:
    manager = override(staff[YONETIM], RATES.key, CHANGE)
    client = api(manager)
    assert client.get(f"{URL}/rates/").status_code == 200
    payload = {
        "stage": "PRODUCTION",
        "kind": "ENERGY",
        "rate_per_kg": "1",
        "valid_from": "2026-01-01",
    }
    refused = client.post(f"{URL}/rates/", payload, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == required((RATES.key, CHANGE))
    labor = client.post(
        f"{URL}/personnel-costs/2026/9/labor-rate/",
        {"stage": "PRODUCTION", "valid_from": "2026-10-01"},
        format="json",
    )
    assert labor.status_code == 403
    assert labor.json()["required"] == required((RATES.key, CHANGE))
    with pytest.raises(MissingAccess) as exc:
        services.add_labor_rate_from_personnel_cost(
            manager, 2026, 9, CostStage.PRODUCTION, date(2026, 10, 1)
        )
    assert exc.value.required == ((RATES.key, CHANGE),)
    # Personel maliyetinin kendi işleri açık kalır.
    assert client.get(f"{URL}/cost-centers/").status_code == 200


def test_lot_costs_granted_to_a_price_viewer(make_user: Callable[..., User]) -> None:
    """Lot maliyetleri Maliyetleri görür'ü ister; ikisi verilen satın almacı lot maliyetlerini ve
    raporları okur, yeniden hesaplayamaz, gider oranlarını göremez."""
    buyer = make_user(SATIN_ALMA)
    client = api(buyer)
    assert client.get(f"{URL}/lot-costs/").status_code == 403
    override(buyer, COSTS.key, VIEW, effect="grant")
    override(buyer, LOT_COSTS.key, VIEW, effect="grant")
    assert client.get(f"{URL}/lot-costs/").status_code == 200
    assert client.get(f"{URL}/reports/cost-trend/").status_code == 200
    refused = client.post(f"{URL}/lots/999999/recalculate/", {"note": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == required((LOT_COSTS.key, CHANGE))
    rates = client.get(f"{URL}/rates/")
    assert rates.status_code == 403
    assert rates.json()["required"] == required((RATES.key, VIEW))
    # Ön koşulu (Fiyatları görür) kaldırılınca Maliyetleri görür ve lot maliyetleri de düşer.
    override(buyer, PRICES.key, VIEW)
    assert client.get(f"{URL}/lot-costs/").status_code == 403


def test_old_labor_note_amount_follows_personnel_cost_view(staff: dict[str, User]) -> None:
    """Plan §5.6: eski işçilik oranı notundaki tutar Personel maliyeti: Görür'ü olmayana
    gösterilmez; yeni not tutar taşımaz."""
    manager = staff[YONETIM]
    old = _rate(manager, OLD_NOTE, date(2026, 10, 1))
    new = _rate(manager, "Personel maliyetinden (BR-2026-00002)", date(2026, 11, 1))
    plain = _rate(manager, "Enerji faturası 1.234,56 TL", date(2026, 12, 1))
    client = api(manager)

    def notes() -> dict[int, str]:
        response = client.get(f"{URL}/rates/")
        assert response.status_code == 200
        return {row["id"]: row["note"] for row in response.json()["results"]}

    assert notes()[old.pk] == OLD_NOTE
    override(manager, PERSONNEL_COST.key, VIEW)
    shown = notes()
    assert shown[old.pk] == "Personel maliyeti Eylül 2026 (BR-2026-00001)"
    assert shown[new.pk] == "Personel maliyetinden (BR-2026-00002)"
    assert shown[plain.pk] == "Enerji faturası 1.234,56 TL"
    assert client.get(f"{URL}/rates/{old.pk}/").json()["note"] == shown[old.pk]
    assert client.get(f"{URL}/cost-centers/").status_code == 403


def test_personnel_cost_change_revoked_keeps_the_report(staff: dict[str, User]) -> None:
    client = api(override(staff[YONETIM], PERSONNEL_COST.key, CHANGE))
    assert client.get(f"{URL}/cost-centers/").status_code == 200
    assert client.get(f"{URL}/personnel-costs/2026/9/").status_code == 200
    assert client.options(f"{URL}/personnel-costs/2026/9/labor-rate/").status_code == 200
    refused = client.put(
        f"{URL}/cost-centers/", {"department": "Dolum", "stage": "FILLING"}, format="json"
    )
    assert refused.status_code == 403
    assert refused.json()["required"] == required((PERSONNEL_COST.key, CHANGE))
    labor = client.post(
        f"{URL}/personnel-costs/2026/9/labor-rate/",
        {"stage": "PRODUCTION", "valid_from": "2026-10-01"},
        format="json",
    )
    assert labor.status_code == 403
    assert labor.json()["required"] == required((PERSONNEL_COST.key, CHANGE))


def test_unrouted_methods_keep_todays_rule(staff: dict[str, User]) -> None:
    """Bugün her metot (HEAD, OPTIONS ve karşılanmayan metotlar) yönetime açıktı; karşılanmayan
    metot yetkiden sonra 405 döner."""
    manager, other = api(staff[YONETIM]), api(staff[PLANLAMA])
    rate = _rate(staff[YONETIM], "", date(2026, 10, 1))

    assert manager.delete(f"{URL}/rates/{rate.pk}/").status_code == 405
    assert other.delete(f"{URL}/rates/{rate.pk}/").status_code == 403
    assert manager.post(f"{URL}/lot-costs/").status_code == 405
    assert other.post(f"{URL}/lot-costs/").status_code == 403
    assert manager.post(f"{URL}/reports/cost-trend/").status_code == 405
    assert other.post(f"{URL}/reports/cost-trend/xlsx/").status_code == 403
    assert manager.get(f"{URL}/lots/999999/recalculate/").status_code == 404
    assert other.get(f"{URL}/lots/999999/recalculate/").status_code == 403
    assert manager.put(f"{URL}/lots/999999/recalculate/").status_code == 405
    labor = f"{URL}/personnel-costs/2026/9/labor-rate/"
    assert manager.get(labor).status_code == 405
    assert manager.options(labor).status_code == 200
    assert other.options(labor).status_code == 403
    assert other.get(labor).status_code == 403
    assert manager.post(f"{URL}/cost-centers/").status_code == 405
    assert other.post(f"{URL}/cost-centers/").status_code == 403
    assert manager.post(f"{URL}/personnel-costs/2026/9/xlsx/").status_code == 405
    assert manager.head(f"{URL}/rates/").status_code == 200
    assert other.head(f"{URL}/rates/").status_code == 403
    assert api(None).delete(f"{URL}/rates/{rate.pk}/").status_code == 401


def test_each_service_names_its_section_and_level(make_user: Callable[..., User]) -> None:
    """Personel maliyeti servisleri plan §3.11'deki bölüme bağlıdır (rolü olmayan kişi)."""
    nobody = make_user()
    calls: list[tuple[str, Callable[[], object], tuple[tuple[str, str], ...]]] = [
        (
            "set_department_cost_center",
            lambda: services.set_department_cost_center(nobody, "Dolum", CostStage.FILLING),
            ((PERSONNEL_COST.key, CHANGE),),
        ),
        (
            "add_labor_rate_from_personnel_cost",
            lambda: services.add_labor_rate_from_personnel_cost(
                nobody, 2026, 9, CostStage.PRODUCTION, date(2026, 10, 1)
            ),
            ((PERSONNEL_COST.key, CHANGE),),
        ),
    ]
    wrong: list[str] = []
    for name, call, expected in calls:
        try:
            call()
        except MissingAccess as error:
            if error.required != expected:
                wrong.append(f"{name}: {error.required} != {expected}")
        else:
            wrong.append(f"{name}: reddedilmedi")
    assert not wrong, "\n".join(wrong)


def test_cost_calculation_runs_for_a_receipt_poster_without_costing_access(
    staff: dict[str, User], commit: Callable[[], Any]
) -> None:
    """Giriş noktası kuralı (plan §5.4, "maliyet hesabı"): mal kabulü kaydeden depocunun maliyet
    yetkisi yoktur; lot maliyeti yine hesaplanır."""
    plant = build_plant(staff[PLANLAMA], stock=False)
    receipt = inventory.create_goods_receipt(
        staff[DEPO],
        {
            "supplier": SupplierFactory.create(),
            "receipt_date": date.today(),
            "quarantine_location": plant.quarantine,
        },
        [{"material": plant.las, "quantity": D("100"), "unit": unit("KG"), "unit_price": D("2")}],
    )
    with commit():
        inventory.post_goods_receipt(staff[DEPO], receipt)
    lot = receipt.lines.get().created_lot
    cost = LotCost.objects.get(lot=lot, is_current=True)
    assert cost.unit_cost == D("2")
