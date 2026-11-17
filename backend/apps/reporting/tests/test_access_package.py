"""Paket denkliği: panolar ve raporlar (docs/plan/kisi-yetkileri.md §3.15, §5.5 3. parça).

Bugünkü her rol denetimi bir yetki ifadesine eşlenir; kişiye özel ayar yokken 256 rol bileşiminde
aynı kararı verdiği kanıtlanır.

- Panolar: eski `DASHBOARDS` rolleri hem pano listesini hem pano verisini korurdu.
- Raporlar: `can_view` rapor listesini, ekranı, dışa aktarmayı ve arka plan işini korur; rapor
  dosyasının indirilmesinde aynı yetki yeniden denetlenir (§8 madde 12; rol değişmedikçe aynı
  karar).
- Hassas sütunlar: `can_see("cost")` Maliyetleri görür'e, `can_see("price")` Fiyatları görür'e.
- Ön yüz (`Dashboards.tsx`): kart bağlantıları hedef rota ve sekmenin korumasıyla (plan §5.9);
  kayıt bağlantıları (`link(...)`) bugün panoyu gören herkese koşulsuz, plan hedef sayfa
  açılabiliyorsa gösterir. Panoda çizilen bağlantıda bugünkü karar "panoyu gören ve hedefi
  açabilen"dir.

6. adımda modül bölüm denetimine geçti: arka uç satırlarının koddaki rol sabitlerine bağlantısı
kaldırıldı (sabitler yok); satırlar eski rollerin kataloğa denkliğini kayıt olarak tutar, koddaki
bölümleri `test_code_uses_the_sections` denetler. Ön yüz sabitlerine bağlantı 8. adıma kadar
kalır. `menuRoles(...)` satırları kabuğun `MENU_ROLES` tablosunu kullanır
(`apps/core/tests/test_access_package_shell.py`).
"""

from apps.core.access import APPROVE, COSTS, PRICES
from apps.core.tests.access_helpers import (
    SIGNED_IN,
    OldRoles,
    Row,
    all_of,
    any_of,
    assert_rows,
    effective_for,
    level,
    read,
    role_subsets,
)
from apps.core.tests.test_access_package_shell import (
    MENU_ROLES,
    Planned,
    page,
    planned_errors,
    visible,
)
from apps.filling import access as filling
from apps.hse import access as hse
from apps.inventory import access as inventory
from apps.maintenance import access as maintenance
from apps.production import access as production
from apps.purchasing import access as purchasing
from apps.quality import access as quality
from apps.reporting.access import (
    FILLING,
    LAB,
    MANAGEMENT,
    PRODUCTION,
    SHIPPING,
    SHIPPING_REPORT,
    STOCK,
    WAREHOUSE,
)
from apps.reporting.api.views import DASHBOARDS
from apps.reporting.reports import REPORTS, SENSITIVE_SECTIONS
from apps.sales import access as sales

# Eski api/views.py DASHBOARDS rol listeleri (5. adıma kadar koddaydı).
OLD_DASHBOARD_ROLES: dict[str, tuple[str, ...]] = {
    "management": ("yonetim", "planlama"),
    "warehouse": ("depo", "planlama", "yonetim"),
    "lab": ("laboratuvar", "planlama", "yonetim"),
    "production": ("uretim", "planlama", "yonetim"),
    "shipping": ("sevkiyat", "depo", "planlama", "yonetim"),
}
OLD_STOCK_ROLES = ("depo", "planlama", "yonetim", "satin_alma")  # eski reports.STOCK_ROLES
OLD_COST_ROLES = ("yonetim",)  # eski reports.SENSITIVE_ROLES["cost"]
OLD_PRICE_ROLES = ("satin_alma", "yonetim")  # eski reports.SENSITIVE_ROLES["price"]


def _dashboard(code: str) -> tuple[str, ...]:
    return OLD_DASHBOARD_ROLES[code]


def _on_dashboard(code: str, target: OldRoles) -> tuple[str, ...]:
    """Panoda çizilen bağlantının bugünkü kararı: panoyu gören ve hedefi açabilen roller."""
    roles = _dashboard(code)
    if target == SIGNED_IN:
        return roles
    return tuple(role for role in roles if role in target)


