import type { PortalKind } from "../../api/portal";
import type { CurrentUser } from "../../api/types";
import { PORTAL_PATH } from "../../auth/paths";

export const PORTAL_PATHS = {
  orders: `${PORTAL_PATH}/siparisler`,
  shipments: `${PORTAL_PATH}/sevkiyatlar`,
  receipts: `${PORTAL_PATH}/teslimatlar`,
  ledger: `${PORTAL_PATH}/cari`,
} as const;

export const orderPath = (id: number) => `${PORTAL_PATHS.orders}/${id}`;
export const shipmentPath = (id: number) => `${PORTAL_PATHS.shipments}/${id}`;
export const receiptPath = (id: number) => `${PORTAL_PATHS.receipts}/${id}`;

/** Portal kullanıcısının türü; çalışanda boş. */
export function portalKind(user: CurrentUser | null | undefined): PortalKind | null {
  if (user?.account_type === "customer_portal") return "customer";
  if (user?.account_type === "supplier_portal") return "supplier";
  return null;
}
