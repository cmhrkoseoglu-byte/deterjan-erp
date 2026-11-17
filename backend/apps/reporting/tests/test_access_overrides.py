"""Kişiye özel ayarla panolar ve raporlar (docs/plan/kisi-yetkileri.md §10, 6. adım): kaldırılan
ya da verilen bölüm pano listesinde, panoda, rapor listesinde, ekranda, dışa aktarmada, arka plan
işinde ve rapor dosyasının indirilmesinde aynı kararı verir. Hassas veri (Maliyetleri görür,
Fiyatları görür) sütunları, panodaki tutarları ve indirmeyi açar ya da kapatır."""

import io
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.access import COSTS, PRICES, VIEW
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AccessOverride, User
from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA, SATIN_ALMA, YONETIM
from apps.inventory.services import set_lot_cost
from apps.inventory.testing import assert_stock_invariants
from apps.inventory.tests.factories import stocked_lot
from apps.reporting import services
from apps.reporting.access import LAB, MANAGEMENT, STOCK, WAREHOUSE
from apps.reporting.models import ReportJob
from apps.reporting.reports import REPORTS

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

BASE = "/api/v1/reporting"
Commit = Callable[[], AbstractContextManager[Any]]
GONE = "Bu dosyayı indirme yetkiniz artık yok."


@pytest.fixture
def invariants(db: None) -> Iterator[None]:
    """Test sonunda stok değişmezlerini doğrular (CLAUDE.md §7)."""
    yield
    assert_stock_invariants()


