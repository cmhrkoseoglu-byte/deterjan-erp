import type { ReactNode } from "react";
import type { RouteObject } from "react-router-dom";
import { RequireAuth } from "./auth/RequireAuth";
import { RequireRole } from "./auth/RequireRole";
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
import { MasterDataPage } from "./modules/masterdata/MasterDataPage";
import { QualityPage } from "./modules/quality/QualityPage";
import { SamplePage } from "./modules/quality/SamplePage";
import { SpecificationPage } from "./modules/quality/SpecificationPage";
import { ReturnPage } from "./modules/returns/ReturnPage";
import { ReturnsPage } from "./modules/returns/ReturnsPage";
import { TracePage } from "./modules/traceability/TracePage";
import { CostingPage } from "./modules/costing/CostingPage";
import { ReportingPage } from "./modules/reporting/ReportingPage";
import { LotCostPage } from "./modules/costing/LotCostPage";
import { RecipeListPage } from "./modules/recipes/RecipeListPage";
import { RecipePage } from "./modules/recipes/RecipePage";
import { VersionPage } from "./modules/recipes/VersionPage";
import { CustomerPage } from "./modules/sales/CustomerPage";
import { SalesOrderPage } from "./modules/sales/OrderPage";
import { ShipmentPickPage } from "./modules/sales/PickPage";
import { SalesPage } from "./modules/sales/SalesPage";
import { PurchaseOrderPage } from "./modules/purchasing/OrderPage";
import { PurchasingPage } from "./modules/purchasing/PurchasingPage";
import { ShipmentPage } from "./modules/sales/ShipmentPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { ModulePlaceholderPage } from "./pages/ModulePlaceholderPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { NotificationsPage } from "./pages/NotificationsPage";

function menuRoles(key: string) {
  return MENU.find((item) => item.key === key)!.roles;
}

function recipesPage(page: ReactNode) {
  return <RequireRole roles={menuRoles("recipes")}>{page}</RequireRole>;
}

function productionPage(page: ReactNode) {
  return <RequireRole roles={menuRoles("production")}>{page}</RequireRole>;
}

function fillingPage(page: ReactNode) {
  return <RequireRole roles={menuRoles("filling")}>{page}</RequireRole>;
}

function salesPage(page: ReactNode) {
  return <RequireRole roles={menuRoles("sales")}>{page}</RequireRole>;
}

function returnsPage(page: ReactNode) {
  return <RequireRole roles={menuRoles("returns")}>{page}</RequireRole>;
}

function costingPage(page: ReactNode) {
  return <RequireRole roles={menuRoles("costing")}>{page}</RequireRole>;
}

function qualityPage(page: ReactNode) {
  return <RequireRole roles={menuRoles("quality")}>{page}</RequireRole>;
}

