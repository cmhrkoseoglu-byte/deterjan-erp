"""Maliyet: paket denkliği (docs/plan/kisi-yetkileri.md §3.11 ve §5.5, 3. parça).

Bugünkü her rol denetimi planın bölüm ve düzeyine eşlenir; kişiye özel ayar yokken iki taraf 256
rol bileşiminin hepsinde aynı kararı vermelidir. Maliyet uç noktaları bugün `COST_ROLES` ister
(`CostPermissionMixin`), personel maliyeti servisleri `PERSONNEL_COST_ROLES`; ön yüzde menü ve
sayfa korumaları satır içi rol dizisidir.
"""

from apps.core.access import CHANGE, VIEW
from apps.core.tests.access_helpers import Need, Row, all_of, any_of, assert_rows, level
from apps.costing.access import LOT_COSTS, PERSONNEL_COST, RATES

YONETIM = ("yonetim",)
API_ROLES = "apps.costing.api.views:COST_ROLES"
SERVICE_ROLES = "apps.costing.services:PERSONNEL_COST_ROLES"
PAYROLL_LOG_ROLES = "apps.personnel.services:PERSONNEL_ROLES"
# Rapor adresi → JSON ve Excel görünümleri (`ReportView` alt sınıfları, api/urls.py REPORTS).
REPORTS = (
    ("cost-trend", "CostTrendView", "CostTrendExcelView"),
    ("batch-variance", "BatchVarianceView", "BatchVarianceExcelView"),
    ("scrap-cost", "ScrapCostView", "ScrapCostExcelView"),
    ("top-materials", "TopMaterialsView", "TopMaterialsExcelView"),
    ("stock-value", "StockValueView", "StockValueExcelView"),
)

# Modülün Görür'ü olan bölümlerinden biri: menü ve modül sayfası (plan §2 ve §5.9).
ANY_SECTION = any_of(level(LOT_COSTS, VIEW), level(RATES, VIEW), level(PERSONNEL_COST, VIEW))
# Onaylı aydan işçilik oranı Gider oranları: Değiştirir'i de ister (plan §3.11).
LABOR_RATE = all_of(level(PERSONNEL_COST, CHANGE), level(RATES, CHANGE))


def api(source: str, need: Need) -> Row:
    """api/views.py `CostPermissionMixin.get_permissions`: `HasRole(*COST_ROLES)`."""
    return Row(f"api/views.py {source}", YONETIM, need, live=API_ROLES)


ROWS = [
    api("LotCostViewSet GET lot-costs/, lot-costs/{pk}/", level(LOT_COSTS, VIEW)),
    api("LotCostHistoryView GET lots/{pk}/", level(LOT_COSTS, VIEW)),
    api("LotRecalculateView GET lots/{pk}/recalculate/", level(LOT_COSTS, VIEW)),
    api("LotRecalculateView POST lots/{pk}/recalculate/", level(LOT_COSTS, CHANGE)),
    api("CostRateViewSet GET rates/, rates/{pk}/", level(RATES, VIEW)),
    api("CostRateViewSet POST rates/, PUT/PATCH rates/{pk}/", level(RATES, CHANGE)),
    api("StandardCostViewSet GET standard-costs/, standard-costs/{pk}/", level(RATES, VIEW)),
    api(
        "StandardCostViewSet POST standard-costs/, PUT/PATCH standard-costs/{pk}/",
        level(RATES, CHANGE),
    ),
    *(
        api(f"{data}, {excel} GET reports/{name}/, reports/{name}/xlsx/", level(LOT_COSTS, VIEW))
        for name, data, excel in REPORTS
    ),
    api("PersonnelCostView GET personnel-costs/{year}/{month}/", level(PERSONNEL_COST, VIEW)),
    api(
        "PersonnelCostExcelView GET personnel-costs/{year}/{month}/xlsx/",
        level(PERSONNEL_COST, VIEW),
    ),
    api("PersonnelLaborRateView POST personnel-costs/{year}/{month}/labor-rate/", LABOR_RATE),
    api("CostCenterView GET cost-centers/", level(PERSONNEL_COST, VIEW)),
    api("CostCenterView PUT cost-centers/", level(PERSONNEL_COST, CHANGE)),
    # services.py `_require_personnel_cost_role`: `user_has_role(actor, PERSONNEL_COST_ROLES)`.
    Row(
        "services.set_department_cost_center",
        YONETIM,
        level(PERSONNEL_COST, CHANGE),
        live=SERVICE_ROLES,
    ),
    Row("services.add_labor_rate_from_personnel_cost", YONETIM, LABOR_RATE, live=SERVICE_ROLES),
    # Personel maliyeti Excel'i bordro erişim günlüğünü personelin yardımcısıyla yazar; bugün
    # oradaki `_require_role` da denetler. Plan §5.4: maliyet kendi bölümüyle denetler, günlük
    # yardımcısını denetimsiz çağırır.
    Row(
        "PersonnelCostExcelView → personnel.services.record_payroll_access",
        YONETIM,
        level(PERSONNEL_COST, VIEW),
        live=PAYROLL_LOG_ROLES,
    ),
    # Ön yüz: satır içi rol dizileri.
    Row("frontend/src/layout/menu.ts MENU costing roles", YONETIM, ANY_SECTION),
    Row("frontend/src/routes.tsx costingPage maliyet/:tab? (CostingPage)", YONETIM, ANY_SECTION),
    Row(
        "frontend/src/routes.tsx costingPage maliyet/lotlar/:lotId (LotCostPage)",
        YONETIM,
        level(LOT_COSTS, VIEW),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