def override(user: User, key: str, level: str = VIEW, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def required(response: Any) -> list[dict[str, str]]:
    return list(response.json()["required"])


def costed_lot(quantity: str, unit_cost: str) -> Any:
    lot = stocked_lot(quantity)
    return set_lot_cost(None, lot, Decimal(unit_cost), estimated=False)


def background_job(user: User, code: str, commit: Commit, monkeypatch: Any) -> ReportJob:
    """Raporu arka plan işi olarak hazırlatır (Celery testte hemen çalışır)."""
    monkeypatch.setattr(services, "SYNC_ROW_LIMIT", -1)
    with commit():
        response = api(user).post(
            f"{BASE}/reports/{code}/export/", {"file_format": "xlsx"}, format="json"
        )
    assert response.status_code == 202, response.content
    job = ReportJob.objects.get(pk=response.json()["id"])
    assert job.status == ReportJob.Status.DONE, job.error
    return job


def sheet_values(response: Any) -> set[Any]:
    sheet = load_workbook(io.BytesIO(b"".join(response.streaming_content))).active
    return {c for row in sheet.iter_rows(values_only=True) for c in row if c}


# --- panolar ---------------------------------------------------------------------------------


def test_dashboard_revoked_from_depo(make_user: Callable[..., User]) -> None:
    depo = override(make_user(DEPO), WAREHOUSE.key)
    client = api(depo)

    codes = [d["code"] for d in client.get(f"{BASE}/dashboards/").json()]
    assert codes == ["shipping"]
    refused = client.get(f"{BASE}/dashboards/warehouse/")
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Bu panoyu görme yetkiniz yok."
    assert required(refused) == [{"key": WAREHOUSE.key, "level": VIEW}]
    assert client.head(f"{BASE}/dashboards/warehouse/").status_code == 403
    # Bilinmeyen pano önce 404; OPTIONS bugünkü gibi herkese açık; karşılanmayan metot 405.
    assert client.get(f"{BASE}/dashboards/nope/").status_code == 404
    assert client.options(f"{BASE}/dashboards/warehouse/").status_code == 200
    assert client.post(f"{BASE}/dashboards/warehouse/").status_code == 405
    assert client.get(f"{BASE}/dashboards/shipping/").status_code == 200


def test_dashboard_granted_to_lab(make_user: Callable[..., User]) -> None:
    lab = make_user(LABORATUVAR)
    client = api(lab)
    assert client.get(f"{BASE}/dashboards/management/").status_code == 403

    override(lab, MANAGEMENT.key, effect="grant")

    assert [d["code"] for d in client.get(f"{BASE}/dashboards/").json()] == ["management", "lab"]
    data = client.get(f"{BASE}/dashboards/management/").json()
    assert data["stock_value"] is None
    assert data["approvals"]["purchase_orders"]["total_try"] is None


def test_management_dashboard_money_follows_costs_and_prices(
    make_user: Callable[..., User],
) -> None:
    costed_lot("10", "2.5")
    planner = make_user(PLANLAMA)
    client = api(planner)
    data = client.get(f"{BASE}/dashboards/management/").json()
    assert data["stock_value"] is None
    assert data["approvals"]["purchase_orders"]["total_try"] is None

    # Fiyatları görür onay bekleyen siparişlerin TL toplamını açar, stok değerini açmaz.
    override(planner, PRICES.key, effect="grant")
    data = client.get(f"{BASE}/dashboards/management/").json()
    assert data["approvals"]["purchase_orders"]["total_try"] == "0"
    assert data["stock_value"] is None

    # Maliyetleri görür stok değerini açar.
    override(planner, COSTS.key, effect="grant")
    data = client.get(f"{BASE}/dashboards/management/").json()
    assert data["stock_value"]["total"] == "25.00"

    # Yönetimden Fiyatları görür kaldırılınca toplam kapanır.
    manager = override(make_user(YONETIM), PRICES.key)
    data = api(manager).get(f"{BASE}/dashboards/management/").json()
    assert data["approvals"]["purchase_orders"]["total_try"] is None


# --- raporlar --------------------------------------------------------------------------------


def test_stock_reports_revoked_from_depo(make_user: Callable[..., User]) -> None:
    depo = override(make_user(DEPO), STOCK.key)
    client = api(depo)

    assert client.get(f"{BASE}/reports/").json() == []
    for code in ("stock-status", "stock-movements"):
        refused = client.get(f"{BASE}/reports/{code}/")
        assert refused.status_code == 403, code
        assert refused.json()["detail"] == "Bu raporu görme yetkiniz yok."
        assert required(refused) == [{"key": STOCK.key, "level": VIEW}]
        # Yetki gövdeden önce denetlenir: bozuk gövde de 403.
        export = client.post(f"{BASE}/reports/{code}/export/", {"file_format": "csv"})
        assert export.status_code == 403
        assert required(export) == [{"key": STOCK.key, "level": VIEW}]
        assert client.options(f"{BASE}/reports/{code}/").status_code == 200
    with pytest.raises(BusinessRuleError) as error:
        services.export_report(depo, REPORTS["stock-status"], {}, "xlsx")
    assert error.value.code == "report_forbidden"


def test_quality_report_granted_to_depo(make_user: Callable[..., User]) -> None:
    depo = make_user(DEPO)
    client = api(depo)
    assert client.get(f"{BASE}/reports/quality/").status_code == 403

    override(depo, LAB.key, effect="grant")

    codes = {r["code"] for r in client.get(f"{BASE}/reports/").json()}
    assert codes == {"stock-status", "stock-movements", "quality"}
    assert client.get(f"{BASE}/reports/quality/").status_code == 200
    # Pano ve rapor aynı bölümde: laboratuvar panosu da açılır.
    assert client.get(f"{BASE}/dashboards/lab/").status_code == 200


def test_cost_columns_follow_costs(make_user: Callable[..., User]) -> None:
    costed_lot("10", "2.5")
    depo = override(make_user(DEPO), PRICES.key, effect="grant")
    override(depo, COSTS.key, effect="grant")  # Maliyetleri görür, Fiyatları görür'ü ister
    page = api(depo).get(f"{BASE}/reports/stock-status/").json()
    assert {"unit_cost", "value"} <= {c["key"] for c in page["columns"]}
    assert any(item["kind"] == "money" for item in page["summary"])

    manager = override(make_user(YONETIM), COSTS.key)
    page = api(manager).get(f"{BASE}/reports/stock-status/").json()
    assert "value" not in {c["key"] for c in page["columns"]}
    assert all(item["kind"] != "money" for item in page["summary"])


def test_background_job_fails_when_section_revoked_before_it_runs(
    make_user: Callable[..., User], commit: Commit, monkeypatch: Any
) -> None:
    stocked_lot("10")
    depo = make_user(DEPO)
    monkeypatch.setattr(services, "SYNC_ROW_LIMIT", -1)
    job = services.create_job(depo, REPORTS["stock-status"], {}, "xlsx")
    override(depo, STOCK.key)

    job = services.run_job(job.pk)

    assert job.status == ReportJob.Status.FAILED
    assert job.error == "Bu raporu görme yetkiniz yok."


# --- rapor dosyasının indirilmesi (§8 madde 12) ----------------------------------------------


def test_job_stores_section_and_sensitive_kinds(
    make_user: Callable[..., User], commit: Commit, monkeypatch: Any
) -> None:
    costed_lot("10", "2.5")
    manager_job = background_job(make_user(YONETIM), "stock-status", commit, monkeypatch)
    assert (manager_job.section, manager_job.has_costs, manager_job.has_prices) == (
        STOCK.key,
        True,
        False,
    )
    depo_job = background_job(make_user(DEPO), "stock-status", commit, monkeypatch)
    assert (depo_job.section, depo_job.has_costs) == (STOCK.key, False)
    lab_job = background_job(make_user(LABORATUVAR), "quality", commit, monkeypatch)
    assert (lab_job.section, lab_job.has_costs) == (LAB.key, False)


def test_download_rechecks_the_section(
    make_user: Callable[..., User], commit: Commit, monkeypatch: Any
) -> None:
    stocked_lot("10")
    depo = make_user(DEPO)
    job = background_job(depo, "stock-movements", commit, monkeypatch)
    client = api(depo)
    assert client.get(f"{BASE}/jobs/{job.pk}/download/").status_code == 200
    assert client.get(f"{BASE}/jobs/{job.pk}/").json()["download_required"] == []

    override(depo, STOCK.key)

    refused = client.get(f"{BASE}/jobs/{job.pk}/download/")
    assert refused.status_code == 403
    assert refused.json()["detail"] == GONE
    assert required(refused) == [{"key": STOCK.key, "level": VIEW}]
    assert client.head(f"{BASE}/jobs/{job.pk}/download/").status_code == 403
    # İş listesi ve ayrıntısı değişmez.
    detail = client.get(f"{BASE}/jobs/{job.pk}/").json()
    assert detail["can_download"] is True
    # Ön yüz indirme bağlantısını eksik yetki varken göstermez (plan §8 madde 12).
    assert detail["download_required"] == [{"key": STOCK.key, "level": VIEW}]
    assert [j["id"] for j in client.get(f"{BASE}/jobs/").json()["results"]] == [job.pk]
    # Başkasının dosyası önce 404 (yetki denetiminden önce).
    other = override(make_user(DEPO), STOCK.key)
    assert api(other).get(f"{BASE}/jobs/{job.pk}/download/").status_code == 404

    AccessOverride.objects.filter(user=depo).delete()
    depo.refresh_access()
    assert client.get(f"{BASE}/jobs/{job.pk}/download/").status_code == 200


def test_download_of_not_ready_file_stays_404(
    make_user: Callable[..., User], commit: Commit, monkeypatch: Any
) -> None:
    depo = make_user(DEPO)
    job = background_job(depo, "stock-status", commit, monkeypatch)
    assert job.expires_at is not None
    services.expire_jobs(job.expires_at + timedelta(days=1))
    override(depo, STOCK.key)
    assert api(depo).get(f"{BASE}/jobs/{job.pk}/download/").status_code == 404


def test_download_rechecks_costs_of_a_file_with_cost_columns(
    make_user: Callable[..., User], commit: Commit, monkeypatch: Any
) -> None:
    costed_lot("10", "2.5")
    manager = make_user(YONETIM)
    job = background_job(manager, "stock-status", commit, monkeypatch)
    client = api(manager)
    assert "Stok değeri (TL)" in sheet_values(client.get(f"{BASE}/jobs/{job.pk}/download/"))

    override(manager, COSTS.key)

    refused = client.get(f"{BASE}/jobs/{job.pk}/download/")
    assert refused.status_code == 403
    assert refused.json()["detail"] == GONE
    assert required(refused) == [{"key": COSTS.key, "level": VIEW}]
    # Maliyet sütunu olmayan dosya Maliyetleri görür istemez.
    depo = override(make_user(DEPO), COSTS.key)
    plain = background_job(depo, "stock-status", commit, monkeypatch)
    assert api(depo).get(f"{BASE}/jobs/{plain.pk}/download/").status_code == 200


def test_download_rechecks_prices_and_every_missing_right(
    make_user: Callable[..., User], commit: Commit, monkeypatch: Any
) -> None:
    buyer = make_user(SATIN_ALMA)
    job = background_job(buyer, "stock-status", commit, monkeypatch)
    # Fiyat sütunu bugün hiçbir raporda yok; dosyada fiyat olsaydı Fiyatları görür de aranırdı.
    ReportJob.objects.filter(pk=job.pk).update(has_prices=True)
    client = api(buyer)
    assert client.get(f"{BASE}/jobs/{job.pk}/download/").status_code == 200

    override(buyer, PRICES.key)
    override(buyer, STOCK.key)

    refused = client.get(f"{BASE}/jobs/{job.pk}/download/")
    assert refused.status_code == 403
    assert required(refused) == [
        {"key": STOCK.key, "level": VIEW},
        {"key": PRICES.key, "level": VIEW},
    ]


def test_download_granted_section_opens_a_handed_over_file(
    make_user: Callable[..., User], commit: Commit, monkeypatch: Any
) -> None:
    """Rolü değişmeyen kişide indirme isteğin kararını izler; yetki verilince dosya iner."""
    lab = make_user(LABORATUVAR)
    job = background_job(make_user(YONETIM), "task-durations", commit, monkeypatch)
    ReportJob.objects.filter(pk=job.pk).update(created_by=lab)
    client = api(lab)
    refused = client.get(f"{BASE}/jobs/{job.pk}/download/")
    assert refused.status_code == 403
    assert required(refused) == [{"key": MANAGEMENT.key, "level": VIEW}]

    override(lab, MANAGEMENT.key, effect="grant")

    assert client.get(f"{BASE}/jobs/{job.pk}/download/").status_code == 200
