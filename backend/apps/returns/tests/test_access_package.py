"""İadeler: paket denkliği (docs/plan/kisi-yetkileri.md §3.8 ve §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, kayıt türü ve ön yüz) bir yetki ifadesine eşlenir. Kişiye
özel ayar yokken eski denetim ile yeni yetki, admin dışındaki 8 rolün bütün bileşimlerinde aynı
kararı verir. `live` satırları koddaki rol sabitini de denetler.

Satır olmayan: `apply_lot_outcome` denetim yapmaz (iade sonucu ardıl adımdır, plan §5.4).
Teslim almadaki lot bekletme (`inventory.block_lot(..., quality_decision=True)`) ve numune açma
(`quality.open_sample`) da denetimsizdir; teslim alma kararı yalnız `RECEIVE_ROLES`'tur.
"""

from apps.core.access import CHANGE
from apps.core.tests.access_helpers import SIGNED_IN, Row, any_of, assert_rows, level, read
from apps.returns.access import RECEIVING, RETURNS
from apps.sales.access import ORDERS as SALES_ORDERS
from apps.sales.access import PICKING, SHIPMENTS, SHIPPED_LOTS

VIEWSET = "CustomerReturnViewSet"
SERVICES = "apps.returns.services"
CONFIG = "frontend:src/modules/returns/config.ts"

SHIPPING = ("sevkiyat",)
RECEIVERS = ("sevkiyat", "depo")
# İadeler sayfasının bugünkü koruması: menuRoles("returns").
RETURNS_PAGE = ("sevkiyat", "laboratuvar", "depo", "yonetim")

# Sevkiyat sayfası (sevkiyat/sevkiyatlar/:shipmentId) modülün Görür'ü olan bölümlerinin
# birleşimiyle açılır (plan §5.9); bağlantı hedef sayfa açılabiliyorsa görünür.
SALES_VIEW = any_of(level(SALES_ORDERS), level(SHIPMENTS), level(PICKING), level(SHIPPED_LOTS))

ROWS = [
    # --- API (api/views.py; inventory.DocumentViewSet → RolePermissionMixin) ---
    Row(
        f"API {VIEWSET} create, update, partial_update, cancel (write_roles = (SEVKIYAT,))",
        SHIPPING,
        level(RETURNS, CHANGE),
    ),
    Row(
        f"API {VIEWSET} receive (action_roles = (SEVKIYAT, DEPO))",
        RECEIVERS,
        level(RECEIVING, CHANGE),
    ),
    Row(
        f"API {VIEWSET} scrap (action_roles = (DEPO, SEVKIYAT))",
        RECEIVERS,
        level(RECEIVING, CHANGE),
    ),
    Row(
        f"API {VIEWSET} list, retrieve, metadata (READ_ACTIONS → IsAuthenticated)",
        SIGNED_IN,
        read(RETURNS),
    ),
    # --- servis (services.py, _require_role) ---
    Row(
        "Servis create_return, update_return, cancel_return (EDIT_ROLES)",
        SHIPPING,
        level(RETURNS, CHANGE),
        live=f"{SERVICES}:EDIT_ROLES",
    ),
    Row(
        "Servis receive_return (RECEIVE_ROLES)",
        RECEIVERS,
        level(RECEIVING, CHANGE),
        live=f"{SERVICES}:RECEIVE_ROLES",
    ),
    Row(
        "Servis scrap_line (SCRAP_ROLES)",
        RECEIVERS,
        level(RECEIVING, CHANGE),
        live=f"{SERVICES}:SCRAP_ROLES",
    ),
    # --- apps.py: kayıt paneli ---
    Row(
        "apps.py register_record_type returns.customerreturn, roles yok (yorum ve geçmiş okuması)",
        SIGNED_IN,
        read(RETURNS),
    ),
    # --- ön yüz: frontend/src/modules/returns ---
    Row(
        "Ön yüz ReturnsPage.tsx yeni iade düğmesi (RETURN_EDIT_ROLES)",
        SHIPPING,
        level(RETURNS, CHANGE),
        live=f"{CONFIG}:RETURN_EDIT_ROLES",
    ),
    Row(
        "Ön yüz ReturnPage.tsx editable: formu düzenleme ve taslağı kaydet (RETURN_EDIT_ROLES)",
        SHIPPING,
        level(RETURNS, CHANGE),
        live=f"{CONFIG}:RETURN_EDIT_ROLES",
    ),
    Row(
        "Ön yüz ReturnPage.tsx canCancel: taslağı iptal et (RETURN_EDIT_ROLES)",
        SHIPPING,
        level(RETURNS, CHANGE),
        live=f"{CONFIG}:RETURN_EDIT_ROLES",
    ),
    Row(
        "Ön yüz ReturnPage.tsx canReceive: teslim al (RETURN_RECEIVE_ROLES)",
        RECEIVERS,
        level(RECEIVING, CHANGE),
        live=f"{CONFIG}:RETURN_RECEIVE_ROLES",
    ),
    Row(
        "Ön yüz ReturnPage.tsx canScrap: imha et (RETURN_SCRAP_ROLES)",
        RECEIVERS,
        level(RECEIVING, CHANGE),
        live=f"{CONFIG}:RETURN_SCRAP_ROLES",
    ),
    Row(
        "Ön yüz ReturnPage.tsx canOpenShipment: sevkiyat bağlantısı (SHIPMENT_VIEW_ROLES = "
        "MENU sales.roles)",
        ("sevkiyat", "yonetim", "planlama", "depo"),
        SALES_VIEW,
    ),
    # --- kabuk: modülün menü, rota ve arama girişleri ---
    Row(
        "Ön yüz layout/menu.ts MENU returns.roles",
        RETURNS_PAGE,
        level(RETURNS),
    ),
    Row(
        "Ön yüz routes.tsx returnsPage: iadeler ve iadeler/:returnId",
        RETURNS_PAGE,
        level(RETURNS),
    ),
    Row(
        "Ön yüz pages/SearchPage.tsx returns kaynağı (menuRoles('returns'); hedef iade sayfası)",
        RETURNS_PAGE,
        level(RETURNS),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