// Hazır modül sayfaları. Erişim menüdeki rollerle aynıdır; asıl yetki backend'dedir.
const pageRoutes: RouteObject[] = [
  {
    path: "ana-veriler/:tab?",
    element: (
      <RequireRole roles={menuRoles("masterdata")}>
        <MasterDataPage />
      </RequireRole>
    ),
  },
  { path: "receteler", element: recipesPage(<RecipeListPage />) },
  { path: "receteler/:recipeId", element: recipesPage(<RecipePage />) },
  { path: "receteler/:recipeId/surumler/:versionId", element: recipesPage(<VersionPage />) },
  // Depo: menü herkese açık; sekmeler ve düğmeler rolle daralır.
  { path: "depo/lotlar/:lotId", element: <LotPage /> },
  { path: "depo/mal-kabul/:receiptId", element: <GoodsReceiptPage /> },
  { path: "depo/sayim/:adjustmentId", element: <AdjustmentPage /> },
  { path: "depo/:tab?", element: <InventoryPage /> },
  // Üretim: planlama emir açar, depo hazırlar, üretim tartar; düğmeler rolle daralır.
  { path: "uretim/emirler/:orderId/hazirlama", element: productionPage(<PrepPage />) },
  { path: "uretim/emirler/:orderId", element: productionPage(<OrderPage />) },
  { path: "uretim/sarjlar/:batchId", element: productionPage(<BatchPage />) },
  { path: "uretim/:tab?", element: productionPage(<ProductionPage />) },
  // Kalite: laboratuvar numune ve spesifikasyon, yönetim şartlı kabul onayı.
  { path: "kalite/numuneler/:sampleId", element: qualityPage(<SamplePage />) },
  { path: "kalite/spesifikasyonlar/:specId", element: qualityPage(<SpecificationPage />) },
  { path: "kalite/:tab?", element: qualityPage(<QualityPage />) },
  // Dolum: planlama emir ve ambalaj reçetesi, depo ambalaj hazırlar, dolum hattı doldurur.
  { path: "dolum/emirler/:orderId/hazirlama", element: fillingPage(<FillingPrepPage />) },
  { path: "dolum/emirler/:orderId", element: fillingPage(<FillingOrderPage />) },
  { path: "dolum/partiler/:runId", element: fillingPage(<RunPage />) },
  { path: "dolum/ambalaj-receteleri/:specId", element: fillingPage(<SpecPage />) },
  { path: "dolum/:tab?", element: fillingPage(<FillingPage />) },
  // Sevkiyat: sevkiyat ve yönetim sipariş açar; planlama ve depo siparişleri ve rezervasyonu görür.
  { path: "sevkiyat/siparisler/:orderId", element: salesPage(<SalesOrderPage />) },
  { path: "sevkiyat/musteriler/:customerId", element: salesPage(<CustomerPage />) },
  // Sevkiyat: sevkiyat planlar ve sevki onaylar; depo tablette lot okutur ve yüklemeyi bitirir.
  { path: "sevkiyat/sevkiyatlar/:shipmentId", element: salesPage(<ShipmentPage />) },
  { path: "sevkiyat/sevkiyatlar/:shipmentId/toplama", element: salesPage(<ShipmentPickPage />) },
  { path: "sevkiyat/:tab?", element: salesPage(<SalesPage />) },
  // İadeler: sevkiyat açar, sevkiyat ya da depo teslim alır, depo imha eder; laboratuvar izler.
  { path: "iadeler", element: returnsPage(<ReturnsPage />) },
  { path: "iadeler/:returnId", element: returnsPage(<ReturnPage />) },
  // Satın alma: satın alma ve yönetim sipariş açar; depo siparişleri tutarsız görür ve mal kabul
  // açar; planlama, depo ve üretim talep açar.
  {
    path: "satin-alma/siparisler/:orderId",
    element: (
      <RequireRole roles={menuRoles("purchasing")}>
        <PurchaseOrderPage />
      </RequireRole>
    ),
  },
  {
    path: "satin-alma/:tab?",
    element: (
      <RequireRole roles={menuRoles("purchasing")}>
        <PurchasingPage />
      </RequireRole>
    ),
  },
  // İzlenebilirlik ve geri çağırma: laboratuvar ve yönetim.
  {
    path: "izlenebilirlik/:tab?",
    element: (
      <RequireRole roles={menuRoles("traceability")}>
        <TracePage />
      </RequireRole>
    ),
  },
  // Maliyet: yalnızca yönetim (ve admin); tutarlar backend'de de yalnızca bu rollere döner.
  { path: "maliyet/lotlar/:lotId", element: costingPage(<LotCostPage />) },
  { path: "maliyet/:tab?", element: costingPage(<CostingPage />) },
  // Panolar ve raporlar: menü herkese açık; panolar ve raporlar rolle daralır (backend listesi).
  { path: "raporlar/:tab?", element: <ReportingPage /> },
];
const IMPLEMENTED = new Set([
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
  "reporting",
]);

// Modül sayfaları hazır olana kadar menüdeki diğer iç bağlantılar rol korumalı bir yer tutucuya gider.
const moduleRoutes: RouteObject[] = MENU.filter(
  (item) => item.path !== "/" && !item.external && !IMPLEMENTED.has(item.key),
).map((item) => ({
  path: `${item.path.slice(1)}/*`,
  element: (
    <RequireRole roles={item.roles}>
      <ModulePlaceholderPage title={item.label} phase={item.phase} />
    </RequireRole>
  ),
}));

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "bildirimler", element: <NotificationsPage /> },
          ...pageRoutes,
          ...moduleRoutes,
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
