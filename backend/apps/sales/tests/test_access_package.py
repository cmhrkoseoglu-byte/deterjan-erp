"""Sevkiyat: paket denkliği (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, kayıt türü, ön yüz) planın §3.7 tablosundaki yetkiye
eşlenir. Kişiye özel ayar yokken eski ve yeni denetim, admin dışındaki 8 rolün bütün
bileşimlerinde aynı kararı verir. `live=` satırları koddaki rol sabitine de bağlıdır.

Satır olmayanlar:
- `SalesPage` varsayılan sekmesi (depo ve sipariş yazmayan kişi toplamaya düşer) rol
  görünümüdür (plan §5.9), rolle kalır.
- Rezervasyonların lot serbest durumdan çıkınca bırakılması (`handlers`,
  `services.release_unusable_lot`) bugün de denetimsizdir; plan §5.4 giriş noktası kuralı.
"""

from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.tests.access_helpers import Row, any_of, assert_rows, level, read
from apps.sales.access import ORDERS, PICKING, SHIPMENTS, SHIPPED_LOTS

VIEWS = "apps.sales.api.views"
SERVICES = "apps.sales.services"
CONFIG = "frontend:src/modules/sales/config.ts"
# api/views.py READ_ROLES; layout/menu.ts MENU "sales" ve routes.tsx `salesPage` koruması da aynı.
READERS = ("sevkiyat", "yonetim", "planlama", "depo")
ORDER_WRITERS = ("sevkiyat", "yonetim")  # services.ORDER_ROLES = api/views.py WRITE_ROLES
SHIPPERS = ("sevkiyat",)  # services.SHIPMENT_ROLES
PICKERS = ("depo",)  # services.PICK_ROLES

# Modül sayfaları ve menü: Görür'ü olan bölümlerin birleşimi (plan §2, §5.9).
MODULE_VIEW = any_of(
    level(ORDERS, VIEW), level(SHIPMENTS, VIEW), level(PICKING, VIEW), level(SHIPPED_LOTS, VIEW)
)
# İptal uç noktası durumu bilmeden denetler: taslak Değiştirir, onaylı sipariş Onaylar ister.
ORDER_CANCEL = any_of(level(ORDERS, CHANGE), level(ORDERS, APPROVE))
# Sevkiyat okuması: iki bölümden birinde okuma yeter (plan §5.1).
SHIPMENT_READ = read(SHIPMENTS, PICKING)

