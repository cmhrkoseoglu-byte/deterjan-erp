import type { PurchaseOrderStatus, PurchaseRequestStatus } from "../../api/purchasing";
import type { Role } from "../../api/types";

// Yetkiler backend ile aynıdır (apps/purchasing/services.py); arayüz yalnızca düğmeleri gizler.
export const ORDER_WRITE_ROLES: Role[] = ["satin_alma", "yonetim"];
/** Siparişleri görür (depo tutarsız). */
export const ORDER_READ_ROLES: Role[] = ["satin_alma", "yonetim", "depo"];
/** Siparişten mal kabul açar. */
export const RECEIVE_ROLES: Role[] = ["depo", "satin_alma", "yonetim"];
/** Talep açar. */
export const REQUEST_ROLES: Role[] = ["planlama", "depo", "uretim", "satin_alma", "yonetim"];
export const SUGGESTION_ROLES: Role[] = ["satin_alma", "yonetim", "planlama"];
export const PERFORMANCE_ROLES: Role[] = ["satin_alma", "yonetim"];
/** Onay limiti ayarı (Karar D-13). */
export const SETTINGS_ROLES: Role[] = ["yonetim"];

export const PURCHASING_BASE = "/satin-alma";
export const purchaseOrderPath = (id: number | "yeni") => `${PURCHASING_BASE}/siparisler/${id}`;

export const ORDER_STATUS_COLOR: Record<PurchaseOrderStatus, string> = {
  DRAFT: "blue",
  PENDING_APPROVAL: "yellow",
  APPROVED: "indigo",
  SENT: "cyan",
  PARTIALLY_RECEIVED: "orange",
  RECEIVED: "green",
  CANCELLED: "gray",
};

export const REQUEST_STATUS_COLOR: Record<PurchaseRequestStatus, string> = {
  OPEN: "blue",
  ORDERED: "green",
  CANCELLED: "gray",
};

/** Mal kabul yapılabilen sipariş durumları. */
export const RECEIVABLE_STATUSES: PurchaseOrderStatus[] = [
  "APPROVED",
  "SENT",
  "PARTIALLY_RECEIVED",
];
/** İptal edilebilen durumlar (mal kabul gelmeden). */
export const CANCELLABLE_STATUSES: PurchaseOrderStatus[] = [
  "DRAFT",
  "PENDING_APPROVAL",
  "APPROVED",
  "SENT",
];
