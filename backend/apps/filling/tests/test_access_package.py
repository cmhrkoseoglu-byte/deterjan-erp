"""Dolum: paket denkliği (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, kayıt türü, ön yüz) planın §3.6 tablosundaki yetkiye
eşlenir. Kişiye özel ayar yokken eski ve yeni denetim, admin dışındaki 8 rolün bütün
bileşimlerinde aynı kararı verir. `live=` satırları koddaki rol sabitine de bağlıdır.

Satır olmayanlar:
- `FillingPage` varsayılan sekme sırası rol görünümüdür (plan §5.9), rolle kalır.
- Yeni dolum emri sayfası (`/dolum/emirler/yeni`) bugün modülü görenlere açık; plan §8 madde 3 ile
  yalnız emir açabilenlere daralır (bilinen ilk gün farkı).
- `FillingOrderViewSet`'te listede olmayan yazma eylemi için `default_roles` (planlama) yedeği: her
  yazma eylemi listede olduğu için bugün hiçbir uç noktada çalışmaz; plan §5.4'te bilinmeyen
  yazma eylemi reddedilir.
"""

from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.tests.access_helpers import SIGNED_IN, Row, any_of, assert_rows, level, read
from apps.filling.access import ORDERS, PREP, RUNS, SPECS

SERVICES = "apps.filling.services"
CONFIG = "frontend:src/modules/filling/config.ts"
# layout/menu.ts MENU "filling": menü öğesi ve routes.tsx `fillingPage` koruması.
MENU_ROLES = ("dolum", "planlama", "depo", "yonetim")
PLANNER = ("planlama",)
WAREHOUSE = ("depo",)
FILLER = ("dolum",)

# Dolum emri ve partisi okuması: üç bölümden birinde okuma yeter (plan §5.1).
RECORD_READ = read(ORDERS, PREP, RUNS)
SPEC_READ = read(SPECS)
# Modül sayfaları: Görür'ü olan bölümlerin birleşimi (plan §2, §5.9).
MODULE_VIEW = any_of(level(ORDERS, VIEW), level(PREP, VIEW), level(RUNS, VIEW), level(SPECS, VIEW))
# İptal uç noktası durumu bilmeden denetler: taslak Değiştirir, onaylı emir Onaylar ister.
ORDER_CANCEL = any_of(level(ORDERS, CHANGE), level(ORDERS, APPROVE))

