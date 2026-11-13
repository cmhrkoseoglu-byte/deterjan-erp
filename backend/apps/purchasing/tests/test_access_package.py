"""Satın alma: paket denkliği (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, fiyat görünürlüğü, kayıt türü, ön yüz) planın §3.10
tablosundaki yetkiye eşlenir; onay ve D-13 §5.4'teki gibi çevrilir. Kişiye özel ayar yokken eski
ve yeni denetim, admin dışındaki 8 rolün bütün bileşimlerinde aynı kararı verir. `live=`
satırları koddaki rol sabitine de bağlıdır; 5. adımda backend sabitleri kalktı, satırlar
dondurulmuş rol listeleriyle kalır (ön yüz sabitleri 8. adıma kadar `live=`).

Satır olmayanlar:
- `PurchasingPage` varsayılan sekme sırası (siparişler, teslimatlar, talepler) rol görünümüdür
  (plan §5.9), rolle kalır.
- Sipariş sayfası (`/satin-alma/siparisler/:orderId`, yeni sipariş dahil) bugün modülü görenlere
  açık; plan §8 madde 3 ile yalnız siparişleri görebilenlere daralır (bilinen ilk gün farkı).
- `OrderPage` onayla düğmesi rol değil sunucudaki `can_approve`'u izler (satırı aşağıda).
- Kişi kendi talebini düzenler ve iptal eder: satır kuralıdır, rol denetimi değildir (plan §4).
"""

from apps.core.access import APPROVE, CHANGE, PRICES, VIEW
from apps.core.tests.access_helpers import Row, all_of, any_of, assert_rows, level, read
from apps.purchasing.access import (
    DELIVERIES,
    ORDERS,
    OVER_LIMIT,
    PERFORMANCE,
    REQUESTS,
    SETTINGS,
    SUGGESTIONS,
)

CONFIG = "frontend:src/modules/purchasing/config.ts"
# layout/menu.ts MENU "purchasing" ve routes.tsx `satin-alma/:tab?` koruması.
MENU_ROLES = ("satin_alma", "yonetim", "depo", "planlama", "uretim")
# 4. adım sonundaki backend sabitleri (5. adımda kaldırıldı): services.ORDER_ROLES,
# api/views.py ORDER_READ_ROLES, services.APPROVER_ROLES, REQUEST_ROLES, RECEIPT_ROLES,
# api/views.py SUGGESTION_ROLES ve PERFORMANCE_ROLES.
ORDER_WRITERS = ("satin_alma", "yonetim")
ORDER_READERS = ("satin_alma", "yonetim", "depo")
APPROVERS = ("yonetim",)
REQUESTERS = ("planlama", "depo", "uretim", "satin_alma", "yonetim")
RECEIVERS = ("depo", "satin_alma", "yonetim")
SUGGESTION_READERS = ("satin_alma", "yonetim", "planlama")
PERFORMANCE_READERS = ("satin_alma", "yonetim")

# Modül sayfaları ve menü: Görür'ü olan bölümlerin birleşimi (plan §2, §5.9).
MODULE_VIEW = any_of(
    level(REQUESTS, VIEW),
    level(SUGGESTIONS, VIEW),
    level(ORDERS, VIEW),
    level(DELIVERIES, VIEW),
    level(PERFORMANCE, VIEW),
    level(SETTINGS, VIEW),
)
# Onay uç noktası ve `approve_order`'ın ilk denetimi (plan §5.4).
APPROVES = any_of(level(ORDERS, APPROVE), level(OVER_LIMIT, APPROVE))
# İptal uç noktası durumu bilmeden denetler: taslak ya da onay bekleyen Değiştirir, onaylı ya da
# gönderilmiş sipariş Onaylar ister.
ORDER_CANCEL = any_of(level(ORDERS, CHANGE), level(ORDERS, APPROVE))
SEES_PRICES = level(PRICES, VIEW)
# Sipariş PDF'i tutarlı belgedir: sipariş Görür ve Fiyatları görür (plan §5.6).
ORDER_PDF = all_of(level(ORDERS, VIEW), SEES_PRICES)