ROWS: list[Row] = [
    # Panolar (DashboardListView ve DashboardView).
    Row(
        "reporting.api.views.DASHBOARDS['management']",
        ("yonetim", "planlama"),
        level(MANAGEMENT),
    ),
    Row(
        "reporting.api.views.DASHBOARDS['warehouse']",
        ("depo", "planlama", "yonetim"),
        level(WAREHOUSE),
    ),
    Row(
        "reporting.api.views.DASHBOARDS['lab']",
        ("laboratuvar", "planlama", "yonetim"),
        level(LAB),
    ),
    Row(
        "reporting.api.views.DASHBOARDS['production']",
        ("uretim", "planlama", "yonetim"),
        level(PRODUCTION),
    ),
    Row(
        "reporting.api.views.DASHBOARDS['shipping']",
        ("sevkiyat", "depo", "planlama", "yonetim"),
        level(SHIPPING),
    ),
    # Yönetim panosundaki stok değeri: show_costs=can_see(user, "cost").
    Row(
        "reporting.api.views.DASHBOARDS['management'] show_costs → stock_value",
        OLD_COST_ROLES,
        level(COSTS),
    ),
    # Raporlar (can_view: reports_for, _definition, export_report, run_job). İndirme
    # (ReportJobDownloadView) raporun bölümünü ve dosyadaki hassas türü yeniden denetler; rol
    # değişmedikçe istekteki kararla aynıdır (§8 madde 12).
    Row(
        "reporting.reports.STOCK_ROLES (stock-status, stock-movements)",
        OLD_STOCK_ROLES,
        level(STOCK),
    ),
    Row(
        "reporting.reports.REPORTS['production'].roles",
        ("uretim", "planlama", "yonetim"),
        level(PRODUCTION),
    ),
    Row(
        "reporting.reports.REPORTS['filling'].roles",
        ("dolum", "planlama", "yonetim"),
        level(FILLING),
    ),
    Row(
        "reporting.reports.REPORTS['quality'].roles",
        ("laboratuvar", "planlama", "yonetim"),
        level(LAB),
    ),
    Row(
        "reporting.reports.REPORTS['shipments'].roles",
        ("sevkiyat", "planlama", "yonetim"),
        level(SHIPPING_REPORT),
    ),
    Row(
        "reporting.reports.REPORTS['task-durations'].roles",
        ("planlama", "yonetim"),
        level(MANAGEMENT),
    ),
    # Hassas sütunlar ve özetler.
    Row(
        "reporting.reports.can_see('cost'): visible_columns, visible_summary (money)",
        OLD_COST_ROLES,
        level(COSTS),
    ),
    Row(
        "reporting.reports.SENSITIVE_ROLES['price'] (fiyat sütunu bugün yok)",
        OLD_PRICE_ROLES,
        level(PRICES),
    ),
    # Ön yüz: yönetim panosunun kart bağlantıları ve başlığı.
    Row(
        "Dashboards.tsx Approvals /kalite/onay kartı (APPROVAL_ROLES)",
        ("yonetim",),
        page("quality", quality.CONDITIONAL),
        live="frontend:src/modules/quality/config.ts:APPROVAL_ROLES",
    ),
    Row(
        "Dashboards.tsx Approvals /satin-alma/siparisler kartı (ORDER_READ_ROLES)",
        ("satin_alma", "yonetim", "depo"),
        page("purchasing", purchasing.ORDERS),
        live="frontend:src/modules/purchasing/config.ts:ORDER_READ_ROLES",
    ),
    Row(
        "Dashboards.tsx ManagementView başlığı 'Onayınızı bekleyenler' (APPROVAL_ROLES)",
        ("yonetim",),
        any_of(level(quality.CONDITIONAL, APPROVE), level(purchasing.OVER_LIMIT, APPROVE)),
        live="frontend:src/modules/quality/config.ts:APPROVAL_ROLES",
    ),
    # menuRoles("hse") giriş yapan herkes; bağlantı yalnız yönetim panosunda çizilir (rolsüz kişi
    # panoyu açamaz, §8 madde 1 burada görünmez).
    Row(
        "Dashboards.tsx /isg/olaylar bağlantıları (Approvals kartı, Dikkat 'injuries')",
        ("yonetim", "planlama"),
        all_of(level(MANAGEMENT), page("hse", hse.INCIDENT_REPORT, hse.INCIDENTS)),
    ),
    Row(
        "Dashboards.tsx Dikkat 'stock' /depo/stok (menuRoles('inventory'))",
        MENU_ROLES["inventory"],
        page("inventory", inventory.STOCK),
    ),
    Row(
        "Dashboards.tsx Dikkat 'expired' /depo/lotlar (menuRoles('inventory'))",
        MENU_ROLES["inventory"],
        page("inventory", inventory.LOTS),
    ),
    Row(
        "Dashboards.tsx Dikkat 'late-orders' ve Pipeline /sevkiyat/siparisler (menuRoles('sales'))",
        MENU_ROLES["sales"],
        page("sales", sales.ORDERS),
    ),
    Row(
        "Dashboards.tsx Dikkat 'downtimes' /bakim/duruslar (menuRoles('maintenance'))",
        MENU_ROLES["maintenance"],
        page("maintenance", maintenance.DOWNTIMES),
    ),
    Row(
        "Dashboards.tsx Dikkat 'plans' /bakim/planlar (menuRoles('maintenance'))",
        MENU_ROLES["maintenance"],
        page("maintenance", maintenance.PLANS),
    ),
    Row(
        "Dashboards.tsx Dikkat 'qc' /kalite/numuneler (menuRoles('quality'))",
        MENU_ROLES["quality"],
        page("quality", quality.SAMPLES),
    ),
    Row(
        "Dashboards.tsx Pipeline /uretim/emirler (menuRoles('production'))",
        MENU_ROLES["production"],
        page("production", production.ORDERS),
    ),
    Row(
        "Dashboards.tsx Pipeline /dolum/emirler (menuRoles('filling'))",
        MENU_ROLES["filling"],
        page("filling", filling.ORDERS),
    ),
    # Kayıt bağlantıları: bugün panoyu gören herkese.
    Row(
        "Dashboards.tsx ManagementView lot bağlantıları (inventory.lot)",
        ("yonetim", "planlama"),
        all_of(level(MANAGEMENT), read(inventory.LOTS)),
    ),
    Row(
        "Dashboards.tsx WarehouseView emir bağlantıları (production.productionorder)",
        ("depo", "planlama", "yonetim"),
        all_of(level(WAREHOUSE), visible("production")),
    ),
    Row(
        "Dashboards.tsx WarehouseView emir bağlantıları (filling.fillingorder)",
        ("depo", "planlama", "yonetim"),
        all_of(level(WAREHOUSE), visible("filling")),
    ),
    Row(
        "Dashboards.tsx WarehouseView sevkiyat bağlantıları (sales.shipment)",
        ("depo", "planlama", "yonetim"),
        all_of(level(WAREHOUSE), visible("sales")),
    ),
    Row(
        "Dashboards.tsx ProductionView şarj ve emir bağlantıları",
        ("uretim", "planlama", "yonetim"),
        all_of(level(PRODUCTION), visible("production")),
    ),
    Row(
        "Dashboards.tsx ShippingView sevkiyat ve sipariş bağlantıları",
        ("sevkiyat", "depo", "planlama", "yonetim"),
        all_of(level(SHIPPING), visible("sales")),
    ),
]