ROWS = [
    # --- API: apps/filling/api/views.py (RolePermissionMixin) ---------------------------------
    Row("views.PackagingSpecViewSet okuma (list, retrieve, metadata)", SIGNED_IN, SPEC_READ),
    Row("views.PackagingSpecLineViewSet okuma (retrieve)", SIGNED_IN, SPEC_READ),
    Row(
        "views.FillingOrderViewSet okuma (list, retrieve, metadata, GET picks, pick_suggestions)",
        SIGNED_IN,
        RECORD_READ,
    ),
    Row("views.FillingRunViewSet okuma (list, retrieve, metadata)", SIGNED_IN, RECORD_READ),
    # Plan §3.6: parti ve emir tüketim raporları Dolum hattı bölümünün açık okumasıdır.
    Row("views.FillingOrderViewSet.report (emir tüketim raporu)", SIGNED_IN, read(RUNS)),
    Row("views.FillingRunViewSet.report (parti tüketim raporu)", SIGNED_IN, read(RUNS)),
    Row("views.PackagingSpecViewSet.create (default_roles)", PLANNER, level(SPECS, CHANGE)),
    Row(
        "views.PackagingSpecViewSet.update/partial_update (default_roles)",
        PLANNER,
        level(SPECS, CHANGE),
    ),
    Row("views.PackagingSpecViewSet.copy (default_roles)", PLANNER, level(SPECS, CHANGE)),
    Row("views.PackagingSpecViewSet.lines POST (default_roles)", PLANNER, level(SPECS, CHANGE)),
    Row("views.PackagingSpecViewSet.approve (default_roles)", PLANNER, level(SPECS, APPROVE)),
    Row(
        "views.PackagingSpecLineViewSet.update/partial_update/destroy (default_roles)",
        PLANNER,
        level(SPECS, CHANGE),
    ),
    Row("views.FillingOrderViewSet.create", PLANNER, level(ORDERS, CHANGE)),
    Row("views.FillingOrderViewSet.update/partial_update", PLANNER, level(ORDERS, CHANGE)),
    Row("views.FillingOrderViewSet.approve", PLANNER, level(ORDERS, APPROVE)),
    Row("views.FillingOrderViewSet.cancel", PLANNER, ORDER_CANCEL),
    Row("views.FillingOrderViewSet.start_prep", WAREHOUSE, level(PREP, CHANGE)),
    Row("views.FillingOrderViewSet.mark_ready", WAREHOUSE, level(PREP, CHANGE)),
    Row("views.FillingOrderViewSet.picks POST", WAREHOUSE, level(PREP, CHANGE)),
    Row("views.FillingOrderViewSet.finish (dolumu bitirir)", FILLER, level(RUNS, CHANGE)),
    Row(
        "views.FillingRunViewSet.create (parti başlatma, default_roles)",
        FILLER,
        level(RUNS, CHANGE),
    ),
    Row("views.FillingRunViewSet.consume_bulk (default_roles)", FILLER, level(RUNS, CHANGE)),
    Row("views.FillingRunViewSet.scan (default_roles)", FILLER, level(RUNS, CHANGE)),
    Row("views.FillingRunViewSet.scrap (default_roles)", FILLER, level(RUNS, CHANGE)),
    Row("views.FillingRunViewSet.finish (default_roles)", FILLER, level(RUNS, CHANGE)),
    Row("views.FillingRunViewSet.cancel (default_roles)", FILLER, level(RUNS, CHANGE)),
    # --- servis: apps/filling/services.py (_require_role) -------------------------------------
    Row(
        "services.create_spec (SPEC_ROLES; copy_spec da bunu çağırır)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{SERVICES}:SPEC_ROLES",
    ),
    Row(
        "services.update_spec (SPEC_ROLES)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{SERVICES}:SPEC_ROLES",
    ),
    Row(
        "services.add_spec_line (SPEC_ROLES)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{SERVICES}:SPEC_ROLES",
    ),
    Row(
        "services.update_spec_line (SPEC_ROLES)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{SERVICES}:SPEC_ROLES",
    ),
    Row(
        "services.remove_spec_line (SPEC_ROLES)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{SERVICES}:SPEC_ROLES",
    ),
    Row(
        "services.approve_spec (SPEC_ROLES)",
        PLANNER,
        level(SPECS, APPROVE),
        live=f"{SERVICES}:SPEC_ROLES",
    ),
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
        "services.pick_packaging (PREP_ROLES)",
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
        "services.start_run (FILLING_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{SERVICES}:FILLING_ROLES",
    ),
    Row(
        "services.consume_bulk (FILLING_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{SERVICES}:FILLING_ROLES",
    ),
    Row(
        "services.scan_packaging_lot (FILLING_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{SERVICES}:FILLING_ROLES",
    ),
    Row(
        "services.record_scrap (FILLING_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{SERVICES}:FILLING_ROLES",
    ),
    Row(
        "services.finish_run (FILLING_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{SERVICES}:FILLING_ROLES",
    ),
    Row(
        "services.cancel_run (FILLING_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{SERVICES}:FILLING_ROLES",
    ),
    Row(
        "services.finish_filling (FILLING_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{SERVICES}:FILLING_ROLES",
    ),
    # --- kayıt türleri: apps/filling/apps.py (register_record_type, rolsüz) -------------------
    Row("records filling.fillingorder (yorum, geçmiş, ek)", SIGNED_IN, RECORD_READ),
    Row("records filling.fillingrun (yorum, geçmiş, ek)", SIGNED_IN, RECORD_READ),
    Row("records filling.packagingspec (yorum, geçmiş, ek)", SIGNED_IN, SPEC_READ),
    # --- ön yüz: menü ve rotalar ------------------------------------------------------------------
    Row("layout/menu.ts MENU filling", MENU_ROLES, MODULE_VIEW),
    Row(
        "routes.tsx fillingPage: dolum/:tab?, emirler/:orderId (var olan emir), "
        "emirler/:orderId/hazirlama, partiler/:runId",
        MENU_ROLES,
        MODULE_VIEW,
    ),
    # Plan §5.9: tek bölüme ait alt sayfa o bölümün Görür'üyle açılır.
    Row(
        "routes.tsx fillingPage: dolum/ambalaj-receteleri/:specId",
        MENU_ROLES,
        level(SPECS, VIEW),
    ),
    # --- ön yüz: frontend/src/modules/filling ----------------------------------------------------
    Row("FillingPage TABS emirler (roles: [])", MENU_ROLES, level(ORDERS, VIEW)),
    Row(
        "FillingPage TABS hazirlama (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, VIEW),
        live=f"{CONFIG}:PREP_ROLES",
    ),
    Row("FillingPage TABS hat (roles: [])", MENU_ROLES, level(RUNS, VIEW)),
    Row("FillingPage TABS ambalaj-receteleri (roles: [])", MENU_ROLES, level(SPECS, VIEW)),
    Row(
        "FillingPage OrdersTab yeni emir düğmesi (PLAN_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "FillingPage SpecsTab yeni ambalaj reçetesi düğmesi (PLAN_ROLES)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "OrderPage onayla düğmesi (PLAN_ROLES, taslak)",
        PLANNER,
        level(ORDERS, APPROVE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "OrderPage taslak düzenleme formu (PLAN_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi taslak emirde (PLAN_ROLES)",
        PLANNER,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi onaylı ya da hazırlıktaki emirde (PLAN_ROLES)",
        PLANNER,
        level(ORDERS, APPROVE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "OrderPage hazırlama sayfası düğmesi (PREP_ROLES)",
        WAREHOUSE,
        level(PREP, VIEW),
        live=f"{CONFIG}:PREP_ROLES",
    ),
    Row(
        "OrderPage parti başlat düğmesi (LINE_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{CONFIG}:LINE_ROLES",
    ),
    Row(
        "OrderPage dolumu bitir düğmesi (LINE_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{CONFIG}:LINE_ROLES",
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
        "RunPage bulk, okutma, fire, bitir ve iptal (LINE_ROLES)",
        FILLER,
        level(RUNS, CHANGE),
        live=f"{CONFIG}:LINE_ROLES",
    ),
    Row(
        "SpecPage düzenleme formu ve satırlar (PLAN_ROLES)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "SpecPage sürümü onayla düğmesi (PLAN_ROLES)",
        PLANNER,
        level(SPECS, APPROVE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
    Row(
        "SpecPage yeni sürüm (kopyala) düğmesi (PLAN_ROLES)",
        PLANNER,
        level(SPECS, CHANGE),
        live=f"{CONFIG}:PLAN_ROLES",
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
