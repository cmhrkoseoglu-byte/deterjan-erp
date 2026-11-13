"""Paket denkliği: ön yüz kabuğu (docs/plan/kisi-yetkileri.md §5.5 3. parça, §2 ve §5.9).

Menü öğelerinin rol listeleri (`frontend/src/layout/menu.ts`), rota korumaları (`routes.tsx`) ve
arama kaynakları (`pages/SearchPage.tsx`) yetki ifadeleriyle karşılaştırılır:

- menüde modül, ekranı olan bölümlerinden birinde Görür varsa görünür (plan §2); modül sayfaları
  ve birden çok bölümün kayıtlarını gösteren alt sayfalar aynı birleşimle açılır (plan §5.9);
- tek bölüme ait alt sayfalar o bölümün Görür'üyle açılır (plan §5.9);
- arama kaynağı, kayıt türünün okuma bölümlerinden (plan §5.1) birinde Görür ister. Kayıt okuması
  (`r`) değil: açık okumalı kaynaklar o zaman herkese açılırdı.

`MENU_ROLES` menü öğelerinin bugünkü rol listeleridir (dondurulmuş); `menuRoles(...)` kullanan
satırlar bu tabloyu kullanır, tablo da `menu.ts` ile ayrıca karşılaştırılır.

§8'deki ilk gün değişiklikleri `PLANNED` listesindedir: bugünkü karar plandaki yeni rollere
daralır; test yeni kararın genişlemediğini ve paketlerin yeni rollere denk olduğunu kanıtlar.

Rol görünümünde kalanlar (`/pano` ve açılış sayfasının yönetim rolü kuralı, üst bant rengi, rol
rozetleri) satır değildir (plan §5.9 "Rol görünümü").
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from apps.core import access
from apps.core.access import CHANGE, VIEW, Kind, SectionRef
from apps.core.tests.access_helpers import (
    ADMIN_ONLY,
    ANY_ROLE,
    REPO_ROOT,
    SIGNED_IN,
    Need,
    OldRoles,
    Row,
    all_of,
    any_of,
    assert_rows,
    level,
    old_allows,
    read,
    role_subsets,
    row_errors,
)
from apps.costing import access as costing
from apps.filling import access as filling
from apps.golive import access as golive
from apps.inventory import access as inventory
from apps.personnel import access as personnel
from apps.production import access as production
from apps.purchasing import access as purchasing
from apps.quality import access as quality
from apps.returns import access as returns
from apps.sales import access as sales


def visible(module_key: str) -> Need:
    """Menüde modül görünür, modül sayfası açılır: ekranı olan bölümlerinden birinde Görür.

    Menüde kendi modülü olmayan gruplar (Hassas veriler, Görevler, Sistem; `menu=False`) bu kurala
    girmez: Sistem menüsü yalnız admine açıktır (çekirdeğin satırları).
    """
    if not access.module(module_key).menu:
        raise ValueError(f"{module_key}: menüde kendi modülü yok.")
    sections = [item for item in access.sections(module_key) if item.kind is Kind.SECTION]
    if not sections:
        raise ValueError(f"{module_key}: ekranı olan bölüm yok.")
    return any_of(*(level(item, VIEW) for item in sections))


def page(module_key: str, *tabs: SectionRef) -> Need:
    """Modülün bir sekmesine giden bağlantı: modül sayfasının ve sekmenin koruması (plan §5.9)."""
    return all_of(visible(module_key), any_of(*(level(tab, VIEW) for tab in tabs)))


@dataclass(frozen=True)
class Planned:
    """§8'deki ilk gün değişikliği: bugünkü denetim (`row.roles`) yetkiyle `new` rollerine
    daralır."""

    item: str
    row: Row
    new: OldRoles


def planned_errors(changes: Sequence[Planned]) -> list[str]:
    """Planlı farkların hataları: paketler yeni rollere denk değilse, yeni karar bugünkünden
    genişse ya da hiç fark yoksa (satır o zaman ROWS'a taşınmalı)."""
    errors = row_errors([Row(f"{c.row.source} [{c.item}]", c.new, c.row.need) for c in changes])
    for change in changes:
        old, new = change.row.roles, change.new
        wider = [s for s in role_subsets() if old_allows(new, s) and not old_allows(old, s)]
        if wider:
            errors.append(f"{change.row.source}: yeni karar bugünkünden geniş ({len(wider)}).")
        if all(old_allows(new, s) == old_allows(old, s) for s in role_subsets()):
            errors.append(f"{change.row.source}: fark yok; satır ROWS'a taşınmalı.")
    return errors


# --- menü ------------------------------------------------------------------------------------

# `layout/menu.ts` MENU öğelerinin bugünkü rolleri: boş dizi giriş yapan herkes, ["admin"] yalnız
# admin.
MENU_ROLES: dict[str, OldRoles] = {
    "dashboard": ("yonetim",),
    "home": SIGNED_IN,
    "masterdata": ("planlama", "yonetim"),
    "recipes": ("planlama", "laboratuvar"),
    "inventory": SIGNED_IN,
    "production": ("uretim", "planlama", "depo", "yonetim"),
    "quality": ("laboratuvar", "yonetim"),
    "filling": ("dolum", "planlama", "depo", "yonetim"),
    "sales": ("sevkiyat", "yonetim", "planlama", "depo"),
    "returns": ("sevkiyat", "laboratuvar", "depo", "yonetim"),
    "traceability": ("laboratuvar", "yonetim"),
    "purchasing": ("satin_alma", "yonetim", "depo", "planlama", "uretim"),
    "costing": ("yonetim",),
    "maintenance": ("uretim", "dolum", "laboratuvar", "planlama", "yonetim"),
    "hse": SIGNED_IN,
    "personnel": ("yonetim",),
    "reporting": SIGNED_IN,
    "golive": ("yonetim", "planlama", "depo"),
    "help": SIGNED_IN,
    "system": ADMIN_ONLY,
    "admin": ADMIN_ONLY,
}

MENU_FILE = REPO_ROOT / "frontend" / "src" / "layout" / "menu.ts"
_MENU_ITEM = re.compile(r'key:\s*"(?P<key>[a-z_]+)".*?roles:\s*\[(?P<roles>[^\]]*)\]', re.S)
_ROLE = re.compile(r"[\"']([a-z_]+)[\"']")


def menu_ts_roles() -> dict[str, tuple[str, ...]]:
    """`menu.ts` MENU dizisindeki öğelerin rol dizileri (bugünkü kod)."""
    text = MENU_FILE.read_text(encoding="utf-8")
    start = text.index("export const MENU")
    end = text.index("export function", start)
    return {
        match["key"]: tuple(_ROLE.findall(match["roles"]))
        for match in _MENU_ITEM.finditer(text, start, end)
    }


def _menu_form(roles: OldRoles) -> set[str]:
    if roles == SIGNED_IN:
        return set()
    if roles == ADMIN_ONLY:
        return {"admin"}
    return set(roles)


def _menu(key: str, routes: str) -> Row:
    """Menü öğesi ve modülün rotaları: `menuRoles(key)` ↔ modül görünür."""
    return Row(f"menu.ts MENU[{key}]; routes.tsx {routes}", MENU_ROLES[key], visible(key))


ROWS: list[Row] = [
    # Menü ve modül sayfaları. Birden çok bölümün kayıtlarını gösteren alt sayfalar (emir,
    # hazırlama, parti, numune, toplama, sevkiyat, iş emri) modülün birleşimiyle açılır.
    _menu("masterdata", "ana-veriler/:tab?"),
    _menu("recipes", "receteler, receteler/:recipeId, receteler/:recipeId/surumler/:versionId"),
    _menu("inventory", "depo/:tab? (korumasız)"),
    _menu(
        "production",
        "uretim/:tab?, uretim/emirler/:orderId (var olan emir), .../hazirlama, "
        "uretim/sarjlar/:batchId",
    ),
    _menu("quality", "kalite/:tab?, kalite/numuneler/:sampleId"),
    _menu(
        "filling",
        "dolum/:tab?, dolum/emirler/:orderId (var olan emir), .../hazirlama, dolum/partiler/:runId",
    ),
    _menu("sales", "sevkiyat/:tab? ve sevkiyat/* alt sayfaları"),
    _menu("returns", "iadeler, iadeler/:returnId"),
    _menu("traceability", "izlenebilirlik/:tab?"),
    _menu("purchasing", "satin-alma/:tab?"),
    _menu("costing", "maliyet/:tab?"),
    _menu("maintenance", "bakim/:tab?, bakim/is-emirleri/:workOrderId"),
    _menu("personnel", "(menü bağlantısı; sayfaları aşağıda)"),
    _menu("golive", "gecis/:tab?"),
    # MENU[admin] (Django paneli) ve /sistem yalnız admin: test_access_package.py (çekirdek).
    # Tek bölüme ait alt sayfalar (plan §5.9).
    Row(
        "routes.tsx personel, personel/:employeeId (personnelPage)",
        MENU_ROLES["personnel"],
        level(personnel.CARDS),
    ),
    Row(
        "routes.tsx personel/puantaj, personel/tatiller (personnelPage)",
        MENU_ROLES["personnel"],
        level(personnel.ATTENDANCE),
    ),
    Row(
        "routes.tsx personel/ucretler (personnelPage)",
        MENU_ROLES["personnel"],
        level(personnel.WAGES),
    ),
    Row(
        "routes.tsx personel/bordro (personnelPage)",
        MENU_ROLES["personnel"],
        level(personnel.PAYROLL),
    ),
    Row(
        "routes.tsx maliyet/lotlar/:lotId (costingPage)",
        MENU_ROLES["costing"],
        level(costing.LOT_COSTS),
    ),
    Row(
        "routes.tsx kalite/spesifikasyonlar/:specId (qualityPage)",
        MENU_ROLES["quality"],
        level(quality.SPECS),
    ),
    Row(
        "routes.tsx dolum/ambalaj-receteleri/:specId (fillingPage)",
        MENU_ROLES["filling"],
        level(filling.SPECS),
    ),
    Row(
        "routes.tsx gecis/karsilastirma/:comparisonId (menuRoles('golive'))",
        MENU_ROLES["golive"],
        level(golive.COMPARISONS),
    ),
    # Depo'nun kayıt sayfaları kayıt okumasıyla açılır (plan §5.9); bugün korumasız.
    Row("routes.tsx depo/lotlar/:lotId (korumasız)", SIGNED_IN, read(inventory.LOTS)),
    Row("routes.tsx depo/mal-kabul/:receiptId (korumasız)", SIGNED_IN, read(inventory.RECEIPTS)),
    Row("routes.tsx depo/sayim/:adjustmentId (korumasız)", SIGNED_IN, read(inventory.ADJUSTMENTS)),
    # Arama kaynakları (SearchPage.tsx sources()).
    Row(
        "SearchPage.tsx sources() lots (menuRoles('inventory'))",
        MENU_ROLES["inventory"],
        level(inventory.LOTS),
    ),
    Row(
        "SearchPage.tsx sources() receipts (satır içi dizi)",
        ("depo", "planlama", "yonetim", "satin_alma", "laboratuvar"),
        level(inventory.RECEIPTS),
    ),
    Row(
        "SearchPage.tsx sources() productionOrders, batches (menuRoles('production'))",
        MENU_ROLES["production"],
        any_of(level(production.ORDERS), level(production.PREP), level(production.BATCHES)),
    ),
    Row(
        "SearchPage.tsx sources() fillingOrders, runs (menuRoles('filling'))",
        MENU_ROLES["filling"],
        any_of(level(filling.ORDERS), level(filling.PREP), level(filling.RUNS)),
    ),
    Row(
        "SearchPage.tsx sources() salesOrders (menuRoles('sales'))",
        MENU_ROLES["sales"],
        level(sales.ORDERS),
    ),
    Row(
        "SearchPage.tsx sources() shipments (menuRoles('sales'))",
        MENU_ROLES["sales"],
        any_of(level(sales.SHIPMENTS), level(sales.PICKING)),
    ),
    Row(
        "SearchPage.tsx sources() purchaseOrders (ORDER_READ_ROLES)",
        ("satin_alma", "yonetim", "depo"),
        level(purchasing.ORDERS),
        live="frontend:src/modules/purchasing/config.ts:ORDER_READ_ROLES",
    ),
    Row(
        "SearchPage.tsx sources() samples (menuRoles('quality'))",
        MENU_ROLES["quality"],
        any_of(level(quality.SAMPLES), level(quality.CONDITIONAL)),
    ),
    Row(
        "SearchPage.tsx sources() returns (menuRoles('returns'))",
        MENU_ROLES["returns"],
        level(returns.RETURNS),
    ),
]

# §8'deki ilk gün değişiklikleri (plan §5.5 "İzin listesi").
PLANNED: list[Planned] = [
    Planned(
        "§8 madde 1: rolsüz kullanıcı İSG'yi görmez",
        _menu("hse", "isg/:tab?, isg/olaylar/:incidentId"),
        ANY_ROLE,
    ),
    Planned(
        "§8 madde 1: rolsüz kullanıcı Panolar ve raporlar'ı görmez (İndirmeler açık kalır)",
        _menu("reporting", "raporlar/:tab? (korumasız; raporlar/indirmeler hariç)"),
        ANY_ROLE,
    ),
    Planned(
        "§8 madde 3: yeni üretim emri sayfası yalnız emir açabilene",
        Row(
            "routes.tsx uretim/emirler/yeni (productionPage)",
            MENU_ROLES["production"],
            level(production.ORDERS, CHANGE),
        ),
        ("planlama",),
    ),
    Planned(
        "§8 madde 3: yeni dolum emri sayfası yalnız emir açabilene",
        Row(
            "routes.tsx dolum/emirler/yeni (fillingPage)",
            MENU_ROLES["filling"],
            level(filling.ORDERS, CHANGE),
        ),
        ("planlama",),
    ),
    Planned(
        "§8 madde 3: satın alma sipariş ayrıntısı yalnız siparişleri görebilene",
        Row(
            "routes.tsx satin-alma/siparisler/:orderId (menuRoles('purchasing'))",
            MENU_ROLES["purchasing"],
            level(purchasing.ORDERS),
        ),
        ("satin_alma", "yonetim", "depo"),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_planned_changes() -> None:
    errors = planned_errors(PLANNED)
    assert not errors, "Planlı farklar bozuk:\n" + "\n".join(errors)


def test_menu_free_groups_do_not_open_a_menu() -> None:
    """Hassas veriler, Görevler ve Sistem gruplarının menüde modülü yoktur (Sistem yalnız admin)."""
    for module_key in ("sensitive", "workflow", "system"):
        with pytest.raises(ValueError, match="menüde kendi modülü yok"):
            visible(module_key)


def test_menu_roles_match_menu_ts() -> None:
    """`MENU_ROLES` bugünkü `menu.ts` ile aynı: `menuRoles(...)` satırlarının canlı denetimi."""
    live = menu_ts_roles()
    assert set(live) == set(MENU_ROLES)
    for key, roles in MENU_ROLES.items():
        assert set(live[key]) == _menu_form(roles), key
