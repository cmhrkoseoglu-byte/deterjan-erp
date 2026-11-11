"""Depo ve stok: paket denkliği (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Modüldeki bugünkü her rol denetimi (API, servis, serializer, kayıt türleri ve ön yüz) planın §3.3
tablosundaki yetkiye eşlenir. `assert_rows`, kişiye özel ayar yokken eski denetimin ve yeni
yetkinin 8 rolün bütün bileşimlerinde aynı kararı verdiğini kanıtlar.
"""

from apps.core.access import APPROVE, CHANGE, COSTS, PRICES
from apps.core.roles import (
    ADMIN,
    DEPO,
    DOLUM,
    LABORATUVAR,
    PLANLAMA,
    SATIN_ALMA,
    SEVKIYAT,
    URETIM,
    YONETIM,
)
from apps.core.tests.access_helpers import (
    ADMIN_ONLY,
    SIGNED_IN,
    Row,
    any_of,
    assert_rows,
    frontend_roles,
    level,
    read,
)
from apps.costing.access import LOT_COSTS
from apps.inventory.access import (
    ADJUSTMENTS,
    LOT_BLOCK,
    LOTS,
    MANUAL_RELEASE,
    PALLETS,
    RECEIPT_PRICES,
    RECEIPTS,
    STOCK,
)
from apps.masterdata.access import CARDS

VIEWS = "apps.inventory.api.views"
SERIALIZERS = "apps.inventory.api.serializers"
SERVICES = "apps.inventory.services"
CONFIG = "frontend:src/modules/inventory/config.ts"

PALLET_WRITERS = (DEPO, DOLUM, SEVKIYAT, URETIM)
PRICE_ROLES = (SATIN_ALMA, YONETIM)

# Depo menüsü ve sayfaları: modülün Görür'ü olan bölümlerinden birinde Görür (plan §2, §5.9).
MODULE_VIEW = any_of(level(STOCK), level(LOTS), level(PALLETS), level(RECEIPTS), level(ADJUSTMENTS))

