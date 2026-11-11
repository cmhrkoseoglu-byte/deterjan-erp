"""Üretim: paket denkliği (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, kayıt türü, ön yüz) planın §3.4 tablosundaki yetkiye
eşlenir. Kişiye özel ayar yokken eski ve yeni denetim, admin dışındaki 8 rolün bütün
bileşimlerinde aynı kararı verir. `live=` satırları koddaki rol sabitine de bağlıdır.

Satır olmayanlar:
- `ProductionPage` varsayılan sekme sırası rol görünümüdür (plan §5.9), rolle kalır.
- Yeni emir sayfası (`/uretim/emirler/yeni`) bugün modülü görenlere açık; plan §8 madde 3 ile
  yalnız emir açabilenlere daralır (bilinen ilk gün farkı).
- `RolePermissionMixin`'in listede olmayan yazma eylemi için `HasRole(PLANLAMA)` yedeği: her
  yazma eylemi listede olduğu için bugün hiçbir uç noktada çalışmaz; plan §5.4'te bilinmeyen
  yazma eylemi reddedilir.
"""

from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.tests.access_helpers import SIGNED_IN, Row, any_of, assert_rows, level, read
from apps.production.access import BATCHES, ORDERS, PREP

SERVICES = "apps.production.services"
CONFIG = "frontend:src/modules/production/config.ts"
# layout/menu.ts MENU "production": menü öğesi ve routes.tsx `productionPage` koruması.
MENU_ROLES = ("uretim", "planlama", "depo", "yonetim")
PLANNER = ("planlama",)
WAREHOUSE = ("depo",)
OPERATOR = ("uretim",)

# Emir ve şarj okuması: üç bölümden birinde okuma yeter (plan §5.1).
RECORD_READ = read(ORDERS, PREP, BATCHES)
# Modül sayfaları: Görür'ü olan bölümlerin birleşimi (plan §2, §5.9).
MODULE_VIEW = any_of(level(ORDERS, VIEW), level(PREP, VIEW), level(BATCHES, VIEW))
# İptal uç noktası durumu bilmeden denetler: taslak Değiştirir, onaylı emir Onaylar ister.
ORDER_CANCEL = any_of(level(ORDERS, CHANGE), level(ORDERS, APPROVE))