ROWS = [
    # --- API: apps/purchasing/api/views.py PurchaseRequestViewSet (permission_classes) --------
    Row(
        "views.PurchaseRequestViewSet okuma (list, retrieve)",
        REQUESTERS,
        level(REQUESTS, VIEW),
    ),
    Row(
        "views.PurchaseRequestViewSet.create, update/partial_update, cancel",
        REQUESTERS,
        level(REQUESTS, CHANGE),
    ),
    # --- API: PurchaseOrderViewSet.get_permissions -------------------------------------------
    Row(
        "views.PurchaseOrderViewSet okuma (list, retrieve)",
        ORDER_READERS,
        read(ORDERS),
    ),
    Row("views.PurchaseOrderViewSet.pdf", ORDER_WRITERS, ORDER_PDF),
    Row(
        "views.PurchaseOrderViewSet.create",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "views.PurchaseOrderViewSet.update/partial_update",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "views.PurchaseOrderViewSet.submit (yönetim onayına gönder)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "views.PurchaseOrderViewSet.approve",
        ORDER_WRITERS,
        APPROVES,
    ),
    Row(
        "views.PurchaseOrderViewSet.return_to_draft",
        ORDER_WRITERS,
        APPROVES,
    ),
    Row(
        "views.PurchaseOrderViewSet.send (tedarikçiye gönder)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "views.PurchaseOrderViewSet.cancel",
        ORDER_WRITERS,
        ORDER_CANCEL,
    ),
    Row(
        "views.PurchaseOrderViewSet.close (kalanı kapat)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "views.PurchaseOrderViewSet.receive (siparişten mal kabul)",
        RECEIVERS,
        level(DELIVERIES, CHANGE),
    ),
    # Bugün yalnız GET okumadır: HEAD ve OPTIONS (PDF ve mal kabul yolunda da) ile karşılanmayan
    # metotlar ORDER_ROLES'u ister; karşılanmayan yoldaki GET (ör. approve/) ORDER_READ_ROLES'u.
    Row(
        "views.PurchaseOrderViewSet HEAD, OPTIONS ve karşılanmayan metot (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "views.PurchaseOrderViewSet karşılanmayan yoldaki GET (ORDER_READ_ROLES)",
        ORDER_READERS,
        read(ORDERS),
    ),
    Row(
        "views.PurchaseRequestViewSet karşılanmayan metot (REQUEST_ROLES)",
        REQUESTERS,
        level(REQUESTS, CHANGE),
    ),
    # --- API: okuma uç noktaları ve ayarlar ----------------------------------------------------
    Row(
        "views.ExpectedDeliveriesView",
        ORDER_READERS,
        level(DELIVERIES, VIEW),
    ),
    Row(
        "views.ReceiptLinksView (mal kabulün sipariş bağlantıları)",
        ORDER_READERS,
        level(DELIVERIES, VIEW),
    ),
    Row(
        "views.SuggestionsView",
        SUGGESTION_READERS,
        level(SUGGESTIONS, VIEW),
    ),
    Row(
        "views.SupplierPerformanceView",
        PERFORMANCE_READERS,
        level(PERFORMANCE, VIEW),
    ),
    # Ayar değerlerini sipariş yazan kişi de okur (plan §3.10, sekmeyi görmez).
    Row(
        "views.PurchasingSettingsView GET HasRole(SATIN_ALMA, YONETIM)",
        ("satin_alma", "yonetim"),
        any_of(level(SETTINGS, VIEW), level(ORDERS, CHANGE)),
    ),
    Row(
        "views.PurchasingSettingsView PATCH (APPROVER_ROLES)",
        APPROVERS,
        level(SETTINGS, CHANGE),
    ),
    Row(
        "views.PurchasingSettingsView HEAD, OPTIONS ve karşılanmayan metot (APPROVER_ROLES)",
        APPROVERS,
        level(SETTINGS, CHANGE),
    ),
    Row(
        "views.ExpectedDeliveriesView, ReceiptLinksView karşılanmayan metot (ORDER_READ_ROLES)",
        ORDER_READERS,
        level(DELIVERIES, VIEW),
    ),
    Row(
        "views.SuggestionsView karşılanmayan metot (SUGGESTION_ROLES)",
        SUGGESTION_READERS,
        level(SUGGESTIONS, VIEW),
    ),
    Row(
        "views.SupplierPerformanceView karşılanmayan metot (PERFORMANCE_ROLES)",
        PERFORMANCE_READERS,
        level(PERFORMANCE, VIEW),
    ),
    # --- servis: apps/purchasing/services.py ---------------------------------------------------
    Row(
        "services.update_settings (APPROVER_ROLES)",
        APPROVERS,
        level(SETTINGS, CHANGE),
    ),
    Row(
        "services.create_request elle talep (REQUEST_ROLES)",
        REQUESTERS,
        level(REQUESTS, CHANGE),
    ),
    Row(
        "services._can_edit_request başkasının talebi: update_request, cancel_request "
        "(ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "services.create_order (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "services.update_order (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "services.submit_for_approval (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "services.approve_order ilk denetim (ORDER_ROLES)",
        ORDER_WRITERS,
        APPROVES,
    ),
    # D-13: yönetim her tutarı, satın alma yalnız limit girilmiş ve tutar limit içindeyse onaylar.
    Row(
        "services.can_approve limit üstü ya da limit girilmemiş (APPROVER_ROLES)",
        APPROVERS,
        level(OVER_LIMIT, APPROVE),
    ),
    Row(
        "services.can_approve limit içinde (APPROVER_ROLES ya da SATIN_ALMA)",
        ("yonetim", "satin_alma"),
        APPROVES,
    ),
    Row(
        "services.return_to_draft (APPROVER_ROLES)",
        APPROVERS,
        level(OVER_LIMIT, APPROVE),
    ),
    Row(
        "services.mark_sent (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "services.cancel_order taslak ya da onay bekleyen sipariş (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "services.cancel_order onaylı ya da gönderilmiş sipariş (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, APPROVE),
    ),
    Row(
        "services.close_order (ORDER_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
    ),
    Row(
        "services.create_receipt_from_order (RECEIPT_ROLES)",
        RECEIVERS,
        level(DELIVERIES, CHANGE),
    ),
    # --- fiyat görünürlüğü ve kayıt türü -------------------------------------------------------
    Row(
        "api/serializers.py can_see_prices: PriceHidingMixin fiyat alanları (ORDER_ROLES)",
        ORDER_WRITERS,
        SEES_PRICES,
    ),
    Row(
        "apps.py price_fields: geçmişte gizli fiyat alanları (ORDER_ROLES)",
        ORDER_WRITERS,
        SEES_PRICES,
    ),
    Row(
        "records purchasing.purchaseorder (yorum, geçmiş, ek; ORDER_READ_ROLES)",
        ORDER_READERS,
        read(ORDERS),
    ),
    # --- ön yüz: menü, rotalar ve arama -------------------------------------------------------
    Row("layout/menu.ts MENU purchasing", MENU_ROLES, MODULE_VIEW),
    Row("routes.tsx satin-alma/:tab? (menuRoles purchasing)", MENU_ROLES, MODULE_VIEW),
    Row(
        "pages/SearchPage.tsx kaynak purchaseOrders (ORDER_READ_ROLES)",
        ORDER_READERS,
        read(ORDERS),
        live=f"{CONFIG}:ORDER_READ_ROLES",
    ),
    # --- ön yüz: frontend/src/modules/purchasing ------------------------------------------------
    Row(
        "PurchasingPage TABS siparisler (ORDER_READ_ROLES)",
        ORDER_READERS,
        level(ORDERS, VIEW),
        live=f"{CONFIG}:ORDER_READ_ROLES",
    ),
    Row(
        "PurchasingPage TABS teslimatlar (ORDER_READ_ROLES)",
        ORDER_READERS,
        level(DELIVERIES, VIEW),
        live=f"{CONFIG}:ORDER_READ_ROLES",
    ),
    Row(
        "PurchasingPage TABS talepler (REQUEST_ROLES)",
        REQUESTERS,
        level(REQUESTS, VIEW),
        live=f"{CONFIG}:REQUEST_ROLES",
    ),
    Row(
        "PurchasingPage TABS oneriler (SUGGESTION_ROLES)",
        SUGGESTION_READERS,
        level(SUGGESTIONS, VIEW),
        live=f"{CONFIG}:SUGGESTION_ROLES",
    ),
    Row(
        "PurchasingPage TABS performans (PERFORMANCE_ROLES)",
        PERFORMANCE_READERS,
        level(PERFORMANCE, VIEW),
        live=f"{CONFIG}:PERFORMANCE_ROLES",
    ),
    Row(
        "PurchasingPage TABS ayarlar (SETTINGS_ROLES)",
        APPROVERS,
        level(SETTINGS, VIEW),
        live=f"{CONFIG}:SETTINGS_ROLES",
    ),
    Row(
        "PurchasingPage SettingsTab kaydet düğmesi (sekme: SETTINGS_ROLES)",
        APPROVERS,
        level(SETTINGS, CHANGE),
        live=f"{CONFIG}:SETTINGS_ROLES",
    ),
    Row(
        "PurchasingPage RequestsTab yeni talep düğmesi (sekme: REQUEST_ROLES)",
        REQUESTERS,
        level(REQUESTS, CHANGE),
        live=f"{CONFIG}:REQUEST_ROLES",
    ),
    Row(
        "PurchasingPage RequestsTab başkasının talebini düzenle ve iptal et (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "PurchasingPage RequestsTab sipariş bağlantısı (ORDER_READ_ROLES)",
        ORDER_READERS,
        level(ORDERS, VIEW),
        live=f"{CONFIG}:ORDER_READ_ROLES",
    ),
    Row(
        "PurchasingPage SuggestionsTab talep aç düğmesi (sekme: SUGGESTION_ROLES)",
        SUGGESTION_READERS,
        all_of(level(SUGGESTIONS, VIEW), level(REQUESTS, CHANGE)),
        live=f"{CONFIG}:SUGGESTION_ROLES",
    ),
    Row(
        "PurchasingPage OrdersTab tutar sütunu (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        SEES_PRICES,
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "PurchasingPage OrdersTab yeni sipariş düğmesi (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "PurchasingPage DeliveriesTab satırdan sipariş sayfası (sekme: ORDER_READ_ROLES)",
        ORDER_READERS,
        level(ORDERS, VIEW),
        live=f"{CONFIG}:ORDER_READ_ROLES",
    ),
    Row(
        "OrderPage taslak düzenleme formu ve taslağı kaydet (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage yönetim onayına gönder düğmesi ve notu (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage taslağa geri gönder düğmesi hasAnyRole(['yonetim'])",
        ("yonetim",),
        level(OVER_LIMIT, APPROVE),
    ),
    Row(
        "OrderPage gönderildi düğmesi (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage mal kabul aç düğmesi (RECEIVE_ROLES)",
        RECEIVERS,
        level(DELIVERIES, CHANGE),
        live=f"{CONFIG}:RECEIVE_ROLES",
    ),
    Row(
        "OrderPage PDF düğmesi (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        ORDER_PDF,
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage kalanı kapat düğmesi (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi taslak ya da onay bekleyen siparişte (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, CHANGE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage iptal düğmesi onaylı ya da gönderilmiş siparişte (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        level(ORDERS, APPROVE),
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
    Row(
        "OrderPage showPrices: birim fiyat, satır tutarı ve toplam (ORDER_WRITE_ROLES)",
        ORDER_WRITERS,
        SEES_PRICES,
        live=f"{CONFIG}:ORDER_WRITE_ROLES",
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
