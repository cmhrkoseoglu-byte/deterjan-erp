import type { ReactNode } from "react";
import type { RouteObject } from "react-router-dom";
import {
  DASHBOARD_PATH,
  MY_ACCESS_PATH,
  PRIVACY_PATH,
  SEARCH_PATH,
  TASKS_PATH,
} from "./auth/paths";
import { RequireAuth } from "./auth/RequireAuth";
import { RequireAccess, RequirePage } from "./auth/RequireAccess";
import type { PageKey } from "./auth/pageAccess";
import { AppLayout } from "./layout/AppLayout";
import { MENU } from "./layout/menu";
import { AdjustmentPage } from "./modules/inventory/AdjustmentPage";
import { GoodsReceiptPage } from "./modules/inventory/GoodsReceiptPage";
import { InventoryPage } from "./modules/inventory/InventoryPage";
import { LotPage } from "./modules/inventory/LotPage";
import { BatchPage } from "./modules/production/BatchPage";
import { OrderPage } from "./modules/production/OrderPage";
import { PrepPage } from "./modules/production/PrepPage";
import { ProductionPage } from "./modules/production/ProductionPage";
import { FillingPage } from "./modules/filling/FillingPage";
import { FillingOrderPage } from "./modules/filling/OrderPage";
import { FillingPrepPage } from "./modules/filling/PrepPage";
import { RunPage } from "./modules/filling/RunPage";
import { SpecPage } from "./modules/filling/SpecPage";
import { HsePage } from "./modules/hse/HsePage";
import { IncidentPage } from "./modules/hse/IncidentPage";
import { AttendancePage } from "./modules/personnel/AttendancePage";
import { EmployeePage } from "./modules/personnel/EmployeePage";
import { HolidaysPage } from "./modules/personnel/HolidaysPage";
import { PayrollPage } from "./modules/personnel/PayrollPage";
import { PersonnelPage } from "./modules/personnel/PersonnelPage";
import { WagesPage } from "./modules/personnel/WagesPage";
import { MaintenancePage } from "./modules/maintenance/MaintenancePage";
import { WorkOrderPage } from "./modules/maintenance/WorkOrderPage";
import { MasterDataPage } from "./modules/masterdata/MasterDataPage";
import { QualityPage } from "./modules/quality/QualityPage";
import { SamplePage } from "./modules/quality/SamplePage";
import { SpecificationPage } from "./modules/quality/SpecificationPage";
import { ReturnPage } from "./modules/returns/ReturnPage";
import { ReturnsPage } from "./modules/returns/ReturnsPage";
import { TracePage } from "./modules/traceability/TracePage";
import { CostingPage } from "./modules/costing/CostingPage";
import { ManagementHomePage } from "./modules/reporting/ManagementHomePage";
import { ReportingPage } from "./modules/reporting/ReportingPage";
import { LotCostPage } from "./modules/costing/LotCostPage";
import { RecipeListPage } from "./modules/recipes/RecipeListPage";
import { RecipePage } from "./modules/recipes/RecipePage";
import { VersionPage } from "./modules/recipes/VersionPage";
import { CustomerPage } from "./modules/sales/CustomerPage";
import { PortalRequestPage } from "./modules/sales/PortalRequests";
import { SalesOrderPage } from "./modules/sales/OrderPage";
import { ShipmentPickPage } from "./modules/sales/PickPage";
import { SalesPage } from "./modules/sales/SalesPage";
import { PurchaseOrderPage } from "./modules/purchasing/OrderPage";
import { PurchasingPage } from "./modules/purchasing/PurchasingPage";
import { LedgerPage } from "./modules/ledger/LedgerPage";
import { PartnerLedgerPage } from "./modules/ledger/PartnerLedgerPage";
import { ShipmentPage } from "./modules/sales/ShipmentPage";
import { SecurityPage } from "./modules/security/SecurityPage";
import { PrivacyNoticePage } from "./pages/PrivacyNoticePage";
import { CustomerShipmentPage, CustomerShipmentsPage } from "./modules/portal/CustomerPages";
import { LedgerPage as PortalLedgerPage } from "./modules/portal/LedgerPage";
import { OnlyFor, PortalOrderRoute, PortalOrdersRoute } from "./modules/portal/OrdersRoute";
import { PortalHome, PortalLayout } from "./modules/portal/PortalLayout";
import { NewRequestPage, RequestPage, RequestsPage } from "./modules/portal/RequestPages";
import { ReceiptPage, ReceiptsPage } from "./modules/portal/SupplierPages";
import { UserAccessPage } from "./modules/system/access/UserAccessPage";
import { SystemPage } from "./modules/system/SystemPage";
import { ComparisonPage } from "./modules/golive/ComparisonPage";
import { GoLivePage } from "./modules/golive/GoLivePage";
import { ProblemPage } from "./modules/golive/ProblemPage";
import { HelpPage } from "./modules/help/HelpPage";
import { HomePage } from "./pages/HomePage";
import { HomeRedirect } from "./pages/HomeRedirect";
import { MyAccessPage } from "./pages/MyAccessPage";
import { LoginPage } from "./pages/LoginPage";
import { ModulePlaceholderPage } from "./pages/ModulePlaceholderPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { RouteErrorPage } from "./pages/RouteErrorPage";
import { SearchPage } from "./pages/SearchPage";

