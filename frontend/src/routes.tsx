import type { RouteObject } from "react-router-dom";
import { RequireAuth } from "./auth/RequireAuth";
import { RequireRole } from "./auth/RequireRole";
import { AppLayout } from "./layout/AppLayout";
import { MENU } from "./layout/menu";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { ModulePlaceholderPage } from "./pages/ModulePlaceholderPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { NotificationsPage } from "./pages/NotificationsPage";

// Modül sayfaları hazır olana kadar menüdeki her iç bağlantı rol korumalı bir yer tutucuya gider.
const moduleRoutes: RouteObject[] = MENU.filter((item) => item.path !== "/" && !item.external).map(
  (item) => ({
    path: `${item.path.slice(1)}/*`,
    element: (
      <RequireRole roles={item.roles}>
        <ModulePlaceholderPage title={item.label} phase={item.phase} />
      </RequireRole>
    ),
  }),
);

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
          ...moduleRoutes,
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