ROWS = [
    # --- API: apps/sales/api/views.py SalesOrderViewSet.get_permissions -----------------------
    Row(
        "views.SalesOrderViewSet okuma (list, retrieve, metadata, candidates)",
        READERS,
        read(ORDERS),
        live=f"{VIEWS}:READ_ROLES",
    ),
    Row(
        "views.SalesOrderViewSet.create",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{VIEWS}:WRITE_ROLES",
    ),
    Row(
        "views.SalesOrderViewSet.update/partial_update",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{VIEWS}:WRITE_ROLES",
    ),
    Row(
        "views.SalesOrderViewSet.confirm (onayla ve rezerve et)",
        ORDER_WRITERS,
        level(ORDERS, APPROVE),
        live=f"{VIEWS}:WRITE_ROLES",
    ),
    Row("views.SalesOrderViewSet.cancel", ORDER_WRITERS, ORDER_CANCEL, live=f"{VIEWS}:WRITE_ROLES"),
    Row(
        "views.SalesOrderViewSet.close",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{VIEWS}:WRITE_ROLES",
    ),
    Row(
        "views.SalesOrderViewSet.reserve_shortages, reserve, release (rezervasyon)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{VIEWS}:WRITE_ROLES",
    ),
    # --- API: ShipmentViewSet.get_permissions ve action_roles -------------------------------
    Row(
        "views.ShipmentViewSet okuma (list, retrieve)",
        READERS,
        SHIPMENT_READ,
        live=f"{VIEWS}:READ_ROLES",
    ),
    Row(
        "views.ShipmentViewSet.suggestions (toplama önerisi)",
        READERS,
        any_of(level(SHIPMENTS, VIEW), level(PICKING, VIEW)),
        live=f"{VIEWS}:READ_ROLES",
    ),
    Row(
        "views.ShipmentViewSet.waybill, waybill_pdf (irsaliye)",
        READERS,
        level(SHIPMENTS, VIEW),
        live=f"{VIEWS}:READ_ROLES",
    ),
    Row(
        "views.ShipmentViewSet.create (sevkiyat planla)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "views.ShipmentViewSet.update/partial_update (araç, şoför)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "views.ShipmentViewSet.cancel (sevk öncesi)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "views.ShipmentViewSet.dispatch_shipment (sevki onayla)",
        SHIPPERS,
        level(SHIPMENTS, APPROVE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "views.ShipmentViewSet.action_roles pick, undo_pick, load",
        PICKERS,
        level(PICKING, CHANGE),
        live=f"{SERVICES}:PICK_ROLES",
    ),
    # --- API: ShippedLotViewSet (satır içi HasRole) ------------------------------------------
    Row(
        "views.ShippedLotViewSet HasRole(SEVKIYAT, YONETIM)",
        ("sevkiyat", "yonetim"),
        level(SHIPPED_LOTS, VIEW),
    ),
    # --- servis: apps/sales/services.py (_require_role, _require_roles) -----------------------
    Row(
        "services.create_order (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.update_order (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.confirm_order (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, APPROVE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.cancel_order taslak sipariş (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.cancel_order onaylı sipariş (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, APPROVE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.close_order (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.reserve_shortages (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.reserve_lot (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.release_line_reservation (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.plan_shipment (SHIPMENT_ROLES)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "services.update_shipment (SHIPMENT_ROLES)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "services.cancel_shipment (SHIPMENT_ROLES)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "services.dispatch_shipment (SHIPMENT_ROLES)",
        SHIPPERS,
        level(SHIPMENTS, APPROVE),
        live=f"{SERVICES}:SHIPMENT_ROLES",
    ),
    Row(
        "services.pick_lot (PICK_ROLES)",
        PICKERS,
        level(PICKING, CHANGE),
        live=f"{SERVICES}:PICK_ROLES",
    ),
    Row(
        "services.undo_pick (PICK_ROLES)",
        PICKERS,
        level(PICKING, CHANGE),
        live=f"{SERVICES}:PICK_ROLES",
    ),
    Row(
        "services.mark_loaded (PICK_ROLES)",
        PICKERS,
        level(PICKING, CHANGE),
        live=f"{SERVICES}:PICK_ROLES",
    ),
    # --- kayıt türleri: apps/sales/apps.py (register_record_type roles=READ_ROLES) -------------
    Row(
        "records sales.salesorder (yorum, geçmiş, ek)",
        READERS,
        read(ORDERS),
        live=f"{VIEWS}:READ_ROLES",
    ),
    Row(
        "records sales.shipment (yorum, geçmiş, ek)",
        READERS,
        SHIPMENT_READ,
        live=f"{VIEWS}:READ_ROLES",
    ),
    # --- ön yüz: menü, rotalar ve arama -------------------------------------------------------
    Row("layout/menu.ts MENU sales", READERS, MODULE_VIEW),
    Row(
        "routes.tsx salesPage: sevkiyat/:tab?, siparisler/:orderId (yeni dahil), "
        "musteriler/:customerId, sevkiyatlar/:shipmentId, sevkiyatlar/:shipmentId/toplama",
        READERS,
        MODULE_VIEW,
    ),
    Row("pages/SearchPage.tsx kaynak salesOrders (menuRoles sales)", READERS, read(ORDERS)),
    Row("pages/SearchPage.tsx kaynak shipments (menuRoles sales)", READERS, SHIPMENT_READ),
    # --- ön yüz: frontend/src/modules/sales -----------------------------------------------------
    Row("SalesPage TABS siparisler (roles: [])", READERS, level(ORDERS, VIEW)),
    Row("SalesPage TABS sevkiyatlar (roles: [])", READERS, level(SHIPMENTS, VIEW)),
    Row(
        "SalesPage TABS toplama (PICK_ROLES)",
        PICKERS,
        level(PICKING, VIEW),
        live=f"{CONFIG}:PICK_ROLES",
    ),
    Row("SalesPage TABS musteriler (roles: [])", READERS, level(ORDERS, VIEW)),
    Row(
        "SalesPage OrdersTab yeni sipariş düğmesi (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage taslak düzenleme formu ve taslağı kaydet (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage onayla düğmesi (ORDER_WRITE_ROLES, taslak)",
        ORDER_WRITERS,
        level(ORDERS, APPROVE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage rezervasyon: eksikleri rezerve et, elle rezerve, bırak (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage siparişi kapat düğmesi (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi taslak siparişte (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi onaylı siparişte (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, APPROVE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage sevkiyat planla düğmesi (SHIPMENT_WRITE_ROLES)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{CONFIG}:SHIPMENT_WRITE_ROLES",
    ),
    Row(
        "ShipmentPage başlığı düzenle ve iptal düğmeleri (SHIPMENT_WRITE_ROLES)",
        SHIPPERS,
        level(SHIPMENTS, CHANGE),
        live=f"{CONFIG}:SHIPMENT_WRITE_ROLES",
    ),
    Row(
        "ShipmentPage sevki onayla düğmesi (SHIPMENT_WRITE_ROLES)",
        SHIPPERS,
        level(SHIPMENTS, APPROVE),
        live=f"{CONFIG}:SHIPMENT_WRITE_ROLES",
    ),
    Row(
        "ShipmentPage toplamayı aç, yükleme tamam, okutmayı geri al (PICK_ROLES)",
        PICKERS,
        level(PICKING, CHANGE),
        live=f"{CONFIG}:PICK_ROLES",
    ),
    Row(
        "PickPage okutma, öneri sorgusu, okutmayı geri al, yükleme tamam (PICK_ROLES)",
        PICKERS,
        level(PICKING, CHANGE),
        live=f"{CONFIG}:PICK_ROLES",
    ),
    Row(
        "CustomerPage sevk edilen lotlar paneli (SHIPPED_LOT_ROLES)",
        ("sevkiyat", "yonetim"),
        level(SHIPPED_LOTS, VIEW),
        live=f"{CONFIG}:SHIPPED_LOT_ROLES",
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