# §8'deki ilk gün değişiklikleri (plan §5.5 "İzin listesi").
PLANNED: list[Planned] = [
    Planned(
        "§8 madde 2: laboratuvar panosundaki numune numaraları planlamada düz metin",
        Row(
            "Dashboards.tsx LabView numune bağlantıları (quality.sample)",
            ("laboratuvar", "planlama", "yonetim"),
            all_of(level(LAB), visible("quality")),
        ),
        ("laboratuvar", "yonetim"),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_planned_changes() -> None:
    errors = planned_errors(PLANNED)
    assert not errors, "Planlı farklar bozuk:\n" + "\n".join(errors)


# Onay bekleyen satın alma siparişlerinin TL toplamı (plan §8, sahibin onayı 2026-11-11): plan
# §3.15 ve §3.18 Fiyatları görür'e bağlar; 5. adıma kadar kod yalnız yönetime gösteriyordu
# (show_costs, D-15), 6. adımda show_prices=Fiyatları görür.
# Kural bir rol listesiyle yazılamaz (yönetim ya da planlama ve satın alma birlikte); katalog
# tarafını bu test, kod tarafını adıma bağlı
# `test_pending_purchase_total_for_planning_and_purchasing` denetler.
PENDING_PURCHASE_TOTAL = all_of(level(MANAGEMENT), level(PRICES))


def test_pending_purchase_total_follows_the_approved_rule() -> None:
    for subset in role_subsets():
        expected = "yonetim" in subset or {"planlama", "satin_alma"} <= subset
        assert PENDING_PURCHASE_TOTAL.evaluate(effective_for(subset)) is expected, sorted(subset)


def test_code_uses_the_sections() -> None:
    """Koddaki panolar, raporlar ve hassas sütunlar satırlardaki bölümleri kullanır."""
    assert {code: section for code, (_, section, _) in DASHBOARDS.items()} == {
        "management": MANAGEMENT,
        "warehouse": WAREHOUSE,
        "lab": LAB,
        "production": PRODUCTION,
        "shipping": SHIPPING,
    }
    assert set(DASHBOARDS) == set(OLD_DASHBOARD_ROLES)
    assert {code: d.section for code, d in REPORTS.items()} == {
        "stock-status": STOCK,
        "stock-movements": STOCK,
        "production": PRODUCTION,
        "filling": FILLING,
        "quality": LAB,
        "shipments": SHIPPING_REPORT,
        "task-durations": MANAGEMENT,
    }
    assert SENSITIVE_SECTIONS == {"cost": COSTS, "price": PRICES}
    # Yönetim panosundaki İSG bağlantısı: panoyu gören ve menüsü açık olan (ön yüz tablosu).
    assert set(_on_dashboard("management", MENU_ROLES["hse"])) == {"yonetim", "planlama"}