ROWS = [
    # --- API: apps/production/api/views.py (RolePermissionMixin, action_roles) -------------------
    Row(
        "views.ProductionOrderViewSet okuma (list, retrieve, metadata, GET picks, "
        "pick_suggestions)",
        SIGNED_IN,
        RECORD_READ,
    ),
    Row("views.ProductionBatchViewSet okuma (list, retrieve, metadata)", SIGNED_IN, RECORD_READ),
    Row("views.ProductionOrderViewSet.create", PLANNER, level(ORDERS, CHANGE)),
    Row("views.ProductionOrderViewSet.update/partial_update", PLANNER, level(ORDERS, CHANGE)),
    Row("views.ProductionOrderViewSet.approve", PLANNER, level(ORDERS, APPROVE)),
    Row("views.ProductionOrderViewSet.cancel", PLANNER, ORDER_CANCEL),
    Row("views.ProductionOrderViewSet.complete (elle tamamlama)", PLANNER, level(ORDERS, CHANGE)),
    Row("views.ProductionOrderViewSet.start_prep", WAREHOUSE, level(PREP, CHANGE)),
    Row("views.ProductionOrderViewSet.mark_ready", WAREHOUSE, level(PREP, CHANGE)),
    Row("views.ProductionOrderViewSet.picks POST", WAREHOUSE, level(PREP, CHANGE)),
    Row("views.ProductionBatchViewSet.create (şarj başlatma)", OPERATOR, level(BATCHES, CHANGE)),
    Row("views.ProductionBatchViewSet.consume (tartım)", OPERATOR, level(BATCHES, CHANGE)),
    Row("views.ProductionBatchViewSet.finish", OPERATOR, level(BATCHES, CHANGE)),
    Row("views.ProductionBatchViewSet.cancel", OPERATOR, level(BATCHES, CHANGE)),
    # --- servis: apps/production/services.py (_require_role) ----------------------------------
    Row(
        "services.create_order (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.update_order (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.set_rework_additions (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.approve_order (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, APPROVE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.cancel_order taslak emir (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.cancel_order onaylı ya da hazırlıktaki emir (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, APPROVE),
        live=f"{SERVICES}:ORDER_ROLES",
    ),
    Row(
        "services.start_material_prep (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, CHANGE),
        live=f"{SERVICES}:PREP_ROLES",
    ),
    Row(
        "services.pick_material (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, CHANGE),
        live=f"{SERVICES}:PREP_ROLES",
    ),
    Row(
        "services.mark_material_ready (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, CHANGE),
        live=f"{SERVICES}:PREP_ROLES",
    ),
    Row(
        "services.start_batch (PRODUCTION_ROLES)",
        OPERATOR,
        level(BATCHES, CHANGE),
        live=f"{SERVICES}:PRODUCTION_ROLES",
    ),
    Row(
        "services.record_consumption (PRODUCTION_ROLES)",
        OPERATOR,
        level(BATCHES, CHANGE),
        live=f"{SERVICES}:PRODUCTION_ROLES",
    ),
    Row(
        "services.finish_batch (PRODUCTION_ROLES)",
        OPERATOR,
        level(BATCHES, CHANGE),
        live=f"{SERVICES}:PRODUCTION_ROLES",
    ),
    Row(
        "services.cancel_batch (PRODUCTION_ROLES)",
        OPERATOR,
        level(BATCHES, CHANGE),
        live=f"{SERVICES}:PRODUCTION_ROLES",
    ),
    # --- kayıt türleri: apps/production/apps.py (register_record_type, rolsüz) ----------------
    Row("records production.productionorder (yorum, geçmiş, ek)", SIGNED_IN, RECORD_READ),
    Row("records production.productionbatch (yorum, geçmiş, ek)", SIGNED_IN, RECORD_READ),
    # --- ön yüz: menü ve rotalar ------------------------------------------------------------------
    Row("layout/menu.ts MENU production", MENU_ROLES, MODULE_VIEW),
    Row(
        "routes.tsx productionPage: uretim/:tab?, emirler/:orderId (var olan emir), "
        "emirler/:orderId/hazirlama, sarjlar/:batchId",
        MENU_ROLES,
        MODULE_VIEW,
    ),
    # --- ön yüz: frontend/src/modules/production -------------------------------------------------
    Row("ProductionPage TABS emirler (roles: [])", MENU_ROLES, level(ORDERS, VIEW)),
    Row(
        "ProductionPage TABS hazirlama (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, VIEW),
        live=f"{CONFIG}:PREP_ROLES",
    ),
    Row("ProductionPage TABS sarjlar (roles: [])", MENU_ROLES, level(BATCHES, VIEW)),
    Row(
        "ProductionPage OrdersTab yeni emir düğmesi (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_ROLES",
    ),
    Row(
        "OrderPage onayla düğmesi (ORDER_ROLES, taslak)",
        PLANNER,
        level(ORDERS, APPROVE),
        live=f"{CONFIG}:ORDER_ROLES",
    ),
    Row(
        "OrderPage taslak düzenleme formu (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi taslak emirde (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi onaylı ya da hazırlıktaki emirde (ORDER_ROLES)",
        PLANNER,
        level(ORDERS, APPROVE),
        live=f"{CONFIG}:ORDER_ROLES",
    ),
    Row(
        "OrderPage hazırlama sayfası düğmesi (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, VIEW),
        live=f"{CONFIG}:PREP_ROLES",
    ),
    Row(
        "OrderPage şarj başlat düğmesi (BATCH_ROLES)",
        OPERATOR,
        level(BATCHES, CHANGE),
        live=f"{CONFIG}:BATCH_ROLES",
    ),
    Row(
        "PrepPage okutma formu (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, CHANGE),
        live=f"{CONFIG}:PREP_ROLES",
    ),
    Row(
        "PrepPage hazır bildir düğmesi (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, CHANGE),
        live=f"{CONFIG}:PREP_ROLES",
    ),
    Row(
        "BatchPage tartım, bitir ve iptal (BATCH_ROLES)",
        OPERATOR,
        level(BATCHES, CHANGE),
        live=f"{CONFIG}:BATCH_ROLES",
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