ROWS = [
    # --- api/views.py: lotlar (RolePermissionMixin: okuma ve baskı IsAuthenticated) ---
    Row("views.LotViewSet list, retrieve, metadata, trace", SIGNED_IN, read(LOTS)),
    Row(
        "views.LotViewSet label, case_label, print_label (lot ve koli etiketi)",
        SIGNED_IN,
        read(LOTS),
    ),
    Row(
        "views.LotViewSet block (write_roles = LOT_DECISION_ROLES)",
        (LABORATUVAR,),
        level(LOT_BLOCK, APPROVE),
        live=f"{VIEWS}:LOT_DECISION_ROLES",
    ),
    # MANUAL_RELEASE_ROLES = (ADMIN,): `live` admin'i taşıyamaz, test_admin_only_constants sabitler.
    Row(
        "views.LotViewSet release (action_roles = MANUAL_RELEASE_ROLES, D-5)",
        ADMIN_ONLY,
        level(MANUAL_RELEASE, APPROVE),
    ),
    # --- api/views.py: hareket, bakiye, transfer, açılış stoku ---
    Row("views.StockMovementViewSet list, retrieve, metadata", SIGNED_IN, read(STOCK)),
    Row(
        "views.StockMovementViewSet reverse (write_roles = STOCK_WRITE_ROLES)",
        (DEPO,),
        level(STOCK, CHANGE),
        live=f"{VIEWS}:STOCK_WRITE_ROLES",
    ),
    Row("views.StockBalanceViewSet list, available, metadata", SIGNED_IN, read(STOCK)),
    Row(
        "views.TransferView POST (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(STOCK, CHANGE),
        live=f"{VIEWS}:STOCK_WRITE_ROLES",
    ),
    Row(
        "views.OpeningImportView POST (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(STOCK, CHANGE),
        live=f"{VIEWS}:STOCK_WRITE_ROLES",
    ),
    Row(
        "views.OpeningTemplateView GET (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(STOCK, CHANGE),
        live=f"{VIEWS}:STOCK_WRITE_ROLES",
    ),
    # --- api/views.py: mal kabul ---
    Row("views.GoodsReceiptViewSet list, retrieve, metadata", SIGNED_IN, read(RECEIPTS)),
    # Lot etiketleri açık kayıtlar kapatılınca da açık kalır (plan §3.3, §5.3): Lotlar okuması.
    Row(
        "views.GoodsReceiptViewSet labels, print_labels (mal kabul lot etiketleri)",
        SIGNED_IN,
        read(LOTS),
    ),
    Row(
        "views.GoodsReceiptViewSet create, update, partial_update, post, cancel "
        "(write_roles = STOCK_WRITE_ROLES)",
        (DEPO,),
        level(RECEIPTS, CHANGE),
        live=f"{VIEWS}:STOCK_WRITE_ROLES",
    ),
    Row(
        "views.GoodsReceiptViewSet costs (action_roles = RECEIPT_PRICE_ROLES)",
        PRICE_ROLES,
        level(RECEIPT_PRICES, CHANGE),
        live=f"{SERIALIZERS}:RECEIPT_PRICE_ROLES",
    ),
    # --- api/views.py: sayım düzeltme ---
    Row("views.StockAdjustmentViewSet list, retrieve, metadata", SIGNED_IN, read(ADJUSTMENTS)),
    Row(
        "views.StockAdjustmentViewSet create, update, partial_update, cancel "
        "(write_roles = STOCK_WRITE_ROLES)",
        (DEPO,),
        level(ADJUSTMENTS, CHANGE),
        live=f"{VIEWS}:STOCK_WRITE_ROLES",
    ),
    Row(
        "views.StockAdjustmentViewSet post (write_roles = STOCK_WRITE_ROLES; D-3)",
        (DEPO,),
        level(ADJUSTMENTS, APPROVE),
        live=f"{VIEWS}:STOCK_WRITE_ROLES",
    ),
    # --- api/views.py: palet etiketi ve okutma ---
    Row(
        "views.PalletLabelViewSet list, retrieve, metadata, label, print_label",
        SIGNED_IN,
        read(PALLETS),
    ),
    Row(
        "views.PalletLabelViewSet create (write_roles = PALLET_ROLES)",
        PALLET_WRITERS,
        level(PALLETS, CHANGE),
        live=f"{VIEWS}:PALLET_ROLES",
    ),
    # Okutma lot, palet, lokasyon ya da malzeme çözer; hepsi herkese okunur.
    Row("views.ScanView GET (IsAuthenticated)", SIGNED_IN, read(LOTS, PALLETS, CARDS)),
    # --- api/serializers.py: mal kabul fiyatları (can_see_receipt_prices) ---
    Row(
        "serializers.GoodsReceiptLineSerializer.to_representation (fiyat alanları)",
        PRICE_ROLES,
        level(PRICES),
        live=f"{SERIALIZERS}:RECEIPT_PRICE_ROLES",
    ),
    Row(
        "serializers.GoodsReceiptDetailSerializer.get_extra_costs (ek masraflar)",
        PRICE_ROLES,
        level(PRICES),
        live=f"{SERIALIZERS}:RECEIPT_PRICE_ROLES",
    ),
    # Fiyatı görebilen ama giremeyen kişinin gönderdiği fiyat yok sayılır (plan §5.6).
    Row(
        "serializers.GoodsReceiptLineSerializer.to_internal_value (gönderilen fiyat alanları)",
        PRICE_ROLES,
        level(RECEIPT_PRICES, CHANGE),
        live=f"{SERIALIZERS}:RECEIPT_PRICE_ROLES",
    ),
    # --- services.py ---
    Row(
        "services.can_decide_lot → block_lot (LOT_DECISION_ROLES)",
        (LABORATUVAR,),
        level(LOT_BLOCK, APPROVE),
        live=f"{SERVICES}:LOT_DECISION_ROLES",
    ),
    Row(
        "services.release_lot elle serbest bırakma (user.is_admin; D-5)",
        ADMIN_ONLY,
        level(MANUAL_RELEASE, APPROVE),
    ),
    # --- apps.py: kayıt türleri (yorum, geçmiş, ek) ---
    Row("apps.py register_record_type inventory.lot (roles yok)", SIGNED_IN, read(LOTS)),
    Row(
        "apps.py inventory.lot hidden_fields lot_cost_fields (satır içi (YONETIM,))",
        (YONETIM,),
        level(COSTS),
    ),
    Row(
        "apps.py register_record_type inventory.goodsreceipt (roles yok)",
        SIGNED_IN,
        read(RECEIPTS),
    ),
    Row(
        "apps.py register_record_type inventory.stockadjustment (roles yok)",
        SIGNED_IN,
        read(ADJUSTMENTS),
    ),
    Row("apps.py register_attachment_target inventory.lot (can_add yok)", SIGNED_IN, read(LOTS)),
    Row(
        "apps.py register_attachment_target inventory.goodsreceipt (can_add yok)",
        SIGNED_IN,
        read(RECEIPTS),
    ),
    # --- ön yüz: modules/inventory ---
    Row("frontend InventoryPage.tsx TABS stok (roles: [])", SIGNED_IN, level(STOCK)),
    Row("frontend InventoryPage.tsx TABS lotlar (roles: [])", SIGNED_IN, level(LOTS)),
    Row(
        "frontend InventoryPage.tsx TABS mal-kabul (satır içi roller)",
        (DEPO, PLANLAMA, YONETIM, SATIN_ALMA, LABORATUVAR),
        level(RECEIPTS),
    ),
    Row(
        "frontend InventoryPage.tsx TABS sayim (satır içi roller)",
        (DEPO, YONETIM),
        level(ADJUSTMENTS),
    ),
    Row(
        "frontend ListTabs.tsx StockTab açılış stoku içe aktarma (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(STOCK, CHANGE),
        live=f"{CONFIG}:STOCK_WRITE_ROLES",
    ),
    Row(
        "frontend ListTabs.tsx ReceiptsTab yeni mal kabul ve siparişten mal kabul "
        "(STOCK_WRITE_ROLES)",
        (DEPO,),
        level(RECEIPTS, CHANGE),
        live=f"{CONFIG}:STOCK_WRITE_ROLES",
    ),
    Row(
        "frontend ListTabs.tsx AdjustmentsTab yeni sayım (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(ADJUSTMENTS, CHANGE),
        live=f"{CONFIG}:STOCK_WRITE_ROLES",
    ),
    Row(
        "frontend GoodsReceiptPage.tsx ReceiptForm editable: taslak kaydet, kaydet ve stoka al, "
        "iptal, form (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(RECEIPTS, CHANGE),
        live=f"{CONFIG}:STOCK_WRITE_ROLES",
    ),
    # Panel sunucunun fiyat kararıyla açılır (extra_costs !== null) ve fiyat girer: görünmesi
    # Fiyatları görür'e, kaydetmesi bu bölüme bağlanır (plan §5.6).
    Row(
        "frontend GoodsReceiptPage.tsx ReceiptCostsPanel düzenleme (extra_costs !== null)",
        PRICE_ROLES,
        level(RECEIPT_PRICES, CHANGE),
        live=f"{SERIALIZERS}:RECEIPT_PRICE_ROLES",
    ),
    Row(
        "frontend AdjustmentPage.tsx AdjustmentForm editable: taslak kaydet, iptal, form "
        "(STOCK_WRITE_ROLES)",
        (DEPO,),
        level(ADJUSTMENTS, CHANGE),
        live=f"{CONFIG}:STOCK_WRITE_ROLES",
    ),
    Row(
        "frontend AdjustmentPage.tsx AdjustmentForm kaydet ve stoka al düğmesi (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(ADJUSTMENTS, APPROVE),
        live=f"{CONFIG}:STOCK_WRITE_ROLES",
    ),
    Row(
        "frontend LotPage.tsx canBlock (LOT_BLOCK_ROLES)",
        (LABORATUVAR,),
        level(LOT_BLOCK, APPROVE),
        live=f"{CONFIG}:LOT_BLOCK_ROLES",
    ),
    Row(
        "frontend LotPage.tsx canRelease (MANUAL_RELEASE_ROLES)",
        ADMIN_ONLY,
        level(MANUAL_RELEASE, APPROVE),
    ),
    Row(
        "frontend LotPage.tsx canMove: transfer ve ters kayıt düğmeleri (STOCK_WRITE_ROLES)",
        (DEPO,),
        level(STOCK, CHANGE),
        live=f"{CONFIG}:STOCK_WRITE_ROLES",
    ),
    # Düğme /maliyet/lotlar/:id sayfasına gider; sayfa Lot maliyetleri: Görür ile açılır
    # (plan §5.9), bölüm de Maliyetleri görür'ü ister.
    Row(
        "frontend LotPage.tsx canSeeCost: lot maliyeti düğmesi (satır içi ['yonetim'])",
        (YONETIM,),
        level(LOT_COSTS),
    ),
    Row("frontend LotPage.tsx mal kabul bağlantısı (koşulsuz)", SIGNED_IN, read(RECEIPTS)),
    Row(
        "frontend LotLabels.tsx PalletSection canCreate (PALLET_ROLES)",
        PALLET_WRITERS,
        level(PALLETS, CHANGE),
        live=f"{CONFIG}:PALLET_ROLES",
    ),
    # --- ön yüz: ortak dosyalardaki depo öğeleri (menü ve rotalar) ---
    Row("frontend layout/menu.ts inventory (roles: [])", SIGNED_IN, MODULE_VIEW),
    Row("frontend routes.tsx depo/:tab? (korumasız)", SIGNED_IN, MODULE_VIEW),
    Row("frontend routes.tsx depo/lotlar/:lotId (korumasız)", SIGNED_IN, MODULE_VIEW),
    Row("frontend routes.tsx depo/mal-kabul/:receiptId (korumasız)", SIGNED_IN, read(RECEIPTS)),
    Row("frontend routes.tsx depo/sayim/:adjustmentId (korumasız)", SIGNED_IN, read(ADJUSTMENTS)),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_admin_only_constants() -> None:
    """Yalnız admin satırları `live` taşıyamaz; bugünkü sabitler burada sabitlenir."""
    from apps.inventory.api import views

    assert views.MANUAL_RELEASE_ROLES == (ADMIN,)
    assert frontend_roles("src/modules/inventory/config.ts", "MANUAL_RELEASE_ROLES") == (ADMIN,)
