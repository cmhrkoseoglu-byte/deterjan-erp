import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import type { PortalKind } from "../../api/portal";
import { useAuth } from "../../auth/AuthContext";
import { PORTAL_PATHS, portalKind } from "./config";
import { CustomerOrderPage, CustomerOrdersPage } from "./CustomerPages";
import { SupplierOrderPage, SupplierOrdersPage } from "./SupplierPages";

/** `/portal/siparisler`: hesap türüne göre müşteri ya da tedarikçi siparişleri. */
export function PortalOrdersRoute() {
  const { user } = useAuth();
  return portalKind(user) === "supplier" ? <SupplierOrdersPage /> : <CustomerOrdersPage />;
}

/** `/portal/siparisler/:orderId`: hesap türüne göre sipariş sayfası. */
export function PortalOrderRoute() {
  const { user } = useAuth();
  return portalKind(user) === "supplier" ? <SupplierOrderPage /> : <CustomerOrderPage />;
}

/** Yalnız verilen hesap türüne açık portal sayfası; öteki tür Siparişlerim'e döner. */
export function OnlyFor({ kind, children }: { kind: PortalKind; children: ReactNode }) {
  const { user } = useAuth();
  if (portalKind(user) !== kind) return <Navigate to={PORTAL_PATHS.orders} replace />;
  return <>{children}</>;
}