/** Sayfayı `auth/pageAccess.ts`'deki kuralıyla korur. */
function guarded(page: PageKey, element: ReactNode) {
  return <RequirePage page={page}>{element}</RequirePage>;
}

// Hazır modül sayfaları. Korumalar `auth/pageAccess.ts`'deki kurallardır (plan §5.9); asıl yetki
// backend'dedir.
const pageRoutes: RouteObject[] = [
  { path: "ana-veriler/:tab?", element: guarded("masterdata", <MasterDataPage />) },
  { path: "receteler", element: guarded("recipes", <RecipeListPage />) },
  { path: "receteler/:recipeId", element: guarded("recipes", <RecipePage />) },
  {
    path: "receteler/:recipeId/surumler/:versionId",
    element: guarded("recipes", <VersionPage />),
  },
  // Depo: stok, lot ve palet herkese açık; belge sayfaları kayıt okumasıyla açılır.
  { path: "depo/lotlar/:lotId", element: guarded("inventoryLot", <LotPage />) },
  { path: "depo/mal-kabul/:receiptId", element: guarded("inventoryReceipt", <GoodsReceiptPage />) },
  { path: "depo/sayim/:adjustmentId", element: guarded("inventoryAdjustment", <AdjustmentPage />) },
  { path: "depo/:tab?", element: guarded("inventory", <InventoryPage />) },
  // Üretim: modül sayfaları bölümlerin birleşimiyle; yeni emir sayfası emir açabilene.
  { path: "uretim/emirler/:orderId/hazirlama", element: guarded("production", <PrepPage />) },
  { path: "uretim/emirler/:orderId", element: guarded("productionOrder", <OrderPage />) },
  { path: "uretim/sarjlar/:batchId", element: guarded("production", <BatchPage />) },
  { path: "uretim/:tab?", element: guarded("production", <ProductionPage />) },
  // Kalite: numune sayfası modülün birleşimiyle, spesifikasyon kendi bölümüyle.
  { path: "kalite/numuneler/:sampleId", element: guarded("quality", <SamplePage />) },
  {
    path: "kalite/spesifikasyonlar/:specId",
    element: guarded("qualitySpec", <SpecificationPage />),
  },
  { path: "kalite/:tab?", element: guarded("quality", <QualityPage />) },
  // Dolum: yeni emir sayfası emir açabilene; ambalaj reçetesi kendi bölümüyle.
  {
    path: "dolum/emirler/:orderId/hazirlama",
    element: guarded("filling", <FillingPrepPage />),
  },
  { path: "dolum/emirler/:orderId", element: guarded("fillingOrder", <FillingOrderPage />) },
  { path: "dolum/partiler/:runId", element: guarded("filling", <RunPage />) },
  { path: "dolum/ambalaj-receteleri/:specId", element: guarded("fillingSpec", <SpecPage />) },
  { path: "dolum/:tab?", element: guarded("filling", <FillingPage />) },
  // Sevkiyat: sipariş, müşteri, sevkiyat ve toplama sayfaları modülün birleşimiyle.
  { path: "sevkiyat/siparisler/:orderId", element: guarded("sales", <SalesOrderPage />) },
  {
    path: "sevkiyat/portal-talepleri/:requestId",
    element: guarded("sales", <PortalRequestPage />),
  },
  { path: "sevkiyat/musteriler/:customerId", element: guarded("sales", <CustomerPage />) },
  { path: "sevkiyat/sevkiyatlar/:shipmentId", element: guarded("sales", <ShipmentPage />) },
  {
    path: "sevkiyat/sevkiyatlar/:shipmentId/toplama",
    element: guarded("sales", <ShipmentPickPage />),
  },
  { path: "sevkiyat/:tab?", element: guarded("sales", <SalesPage />) },
  // İadeler.
  { path: "iadeler", element: guarded("returns", <ReturnsPage />) },
  { path: "iadeler/:returnId", element: guarded("returns", <ReturnPage />) },
  // Satın alma: sipariş ayrıntısı (yeni dahil) siparişleri görebilene (§8 madde 3).
  {
    path: "satin-alma/siparisler/:orderId",
    element: guarded("purchaseOrder", <PurchaseOrderPage />),
  },
  { path: "satin-alma/:tab?", element: guarded("purchasing", <PurchasingPage />) },
  // Cari hesaplar: sekmeler kendi bölümleriyle; tutarlar backend'de Fiyatları görür ile süzülür.
  {
    path: "cari-hesaplar/:tab/:partnerId",
    element: guarded("ledgerPartner", <PartnerLedgerPage />),
  },
  { path: "cari-hesaplar/:tab?", element: guarded("ledger", <LedgerPage />) },
  // İzlenebilirlik ve geri çağırma.
  { path: "izlenebilirlik/:tab?", element: guarded("traceability", <TracePage />) },
  // Maliyet: lot maliyeti kendi bölümüyle; tutarlar backend'de de yetkiyle süzülür.
  { path: "maliyet/lotlar/:lotId", element: guarded("lotCost", <LotCostPage />) },
  { path: "maliyet/:tab?", element: guarded("costing", <CostingPage />) },
  // Bakım: arıza bildirimi her rolde (ana sayfadaki düğme); bakım ekranları modülün birleşimiyle.
  { path: "bakim/is-emirleri/:workOrderId", element: guarded("maintenance", <WorkOrderPage />) },
  { path: "bakim/:tab?", element: guarded("maintenance", <MaintenancePage />) },
  // İSG: olay bildirimi ve tehlike bilgileri rolü olan herkese; sekmeler yetkiyle daralır.
  { path: "isg/olaylar/:incidentId", element: guarded("hse", <IncidentPage />) },
  { path: "isg/:tab?", element: guarded("hse", <HsePage />) },
  // Personel: kişisel veri (KVKK); her alt sayfa kendi bölümüyle.
  { path: "personel", element: guarded("personnelCards", <PersonnelPage />) },
  { path: "personel/puantaj", element: guarded("personnelAttendance", <AttendancePage />) },
  { path: "personel/ucretler", element: guarded("personnelWages", <WagesPage />) },
  { path: "personel/bordro", element: guarded("personnelPayroll", <PayrollPage />) },
  { path: "personel/tatiller", element: guarded("personnelAttendance", <HolidaysPage />) },
  { path: "personel/:employeeId", element: guarded("personnelCards", <EmployeePage />) },
  // Panolar ve raporlar: İndirmeler herkese açık; panolar ve raporlar yetkiyle daralır.
  { path: "raporlar/:tab?", element: guarded("reporting", <ReportingPage />) },
  // Sistem: yalnızca admin (sistem durumu, yedekler, kullanıcı kilidi/2FA, saha tableti).
  // Sistem > Kullanıcılar > Yetkiler: kişinin rolleri ve kişiye özel yetkileri (plan §6.1).
  {
    path: "sistem/kullanicilar/:userId/yetkiler",
    element: guarded("system", <UserAccessPage />),
  },
  { path: "sistem/:tab?", element: guarded("system", <SystemPage />) },
  // Canlıya geçiş: sorun bildirimini bildiren ve admin açar (backend süzer).
  {
    path: "gecis/karsilastirma/:comparisonId",
    element: guarded("goliveComparison", <ComparisonPage />),
  },
  { path: "gecis/sorunlar/:problemId", element: <ProblemPage /> },
  { path: "gecis/:tab?", element: guarded("golive", <GoLivePage />) },
  // Yardım: rol bazında kılavuzlar ve sayım günü planı; herkese açık.
  { path: "yardim/:guide?", element: <HelpPage /> },
];
const IMPLEMENTED = new Set([
  "dashboard",
  "home",
  "masterdata",
  "recipes",
  "inventory",
  "production",
  "quality",
  "filling",
  "sales",
  "returns",
  "traceability",
  "costing",
  "purchasing",
  "ledger",
  "maintenance",
  "hse",
  "personnel",
  "reporting",
  "system",
  "golive",
  "help",
]);

