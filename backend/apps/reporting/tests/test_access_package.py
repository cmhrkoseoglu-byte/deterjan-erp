"""Paket denkliği: panolar ve raporlar (docs/plan/kisi-yetkileri.md §3.15, §5.5 3. parça).

Bugünkü her rol denetimi bir yetki ifadesine eşlenir; kişiye özel ayar yokken 256 rol bileşiminde
aynı kararı verdiği kanıtlanır.

- Panolar: `DASHBOARDS` rolleri hem pano listesini hem pano verisini korur.
- Raporlar: `can_view` rapor listesini, ekranı, dışa aktarmayı ve arka plan işini korur; rapor
  dosyasının indirilmesinde aynı yetki yeniden denetlenecek (§8 madde 12; rol değişmedikçe aynı
  karar).
- Hassas sütunlar: `can_see("cost")` Maliyetleri görür'e, `can_see("price")` Fiyatları görür'e.
- Ön yüz (`Dashboards.tsx`): kart bağlantıları hedef rota ve sekmenin korumasıyla (plan §5.9);
  kayıt bağlantıları (`link(...)`) bugün panoyu gören herkese koşulsuz, plan hedef sayfa
  açılabiliyorsa gösterir. Panoda çizilen bağlantıda bugünkü karar "panoyu gören ve hedefi
  açabilen"dir.

`DASHBOARDS`, `REPORTS` ve `SENSITIVE_ROLES` sözlük olduğundan `live=` ile okunamaz; koddaki
değerleri `test_live_dict_constants` karşılaştırır. `menuRoles(...)` satırları kabuğun
`MENU_ROLES` tablosunu kullanır (`apps/core/tests/test_access_package_shell.py`).
"""

from collections.abc import Callable, Sequence

import pytest

