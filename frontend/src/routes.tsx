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
import { MasterDataPage } from "./modules/masterdata/MasterDataPage";
import { RecipeListPage } from "./modules/recipes/RecipeListPage";
import { RecipePage } from "./modules/recipes/RecipePage";
import { VersionPage } from "./modules/recipes/VersionPage";
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
];
const IMPLEMENTED = new Set(["masterdata", "recipes", "inventory"]);

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