// Modül sayfaları hazır olana kadar menüdeki diğer iç bağlantılar korumalı bir yer tutucuya gider.
const moduleRoutes: RouteObject[] = MENU.filter(
  (item) => item.path !== "/" && !item.external && !IMPLEMENTED.has(item.key),
).map((item) => ({
  path: `${item.path.slice(1)}/*`,
  element: (
    <RequireAccess allow={item.visible}>
      <ModulePlaceholderPage title={item.label} phase={item.phase} />
    </RequireAccess>
  ),
}));

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage />, errorElement: <RouteErrorPage /> },
  // KVKK aydınlatma metni: giriş gerektirmez (giriş ekranından bağlantı).
  { path: PRIVACY_PATH, element: <PrivacyNoticePage />, errorElement: <RouteErrorPage /> },
  {
    element: <RequireAuth />,
    errorElement: <RouteErrorPage />,
    children: [
      // Müşteri ve tedarikçi portalı (docs/plan/musteri-siparis-takibi.md §4.6): ayrı düzen;
      // portal kullanıcısı yalnız burayı, çalışan burası dışını açar (RequireAuth).
      {
        path: "portal",
        element: <PortalLayout />,
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <PortalHome /> },
          { path: "siparisler", element: <PortalOrdersRoute /> },
          { path: "siparisler/:orderId", element: <PortalOrderRoute /> },
          {
            path: "sevkiyatlar",
            element: (
              <OnlyFor kind="customer">
                <CustomerShipmentsPage />
              </OnlyFor>
            ),
          },
          {
            path: "sevkiyatlar/:shipmentId",
            element: (
              <OnlyFor kind="customer">
                <CustomerShipmentPage />
              </OnlyFor>
            ),
          },
          {
            path: "teslimatlar",
            element: (
              <OnlyFor kind="supplier">
                <ReceiptsPage />
              </OnlyFor>
            ),
          },
          {
            path: "teslimatlar/:receiptId",
            element: (
              <OnlyFor kind="supplier">
                <ReceiptPage />
              </OnlyFor>
            ),
          },
          { path: "cari", element: <PortalLedgerPage /> },
          {
            path: "talepler",
            element: (
              <OnlyFor kind="customer">
                <RequestsPage />
              </OnlyFor>
            ),
          },
          {
            path: "talepler/yeni",
            element: (
              <OnlyFor kind="customer">
                <NewRequestPage />
              </OnlyFor>
            ),
          },
          {
            path: "talepler/:requestId",
            element: (
              <OnlyFor kind="customer">
                <RequestPage />
              </OnlyFor>
            ),
          },
          { path: "guvenlik", element: <SecurityPage /> },
        ],
      },
      {
        element: <AppLayout />,
        // Sayfa hatası menü ve başlık yerinde kalarak içerik alanında gösterilir.
        errorElement: <RouteErrorPage />,
        children: [
          // Açılış: yönetim rolü panoya, diğer herkes Görevlerim'e yönlenir.
          { index: true, element: <HomeRedirect /> },
          { path: TASKS_PATH.slice(1), element: <HomePage /> },
          {
            path: DASHBOARD_PATH.slice(1),
            element: guarded("dashboard", <ManagementHomePage />),
          },
          { path: "bildirimler", element: <NotificationsPage /> },
          // Lot ve belge no araması: herkese açık; her rol yalnızca okuyabildiği listelerde arar.
          { path: SEARCH_PATH.slice(1), element: <SearchPage /> },
          // Güvenlik (şifre, 2FA): her giriş yapmış kullanıcı.
          { path: "guvenlik", element: <SecurityPage /> },
          // Yetkilerim: her giriş yapmış kullanıcı, salt okunur (plan §6.4).
          { path: MY_ACCESS_PATH.slice(1), element: <MyAccessPage /> },
          ...pageRoutes,
          ...moduleRoutes,
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