from apps.core.access import APPROVE, COSTS, PRICES
from apps.core.tests.access_helpers import (
    SIGNED_IN,
    Need,
    OldRoles,
    Row,
    all_of,
    any_of,
    assert_rows,
    level,
    read,
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
from apps.reporting.reports import REPORTS, SENSITIVE_ROLES, STOCK_ROLES
from apps.sales import access as sales

# Satır kaynağı → koddaki rol listesini dönen işlevler (sözlükteki sabitler için canlı denetim).
_LIVE: list[tuple[str, Callable[[], Sequence[str]]]] = []


def _row(source: str, roles: OldRoles, need: Need, *live: Callable[[], Sequence[str]]) -> Row:
    _LIVE.extend((source, value) for value in live)
    return Row(source, roles, need)


def _dashboard(code: str) -> tuple[str, ...]:
    return tuple(DASHBOARDS[code][1])


def _on_dashboard(code: str, target: OldRoles) -> tuple[str, ...]:
    """Panoda çizilen bağlantının bugünkü kararı: panoyu gören ve hedefi açabilen roller."""
    roles = _dashboard(code)
    if target == SIGNED_IN:
        return roles
    return tuple(role for role in roles if role in target)


ROWS: list[Row] = [
    # Panolar (DashboardListView ve DashboardView).
    _row(
        "reporting.api.views.DASHBOARDS['management']",
        ("yonetim", "planlama"),
        level(MANAGEMENT),
        lambda: _dashboard("management"),
    ),
    _row(
        "reporting.api.views.DASHBOARDS['warehouse']",
        ("depo", "planlama", "yonetim"),
        level(WAREHOUSE),
        lambda: _dashboard("warehouse"),
    ),
    _row(
        "reporting.api.views.DASHBOARDS['lab']",
        ("laboratuvar", "planlama", "yonetim"),
        level(LAB),
        lambda: _dashboard("lab"),
    ),
    _row(
        "reporting.api.views.DASHBOARDS['production']",
        ("uretim", "planlama", "yonetim"),
        level(PRODUCTION),
        lambda: _dashboard("production"),
    ),
    _row(
        "reporting.api.views.DASHBOARDS['shipping']",
        ("sevkiyat", "depo", "planlama", "yonetim"),
        level(SHIPPING),
        lambda: _dashboard("shipping"),
    ),
    # Yönetim panosundaki stok değeri: show_costs=can_see(user, "cost").
    _row(
        "reporting.api.views.DASHBOARDS['management'] show_costs → stock_value",
        ("yonetim",),
        level(COSTS),
        lambda: SENSITIVE_ROLES["cost"],
    ),
    # Raporlar (can_view: reports_for, _definition, export_report, run_job).
    Row(
        "reporting.reports.STOCK_ROLES (stock-status, stock-movements)",
        ("depo", "planlama", "yonetim", "satin_alma"),
        level(STOCK),
        live="apps.reporting.reports:STOCK_ROLES",
    ),
    _row(
        "reporting.reports.REPORTS['production'].roles",
        ("uretim", "planlama", "yonetim"),
        level(PRODUCTION),
        lambda: REPORTS["production"].roles,
    ),
    _row(
        "reporting.reports.REPORTS['filling'].roles",
        ("dolum", "planlama", "yonetim"),
        level(FILLING),
        lambda: REPORTS["filling"].roles,
    ),
    _row(
        "reporting.reports.REPORTS['quality'].roles",
        ("laboratuvar", "planlama", "yonetim"),
        level(LAB),
        lambda: REPORTS["quality"].roles,
    ),
    _row(
        "reporting.reports.REPORTS['shipments'].roles",
        ("sevkiyat", "planlama", "yonetim"),
        level(SHIPPING_REPORT),
        lambda: REPORTS["shipments"].roles,
    ),
    _row(
        "reporting.reports.REPORTS['task-durations'].roles",
        ("planlama", "yonetim"),
        level(MANAGEMENT),
        lambda: REPORTS["task-durations"].roles,
    ),
    # Hassas sütunlar ve özetler.
    _row(
        "reporting.reports.can_see('cost'): visible_columns, visible_summary (money)",
        ("yonetim",),
        level(COSTS),
        lambda: SENSITIVE_ROLES["cost"],
    ),
    _row(
        "reporting.reports.SENSITIVE_ROLES['price'] (fiyat sütunu bugün yok)",
        ("satin_alma", "yonetim"),
        level(PRICES),
        lambda: SENSITIVE_ROLES["price"],
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
    _row(
        "Dashboards.tsx /isg/olaylar bağlantıları (Approvals kartı, Dikkat 'injuries')",
        ("yonetim", "planlama"),
        all_of(level(MANAGEMENT), page("hse", hse.INCIDENT_REPORT, hse.INCIDENTS)),
        lambda: _on_dashboard("management", MENU_ROLES["hse"]),
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
    _row(
        "Dashboards.tsx ManagementView lot bağlantıları (inventory.lot)",
        ("yonetim", "planlama"),
        all_of(level(MANAGEMENT), read(inventory.LOTS)),
        lambda: _dashboard("management"),
    ),
    _row(
        "Dashboards.tsx WarehouseView emir bağlantıları (production.productionorder)",
        ("depo", "planlama", "yonetim"),
        all_of(level(WAREHOUSE), visible("production")),
        lambda: _dashboard("warehouse"),
    ),
    _row(
        "Dashboards.tsx WarehouseView emir bağlantıları (filling.fillingorder)",
        ("depo", "planlama", "yonetim"),
        all_of(level(WAREHOUSE), visible("filling")),
        lambda: _dashboard("warehouse"),
    ),
    _row(
        "Dashboards.tsx WarehouseView sevkiyat bağlantıları (sales.shipment)",
        ("depo", "planlama", "yonetim"),
        all_of(level(WAREHOUSE), visible("sales")),
        lambda: _dashboard("warehouse"),
    ),
    _row(
        "Dashboards.tsx ProductionView şarj ve emir bağlantıları",
        ("uretim", "planlama", "yonetim"),
        all_of(level(PRODUCTION), visible("production")),
        lambda: _dashboard("production"),
    ),
    _row(
        "Dashboards.tsx ShippingView sevkiyat ve sipariş bağlantıları",
        ("sevkiyat", "depo", "planlama", "yonetim"),
        all_of(level(SHIPPING), visible("sales")),
        lambda: _dashboard("shipping"),
    ),
]

# §8'deki ilk gün değişiklikleri (plan §5.5 "İzin listesi").
PLANNED: list[Planned] = [
    Planned(
        "§8 madde 2: laboratuvar panosundaki numune numaraları planlamada düz metin",
        _row(
            "Dashboards.tsx LabView numune bağlantıları (quality.sample)",
            ("laboratuvar", "planlama", "yonetim"),
            all_of(level(LAB), visible("quality")),
            lambda: _dashboard("lab"),
        ),
        ("laboratuvar", "yonetim"),
    ),
]

# Plan ile bugünkü kodun ayrıştığı yerler; sahibe soruldu.
MISMATCHES: list[Row] = [
    # Onay bekleyen satın alma siparişlerinin TL toplamı bugün show_costs (yalnız yönetim, D-15)
    # ile döner; plan §3.15 ve §3.18 Fiyatları görür'e bağlar. Pano yönetim ve planlamada açık
    # olduğundan planlama + satın alma kişisi toplamı görmeye başlar.
    _row(
        "reporting.api.views.DASHBOARDS['management'] show_costs → "
        "approvals.purchase_orders.total_try",
        ("yonetim",),
        all_of(level(MANAGEMENT), level(PRICES)),
        lambda: tuple(set(_dashboard("management")) & set(SENSITIVE_ROLES["cost"])),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_planned_changes() -> None:
    errors = planned_errors(PLANNED)
    assert not errors, "Planlı farklar bozuk:\n" + "\n".join(errors)


@pytest.mark.xfail(strict=True, reason="plan §3 ile bugünkü kod farklı; sahibe soruldu")
def test_known_mismatches() -> None:
    assert_rows(MISMATCHES)


def test_live_dict_constants() -> None:
    """Sözlükteki rol listeleri satırlardaki rollerle aynı (bugünkü kod)."""
    rows = {row.source: row for row in [*ROWS, *MISMATCHES, *(p.row for p in PLANNED)]}
    for source, value in _LIVE:
        assert set(value()) == set(rows[source].roles), source
    assert REPORTS["stock-status"].roles == STOCK_ROLES
    assert REPORTS["stock-movements"].roles == STOCK_ROLES
    assert set(DASHBOARDS) == {"management", "warehouse", "lab", "production", "shipping"}
    assert set(REPORTS) == {
        "stock-status",
        "stock-movements",
        "production",
        "filling",
        "quality",
        "shipments",
        "task-durations",
    }
    assert set(SENSITIVE_ROLES) == {"cost", "price"}
